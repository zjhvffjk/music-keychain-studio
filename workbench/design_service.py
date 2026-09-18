# -*- coding: utf-8 -*-
"""迷你CD 专辑设计工作台（design_service）。

从「专辑列表」接进来：给定 歌手 / 专辑 / 封面URL / 曲目，
复用 design_parts v2 引擎（design_disc2 / design_inner2 / make_back_strip 里的
design_back2 / design_tray2）+ spec_minicd 尺寸真源，按 **111.2 固定结构** 出
①②③ 三件套 + 1:1 印刷版面总览；并导出打印文件（A4 300dpi PNG + PDF）+ ZIP。

AI 增强走「程序衍生打底 + 可选上传覆盖」：build 接口接受 aiDisc/aiFold/aiStrip
三个已上传图片路径（来自 /api/upload），给了就用它替代对应程序衍生件。

接口契约同 packaging_service.handle（handler 为 server 的 BaseHTTPRequestHandler）：
  GET  /api/design/album   ?artist=&album=&pic=&tracks=&company=&mood=&style=
        → 拉封面 + 读设计语言 + 返回 notes（不落盘）
  POST /api/design/build   body{artist,album,pic,tracks,company,mood,style,id,
                                aiDisc,aiFold,aiStrip}
        → 出三件套 + 总览 + A4 打印页，存 outputs/迷你CD设计/<jid>/
        → 返回 {ok, jid, parts, sheetUrl, printUrl, notes, design, zipUrl}
  GET  /api/design/file?jid=&name=   → 该任务目录内文件（带越界校验）
  GET  /api/design/zip?jid=          → 打包下载
  GET  /api/design/state?jid=         → 任务 meta
"""
import io
import json
import os
import sys
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
for p in (TOOLS, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

OUT_DIR = Path(ROOT) / "outputs" / "迷你CD设计"
OUT_DIR.mkdir(parents=True, exist_ok=True)

try:
    import noproxy  # noqa: F401  绕过本机代理（server 已 import；这里兜底）
except Exception:
    pass

import spec_minicd as SP
import make_minicd as MC
import design_parts as DP
import make_minicd_sheet as MS

from PIL import Image

DPI = 300
SHEET_DPI = 300


def _slog(*a):
    try:
        print("[design]", *a, flush=True)
    except Exception:
        pass


def _safe_jid(jid):
    jid = (jid or "").strip()
    if not jid or len(jid) > 64:
        return None
    for ch in jid:
        if not (ch.isascii() and (ch.isalnum() or ch == "-")):
            return None
    return jid


def mm(v, dpi):
    return int(round(v * dpi / 25.4))


def _fetch_cover(pic):
    """从封面 URL 拉图；本地路径直接打开；失败返回 None。"""
    if not pic:
        return None
    try:
        if os.path.isfile(pic):
            return Image.open(pic).convert("RGB")
    except Exception:
        pass
    try:
        req = Request(pic, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://music.163.com/",
        })
        with urlopen(req, timeout=25) as r:
            data = r.read()
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as e:
        _slog("cover fetch failed:", type(e).__name__, e)
        return None


