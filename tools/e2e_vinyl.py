# -*- coding: utf-8 -*-
"""工作台「黑胶播放界面」端到端验收。

覆盖：能力上报（vinyl / vinylWidths）→ 带 vinyl 提交任务 → 每条有 vinylUrl →
      下载成品校验尺寸为 1:2 且与播放图不同 → 黑胶总览 → ZIP 含 vinyl/ →
      宽度白名单收敛（越界值回落默认，不炸内存）。
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


def run_and_wait(body, label, timeout_s=180):
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
        if i % 5 == 0 or snap["status"] != "running":
            print("      t=%02ds  %-7s %s/%s  %s" % (
                i + 1, snap["status"], snap.get("done"), snap.get("total"),
                snap.get("phase", "")))
        if snap["status"] != "running":
            break
    return jid, snap


print("=" * 64)
print("  黑胶播放界面 —— 工作台端到端验收")
print("=" * 64)

# ---- 1) 能力上报 ----
print("\n[1] 后端能力上报")
st, b = call("GET", "/api/ping")
d = json.loads(b.decode("utf-8"))
check("ping 返回 200", st == 200, "HTTP %s" % st)
check("版本 >= 1.8.0", d.get("version", "0") >= "1.8.0", "version=%s" % d.get("version"))
check("vinyl 能力可用", d.get("vinyl") is True, str(d.get("vinylWhy") or ""))
ws = d.get("vinylWidths") or []
check("上报画布宽档位白名单", 1200 in ws, "vinylWidths=%s" % (ws,))

# ---- 2) 提交带黑胶的任务（周杰伦 / 3 首 / 宽 1200）----
print("\n[2] POST /api/run（周杰伦 / 3 首 / 开黑胶 / 宽 1200）")
jid, snap = run_and_wait({
    "mode": "artist", "artist": "周杰伦", "top": 3, "source": "auto",
    "ratio": 1968 / 1181, "width": 1181, "dpi": 1000,
    "vip": True, "follow": True, "vinyl": True, "vinylWidth": 1200,
}, "黑胶任务")

check("任务成功完成", snap and snap["status"] == "done",
      (snap or {}).get("error") or "")
items = (snap or {}).get("items") or []
check("产出条目 >= 3", len(items) >= 3, "实际 %d" % len(items))
check("每条都有 vinylUrl", bool(items) and all(it.get("vinylUrl") for it in items))
check("没有下发本机绝对路径",
      all(("vinylPath" not in it) and ("playerPath" not in it) for it in items))

# ---- 3) 下载成品校验：1:2 且与播放图不同 ----
print("\n[3] 下载黑胶成品")
for it in items[:2]:
    st, raw = call("GET", it["vinylUrl"], timeout=30)
    ok = st == 200 and len(raw) > 30000
    size = None
    if ok:
        im = Image.open(io.BytesIO(raw))
        size = im.size
        ok = size == (1200, 2400)
    check("《%s》黑胶 1200×2400（1:2）" % it["name"], ok,
          "HTTP %s  %s  %.0fKB" % (st, size, len(raw) / 1024))

st, a = call("GET", items[0]["vinylUrl"], timeout=30)
st, c = call("GET", items[0]["playerUrl"], timeout=30)
check("黑胶图与播放图内容不同", a != c, "%d vs %d bytes" % (len(a), len(c)))

# ---- 4) 黑胶总览 ----
print("\n[4] 黑胶总览")
st, raw = call("GET", snap.get("vinylOverview") or "/api/none", timeout=30)
ok = st == 200 and len(raw) > 20000
w = Image.open(io.BytesIO(raw)).size if ok else None
check("有黑胶总览且可下载", ok, "HTTP %s %s" % (st, w))

# ---- 5) ZIP ----
print("\n[5] ZIP 打包")
st, raw = call("GET", "/api/zip?id=%s" % jid, timeout=120)
ok = st == 200 and len(raw) > 1000
check("ZIP 可下载", ok, "HTTP %s  %.1fMB" % (st, len(raw) / 1024 / 1024))
if ok:
    names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
    vn = [n for n in names if n.startswith("vinyl/")]
    check("ZIP 含 vinyl/ 目录", len(vn) >= 3, "%d 个文件" % len(vn))
    check("ZIP 含黑胶总览", "总览-黑胶.jpg" in names)

# ---- 6) 宽档位白名单：越界值必须回落，不能真的去分配巨图 ----
print("\n[6] 宽度白名单收敛（越界 → 回落默认 1200）")
jid2, snap2 = run_and_wait({
    "mode": "artist", "artist": "五月天", "top": 1, "source": "auto",
    "ratio": 1968 / 1181, "width": 1181, "dpi": 1000,
    "vip": True, "follow": True,
    "vinyl": True, "vinylWidth": 99999,
}, "越界宽任务", timeout_s=120)
items2 = (snap2 or {}).get("items") or []
check("越界宽任务仍完成", snap2 and snap2["status"] == "done",
      (snap2 or {}).get("error") or "")
if items2 and items2[0].get("vinylUrl"):
    st, raw = call("GET", items2[0]["vinylUrl"], timeout=30)
    size = Image.open(io.BytesIO(raw)).size if st == 200 else None
    check("越界宽回落为 1200×2400", size == (1200, 2400), "%s" % (size,))
else:
    check("越界宽回落为 1200×2400", False, "没有拿到 vinylUrl")

print("\n" + "=" * 64)
print("  通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
if BAD:
    for n in BAD:
        print("    [FAIL] " + n)
print("=" * 64)
sys.exit(1 if BAD else 0)
