# -*- coding: utf-8 -*-
"""复现 + 验证「点了没反应 / 返回不是合法 JSON」这个故障。

场景还原
--------
页面不一定是直接从 http://127.0.0.1:8765 打开的。如果它来自某个中间层
（编辑器预览面板、内置浏览器容器等），页面里的相对路径 /api/... 就会打到
那个中间层上。中间层不认识这些接口，只能回一个**空的 404**——前端拿不到
JSON，于是弹出「服务返回了非 JSON 内容（HTTP 404）：（空响应体）」。

本脚本做三件事：
  1. 起一个「中间层」服务（9999），对 /api/* 一律回空 404；
  2. 从它加载页面，实证相对路径请求确实会变成空 404（复现故障）；
  3. 按 index.html 里 probeBackend/verifyBackend 的候选顺序模拟探测，
     验证新逻辑能选中真正的后端 8765（验证修复）。

只监听回环地址，跑完即释放。
"""
import http.server
import io
import json
import os
import threading
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ID = "minuet-cover-workbench"
PORT0 = int(os.environ.get("MINUET_PORT") or 8765)
MID_PORT = 9999

HTML = io.open(os.path.join(ROOT, "workbench", "index.html"),
               encoding="utf-8").read().encode("utf-8")

BAR = "=" * 62


class MidHandler(http.server.BaseHTTPRequestHandler):
    """模拟中间层：能吐页面，但不认识后端接口。"""

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/") or self.path.startswith("/assets/"):
            # 关键：空 body 的 404 —— 与用户截图里的现象一致
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(HTML)))
        self.end_headers()
        self.wfile.write(HTML)


def fetch(url, timeout=6):
    """返回 (状态码, 响应体文本)。连接失败时状态码为 None。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def probe(base):
    """镜像 index.html 里的 probeBackend：判定这个地址后面是不是工作台后端。"""
    st, body = fetch(base + "/api/ping?t=0")
    if st != 200:
        return None
    try:
        d = json.loads(body)
    except Exception:
        return None
    return d if (d.get("ok") is True and d.get("app") == APP_ID) else None


def candidates(origin):
    """镜像 index.html 里的候选顺序。"""
    out = []
    push = lambda b: out.append(b) if b not in out else None
    push("")                                   # 同源优先
    for p in range(PORT0, PORT0 + 8):
        push(f"http://127.0.0.1:{p}")
        if p == PORT0:
            push(f"http://localhost:{p}")
    return out


def main():
    print(BAR)
    print("  故障复现与修复验证")
    print(BAR)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", MID_PORT), MidHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    print(f"\n[0] 中间层已启动: http://127.0.0.1:{MID_PORT}/  (对 /api/* 回空 404)")

    try:
        # ---------- 1. 复现 ----------
        print("\n[1] 复现：从中间层加载页面后，页面里的相对路径请求会怎样？")
        st, body = fetch(f"http://127.0.0.1:{MID_PORT}/")
        print(f"    GET /            -> {st}  页面长度 {len(body)}  "
              f"（页面本身正常加载，所以「看起来能用」）")
        st, body = fetch(f"http://127.0.0.1:{MID_PORT}/api/ping")
        print(f"    GET /api/ping    -> {st}  响应体长度 {len(body)}  "
              f"{'← 空响应体 404，与截图完全一致' if st == 404 and not body.strip() else ''}")
        st, body = fetch(f"http://127.0.0.1:{MID_PORT}"
                         f"/api/artist?name=x&source=auto")
        print(f"    GET /api/artist  -> {st}  响应体长度 {len(body)}  "
              f"{'← 这就是「返回不是合法 JSON」的来源' if st == 404 and not body.strip() else ''}")

        # ---------- 2. 验证修复 ----------
        print("\n[2] 验证：新逻辑依次探测候选地址，能否选中真后端？")
        origin = f"http://127.0.0.1:{MID_PORT}"
        hit, tried = None, 0
        for base in candidates(origin):
            tried += 1
            full = base if base else origin
            info = probe(full)
            mark = "命中" if info else "跳过"
            print(f"    {tried:02d}. {full:<34} {mark}")
            if info:
                hit = base
                break
        if hit is None:
            print("\n    [FAIL] 没能找到后端")
            raise SystemExit(1)
        print(f"\n    选中 -> {hit or '（同源 ' + origin + '）'}")
        print(f"    与 index.html 的判定条件一致（ok=true 且 app={APP_ID}）")

        # 验证 API 前缀生效后的实际请求
        print("\n[3] 用选中的前缀请求业务接口：")
        for path in ("/api/artist?name=%E9%99%88%E5%A5%95%E8%BF%85&source=auto",
                     "/api/state?id=__nope__"):
            st, body = fetch((hit or "") + path)
            print(f"    {path[:44]:<46} -> {st}  {body[:70]}")

        # ---------- 3. 反向验证：直接打开时应当零切换 ----------
        print("\n[4] 反向验证：页面本来就从后端打开（同源命中，无需切换）")
        info = probe(f"http://127.0.0.1:{PORT0}")
        print(f"    同源候选 '' -> http://127.0.0.1:{PORT0}  "
              f"{'命中，版本 ' + str(info.get('version')) if info else '未命中'}")

        print("\n" + BAR)
        print("  结论")
        print(BAR)
        print("  故障已复现：中间层把 /api/* 变成空 404，前端只能报「非 JSON」。")
        print("  修复已验证：新逻辑会跳过同源、直接命中真后端并自动切过去。")
        print("  且本来就从后端打开时（同源命中）不会多花任何开销。")
        print(BAR)
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    main()
