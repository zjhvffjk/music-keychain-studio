# -*- coding: utf-8 -*-
"""端到端复现：完整走一遍前端的调用序列，打印每步的真实 HTTP 状态与响应体。

目的：确认服务端到底会不会返回「空响应体 404」。
"""
import json
import os
import time
import urllib.error
import urllib.request

WB_PORT = int(os.environ.get("MINUET_PORT") or 8765)
BASE = f"http://127.0.0.1:{WB_PORT}"
HDR = {"Content-Type": "application/json"}


def call(method, path, body=None, timeout=30):
    url = BASE + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in HDR.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


print("=" * 62)
print("  工作台端到端复现")
print("=" * 62)

st, b = call("GET", "/api/ping")
print(f"\n[1] GET /api/ping          -> {st}  {b[:100]}")

st, b = call("GET", "/")
print(f"[2] GET /                  -> {st}  len={len(b)}"
      f"  含'未开始'={'未开始' in b}  含'/api/ping'={'/api/ping' in b}")

st, b = call("GET", "/api/artist?name=%E9%83%91%E6%B6%A6%E6%B3%BD&source=auto")
print(f"[3] GET /api/artist        -> {st}  len={len(b)}")
if st == 200:
    d = json.loads(b)
    print(f"    歌手={d['artist']['name']}  数据源={d['source']}  曲目={len(d['songs'])}")

print("\n[4] POST /api/run  (郑润泽 / 2 首 / auto)")
st, b = call("POST", "/api/run", {
    "mode": "artist", "artist": "郑润泽", "top": 2,
    "source": "auto", "ratio": 1.0, "width": 1181, "dpi": 1000,
    "vip": True, "follow": True,
}, timeout=60)
print(f"    -> {st}  len={len(b)}")
print(f"    body: {b[:220]}")
if st != 200:
    print("\n!!! 复现成功：服务端确实返回了非预期响应")
    raise SystemExit(1)

jid = json.loads(b)["id"]
print(f"\n    job id = {jid}")

for i in range(40):
    time.sleep(1.0)
    st, b = call("GET", f"/api/state?id={jid}", timeout=15)
    if st != 200:
        print(f"\n!!! 轮询失败 HTTP {st}  len={len(b)}  body={b[:200]!r}")
        break
    d = json.loads(b)
    line = (f"    t={i+1:02d}s  status={d['status']:<7} "
            f"{d.get('done', 0)}/{d.get('total', 0)}  {d.get('phase', '')}")
    print(line)
    if d["status"] != "running":
        print(f"\n    结束状态: {d['status']}")
        if d.get("error"):
            print(f"    错误: {d['error']}")
        print(f"    产出: {len(d.get('items') or [])} 张，跳过 {len(d.get('skipped') or [])}")
        break

st, b = call("GET", f"/api/state?id=__no_such_job__")
print(f"\n[5] GET /api/state?不存在    -> {st}  len={len(b)}  {b[:120]}")

st, b = call("GET", "/api/definitely_not_a_route")
print(f"[6] GET /api/definitely..  -> {st}  len={len(b)}  {b[:120]}")

print("\n" + "=" * 62)
print("  结论：以上若均为带内容的 JSON，则服务端不存在「空响应体 404」，")
print("        用户看到的 404 来自服务端之外的响应者。")
print("=" * 62)
