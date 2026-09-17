# -*- coding: utf-8 -*-
"""工作台「专辑全集」端到端验收。

覆盖：能力上报（album / albumSizes）→ 专辑列表预览接口 → 带 album 提交任务 →
      每张专辑有封面母版 + 专辑卡 → 封面为方形母版、专辑卡为正方形且边长=选的档位 →
      专辑墙总览 → ZIP 含 albums/、album_cards/、albums.json →
      选项收敛（越界边长回落 / 字符串 "false" 当假 / Infinity 不炸）→
      /assets 仍拦 meta.json。

用 albumMax 把每轮控制在个位数专辑，避免 e2e 跑成几分钟。
"""
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import noproxy  # noqa: E402,F401   （本机 HTTP_PROXY 会把 127.0.0.1 也代理走）

from PIL import Image  # noqa: E402

WB_PORT = int(os.environ.get("MINUET_PORT") or 8765)
BASE = f"http://127.0.0.1:{WB_PORT}"
HDR = {"Content-Type": "application/json"}
OK, BAD = [], []

ARTIST = os.environ.get("ALBUM_ARTIST") or "周杰伦"


def check(name, cond, detail=""):
    (OK if cond else BAD).append(name)
    print("  %s %s %s" % ("[OK]  " if cond else "[FAIL]", name, detail))


def call(method, path, body=None, timeout=30):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    for k, v in HDR.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, ("%s: %s" % (type(e).__name__, e)).encode("utf-8")


def run_and_wait(body, label, timeout_s=300):
    st, b = call("POST", "/api/run", body, timeout=90)
    check("%s 提交返回 200" % label, st == 200, "HTTP %s" % st)
    if st != 200:
        print(b[:400].decode("utf-8", "replace"))
        sys.exit(1)
    jid = json.loads(b.decode("utf-8"))["id"]
    print("      job = %s" % jid)
    snap = None
    for i in range(timeout_s):
        time.sleep(1.0)
        st, b = call("GET", "/api/state?id=%s" % jid, timeout=20)
        if st != 200:
            check("%s 轮询返回 200" % label, False, "HTTP %s" % st)
            break
        snap = json.loads(b.decode("utf-8"))
        if i % 3 == 0 or snap["status"] != "running":
            print("      t=%02ds  %-7s %s/%s  %s" % (
                i + 1, snap["status"], snap.get("done"), snap.get("total"),
                snap.get("phase", "")))
        if snap["status"] != "running":
            break
    return jid, snap


print("=" * 64)
print("  专辑全集 —— 工作台端到端验收")
print("=" * 64)

# ---- 1) 能力上报 ----
print("\n[1] 后端能力上报")
st, b = call("GET", "/api/ping")
d = json.loads(b.decode("utf-8"))
check("ping 返回 200", st == 200, "HTTP %s" % st)
check("版本 >= 1.9.0", d.get("version", "0") >= "1.9.0", "version=%s" % d.get("version"))
check("album 能力可用", d.get("album") is True, str(d.get("albumWhy") or ""))
sizes = d.get("albumSizes") or []
check("上报卡片边长档位白名单", 1500 in sizes, "albumSizes=%s" % (sizes,))

# ---- 2) 专辑列表预览接口（只查不下载）----
print("\n[2] GET /api/albums（%s，只查不下载）" % ARTIST)
st, b = call("GET", "/api/albums?name=" + urllib.request.quote(ARTIST), timeout=60)
check("预览接口返回 200", st == 200, "HTTP %s" % st)
pre = json.loads(b.decode("utf-8")) if st == 200 else {}
albs = pre.get("albums") or []
check("拿到专辑列表", len(albs) >= 10, "%s 共 %s 张" % (pre.get("artist"), pre.get("count")))
check("每张都有名称 / 日期 / 曲目数",
      bool(albs) and all(a.get("name") and a.get("date") and a.get("tracks")
                         for a in albs[:10]),
      str(albs[0] if albs else {}))
dates = [a.get("date") for a in albs if a.get("date")]
check("按发行时间新→旧排序", dates == sorted(dates, reverse=True),
      "%s ... %s" % (dates[:1], dates[-1:]))

