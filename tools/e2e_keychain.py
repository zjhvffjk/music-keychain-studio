# -*- coding: utf-8 -*-
"""工作台「钥匙扣商品图」端到端验收。

覆盖：能力上报 → 带 keychain 提交任务 → 轮询拿到 keychainUrl →
      下载成品校验尺寸 → 总览 → ZIP 里含 keychain/ 与钥匙扣总览。
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


print("=" * 64)
print("  钥匙扣商品图 —— 工作台端到端验收")
print("=" * 64)

# ---- 1) 能力上报 ----
print("\n[1] 后端能力上报")
st, b = call("GET", "/api/ping")
d = json.loads(b.decode("utf-8"))
check("ping 返回 200", st == 200, "HTTP %s" % st)
check("版本 >= 1.3.0", d.get("version", "0") >= "1.3.0", "version=%s" % d.get("version"))
check("keychain 能力可用", d.get("keychain") is True, str(d.get("keychainWhy") or ""))

# ---- 2) 提交带钥匙扣的任务 ----
print("\n[2] POST /api/run（周杰伦 / 3 首 / 开钥匙扣）")
st, b = call("POST", "/api/run", {
    "mode": "artist", "artist": "周杰伦", "top": 3, "source": "auto",
    "ratio": 1968 / 1181, "width": 1181, "dpi": 1000,
    "vip": True, "follow": True, "keychain": True,
}, timeout=90)
check("提交返回 200", st == 200, "HTTP %s" % st)
if st != 200:
    print(b[:400].decode("utf-8", "replace"))
    sys.exit(1)
jid = json.loads(b.decode("utf-8"))["id"]
print("      job = %s" % jid)

# ---- 3) 轮询 ----
print("\n[3] 轮询进度")
snap = None
for i in range(150):
    time.sleep(1.0)
    st, b = call("GET", "/api/state?id=%s" % jid, timeout=20)
    if st != 200:
        check("轮询返回 200", False, "HTTP %s" % st)
        break
    snap = json.loads(b.decode("utf-8"))
    if i % 5 == 0 or snap["status"] != "running":
        print("      t=%02ds  %-7s %s/%s  %s" % (
            i + 1, snap["status"], snap.get("done"), snap.get("total"),
            snap.get("phase", "")))
    if snap["status"] != "running":
        break

check("任务成功完成", snap and snap["status"] == "done",
      (snap or {}).get("error") or "")
items = (snap or {}).get("items") or []
check("产出条目 >= 3", len(items) >= 3, "实际 %d" % len(items))
check("每条都有 keychainUrl",
      items and all(it.get("keychainUrl") for it in items))
check("没有下发本机绝对路径",
      all("keychainPath" not in it and "playerPath" not in it for it in items))

# ---- 4) 下载成品校验 ----
print("\n[4] 下载钥匙扣成品")
for it in items[:2]:
    st, raw = call("GET", it["keychainUrl"], timeout=30)
    ok = st == 200 and len(raw) > 50000
    size = None
    if ok:
        im = Image.open(io.BytesIO(raw))
        size = im.size
        ok = size == (1920, 1920)
    check("《%s》钥匙扣 1920×1920" % it["name"], ok,
          "HTTP %s  %s  %.0fKB" % (st, size, len(raw) / 1024))

# 钥匙扣图和播放图必须不同（否则等于没叠上去）
st, a = call("GET", items[0]["keychainUrl"], timeout=30)
st, c = call("GET", items[0]["playerUrl"], timeout=30)
check("钥匙扣图与播放图内容不同", a != c, "%d vs %d bytes" % (len(a), len(c)))

# ---- 5) 总览 ----
print("\n[5] 总览图")
check("有 30×50mm 总览", bool(snap.get("overview")))
st, raw = call("GET", snap.get("keychainOverview") or "/api/none", timeout=30)
ok = st == 200 and len(raw) > 20000
w = Image.open(io.BytesIO(raw)).size if ok else None
check("有钥匙扣总览且可下载", ok, "HTTP %s %s" % (st, w))

# ---- 6) ZIP ----
print("\n[6] ZIP 打包")
st, raw = call("GET", "/api/zip?id=%s" % jid, timeout=120)
ok = st == 200 and len(raw) > 1000
check("ZIP 可下载", ok, "HTTP %s  %.1fMB" % (st, len(raw) / 1024 / 1024))
if ok:
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = z.namelist()
    kc = [n for n in names if n.startswith("keychain/")]
    check("ZIP 含 keychain/ 目录", len(kc) >= 3, "%d 个文件" % len(kc))
    check("ZIP 含钥匙扣总览", "总览-钥匙扣.jpg" in names)
    check("ZIP 含封面与播放图",
          any(n.startswith("covers/") for n in names) and
          any(n.startswith("players/") for n in names))

print("\n" + "=" * 64)
print("  通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
if BAD:
    for n in BAD:
        print("    [FAIL] " + n)
print("=" * 64)
sys.exit(1 if BAD else 0)