def _norm_tracks(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        items = [str(x).strip() for x in v]
    else:
        s = str(v).strip()
        if s.startswith("["):
            try:
                items = [str(x).strip() for x in json.loads(s)]
            except Exception:
                items = [t.strip() for t in s.strip("[]").replace("，", ";")
                         .replace("；", ";").split(";")]
        else:
            items = [t.strip() for t in s.replace("；", ";").split(";")]
    items = [t for t in items if t]
    return items or None


def _read_design(cover, mood="", style=""):
    D = DP.read_design(cover)
    if mood:
        D["mood"] = mood
    if style:
        D["style"] = style
        D["ink"] = DP.ink_on(D["main"])
    return D


def build_parts(cover, album, artist, D, tracks, company, ai=None, dpi=DPI):
    """出 ①②③ 三件（override-aware）。返回 (disc, fold, strip)。"""
    MC._dpi[0] = dpi  # make_back_strip 用模块级 _dpi

    # ① 盘面
    disc_d = mm(SP.DISC_D, dpi)
    hole_d = mm(SP.DISC_HOLE, dpi)
    if ai and ai.get("disc"):
        disc = MC.cover_crop(ai["disc"], disc_d, disc_d)
    else:
        disc = DP.design_disc2(cover, disc_d, hole_d, D, album, artist, company)

    # ② 封面折件（左内页 + 右封面）
    fold_w = mm(SP.COVER_W, dpi)
    fold_h = mm(SP.COVER_H, dpi)
    if ai and ai.get("fold"):
        inner_im = MC.cover_crop(ai["fold"], fold_w // 2, fold_h)
        fold = MC.make_cover_fold(inner_im, cover, fold_w, fold_h)
    else:
        inner_im = DP.design_inner2(cover, fold_w // 2, fold_h, D, album, artist, tracks)
        fold = MC.make_cover_fold(inner_im, cover, fold_w, fold_h)

    # ③ 封底条（封底 + 内盘底 + 侧封边缘延展）
    strip_w = mm(SP.BACK_W, dpi)
    strip_h = mm(SP.BACK_H, dpi)
    if ai and ai.get("strip"):
        strip = MC.cover_crop(ai["strip"], strip_w, strip_h)
    else:
        strip = MC.make_back_strip(None, None, strip_w, strip_h, cover, album,
                                   artist, D, tracks, 0, company)
    return disc, fold, strip


UPLOAD_DIR = Path(ROOT) / "outputs" / "工作台" / "_uploads"


def _load_ai(path):
    """AI 增强图：绝对/相对路径直接开；或 /api/upload 返回的 uid（12hex）
    → 在 UPLOAD_DIR 里按前缀解析（扩展名未知，upload 只回 uid）。"""
    if not path:
        return None
    path = str(path).strip().strip('"')
    cand = None
    if os.path.isfile(path):
        cand = path
    elif path and all(c.isascii() and (c.isalnum() or c in "-_") for c in path) \
            and "/" not in path and "\\" not in path and "." not in path:
        # 像 uid：在 uploads 目录找前缀匹配（防路径穿越——不含分隔符与点）
        hits = sorted(UPLOAD_DIR.glob(path + ".*"))
        if hits:
            cand = str(hits[0])
    if not cand:
        return None
    try:
        return Image.open(cand).convert("RGB")
    except Exception:
        return None


def build_job(data):
    """落盘一个设计任务：三件套 + 1:1 总览 + A4 打印页 + 打印 PDF + meta + ZIP。"""
    artist = str(data.get("artist") or "")
    album = str(data.get("album") or "")
    pic = data.get("pic") or ""
    company = str(data.get("company") or "")
    mood = str(data.get("mood") or "")
    style = str(data.get("style") or "")
    tracks = _norm_tracks(data.get("tracks"))
    cover = _fetch_cover(pic)
    if cover is None:
        raise ValueError("封面拉取失败（URL 不可达或被代理拦截）：%s" % pic)
    D = _read_design(cover, mood, style)

    ai = {
        "disc": _load_ai(data.get("aiDisc")),
        "fold": _load_ai(data.get("aiFold")),
        "strip": _load_ai(data.get("aiStrip")),
    }
    has_ai = any(ai.values())

    jid = _safe_jid(data.get("id")) or uuid.uuid4().hex[:16]
    d = OUT_DIR / jid
    d.mkdir(parents=True, exist_ok=True)

    disc, fold, strip = build_parts(cover, album, artist, D, tracks, company,
                                    ai if has_ai else None, DPI)
    disc.save(str(d / "part-disc.png"))
    fold.save(str(d / "part-cover.png"))
    strip.save(str(d / "part-strip.png"))

    # 1:1 总览
    sheet_path = str(d / "★版面总览-1比1.png")
    MS.build_sheet(cover, album, artist, D, tracks, company, sheet_path, SHEET_DPI, png=True)

    # A4 打印参考页（程序衍生结构；与三件套同源引擎，无 AI 覆盖时完全一致）
    page_im, sets, _prev = MC.build_page({"cover": (cover, False)}, DPI, "a4l", 1,
                                          artist, album, D, tracks, 0, company)
    page_im.save(str(d / "打印拼版-A4.png"), quality=95)
    page_im.save(str(d / "打印拼版-A4.pdf"), "PDF", resolution=DPI)

    notes = DP.design_notes(D, album, artist, tracks, has_lyrics=False)
    meta = {
        "id": jid, "kind": "minicd-design", "artist": artist, "album": album,
        "company": company, "tracks": tracks or [], "mood": D["mood"], "style": D["style"],
        "main": list(D["main"]), "hasAi": has_ai,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "parts": {
            "disc": "part-disc.png", "cover": "part-cover.png",
            "strip": "part-strip.png", "sheet": "★版面总览-1比1.png",
            "print": "打印拼版-A4.png", "printPdf": "打印拼版-A4.pdf",
        },
    }
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # 打包 ZIP
    zip_path = OUT_DIR / ("%s.zip" % jid)
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as z:
        for f in ("part-disc.png", "part-cover.png", "part-strip.png",
                  "★版面总览-1比1.png", "打印拼版-A4.png", "打印拼版-A4.pdf", "meta.json"):
            p = d / f
            if p.is_file():
                z.write(str(p), f)

    return {
        "ok": True, "jid": jid,
        "parts": [
            {"name": "盘面", "file": "part-disc.png", "mm": "%g×%g" % (SP.DISC_D, SP.DISC_D)},
            {"name": "封面折件", "file": "part-cover.png", "mm": "%g×%g" % (SP.COVER_W, SP.COVER_H)},
            {"name": "封底条", "file": "part-strip.png", "mm": "%g×%g" % (SP.BACK_W, SP.BACK_H)},
        ],
        "sheetUrl": "/api/design/file?jid=%s&name=%s" % (jid, quote("★版面总览-1比1.png")),
        "printUrl": "/api/design/file?jid=%s&name=%s" % (jid, quote("打印拼版-A4.png")),
        "printPdfUrl": "/api/design/file?jid=%s&name=%s" % (jid, quote("打印拼版-A4.pdf")),
        "zipUrl": "/api/design/zip?jid=%s" % jid,
        "notes": notes,
        "design": {"mood": D["mood"], "style": D["style"], "main": list(D["main"]),
                   "hasAi": has_ai},
    }


def _serve_file(handler, jid, name):
    jid = _safe_jid(jid)
    if not jid:
        return handler._json({"error": "bad jid"}, 400)
    name = (name or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return handler._json({"error": "bad name"}, 400)
    base = (OUT_DIR / jid).resolve()
    fp = (base / name).resolve()
    if not fp.is_file():
        return handler._json({"error": "not found"}, 404)
    if str(fp) != str(base / name):
        return handler._json({"error": "forbidden"}, 403)
    return handler._file(str(fp))


def handle(handler, path, query, method):
    if not path.startswith("/api/design/"):
        return False

    def value(name, default=""):
        return (query.get(name) or [default])[0]

    try:
        if method == "POST":
            length = int(handler.headers.get("Content-Length", "0"))
            raw = handler.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw or b"{}")
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {}
            # query 作为兜底合入（个别前端习惯用 query 传参）
            for k, v in query.items():
                data.setdefault(k, v[0] if isinstance(v, list) and v else v)
            handler._json(build_job(data))
            return True

        # ---------------- GET ----------------
        if path == "/api/design/album":
            artist = value("artist"); album = value("album"); pic = value("pic")
            company = value("company")
            tracks = _norm_tracks(value("tracks", ""))
            cover = _fetch_cover(pic)
            if cover is None:
                handler._json({"ok": False, "error": "封面拉取失败：%s" % pic}, 400)
                return True
            D = _read_design(cover, value("mood", ""), value("style", ""))
            notes = DP.design_notes(D, album, artist, tracks, has_lyrics=False)
            handler._json({
                "ok": True,
                "design": {"mood": D["mood"], "style": D["style"],
                           "main": list(D["main"]),
                           "palette": [list(c) for c in D["palette"][:6]]},
                "notes": notes, "coverSize": list(cover.size),
            })
            return True
        if path == "/api/design/file":
            _serve_file(handler, value("jid"), value("name"))
            return True
        if path == "/api/design/zip":
            jid = _safe_jid(value("jid"))
            if not jid:
                handler._json({"error": "bad jid"}, 400)
                return True
            zp = OUT_DIR / ("%s.zip" % jid)
            if not zp.is_file():
                handler._json({"error": "任务尚未生成或已清理"}, 404)
                return True
            handler._file(str(zp), name="迷你CD设计-%s.zip" % jid)
            return True
        if path == "/api/design/state":
            jid = _safe_jid(value("jid"))
            mp = (OUT_DIR / jid / "meta.json") if jid else None
            if not mp or not mp.is_file():
                handler._json({"error": "not found"}, 404)
                return True
            handler._json(json.loads(mp.read_text(encoding="utf-8")))
            return True
        handler._json({"error": "接口不存在"}, 404)
    except (ValueError, KeyError, TypeError) as e:
        handler._json({"error": str(e)}, 400)
    except Exception as e:
        _slog("handle error:", type(e).__name__, e)
        handler._json({"error": "处理失败：%s" % e}, 500)
    return True


class DesignService:
    """迷你CD 设计工作台后端（接口契约同 PackagingService.handle）。"""
    def handle(self, handler, path, query, method):
        return handle(handler, path, query, method)


SERVICE = DesignService()