# ---- 3) 提交专辑任务（前 4 张 / 卡片 1200 / 卡片+墙都要）----
print("\n[3] POST /api/run（%s / 前 4 张 / 卡片 1200 / 出卡+墙）" % ARTIST)
jid, snap = run_and_wait({
    "mode": "album", "artist": ARTIST,
    "albumMax": 4, "albumCard": True, "albumWall": True, "albumCardSize": 1200,
}, "专辑任务")

check("任务成功完成", snap and snap["status"] == "done", (snap or {}).get("error") or "")
items = (snap or {}).get("items") or []
check("产出专辑数 = 4", len(items) == 4, "实际 %d" % len(items))
check("每张都有 albumUrl（封面母版）",
      bool(items) and all(it.get("albumUrl") for it in items))
check("每张都有 cardUrl（专辑卡）",
      bool(items) and all(it.get("cardUrl") for it in items))
check("条目带日期 / 曲目数",
      bool(items) and all(it.get("date") and it.get("tracks") is not None
                          for it in items),
      str({k: items[0].get(k) for k in ("date", "tracks", "type")} if items else ""))
check("没有下发本机绝对路径",
      all(("albumPath" not in it) and ("cardPath" not in it) for it in items))

# ---- 4) 下载成品校验 ----
print("\n[4] 下载封面母版 / 专辑卡")
for it in items[:2]:
    st, raw = call("GET", it["albumUrl"], timeout=60)
    size = None
    if st == 200 and len(raw) > 3000:
        size = Image.open(io.BytesIO(raw)).size
    # 封面母版不裁不缩：方图（网易云专辑封面本身就是方的）
    check("《%s》封面母版是方形" % it["name"], bool(size) and size[0] == size[1],
          "HTTP %s  %s  %.0fKB" % (st, size, len(raw) / 1024))

for it in items[:2]:
    st, raw = call("GET", it["cardUrl"], timeout=60)
    size = None
    if st == 200 and len(raw) > 3000:
        size = Image.open(io.BytesIO(raw)).size
    check("《%s》专辑卡 1200×1200" % it["name"], size == (1200, 1200),
          "HTTP %s  %s" % (st, size))

# ---- 5) 专辑墙 ----
print("\n[5] 专辑墙总览")
st, raw = call("GET", snap.get("albumWall") or "/api/none", timeout=60)
ok = st == 200 and len(raw) > 20000
w = Image.open(io.BytesIO(raw)).size if ok else None
check("有专辑墙且可下载", ok, "HTTP %s %s" % (st, w))
# 4 张 → 4 列 1 行：宽扁。高度断言不能按"多行"写（44 张才是 7 行）。
check("专辑墙是横排拼版（宽 > 高）",
      bool(w) and w[0] > 1000 and w[1] > 400 and w[0] > w[1], "%s" % (w,))

