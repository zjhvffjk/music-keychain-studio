#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
网易云商品图工作台 —— 本地服务端

把已有的命令行脚本串成可视化工作台:
    fetch163.py / fetch_qq.py  抓取(CDN 母版封面, 非截图; 双源自动回退)
    make_player.py             合成(30x50mm 方形封面播放界面)
    make_keychain.py           合成(1920 钥匙扣商品图, 5 层)
    make_set.py                批处理(热门前 N 首 + 占位图剔除 + 总览)

只有 requests / Pillow / numpy 三个依赖, HTTP 服务用标准库, 不引入框架。

启动:
    python server.py                  # 默认 8765, 自动开浏览器
    python server.py --port 9000      # 指定端口
    python server.py --no-browser     # 不自动开浏览器
    python server.py --force          # 结束已在运行的旧实例并重启

单实例保证:
    启动前先探测端口上是不是本工作台（/api/ping）。
    是 → 只打开浏览器，不再起第二个进程。
    ⚠️ 为什么必须这样：Windows 下 SO_REUSEADDR 是「允许抢占」语义，
       两个进程能同时绑定 8765，请求被随机分发，而 JOBS 表在各自内存里，
       于是「提交任务」和「查进度」落到不同进程 → 行为随机错乱。
       详见 Server 类的注释。

接口一览:
    GET  /                       工作台页面
    GET  /api/ping               健康检查（含 pid / version / 钥匙扣能力）
    GET  /api/artist?name=&source=   查歌手 + 热门歌曲列表(只查不下载)
    GET  /api/song?name=&source=     查单曲候选（QQ 结果优先，带 QQ 角标）
    GET  /api/state?id=          任务进度 / 结果
    GET  /api/zip?id=            打包下载整组(ZIP)
    GET  /assets/<job>/<rel>     预览单张图
    POST /api/run                创建并启动任务
    POST /api/upload?name=       上传封面图(原始字节流)
    POST /api/reveal             在资源管理器打开输出目录

日志:
    workbench/server.log         请求留痕 + 异常堆栈（超过 2MB 自动转到 .1）