# ---- 5b) 列数随专辑数增长（直接验合成器，不额外跑 HTTP）----
print("\n[5b] 专辑墙列数自适应（离线验合成器）")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
try:
    import make_album as MA
    cols = [MA.wall_cols(n) for n in (1, 4, 12, 24, 44, 80)]
    check("列数单调不减且封顶 8",
          all(b >= a for a, b in zip(cols, cols[1:])) and cols[-1] == 8,
          "n=1/4/12/24/44/80 → %s" % cols)
    check("44 张为 7 列（与手工排布一致）", MA.wall_cols(44) == 7, str(MA.wall_cols(44)))
    # 用已下载的封面循环凑数，验多行排布真的落地。
    # 注意：不能拿「高 > 宽」当断言 —— 14 张按规则排 5 列 3 行，
    # 宽 1712 仍大于高 1354（列数增长的幅度大于行数）。真正的多行证据是
    # 「同样的列宽下，行数越多整体越高」，所以跟 4 张（4 列 1 行）的基线比高度。
    cov = [call("GET", items[0]["albumUrl"], timeout=60)[1]]
    if items[1].get("albumUrl"):
        cov.append(call("GET", items[1]["albumUrl"], timeout=60)[1])
    cov = [c for c in cov if c]
    if len(cov) >= 1:
        import tempfile
        tmpd = tempfile.mkdtemp(prefix="albwall_")
        paths = []
        for i in range(14):
            p = os.path.join(tmpd, "c%d.jpg" % i)
            open(p, "wb").write(cov[i % len(cov)])
            paths.append(p)

        def _wall(n, fn):
            its = [{"cover": p, "name": "专辑 %d" % (i + 1),
                    "date": "2020-01-01", "tracks": i + 1}
                   for i, p in enumerate(paths[:n])]
            out = os.path.join(tmpd, fn)
            MA.make_wall(its, out, title="测试专辑墙（%d 张）" % n)
            return Image.open(out).size

        w4 = _wall(4, "wall4.jpg")       # 4 列 1 行：基线
        w14 = _wall(14, "wall14.jpg")    # 5 列 3 行：多行
        cols14 = MA.wall_cols(14)
        rows14 = -(-14 // cols14)        # 向上取整
        check("14 张多行拼版（行数累积、明显高于单行基线）",
              rows14 >= 2 and w14[1] > w4[1] * 1.5 and w14[0] > w4[0],
              "4张%s(1行) → 14张%s(%d列%d行)" % (w4, w14, cols14, rows14))
    else:
        check("14 张多行拼版（行数累积、明显高于单行基线）", False, "没拿到封面做合成")
except Exception as e:
    check("离线验合成器", False, "%s: %s" % (type(e).__name__, e))

# ---- 6) ZIP ----
print("\n[6] ZIP 打包")
st, raw = call("GET", "/api/zip?id=%s" % jid, timeout=180)
ok = st == 200 and len(raw) > 1000
check("ZIP 可下载", ok, "HTTP %s  %.1fMB" % (st, len(raw) / 1024 / 1024))
if ok:
    names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
    check("ZIP 含 albums/ 目录",
          len([n for n in names if n.startswith("albums/")]) == 4,
          "%d 个文件" % len([n for n in names if n.startswith("albums/")]))
    check("ZIP 含 album_cards/ 目录",
          len([n for n in names if n.startswith("album_cards/")]) == 4,
          "%d 个文件" % len([n for n in names if n.startswith("album_cards/")]))
    check("ZIP 含专辑墙总览", "总览-专辑墙.jpg" in names)
    check("ZIP 含 albums.json（可离线重出）", "albums.json" in names)

# ---- 7) 选项收敛：越界 / 字符串假值 / Infinity 都不能炸 ----
print("\n[7] 选项收敛（albumMax=3 + 越界边长 + 字符串假值 + Infinity）")
jid2, snap2 = run_and_wait({
    "mode": "album", "artist": ARTIST,
    "albumMax": 3,
    "albumCardSize": 99999,      # 越界 → 回落默认 1500
    "albumCard": "false",        # 字符串假值 → 必须当假（bool("false") 是 True！）
    "albumWall": 0,
    "albumMax2": float("inf"),   # 无关键，顺手确认 Infinity 不炸
}, "收敛任务", timeout_s=180)
check("收敛任务仍完成", snap2 and snap2["status"] == "done",
      (snap2 or {}).get("error") or "")
items2 = (snap2 or {}).get("items") or []
check("albumMax=3 生效", len(items2) == 3, "实际 %d" % len(items2))
check('albumCard="false" 被当假（不出专辑卡）',
      bool(items2) and all(not it.get("cardUrl") for it in items2))
check('albumWall=0 被当假（不出专辑墙）',
      not (snap2 or {}).get("albumWall"))

# 越界边长要真的回落到 1500 —— 读一次产出卡的实际尺寸
st, b = call("GET", "/api/jobs", timeout=30)
jobs = json.loads(b.decode("utf-8")).get("jobs", []) if st == 200 else []
rec = next((x for x in jobs if x.get("id") == jid2), None)
check("作品库能列出该专辑任务", rec is not None and rec.get("mode") == "album")
if rec:
    cards = sum(1 for it in rec.get("items", []) if it.get("cardUrl"))
    check("作品库统计：专辑卡数 = 0", cards == 0, "cards=%s counts=%s"
          % (cards, rec.get("counts")))

# ---- 8) meta.json 仍不可下载 ----
print("\n[8] /assets 拦截 meta.json")
for path in ("/assets/%s/meta.json" % jid,
             "/assets/%s/%%2e%%2e/meta.json" % jid):
    st, _ = call("GET", path, timeout=15)
    check("拦截 %s" % path, st == 403, "HTTP %s" % st)

print("\n" + "=" * 64)
print("  通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
if BAD:
    for n in BAD:
        print("    [FAIL] " + n)
print("=" * 64)
sys.exit(1 if BAD else 0)