"""
import io
import json
import os
import shutil
import socket
import sys
import threading
import time
import traceback
import urllib.request
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)

# 必须在任何 HTTP 请求之前：本机 HTTP_PROXY 会把 127.0.0.1 也送去代理，
# 于是自家接口返回 502 / 空 404（「刚才还好好的」就是它）。见 tools/noproxy.py
import noproxy  # noqa: E402,F401

# 依赖自检: 缺东西时给一句人话, 而不是甩一段 ImportError 堆栈
_missing = []
for _m in ("PIL", "numpy", "requests"):
    try:
        __import__(_m)
    except ImportError:
        _missing.append({"PIL": "pillow"}.get(_m, _m))
if _missing:
    print("缺少依赖: " + ", ".join(_missing))
    print("请执行:  pip install pillow numpy requests")
    sys.exit(1)

from PIL import Image  # noqa: E402

from fetch163 import (  # noqa: E402
    API, cover_url, download, get_json, resolve_picurl, safe_name, search,
)
from fetch_qq import (  # noqa: E402
    MAX_COVER as QQ_MAX_COVER, comment_total_q, cover_url_q,
    download as download_q, hot_songs_q, search_singer_mid,
    search_song as search_song_q,
)
from make_player import make as make_player  # noqa: E402
from make_set import (  # noqa: E402
    LEAD_MIN, comment_total, contact_sheet, fmt_dur, hot_songs, hot_songs_ex,
    human, is_placeholder, lead_rate, norm, normalize_cover, save_retry,
)

# 钥匙扣商品图（5 层合成）。缺贴片/曲线时只让这一项功能不可用，
# 不让整个工作台起不来 —— 封面和播放界面本来就能独立工作。
try:
    import make_keychain as KC
    _KC_IMPORT_ERR = None
except Exception as _e:                      # pragma: no cover
    KC, _KC_IMPORT_ERR = None, f"{type(_e).__name__}: {_e}"

# 白底商品图（product shot）：纯白/透明底、钥匙扣当主角，支持竖长/方形与拼版。
# 与上面 KC 同属可选能力，缺素材时只让这一项不可用。
try:
    import make_keychain_shop as SHOP
    _SHOP_IMPORT_ERR = None
except Exception as _e:                      # pragma: no cover
    SHOP, _SHOP_IMPORT_ERR = None, f"{type(_e).__name__}: {_e}"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OUT_ROOT = os.path.join(ROOT, "outputs", "工作台")
UPLOAD_DIR = os.path.join(OUT_ROOT, "_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------------- 身份与日志 ----------------
# APP_ID 用于「单实例检测」：启动时先问端口上是不是自己，
# 是就只开浏览器不再起第二个进程（详见 main()）。
APP_ID = "minuet-cover-workbench"
VERSION = "1.7.0"   # 1.7.0: 作品库地基（任务元数据 meta.json 落盘 + /api/jobs 列表/删除/重下）
LOG_FILE = os.path.join(HERE, "server.log")
_LOG_LOCK = threading.Lock()
_MISSING_JOBS = set()   # 已经提醒过的陌生 job id（只用于日志去重）


def slog(tag, msg):
    """服务端日志。写文件便于事后定位——之前只 print 到控制台，
    一旦重定向就被 Python 块缓冲吞掉，出问题时日志是空的，白排查。"""
    line = "[%s] %-7s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), tag, msg)
    try:
        with _LOG_LOCK:
            if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 2_000_000:
                os.replace(LOG_FILE, LOG_FILE + ".1")
            with io.open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass
    try:
        sys.stdout.write(line)
        sys.stdout.flush()
    except Exception:
        pass

# 30mm x 50mm @1000DPI -> 1181 x 1968 px
DEFAULTS = {
    "top": 10,
    "width": 1181,
    "dpi": 1000,
    "ratio": 1968 / 1181,
    "likes": "999w+",          # 红心数网易云不公开, 只能是文案
    "comments": "auto",        # auto = 取接口真实评论数
    "listeners": "999+人",     # 在线人数同样不公开
    "quality": "极高音质",
    "playlist": "我喜欢的音乐",
    "played": 0.0,
    "vip": True,
    "follow": True,
    "allow_placeholder": False,
    "source": "auto",          # auto=网易云优先,版权缺失自动切 QQ
    "dedupe": True,            # 同名歌曲只留热度最高的一版
    "coverSize": 1492,         # 正方形封面母版边长（= 画布里"清晰封面"的边长，1:1 用上）
    "keychain": False,         # 是否同时出「钥匙扣商品图」（5 层合成）
    "shop": False,             # 是否同时出「白底商品图」（product shot）
    "shopCanvas": ["long", "square"],   # 商品图画布：config/canvas_presets.json 里的 key，可多选
    "shopBg": "both",          # 商品图底色: white 白底 / transparent 透明 / both
    "shopGrid": True,          # 商品图是否另出拼版总览
}

JOBS = {}
LOCK = threading.Lock()

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".zip": "application/zip",
    ".ico": "image/x-icon",
}


# ---------------------------------------------------------------- 任务管理

def new_job(title, mode, opt=None):
    jid = uuid.uuid4().hex[:10]
    d = os.path.join(OUT_ROOT, jid)
    os.makedirs(os.path.join(d, "covers"), exist_ok=True)
    os.makedirs(os.path.join(d, "players"), exist_ok=True)
    t0 = time.time()
    job = {
        "id": jid, "title": title, "mode": mode,
        "status": "running", "log": [],
        "done": 0, "total": 0, "phase": "准备中",
        "items": [], "skipped": [], "error": None,
        "overview": None, "keychainOverview": None, "shopGrids": [], "zip": None,
        "dir": d,
        "elapsed": 0.0, "t0": t0,
        # 作品库用：任务一建就落盘，哪怕进程中途被杀，磁盘上也有这条记录（状态 running）
        "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0)),
        "opt": dict(opt or {}),
    }
    with LOCK:
        JOBS[jid] = job
    save_meta(job)          # 先落一条"进行中"，重启后至少能看到任务存在过
    return job


def log(job, msg, level="info"):
    line = {"t": time.strftime("%H:%M:%S"), "m": str(msg), "lv": level}
    with LOCK:
        job["log"].append(line)
        if len(job["log"]) > 600:
            del job["log"][:-400]


def snap(job):
    """返回可 JSON 序列化的任务快照（playerPath 是内部字段, 不下发）"""
    with LOCK:
        items = []
        for it in job["items"]:
            d = dict(it)
            d.pop("playerPath", None)      # 内部字段：本机绝对路径，不下发
            d.pop("coverPath", None)
            d.pop("keychainPath", None)
            d.pop("shopPaths", None)
            items.append(d)
        return {
            "id": job["id"], "title": job["title"], "mode": job["mode"],
            "status": job["status"], "phase": job["phase"],
            "done": job["done"], "total": job["total"],
            "log": list(job["log"]),
            "items": items,
            "skipped": list(job["skipped"]),
            "error": job["error"],
            "overview": job["overview"],
            "keychainOverview": job.get("keychainOverview"),
            "shopGrids": job.get("shopGrids") or [],
            "elapsed": round(job["elapsed"], 1),
        }


def url_of(job, rel):
    """把任务内相对路径转成前端可直接用的 URL

    ⚠️ Windows 的 os.path.relpath 返回反斜杠（players\\01 xxx.png），
       直接 quote 会变成 players%5C01…，部分浏览器会加载不出图。
       统一转成正斜杠再编码。
    """
    if not rel:
        return None
    rel = rel.replace("\\", "/")
    return f"/assets/{job['id']}/{quote(rel)}"


# ---------------------------------------------------------------- 作品库元数据
#
# JOBS 是**进程内存**里的表，进程一重启就全没了（前端刷新后 /api/state 直接 404）。
# 但 outputs/工作台/<id>/ 里的图是实打实留在磁盘上的 —— 之前这些成果没有任何索引，
# 用户重开工作台就"找不到上次做的东西"了。
# meta.json 就是给这些目录补一份自描述索引：一个目录 = 一条作品记录，
# 不依赖进程内存，重启后依然能列出、回看、重下。

META_NAME = "meta.json"
META_SCHEMA = 1


def _rel(job, p):
    """路径 → 任务目录内的相对 posix 路径。

    元数据里只存相对路径：`outputs/工作台/<id>/` 整个目录可以搬走/改名/打包给
    别人，索引依然有效；存绝对路径的话换个盘符、换个用户就全废了。
    """
    if not p:
        return None
    p = str(p)
    if not os.path.isabs(p):
        return p.replace("\\", "/")
    try:
        return os.path.relpath(p, job["dir"]).replace("\\", "/")
    except Exception:
        return None


def _meta_of(job):
    """从内存任务对象抽出可持久化的元数据（**调用方需持有 LOCK**）。"""
    items = []
    for it in job.get("items", []):
        player = _rel(job, it.get("playerPath"))
        items.append({
            "rank": it.get("rank"), "name": it.get("name"),
            "artist": it.get("artist"), "album": it.get("album"),
            "dur": it.get("dur"), "comments": it.get("comments"),
            "mm": it.get("mm"),
            "cover": _rel(job, it.get("coverPath")),
            "player": player,
            # 播放界面同时存了 png 与 jpg（同名不同后缀），不必再占一个字段
            "playerJpg": (os.path.splitext(player)[0] + ".jpg") if player else None,
            "keychain": _rel(job, it.get("keychainPath")),
            "shop": dict(it.get("shopPaths") or {}),
        })

    return {
        "schema": META_SCHEMA,
        "id": job["id"],
        "title": job["title"],
        "mode": job["mode"],
        "status": job["status"],
        "phase": job.get("phase"),
        "error": job.get("error"),
        "created": job.get("created"),
        "createdTs": job.get("t0"),
        "elapsed": round(job.get("elapsed") or 0.0, 1),
        "total": job.get("total"), "done": job.get("done"),
        "artist": job.get("artist"), "source": job.get("source"),
        "skipped": list(job.get("skipped") or []),
        "opt": job.get("opt") or {},
        "overview": job.get("overviewFile"),
        "keychainOverview": job.get("keychainOverviewFile"),
        "shopGrids": list(job.get("shopGrids") or []),
        "counts": {
            "songs": len(items),
            "keychain": sum(1 for i in items if i.get("keychain")),
            "shop": sum(len(i.get("shop") or {}) for i in items),
            "grids": len(job.get("shopGrids") or []),
        },
        "items": items,
    }


def save_meta(job):
    """把任务元数据写成 <任务目录>/meta.json。

    ⚠️ 三层保险，绝不能让它拖累出图主流程（元数据是附属品，写失败不该让任务失败）：
      1) 整个函数吞异常，只记一条 warn；
      2) 先写 .tmp 再 os.replace —— 原子替换。否则用户强杀/断电会留下半个 JSON，
         下次 json.load 直接炸，一条脏数据能把整个作品库列表带崩；
      3) 取 job 数据与写盘各自持有 LOCK 的**短临界区**，不长时间占锁。
    """
    try:
        with LOCK:
            data = _meta_of(job)
        path = os.path.join(job["dir"], META_NAME)
        tmp = path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)          # 原子替换：读到的要么是旧版，要么是新版
    except Exception as e:
        slog("WARN", "meta 写入失败 %s: %s: %s"
             % (job.get("id"), type(e).__name__, e))


def load_meta(jid):
    """读某个任务的 meta.json；不存在或损坏都返回 None（不抛）。"""
    path = os.path.join(OUT_ROOT, jid, META_NAME)
    try:
        with io.open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except FileNotFoundError:
        return None
    except Exception as e:
        slog("WARN", "meta 读取失败 %s: %s: %s" % (jid, type(e).__name__, e))
        return None


def list_meta():
    """列出磁盘上所有历史任务，新的在前。

    以**磁盘目录**为准（而不是内存 JOBS），所以重启后列表依然完整。
    任何一条 meta 损坏都只跳过它自己，不影响其余记录。
    """
    out = []
    try:
        names = os.listdir(OUT_ROOT)
    except OSError:
        return out
    for jid in names:
        if jid.startswith("_"):        # _uploads 之类的内部目录
            continue
        d = load_meta(jid)
        if not d:
            continue
        if not d.get("id"):
            d["id"] = jid               # meta 里漏写 id 就用目录名兜底
        out.append(d)
    out.sort(key=_meta_ts, reverse=True)
    return out


def _safe_jid(jid):
    """jid 必须是 uuid4().hex[:10] 的形状（**ASCII** 字母数字，可带连字符）。

    `/assets/<jid>/<rel>` 与删除接口都拿它直接拼路径，必须挡掉 `..`、`/`、`\\`、
    盘符冒号这些能越出 outputs/工作台/ 的写法。
    ⚠️ 不能只用 `str.isalnum()`：它会把「工作台」「１２３」这类 Unicode 也放行。
    那些虽然不含分隔符、穿越不了，但没必要开口子 —— 白名单就写死 ASCII。
    """
    jid = (jid or "").strip()
    if not jid or len(jid) > 64:
        return None
    for ch in jid:
        if not (ch.isascii() and (ch.isalnum() or ch == "-")):
            return None
    return jid


def _asset_url(jid, rel):
    """作品库卡片用的资源 URL（rel 是任务目录内的相对路径）。"""
    if not rel:
        return None
    return "/assets/%s/%s" % (jid, quote(str(rel).replace("\\", "/")))


def _as_dict(v):
    """meta 是磁盘上的文件，可能被手改、也可能是旧版本写的 —— 一律不信任。"""
    return v if isinstance(v, dict) else {}


def _meta_ts(m):
    """排序键。createdTs 可能是数字、字符串、缺失或 None，
    直接拿它 sort 会在混合类型时抛 TypeError（Py3 不允许 int 与 str 比较）。"""
    t = m.get("createdTs")
    try:
        return float(t)
    except (TypeError, ValueError):
        return 0.0


def job_card(m):
    """把一条 meta.json 记录转成前端可直接渲染的卡片。

    历史任务的图**不靠内存**——只要磁盘目录还在，重启后照样能看、能下。
    `inMemory` 表示这个任务在当前进程里还活着（能看实时进度、能接着操作）。

    ⚠️ 这里对 meta 的每个字段都做了形状防御：一条被手改坏的 meta 只能让**它自己**
    这张卡片难看，绝不能让 `/api/jobs` 整个 500（那等于整个作品库打不开）。
    """
    jid = str(m.get("id") or "")
    raw = [x for x in (m.get("items") or []) if isinstance(x, dict)]

    thumb = None
    for it in raw:
        thumb = _asset_url(jid, it.get("cover")) or _asset_url(jid, it.get("player"))
        if thumb:
            break

    items = []
    for it in raw:
        shop = _as_dict(it.get("shop"))
        items.append({
            "rank": it.get("rank"), "name": it.get("name"),
            "artist": it.get("artist"), "album": it.get("album"),
            "dur": it.get("dur"), "comments": it.get("comments"),
            "mm": it.get("mm"),
            "coverUrl": _asset_url(jid, it.get("cover")),
            "playerUrl": _asset_url(jid, it.get("player")),
            "playerJpgUrl": _asset_url(jid, it.get("playerJpg")),
            "keychainUrl": _asset_url(jid, it.get("keychain")),
            "shopUrls": {str(k): _asset_url(jid, v) for k, v in shop.items()},
        })

    grids = [g for g in (m.get("shopGrids") or []) if isinstance(g, dict)]
    live = JOBS.get(jid)
    return {
        "id": jid,
        "title": m.get("title"), "mode": m.get("mode"),
        # 内存里还活着就以内存状态为准（可能正 running），否则用落盘状态
        "status": (live.get("status") if live else m.get("status")),
        "phase": m.get("phase"), "error": m.get("error"),
        "created": m.get("created"), "createdTs": m.get("createdTs"),
        "elapsed": m.get("elapsed"),
        "total": m.get("total"), "done": m.get("done"),
        "artist": m.get("artist"), "source": m.get("source"),
        "counts": _as_dict(m.get("counts")),
        "inMemory": live is not None,
        "thumb": thumb,
        "overviewUrl": _asset_url(jid, m.get("overview")),
        "keychainOverviewUrl": _asset_url(jid, m.get("keychainOverview")),
        "shopGrids": [{"label": g.get("label"),
                       "url": _asset_url(jid, g.get("file"))}
                      for g in grids],
        "items": items,
    }


def jobs_dir_of(jid):
    """jid → 磁盘上的任务目录（已做形状校验与越界校验）。"""
    jid = _safe_jid(jid)
    if not jid:
        return None
    d = os.path.realpath(os.path.join(OUT_ROOT, jid))
    root = os.path.realpath(OUT_ROOT)
    if d != root and not d.startswith(root + os.sep):
        return None
    return d if os.path.isdir(d) else None


# ---------------------------------------------------------------- 钥匙扣商品图

# 贴片是 1.3MB PNG + 256 项色调曲线，解压一次约 0.2s。整组出图时逐张重读
# 会白等十几秒，所以缓存起来复用（进程级，只加载一次）。
_KC_CACHE = {"overlay": None, "lut": None, "err": None, "stamp": None}


def _asset_stamp():
    """贴片+曲线的指纹（mtime + 大小），用来判断要不要重载"""
    st = []
    for p in (KC.OVERLAY, KC.CURVE_JSON):
        try:
            s = os.stat(p)
            st.append(f"{int(s.st_mtime)}:{s.st_size}")
        except OSError:
            st.append("missing")
    return "|".join(st)


def keychain_assets():
    """惰性加载钥匙扣贴片与色调曲线。返回 (overlay, lut)，失败返回 (None, None)。

    贴片会被 tools/keychain_build.py 重新标定 —— 所以缓存记指纹，
    文件一变就自动重载，不必重启工作台（否则服务会一直拿旧贴片出图）。
    """
    if KC is None:
        return None, None
    stamp = _asset_stamp()
    if _KC_CACHE["overlay"] is None or _KC_CACHE["stamp"] != stamp:
        try:
            _KC_CACHE["overlay"], _KC_CACHE["lut"] = KC.prepare()
            _KC_CACHE["stamp"] = stamp
            _KC_CACHE["err"] = None
            slog("SYS", f"钥匙扣贴片已载入（指纹 {stamp}）")
        except Exception as e:
            _KC_CACHE["err"] = f"{type(e).__name__}: {e}"
            slog("WARN", f"钥匙扣素材加载失败：{_KC_CACHE['err']}")
    return _KC_CACHE["overlay"], _KC_CACHE["lut"]


def keychain_ready():
    """前端用来决定要不要显示这个开关；返回 (可用, 不可用原因)"""
    if KC is None:
        return False, f"钥匙扣模块不可用（{_KC_IMPORT_ERR}）"
    overlay, _ = keychain_assets()
    if overlay is None:
        return False, f"钥匙扣素材缺失：{_KC_CACHE['err']}"
    return True, None


def render_keychain(job, base, cpath, ppath):
    """给一首歌追加一张钥匙扣商品图。返回 (相对路径, 失败原因)"""
    if KC is None:
        return None, f"钥匙扣模块不可用（{_KC_IMPORT_ERR}）"
    overlay, lut = keychain_assets()
    if overlay is None:
        return None, f"钥匙扣素材缺失（{_KC_CACHE['err']}）"
    kpath = os.path.join(job["dir"], "keychain", base + "-钥匙扣.jpg")
    try:
        KC.compose(cpath, ppath, kpath, overlay, lut)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    return os.path.relpath(kpath, job["dir"]), None


# ---------------------------------------------------------------- 白底商品图

# 贴片裁到钥匙扣外轮廓后只有 546×1456（原图 1920²），一次裁好复用，
# 和 _KC_CACHE 一样按指纹失效 —— 重标定贴片后不必重启服务。
_SHOP_CACHE = {"ov": None, "err": None, "stamp": None}

SHOP_BG_TAG = {"white": "", "transparent": "-透明"}


def shop_tag(kind):
    """画布 key → 文件名里的中文简称。

    预设现在是可配置的（tools/make_keychain_shop.py 读 config/canvas_presets.json），
    所以这里**不能写死映射表**，否则用户加完预设这里会 KeyError。
    """
    spec = getattr(SHOP, "CANVAS_SPEC", None) or {}
    return ((spec.get(kind) or {}).get("tag")) or kind


def shop_presets():
    """给前端的预设清单：[{key, label, tag}]，前端按它渲染画布按钮。

    tag 是短标签（按钮上用），label 是完整名字（tooltip 用）——
    预设可能很多，按钮上放完整名字会把侧栏撑爆。
    """
    spec = getattr(SHOP, "CANVAS_SPEC", None) or {}
    return [{"key": k, "label": v.get("label") or k, "tag": v.get("tag") or k}
            for k, v in spec.items()]


def shop_assets():
    """惰性载入商品图用的「裁切后贴片」。失败返回 None。"""
    if SHOP is None:
        return None
    stamp = _asset_stamp()
    if _SHOP_CACHE["ov"] is None or _SHOP_CACHE["stamp"] != stamp:
        try:
            _SHOP_CACHE["ov"] = SHOP.load_overlay_trimmed()
            _SHOP_CACHE["stamp"] = stamp
            _SHOP_CACHE["err"] = None
            slog("SYS", f"商品图贴片已裁切载入（指纹 {stamp}）")
        except Exception as e:
            _SHOP_CACHE["err"] = f"{type(e).__name__}: {e}"
            slog("WARN", f"商品图素材加载失败：{_SHOP_CACHE['err']}")
    return _SHOP_CACHE["ov"]


def shop_ready():
    """前端用来决定要不要显示这个开关；返回 (可用, 不可用原因)"""
    if SHOP is None:
        return False, f"商品图模块不可用（{_SHOP_IMPORT_ERR}）"
    if shop_assets() is None:
        return False, f"商品图素材缺失：{_SHOP_CACHE['err']}"
    return True, None


def shop_plan(opt):
    """把画布 / 底色选项收敛成实际的 (画布列表, 底色列表)。

    前端理论上只会传合法值，但接口是裸的（手工 POST 也能打进来），
    所以统一走 SHOP.parse_canvases 收敛。⚠️ **不能再用 long/square 写死白名单** ——
    预设是可配置的（config/canvas_presets.json），写死会把用户新增的画布当非法值丢掉。
    """
    canvases = SHOP.parse_canvases(opt.get("shopCanvas"))
    bg = opt.get("shopBg") if opt.get("shopBg") in ("white", "transparent", "both") else "both"
    bgs = ["white", "transparent"] if bg == "both" else [bg]
    return canvases, bgs


def render_shop(job, base, ppath, opt):
    """给一首歌追加白底/透明底商品图。

    返回 ({变体键: 任务内相对路径}, 失败原因)；变体键形如 "long_white"。
    白底出 JPG、透明底出 PNG。
    """
    if SHOP is None:
        return {}, f"商品图模块不可用（{_SHOP_IMPORT_ERR}）"
    ov = shop_assets()
    if ov is None:
        return {}, f"商品图素材缺失（{_SHOP_CACHE['err']}）"

    canvases, bgs = shop_plan(opt)
    out_dir = os.path.join(job["dir"], "shop")
    os.makedirs(out_dir, exist_ok=True)

    made, err = {}, None
    for kind in canvases:
        tag = shop_tag(kind)
        for bg in bgs:
            ext = ".png" if bg == "transparent" else ".jpg"
            name = "%s-商品图-%s%s%s" % (base, tag, SHOP_BG_TAG[bg], ext)
            p = os.path.join(out_dir, name)
            try:
                im = SHOP.build_unit(ppath, ov, kind=kind, bg=bg)
                SHOP.save_img(im, p, bg=bg)
                im.close()
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                log(job, f"  └ 商品图 {tag}{SHOP_BG_TAG[bg]} 失败：{err}", "warn")
                continue
            made[f"{kind}_{bg}"] = os.path.relpath(p, job["dir"])
    return made, (None if made else err)



# ---------------------------------------------------------------- 单首渲染

def render_song(job, s, rank, opt):
    """下载封面 + 合成播放界面。返回 (item, 失败原因)"""
    cdir = os.path.join(job["dir"], "covers")
    pdir = os.path.join(job["dir"], "players")

    src = opt.get("_src", "163")

    # --- 评论数 ---
    if opt["comments"] == "auto":
        n = comment_total_q(s["id"]) if src == "qq" else comment_total(s["id"])
        cmt = human(n) if n else "0+"
    else:
        cmt = str(opt["comments"])

    # --- 1) 正方形封面母版（统一裁成 coverSize 正方形）---
    tmp = os.path.join(cdir, safe_name(f"_probe {s['name']} - {s['artists']}.jpg"))
    if src == "qq":
        c_url = cover_url_q(s["pic"], QQ_MAX_COVER)      # QQ 源最大 800x800
        got = download_q(c_url, tmp)
    else:
        # 🔴 请求 2000：网易云 CDN 只能降采样、不能超分，实测母版普遍 1400~2000
        #    （幻听/素颜 = 2000、晴天 1500、Always Online = 1400）。
        #    以前只请求 1000、再放大到画布里的 1492 ⇒ 白丢一半像素，封面发糊。
        c_url = cover_url(s["pic"], 2000)
        got = download(c_url, tmp)
    if not got:
        log(job, f"下载失败 pic={s['pic'][:100]!r} url={c_url[:150]!r}", "err")
        return None, "封面下载失败"
    if not opt["allow_placeholder"] and is_placeholder(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None, "无封面(CDN占位色带)"

    base = safe_name(f"{rank:02d} {s['name']} - {s['artists']}")
    cpath = os.path.join(cdir, base + ".jpg")
    os.replace(tmp, cpath)
    normalize_cover(cpath, int(opt.get("coverSize") or 1492))

    # --- 2) 30x50mm 播放界面 ---
    ppath = os.path.join(pdir, base + ".png")
    make_player(
        cpath, ppath, s["name"], s["artists"], int(s["dur_ms"] / 1000),
        width=opt["width"], played_ratio=opt["played"], playlist=opt["playlist"],
        likes=opt["likes"], comments=cmt, listeners=opt["listeners"],
        quality=opt["quality"], statusbar=False, ratio=opt["ratio"],
        vip=opt["vip"], follow=opt["follow"], video_tag=False, fav_loop=True,
    )
    with Image.open(ppath) as _f:
        im = _f.convert("RGB")
    save_retry(im, ppath, dpi=(opt["dpi"], opt["dpi"]))
    jpath = os.path.join(pdir, base + ".jpg")
    save_retry(im, jpath, quality=96, dpi=(opt["dpi"], opt["dpi"]), subsampling=0)

    mm = (im.size[0] / opt["dpi"] * 25.4, im.size[1] / opt["dpi"] * 25.4)
    log(job, f"{s['name']} — {s['artists']}  {fmt_dur(s['dur_ms'])}  "
             f"评论 {cmt}  →  {im.size[0]}×{im.size[1]}px = "
             f"{mm[0]:.1f}×{mm[1]:.1f}mm", "ok")

    # --- 3) 钥匙扣商品图（可选，复用上面刚出的封面 + 播放界面）---
    kc_rel = None
    if opt.get("keychain"):
        kc_rel, kc_err = render_keychain(job, base, cpath, ppath)
        if kc_rel:
            log(job, "  └ 钥匙扣商品图 1920×1920 已出图", "ok")
        else:
            log(job, f"  └ 钥匙扣出图失败：{kc_err}", "warn")

    # --- 4) 白底商品图（可选，复用刚出的播放界面当卡面）---
    shop_rel = {}
    if opt.get("shop"):
        shop_rel, shop_err = render_shop(job, base, ppath, opt)
        if shop_rel:
            log(job, f"  └ 商品图 {len(shop_rel)} 张已出图：{_shop_label(shop_rel)}", "ok")
        else:
            log(job, f"  └ 商品图出图失败：{shop_err}", "warn")

    return {
        "rank": rank, "name": s["name"], "artist": s["artists"],
        "album": s.get("album", ""), "dur": fmt_dur(s["dur_ms"]),
        "comments": cmt,
        "coverUrl": url_of(job, os.path.relpath(cpath, job["dir"])),
        "playerUrl": url_of(job, os.path.relpath(ppath, job["dir"])),
        "playerJpgUrl": url_of(job, os.path.relpath(jpath, job["dir"])),
        "keychainUrl": url_of(job, kc_rel) if kc_rel else None,
        "shopUrls": {k: url_of(job, v) for k, v in shop_rel.items()},
        "mm": f"{mm[0]:.1f}×{mm[1]:.1f}mm",
        "coverPath": cpath,
        "playerPath": ppath,
        "keychainPath": (os.path.join(job["dir"], kc_rel) if kc_rel else None),
        "shopPaths": shop_rel,
    }, None


def _shop_label(shop_rel):
    """把变体键列表说成人话：竖长·白底 / 淘宝·透明 …

    顺序跟着预设声明顺序走（用户能在 config/canvas_presets.json 里调整），
    不再写死 long/square —— 预设是可配置的。
    """
    spec = getattr(SHOP, "CANVAS_SPEC", None) or {}
    keys = [f"{kind}_{bg}" for kind in spec for bg in ("white", "transparent")
            if f"{kind}_{bg}" in shop_rel]
    for k in shop_rel:                      # 预设里没有的键（理论上不会出现）兜底
        if k not in keys:
            keys.append(k)
    tags = []
    for k in keys:
        kind = k.rpartition("_")[0]         # 用 rpartition：预设 key 里可能带下划线
        tags.append("%s·%s" % (shop_tag(kind), "白底" if k.endswith("white") else "透明"))
    return " / ".join(tags)



def finish(job, made, ar_name, total_label, src=None):
    """收尾: 生成总览 + ZIP"""
    if made:
        job["phase"] = "生成总览"
        tag = {"qq": " · QQ音乐", "163": " · 网易云"}.get(src, "")
        grid = contact_sheet(
            [(it["playerPath"], f"{it['rank']:02d} {it['name']}") for it in made],
            os.path.join(job["dir"], "总览.jpg"),
            cols=min(5, len(made)),      # 不足 5 张时别留空列
            title=f"{ar_name} · {total_label} · 30×50mm{tag}",
        )
        job["overview"] = url_of(job, os.path.relpath(grid, job["dir"]))
        job["overviewFile"] = _rel(job, grid)
        log(job, "总览九宫格已生成", "ok")

    # 钥匙扣总览（1:1，用方形缩略图，别按 3:5 压扁）
    kc_made = [it for it in made if it.get("keychainPath")]
    if kc_made:
        job["phase"] = "生成钥匙扣总览"
        kgrid = contact_sheet(
            [(it["keychainPath"], f"{it['rank']:02d} {it['name']}")
             for it in kc_made],
            os.path.join(job["dir"], "总览-钥匙扣.jpg"),
            cols=min(5, len(kc_made)), thumb_w=300, ratio=1.0,
            title=f"{ar_name} · 钥匙扣商品图{tag}",
        )
        job["keychainOverview"] = url_of(job, os.path.relpath(kgrid, job["dir"]))
        job["keychainOverviewFile"] = _rel(job, kgrid)
        log(job, f"钥匙扣总览已生成（{len(kc_made)} 张）", "ok")

    # 商品图拼版总览：用户选了哪几种画布就出几张（不再写死竖长/方形）
    shop_made = [it for it in made if it.get("shopPaths")]
    if shop_made and job.get("shopGrid", True) and SHOP is not None:
        job["phase"] = "生成商品图总览"
        grids = []
        # 要拼哪些画布，从实际产出里反推；顺序跟预设声明顺序走
        seen = []
        for it in shop_made:
            for key in it["shopPaths"]:
                k = key.rpartition("_")[0]
                if k not in seen:
                    seen.append(k)
        order = list(getattr(SHOP, "CANVAS_SPEC", None) or {})
        for kind in [k for k in order if k in seen] + [k for k in seen if k not in order]:
            label = shop_tag(kind)
            # 白底优先；用户只选了透明底就退而用透明底拼
            prefer = "white" if any(it["shopPaths"].get(f"{kind}_white") for it in shop_made) \
                else "transparent"
            units = []
            for it in shop_made:
                rel = it["shopPaths"].get(f"{kind}_{prefer}")
                if rel:
                    units.append(os.path.join(job["dir"], rel))
            if not units:
                continue
            try:
                ims = []
                for p in units:
                    with Image.open(p) as f:
                        # 🔴 必须转 RGBA：白底版落盘是 JPG（RGB），而 build_grid
                        #    内部用 alpha_composite，模式不匹配会抛
                        #    ValueError: images do not match。
                        #    CLI 那边单元是内存里现成的 RGBA，所以露不出这个问题。
                        ims.append(f.convert("RGBA"))
                g = SHOP.build_grid(ims, bg=prefer)
                bg_tag = "白底" if prefer == "white" else "透明"
                gname = "总览-商品图-%s-%s.%s" % (label, bg_tag,
                                                "jpg" if prefer == "white" else "png")
                gpath = os.path.join(job["dir"], gname)
                SHOP.save_img(g, gpath, bg=prefer)
                grids.append({"label": f"商品图总览 · {label} · {bg_tag}",
                              "file": gname,
                              "url": url_of(job, gname)})
                log(job, f"商品图总览（{label}）已生成（{len(units)} 张，"
                         f"{g.width}×{g.height}）", "ok")
            except Exception as e:
                log(job, f"商品图总览（{label}）失败：{type(e).__name__}: {e}", "warn")
        job["shopGrids"] = grids

    with LOCK:
        job["elapsed"] = time.time() - job["t0"]
        job["status"] = "done"
        job["phase"] = "完成"
        job["artist"] = ar_name          # 作品库列表要显示"做的谁"，落盘留存
        job["source"] = src
    save_meta(job)                       # 收尾落盘：完成态的完整元数据


def fail(job, msg):
    with LOCK:
        job["status"] = "error"
        job["error"] = msg
        job["phase"] = "失败"
        job["elapsed"] = time.time() - job["t0"]
    log(job, msg, "err")
    save_meta(job)                       # 失败也要落盘：作品库要能看出"这条失败了"


# ---------------------------------------------------------------- 三种模式

def pick_source(artist, mode, want):
    """选源。返回 (src_used, ar, pool, notes)

    auto 模式：先查网易云，用**主唱命中率**判断该歌手版权是否在网易云；
    低于 LEAD_MIN 就自动切 QQ音乐。

    为什么要这层判断：网易云不会告诉你「没版权」，它会照样返回一堆
    「他给别人写的歌 + Live 合唱」（周杰伦前 35 首命中率仅 26%），
    直接出图就是错的。
    """
    src_used, ar, pool, notes = None, None, [], []
    if mode not in ("auto", "163", "qq"):
        mode = "auto"

    if mode in ("auto", "163"):
        ar, pool, err = hot_songs_ex(artist, want)
        if err:
            # ⚠️ 关键区分：这是**接口失败**，不是「该歌手没有版权」。
            # 老逻辑把两者混为一谈 → 网易云一被限流就静默切 QQ，
            # 还谎报「网易云没有该歌手」，同一个查询来回换源。
            notes.append(f"⚠ 网易云接口异常：{err}")
            ar, pool = None, []
            if mode == "163":
                notes.append("已锁定网易云源，请稍后重试（或把数据源改成“自动/QQ音乐”）")
                return None, None, [], notes
            notes.append("本次自动降级到 QQ音乐，内容仍可用，仅数据源变化")
        elif pool:
            rate = lead_rate(pool, artist)
            notes.append(f"网易云主唱命中率 {rate:.0%}（前 {len(pool)} 首）")
            if mode == "163" or rate >= LEAD_MIN:
                src_used = "163"
            else:
                notes.append(f"⚠ 低于 {LEAD_MIN:.0%} —— 该歌手版权不在网易云"
                             f"（榜单混入他人作品 / Live 合唱），自动改用 QQ音乐")
                ar, pool = None, []
        else:
            notes.append("网易云没有这位歌手")
            ar = None

    if not pool and mode in ("auto", "qq"):
        qmid, qname = search_singer_mid(artist)
        if qmid:
            ar = {"id": qmid, "name": qname}
            pool = hot_songs_q(qmid, want)
            if pool:
                src_used = "qq"
        if not pool:
            notes.append("QQ音乐也没找到可用歌曲")

    return src_used, ar, pool or [], notes


def run_artist(job, opt):
    artist = (opt.get("artist") or "").strip()
    want = int(opt["top"])
    mode = opt.get("source", "auto") or "auto"
    log(job, f"搜索歌手：{artist}")

    src_used, ar, pool, notes = pick_source(artist, mode, want + 25)
    for nt in notes:
        if nt.startswith("⚠"):
            log(job, nt, "warn")
        else:
            log(job, nt)
    if not pool or not ar:
        why = "；".join(notes) if notes else "两个数据源都没有返回可用歌曲"
        return fail(job, f"没有拿到「{artist}」的可用歌曲：{why}")

    opt["_src"] = src_used
    name = ar.get("name", artist)
    src_tag = "QQ音乐" if src_used == "qq" else "网易云"
    job["title"] = f"{name} · 热门前{want}首"
    log(job, f"歌手 {name}（id={ar.get('id')}）· 数据源 {src_tag}，"
             f"备用池 {len(pool)} 首，目标 {want} 首（无封面自动跳过补位）")
    job["total"] = want

    rank = 0
    seen = set()
    for s in pool:
        if rank >= want:
            break
        if opt.get("dedupe", True) and s["name"] in seen:
            log(job, f"跳过「{s['name']}」：同名重复版本", "warn")
            job["skipped"].append(f"{s['name']}（重复版本）")
            continue
        job["phase"] = f"第 {rank + 1}/{want} 首"
        item, why = render_song(job, s, rank + 1, opt)
        if item is None:
            log(job, f"跳过「{s['name']}」：{why}", "warn")
            job["skipped"].append(f"{s['name']}（{why}）")
            continue
        rank += 1
        seen.add(s["name"])
        job["items"].append(item)
        job["done"] = rank
        time.sleep(0.2)
    if rank == 0:
        return fail(job, "该歌手所有热门歌曲都没有可用封面")
    finish(job, job["items"], name, f"热门前{len(job['items'])}首", src_used)


def run_song(job, opt):
    kw = (opt.get("song") or "").strip()
    log(job, f"搜索单曲：{kw}")
    job["total"] = 1

    # ---- QQ 源：前端点选时就带回了 albummid，直接走腾讯版权曲目 ----
    amid = (opt.get("albummid") or "").strip()
    if amid:
        log(job, "数据源 QQ音乐（腾讯版权）")
        one = None
        try:
            for s in search_song_q(kw, 20):
                if (s.get("albummid") or "") == amid:
                    one = {
                        "id": s.get("songid"),
                        "name": s.get("songname") or kw,
                        "artists": "/".join(x.get("name", "?")
                                            for x in (s.get("singer") or [])),
                        "album": s.get("albumname") or "",
                        "pic": amid,
                        "dur_ms": (s.get("interval") or 0) * 1000,
                    }
                    break
        except Exception as e:
            log(job, f"QQ 曲目信息查询失败：{type(e).__name__}", "warn")
        if one is None:      # 兜底：只靠 albummid 也能出图
            one = {"id": opt.get("songId"), "name": kw, "artists": "",
                   "album": "", "pic": amid, "dur_ms": 0}
        opt["_src"] = "qq"
        job["phase"] = f"合成《{one['name']}》"
        item, why = render_song(job, one, 1, opt)
        if item is None:
            return fail(job, f"「{one['name']}」出图失败：{why}")
        job["items"].append(item)
        job["done"] = 1
        job["title"] = f"{one['name']} — {one['artists']}".strip(" —")
        finish(job, job["items"], one["name"], "30×50mm", "qq")
        return

    res = search(kw, "song", 20)
    songs = res.get("songs") or []
    if not songs:
        return fail(job, f"没搜到「{kw}」")
    pick = int(opt.get("pick") or 0)
    songs = songs[pick:pick + 25] if pick else songs
    opt["_src"] = "163"
    for s in songs:
        one = norm(s)
        # 搜索接口只给 album.picId, 没有 picUrl, 必须补查一次 song/detail
        if not one["pic"]:
            one["pic"] = resolve_picurl(s)
            log(job, f"解析封面地址 [{one['name']}] "
                     f"{'成功' if one['pic'] else '失败'}")
        job["phase"] = f"合成《{one['name']}》"
        item, why = render_song(job, one, 1, opt)
        if item is None:
            job["skipped"].append(f"{one['name']}（{why}）")
            log(job, f"跳过「{one['name']}」：{why}", "warn")
            continue
        job["items"].append(item)
        job["done"] = 1
        job["title"] = f"{one['name']} — {one['artists']}"
        break
    if not job["items"]:
        return fail(job, "候选歌曲都没有可用封面，换个关键词试试")
    finish(job, job["items"], job["items"][0]["name"], "30×50mm", "163")


def run_upload(job, opt):
    """用上传的图片当封面, 套播放界面模板"""
    uid = (opt.get("upload") or "").strip()
    src = None
    for f in os.listdir(UPLOAD_DIR):
        if f.startswith(uid + "."):
            src = os.path.join(UPLOAD_DIR, f)
            break
    if not src or not os.path.exists(src):
        return fail(job, "上传的文件已失效，请重新上传")

    title = (opt.get("title") or "").strip() or "未命名"
    artist = (opt.get("artist") or "").strip() or "未知歌手"
    dur = int(float(opt.get("duration") or 0) or 0)
    log(job, f"载入上传封面：{os.path.basename(src)}")
    job["total"] = 1

    cdir = os.path.join(job["dir"], "covers")
    pdir = os.path.join(job["dir"], "players")
    base = safe_name(f"01 {title} - {artist}")

    # 正方形母版: 居中裁切 (非正方形输入也不变形)
    im = Image.open(src).convert("RGB")
    s0 = min(im.size)
    sq = im.crop(((im.width - s0) // 2, (im.height - s0) // 2,
                  (im.width + s0) // 2, (im.height + s0) // 2))
    if s0 != 1492:
        sq = sq.resize((1492, 1492), Image.LANCZOS)
    cpath = os.path.join(cdir, base + ".jpg")
    save_retry(sq, cpath, quality=96, subsampling=0)

    n = comment_total(opt["songId"]) if opt.get("songId") else 0
    if opt["comments"] == "auto":
        cmt = human(n) if n else "0+"
    else:
        cmt = str(opt["comments"])

    job["phase"] = f"合成《{title}》"
    ppath = os.path.join(pdir, base + ".png")
    make_player(
        cpath, ppath, title, artist, dur,
        width=opt["width"], played_ratio=opt["played"], playlist=opt["playlist"],
        likes=opt["likes"], comments=cmt, listeners=opt["listeners"],
        quality=opt["quality"], statusbar=False, ratio=opt["ratio"],
        vip=opt["vip"], follow=opt["follow"], video_tag=False, fav_loop=True,
    )
    with Image.open(ppath) as _f:
        out = _f.convert("RGB")
    save_retry(out, ppath, dpi=(opt["dpi"], opt["dpi"]))
    jpath = os.path.join(pdir, base + ".jpg")
    save_retry(out, jpath, quality=96, dpi=(opt["dpi"], opt["dpi"]), subsampling=0)
    mm = (out.size[0] / opt["dpi"] * 25.4, out.size[1] / opt["dpi"] * 25.4)
    log(job, f"完成 → {out.size[0]}×{out.size[1]}px = {mm[0]:.1f}×{mm[1]:.1f}mm", "ok")

    kc_rel = None
    if opt.get("keychain"):
        kc_rel, kc_err = render_keychain(job, base, cpath, ppath)
        if kc_rel:
            log(job, "  └ 钥匙扣商品图 1920×1920 已出图", "ok")
        else:
            log(job, f"  └ 钥匙扣出图失败：{kc_err}", "warn")

    shop_rel = {}
    if opt.get("shop"):
        shop_rel, shop_err = render_shop(job, base, ppath, opt)
        if shop_rel:
            log(job, f"  └ 商品图 {len(shop_rel)} 张已出图：{_shop_label(shop_rel)}", "ok")
        else:
            log(job, f"  └ 商品图出图失败：{shop_err}", "warn")

    job["items"].append({
        "rank": 1, "name": title, "artist": artist, "album": "自定义上传",
        "dur": fmt_dur(dur * 1000) if dur else "--:--", "comments": cmt,
        "coverUrl": url_of(job, os.path.relpath(cpath, job["dir"])),
        "playerUrl": url_of(job, os.path.relpath(ppath, job["dir"])),
        "playerJpgUrl": url_of(job, os.path.relpath(jpath, job["dir"])),
        "keychainUrl": url_of(job, kc_rel) if kc_rel else None,
        "shopUrls": {k: url_of(job, v) for k, v in shop_rel.items()},
        "mm": f"{mm[0]:.1f}×{mm[1]:.1f}mm",
        "coverPath": cpath,
        "playerPath": ppath,
        "keychainPath": (os.path.join(job["dir"], kc_rel) if kc_rel else None),
        "shopPaths": shop_rel,
    })
    job["done"] = 1
    finish(job, job["items"], title, "30×50mm")


# ---------------------------------------------------------------- 打包

def build_zip(dirpath, title):
    """把任务目录打成 ZIP。

    参数是 (目录, 标题) 而不是 job 对象 —— 这样**重启后**（内存里没有 job 了）
    也能用 meta.json 里的标题重建 ZIP，作品库的"重下"才有得下载。
    """
    zpath = os.path.join(dirpath, f"{safe_name(title or '作品')}.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for sub in ("covers", "players", "keychain", "shop"):
            d = os.path.join(dirpath, sub)
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                if f.startswith("_probe"):
                    continue
                z.write(os.path.join(d, f), f"{sub}/{f}")
        # 总览类文件都在任务根目录（总览.jpg / 总览-钥匙扣.jpg / 总览-商品图-*.jpg|png）
        for f in sorted(os.listdir(dirpath)):
            if f.startswith("总览") and f.lower().endswith((".jpg", ".png")):
                z.write(os.path.join(dirpath, f), f)
    return zpath


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "MinuetWorkbench/1.0"
    protocol_version = "HTTP/1.1"
    _sent = False          # 本次请求是否已发出响应头（_json/_file 会置 True）

    def log_message(self, *a):
        pass

    def send_error(self, code, message=None, explain=None):
        """默认实现会返回一段 HTML 错误页 → 前端 `r.json()` 解析失败，
        只能得到「返回不是合法 JSON」这种毫无信息量的提示。
        统一改成 JSON，并且**明确带出 HTTP 状态码**，便于一眼定位。"""
        self.close_connection = True
        try:
            default = self.responses.get(code, ("", ""))[0]
            return self._json({"error": message or default or f"HTTP {code}",
                               "code": code}, code)
        except Exception:
            pass

    # ---------- 工具 ----------
    def _cors(self):
        """允许页面从任意来源调用本服务。

        页面可能不是从 http://127.0.0.1:8765 打开的：可能是编辑器/预览面板
        里的中间层地址，也可能是直接双击 index.html（file://，其 Origin 为
        "null"）。这些情况下相对路径 /api/... 会打到错误的服务器上，浏览器
        回一个空的 404，前端只能看到「非 JSON 内容」。放行跨来源后，前端就
        能用绝对地址 http://127.0.0.1:8765 直连真正的后端。
        服务只监听回环地址，不对外暴露，因此放开来源是安全的。"""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")
        # Chrome 的 Private Network Access：从非本地来源的页面访问 127.0.0.1
        # 时，预检必须显式放行，否则请求会被浏览器拦掉。
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self._sent = True
        self.wfile.write(body)

    def _file(self, path, name=None, code=200):
        if not os.path.isfile(path):
            return self._json({"error": "not found"}, 404)
        ext = os.path.splitext(path)[1].lower()
        size = os.path.getsize(path)
        self.send_response(code)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(size))
        # 页面绝不能缓存：否则浏览器可能拿旧界面去调新接口，
        # 表现就是「莫名其妙的报错」，排查成本极高。
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self._cors()
        if name:
            self.send_header(
                "Content-Disposition",
                "attachment; filename*=UTF-8''" + quote(name))
        self.end_headers()
        self._sent = True
        with open(path, "rb") as f:
            while True:
                chunk = f.read(262144)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    # ---------- OPTIONS（跨来源预检） ----------
    def do_OPTIONS(self):
        self._sent = False
        try:
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self._cors()
            self.end_headers()
            self._sent = True
        except Exception:
            pass

    # ---------- GET ----------
    def do_GET(self):
        self._sent = False
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        # 轮询与静态资源太吵，不记；其余请求留痕，便于事后复盘。
        # 带上 UA 与 Referer：排查「请求到底从哪个页面发出来的」时，
        # 这两个头是唯一能把源头钉死的证据（页面 origin 一看 Referer 就清楚）。
        if p not in ("/api/state", "/favicon.ico") and not p.startswith("/assets/"):
            _ua = (self.headers.get("User-Agent") or "")[:70]
            _rf = (self.headers.get("Referer") or "")[:90]
            slog("REQ", "GET %s | UA=%s | REF=%s"
                 % (self.path[:110], _ua, _rf))
        try:
            if p == "/api/ping":
                kc_ok, kc_why = keychain_ready()
                sh_ok, sh_why = shop_ready()
                return self._json({"ok": True, "app": APP_ID, "version": VERSION,
                                   "pid": os.getpid(), "port": self.server.server_port,
                                   "keychain": kc_ok, "keychainWhy": kc_why,
                                   "shop": sh_ok, "shopWhy": sh_why,
                                   "shopPresets": (shop_presets() if sh_ok else [])})
            if p in ("/", "/index.html"):
                return self._file(os.path.join(HERE, "index.html"))
            if p == "/favicon.ico":
                return self._json({}, 404)

            if p.startswith("/assets/"):
                rest = unquote(p[len("/assets/"):])
                jid, _, rel = rest.partition("/")
                job = JOBS.get(jid)
                if job:
                    base = job["dir"]
                else:
                    # 🔴 重启后 JOBS 是空的，但磁盘上的作品还在。以前这里直接 404，
                    #    结果"作品库回看"根本看不到图 —— 历史任务必须也放行。
                    base = jobs_dir_of(jid)
                    if not base:
                        return self._json({"error": "job not found"}, 404)
                base = os.path.realpath(base)
                target = os.path.realpath(os.path.join(base, rel))
                # ⚠️ 必须带上 os.sep 比较：否则 base=…\job123 时，兄弟目录 …\job1234
                #    里的文件也满足 startswith → 前缀绕过。
                if target != base and not target.startswith(base + os.sep):
                    return self._json({"error": "forbidden"}, 403)
                # meta.json / *.tmp 是内部产物（含标题、歌手、选项、相对路径），
                # 只给后端自己用，不该当成素材被下载出去。
                low = os.path.basename(target).lower()
                if low == META_NAME or low.endswith(".tmp"):
                    return self._json({"error": "forbidden"}, 403)
                dl = (q.get("dl") or ["0"])[0] == "1"
                return self._file(target,
                                  name=os.path.basename(target) if dl else None)

            if p == "/api/artist":
                name = (q.get("name") or [""])[0].strip()
                if not name:
                    return self._json({"error": "缺少歌手名"}, 400)
                mode = (q.get("source") or ["auto"])[0]
                src, ar, pool, notes = pick_source(name, mode, 30)
                if not pool or not ar:
                    # 把 notes 里的真实原因带出去：是接口挂了还是真没这位歌手，
                    # 用户需要知道区别，否则只会看到一句含糊的「没找到」。
                    why = "；".join(n.lstrip("⚠ ") for n in notes) or "两个数据源都没有结果"
                    slog("WARN", f"artist/{name}: {why}")
                    return self._json({"error": f"{name}：{why}", "notes": notes}, 404)
                return self._json({
                    "artist": {
                        "id": ar.get("id"), "name": ar.get("name"),
                        "albums": ar.get("albumSize") or 0,
                        "pic": ar.get("picUrl") or ar.get("img1v1Url") or "",
                    },
                    "source": src,
                    "notes": notes,
                    "songs": [{
                        "id": s["id"], "name": s["name"], "artist": s["artists"],
                        "album": s["album"], "dur": fmt_dur(s["dur_ms"]),
                    } for s in pool],
                })

            if p == "/api/song":
                name = (q.get("name") or [""])[0].strip()
                if not name:
                    return self._json({"error": "缺少歌名"}, 400)
                mode = (q.get("source") or ["auto"])[0]
                out, seen = [], set()

                def push(nm, arts, alb, dur, sid, amid, src):
                    key = (nm or "").strip()
                    if not key or key in seen:
                        return
                    seen.add(key)
                    out.append({"id": sid, "name": nm, "artist": arts,
                                "album": alb, "dur": dur, "source": src,
                                "albummid": amid})

                # QQ 音乐排前面：版权曲目（周杰伦等）只有这里有，用户多半要点它
                if mode in ("auto", "qq"):
                    try:
                        for s in search_song_q(name, 15):
                            push(s.get("songname"),
                                 "/".join(x.get("name", "?") for x in (s.get("singer") or [])),
                                 s.get("albumname") or "",
                                 fmt_dur((s.get("interval") or 0) * 1000),
                                 s.get("songid"), s.get("albummid") or "", "qq")
                    except Exception as e:
                        print(f"[qq search] {type(e).__name__}: {e}")

                if mode in ("auto", "163"):
                    res = search(name, "song", 20)
                    for s in (res.get("songs") or [])[:20]:
                        arts = "/".join(x.get("name", "?") for x in s.get("artists", []))
                        push(s.get("name"), arts,
                             (s.get("album") or {}).get("name", ""),
                             fmt_dur(s.get("duration") or 0),
                             s.get("id"), "", "163")
                return self._json({"songs": out[:30]})

            if p == "/api/state":
                jid = (q.get("id") or [""])[0]
                job = JOBS.get(jid)
                if not job:
                    # 轮询请求平时不记日志（每 0.65 秒一次，太吵）。但「查不到
                    # 任务」是重要异常信号：说明这个页面对应的服务进程已经不在
                    # 了（JOBS 是内存里的表，进程重启即清空）。每个陌生 id 只
                    # 提醒一次，避免刷满日志。
                    if jid not in _MISSING_JOBS:
                        _MISSING_JOBS.add(jid)
                        slog("WARN", "state: 查不到任务 id=%r —— 该页面连的服务"
                                     "进程可能已重启，刷新页面即可" % jid)
                    return self._json({"error": "job not found"}, 404)
                return self._json(snap(job))

            if p == "/api/jobs":
                # 作品库列表：以**磁盘上的 meta.json** 为准，所以重启后依然完整
                return self._json({"jobs": [job_card(m) for m in list_meta()]})

            if p == "/api/zip":
                jid = (q.get("id") or [""])[0]
                job = JOBS.get(jid)
                if job:
                    z = build_zip(job["dir"], job["title"])
                    return self._file(z, name=f"{job['title']}.zip")
                # 历史任务（重启后内存里没有）：用 meta.json 里的标题重建 ZIP
                d = jobs_dir_of(jid)
                m = load_meta(jid) if d else None
                if not d or not m:
                    return self._json({"error": "job not found"}, 404)
                z = build_zip(d, m.get("title"))
                return self._file(z, name=f"{m.get('title') or '作品'}.zip")

            return self._json({"error": "bad path"}, 404)
        except BrokenPipeError:
            pass
        except Exception as e:
            try:
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            except Exception:
                pass

    # ---------- POST ----------
    def do_POST(self):
        self._sent = False
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        slog("REQ", "POST %s | UA=%s | REF=%s"
             % (self.path[:110],
                (self.headers.get("User-Agent") or "")[:70],
                (self.headers.get("Referer") or "")[:90]))
        try:
            if p == "/api/upload":
                raw = self._body()
                if len(raw) < 100:
                    return self._json({"error": "文件为空"}, 400)
                name = (q.get("name") or ["upload.jpg"])[0]
                ext = os.path.splitext(name)[1].lower() or ".jpg"
                if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
                    ext = ".jpg"
                uid = uuid.uuid4().hex[:12]
                path = os.path.join(UPLOAD_DIR, uid + ext)
                with open(path, "wb") as f:
                    f.write(raw)
                try:
                    im = Image.open(path)
                    w, h = im.size
                except Exception:
                    os.remove(path)
                    return self._json({"error": "不是有效图片"}, 400)
                return self._json({"upload": uid, "name": name,
                                   "size": f"{w}×{h}", "bytes": len(raw)})

            if p == "/api/reveal":
                data = json.loads(self._body() or b"{}")
                jid = data.get("id", "")
                job = JOBS.get(jid)
                d = job["dir"] if job else jobs_dir_of(jid)
                if not d:
                    return self._json({"error": "job not found"}, 404)
                try:
                    os.startfile(d)  # noqa: S606  (Windows)
                    return self._json({"ok": True})
                except Exception as e:
                    return self._json({"error": str(e)}, 500)

            if p == "/api/jobs/delete":
                # 删除一条作品记录（磁盘上的整个任务目录）。
                # ⚠️ 这是**不可恢复**的删除，所以三重把关：id 形状校验 + 必须在
                #    outputs/工作台/ 以内（jobs_dir_of 已做 realpath 越界检查）
                #    + 只删任务目录本身，绝不递归删到别处。前端必须二次确认后再调。
                data = json.loads(self._body() or b"{}")
                jid = (data.get("id") or "").strip()
                d = jobs_dir_of(jid)
                if not d:
                    return self._json({"error": "job not found"}, 404)
                with LOCK:
                    live = JOBS.get(jid)
                    if live and live.get("status") == "running":
                        return self._json({"error": "任务正在运行，请等它跑完再删"}, 409)
                try:
                    shutil.rmtree(d)
                except Exception as e:
                    return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
                with LOCK:
                    JOBS.pop(jid, None)
                slog("SYS", "作品库删除任务 %s（%s）" % (jid, d))
                return self._json({"ok": True, "id": jid})

            if p == "/api/run":
                req = json.loads(self._body() or b"{}")
                mode = req.get("mode", "artist")
                opt = dict(DEFAULTS)
                for k, v in req.items():
                    if k in DEFAULTS or k in ("artist", "song", "pick", "upload",
                                              "title", "duration", "songId",
                                              "songSource", "albummid"):
                        opt[k] = v
                # 类型收敛, 防止前端传字符串把算术搞崩
                for k in ("top", "width", "dpi", "pick", "duration"):
                    try:
                        opt[k] = int(float(opt.get(k) or 0))
                    except Exception:
                        opt[k] = DEFAULTS.get(k, 0)
                try:
                    opt["ratio"] = float(opt.get("ratio") or DEFAULTS["ratio"])
                    opt["played"] = float(opt.get("played") or 0.0)
                except Exception:
                    opt["ratio"], opt["played"] = DEFAULTS["ratio"], 0.0
                opt["vip"] = bool(opt.get("vip", True))
                opt["follow"] = bool(opt.get("follow", True))
                opt["allow_placeholder"] = bool(opt.get("allow_placeholder", False))
                opt["keychain"] = bool(opt.get("keychain", False))
                opt["shop"] = bool(opt.get("shop", False))
                opt["shopGrid"] = bool(opt.get("shopGrid", True))
                # 画布预设可配置（config/canvas_presets.json），交给 SHOP 收敛，
                # 这里不再写死白名单 —— 否则用户新增的预设会被当非法值丢掉。
                opt["shopCanvas"] = (SHOP.parse_canvases(opt["shopCanvas"])
                                     if SHOP is not None else list(DEFAULTS["shopCanvas"]))
                opt["shopBg"] = opt.get("shopBg") \
                    if opt.get("shopBg") in ("white", "transparent", "both") else "both"
                opt["top"] = max(1, min(opt["top"] or 10, 50))
                opt["width"] = max(600, min(opt["width"] or 1181, 4000))

                titles = {"artist": f"{opt.get('artist', '')}",
                          "song": f"{opt.get('song', '')}",
                          "upload": f"{opt.get('title') or '自定义'}"}
                job = new_job(titles.get(mode, "任务"), mode, opt)
                job["shopGrid"] = opt["shopGrid"]   # finish() 收尾时按它决定要不要拼版

                runner = {"artist": run_artist, "song": run_song,
                          "upload": run_upload}.get(mode)
                if not runner:
                    fail(job, f"未知模式：{mode}")
                    return self._json(snap(job))

                def work():
                    try:
                        runner(job, opt)
                    except Exception as e:
                        import traceback
                        fail(job, f"{type(e).__name__}: {e}")
                        log(job, traceback.format_exc()[-900:], "err")

                threading.Thread(target=work, daemon=True).start()
                return self._json(snap(job))

            return self._json({"error": "bad path"}, 404)
        except BrokenPipeError:
            self.close_connection = True
        except Exception as e:
            slog("ERROR", "POST %s -> %s: %s\n%s"
                 % (self.path, type(e).__name__, e, traceback.format_exc()))
            if getattr(self, "_sent", False):
                self.close_connection = True
            else:
                try:
                    self._json({"error": f"{type(e).__name__}: {e}"}, 500)
                except Exception:
                    self.close_connection = True


class Server(ThreadingHTTPServer):
    """默认的 allow_reuse_address=1 在 Windows 上会让**多个进程同时绑定同一个端口**
    （Windows 的 SO_REUSEADDR 语义与 Linux 不同，是「允许抢占」而非「允许复用
    TIME_WAIT」）。结果：旧进程没退干净也能再起一个新进程，两个进程各自持有
    一份内存里的 JOBS 表，请求被随机分发 → 任务查不到、返回内容不一致。
    关掉它，让重复绑定直接失败，由 main() 去做单实例判定。"""
    allow_reuse_address = False
    daemon_threads = True


def probe_instance(port, timeout=1.5):
    """该端口上是否已经有本工作台在运行？是则返回它的 /api/ping 内容。"""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/ping", timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
            return d if d.get("app") == APP_ID else None
    except Exception:
        return None


def bind_server(prefer, tries=40, force=False):
    """返回 (srv, port, existing)。

    直接 bind，不做「先探测端口再用另一个 socket 绑定」——
    那个写法中间存在竞态窗口，并发启动时两个进程都会认为端口可用。
    """
    for port in range(prefer, prefer + tries):
        existing = probe_instance(port)
        if existing:
            if force:
                slog("SYS", f"端口 {port} 已有实例 pid={existing.get('pid')}，按要求结束它")
                try:
                    os.kill(int(existing["pid"]), 15)
                except Exception as e:
                    slog("WARN", f"结束旧实例失败：{e}")
                for _ in range(20):
                    time.sleep(0.2)
                    if not probe_instance(port, timeout=0.4):
                        break
            else:
                return None, port, existing
        try:
            return Server(("127.0.0.1", port), Handler), port, None
        except OSError:
            continue
    return None, 0, None


def main():
    args = sys.argv[1:]
    # 端口优先级：--port 命令行参数 > 环境变量 MINUET_PORT > 默认 8765
    try:
        prefer = int(os.environ.get("MINUET_PORT") or 8765)
    except ValueError:
        prefer = 8765
    if "--port" in args:
        try:
            prefer = int(args[args.index("--port") + 1])
        except Exception:
            pass
    srv, port, existing = bind_server(prefer, force="--force" in args)
    if not port:
        print(f"找不到可用端口（从 {prefer} 起试了 40 个都被占用了）")
        return
    url = f"http://127.0.0.1:{port}/"
    if existing:
        print("=" * 58)
        print("  工作台已经在运行，直接打开现有窗口即可")
        print("=" * 58)
        print(f"  地址: {url}")
        print(f"  进程: pid={existing.get('pid')}  版本 {existing.get('version')}")
        print("  （想强制重启：  server.py --force）")
        print("=" * 58)
        if "--no-browser" not in args:
            __import__("webbrowser").open(url)
        return
    slog("SYS", f"启动 pid={os.getpid()} port={port} version={VERSION}")
    print("=" * 58)
    print("  网易云商品图工作台")
    print("=" * 58)
    print(f"  地址: {url}")
    print(f"  输出: {OUT_ROOT}")
    print(f"  日志: {LOG_FILE}")
    print(f"  进程: pid={os.getpid()}")
    print("  关闭本窗口即停止服务")
    print("=" * 58)
    if "--no-browser" not in args:
        threading.Timer(0.8, lambda: __import__("webbrowser").open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
