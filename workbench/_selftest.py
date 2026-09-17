# -*- coding: utf-8 -*-
"""工作台端到端自检: 起服务 -> 打接口 -> 真跑一个歌手 -> 校验产出 -> 关闭"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable

# 自检要访问 127.0.0.1，而本机 HTTP_PROXY 会把本地地址也送去代理（返回 502）。
# 必须在发请求前关掉代理对本地/国内地址的接管，否则自检会假失败。
sys.path.insert(0, os.path.join(ROOT, "tools"))
import noproxy  # noqa: E402,F401

OK, BAD = [], []
LOGF = os.path.join(HERE, "_selftest_out.txt")
_log = open(LOGF, "w", encoding="utf-8")


def say(t):
    print(t, flush=True)
    _log.write(str(t) + "\n")
    _log.flush()


def chk(cond, label, extra=""):
    (OK if cond else BAD).append(label)
    say(("  [PASS] " if cond else "  [FAIL] ") + label + (("  " + extra) if extra else ""))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = free_port()
BASE = f"http://127.0.0.1:{PORT}"


def req(path, method="GET", data=None, raw=None, timeout=180):
    body, headers = None, {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if raw is not None:
        body = raw
        headers["Content-Type"] = "application/octet-stream"
    r = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, resp.read()


say("=" * 62)
say("工作台端到端自检")
say("=" * 62)
say(f"端口 {PORT}")

_srv = open(os.path.join(HERE, "_selftest_server.log"), "w", encoding="utf-8")
proc = subprocess.Popen(
    [PY, "-u", os.path.join(HERE, "server.py"), "--port", str(PORT), "--no-browser"],
    cwd=ROOT, stdout=_srv, stderr=subprocess.STDOUT,
    text=True, encoding="utf-8", errors="replace",
)

try:
    # --- 等服务起来 ---
    up = False
    for _ in range(60):
        try:
            req("/", timeout=3)
            up = True
            break
        except Exception:
            time.sleep(0.4)
    chk(up, "服务启动并可访问")
    if not up:
        raise SystemExit(1)

    # --- 1) 首页 ---
    say("\n[1] 首页")
    st, body = req("/")
    html = body.decode("utf-8", "replace")
    chk(st == 200 and "网易云商品图工作台" in html, "首页返回 HTML",
        f"{len(body)} bytes")
    chk("开始生成" in html and "api/run" in html, "页面含关键控件与接口引用")
    # 钥匙扣开关必须在页面上，并且提交时要真的传 keychain
    chk('id="p_keychain"' in html and "keychain:" in html,
        "页面含钥匙扣开关并会提交该选项")

    # --- 2) 查歌手 ---
    say("\n[2] GET /api/artist")
    st, body = req("/api/artist?name=" + urllib.parse.quote("郑润泽"))
    d = json.loads(body)
    chk(st == 200 and d.get("artist", {}).get("name"), "查到歌手",
        d.get("artist", {}).get("name", ""))
    songs = d.get("songs", [])
    chk(len(songs) > 0, "返回热门歌曲列表", f"{len(songs)} 首")
    if songs:
        say(f"      首条: {songs[0]['name']} - {songs[0]['artist']} "
            f"{songs[0]['dur']}")

    # --- 3) 生成任务 ---
    say("\n[3] POST /api/run (歌手热门 x3)")
    st, body = req("/api/run", "POST",
                   {"mode": "artist", "artist": "郑润泽", "top": 3,
                    "comments": "auto"})
    job = json.loads(body)
    jid = job.get("id")
    chk(bool(jid) and job.get("status") == "running", "任务已创建", f"id={jid}")

    # --- 4) 轮询 ---
    say("\n[4] 轮询进度")
    t0 = time.time()
    last = ""
    final = None
    while time.time() - t0 < 240:
        st, body = req(f"/api/state?id={jid}")
        s = json.loads(body)
        cur = f"{s['done']}/{s['total']} {s['phase']}"
        if cur != last:
            say(f"      {cur}")
            last = cur
        if s["status"] != "running":
            final = s
            break
        time.sleep(0.8)
    chk(final is not None, "任务在超时内结束")
    if final is None:
        raise SystemExit(1)
    chk(final["status"] == "done", "任务状态 done",
        final.get("error") or "")
    items = final.get("items", [])
    chk(len(items) == 3, "产出 3 首", f"实际 {len(items)}")

    # --- 5) 校验产出 ---
    say("\n[5] 校验产出图")
    for it in items:
        say(f"      {it['rank']:02d} {it['name']} — {it['artist']} "
            f"{it['dur']} 评论 {it['comments']}  {it['mm']}")
    if items:
        it = items[0]
        import io as _io
        from PIL import Image
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        from make_player import cover_palette

        st, img = req(it["coverUrl"])
        cim = Image.open(_io.BytesIO(img))
        # 注意: 极简白底封面压完只有 8~9KB, 体积不能当质量判据, 尺寸才是
        # 1492 = 商品图里「清晰封面」那层的边长（母版与画布 1:1，不再二次放大）
        chk(st == 200 and cim.size == (1492, 1492),
            "封面为 1492x1492 母版", f"{len(img)//1024} KB {cim.size}")

        st, pimg = req(it["playerUrl"])
        chk(st == 200 and len(pimg) > 20000, "播放界面可预览",
            f"{len(pimg)//1024} KB")

        # 尺寸 / DPI 落地校验
        rel = urllib.parse.unquote(it["playerUrl"].split("/", 3)[3])
        p = os.path.join(ROOT, "outputs", "工作台", jid, rel)
        im = Image.open(p)
        dpi = im.info.get("dpi", (0, 0))[0]
        mm = (im.size[0] / dpi * 25.4, im.size[1] / dpi * 25.4)
        chk(im.size == (1181, 1968), "播放界面像素 1181x1968", str(im.size))
        chk(abs(dpi - 1000) < 1, "DPI 元数据 = 1000", str(round(dpi, 1)))
        chk(abs(mm[0] - 30) < 0.2 and abs(mm[1] - 50) < 0.2,
            "物理尺寸 = 30x50mm", f"{mm[0]:.2f}x{mm[1]:.2f}mm")

        # 配色跟随校验 —— 实测背景色必须等于 cover_palette 对该封面的预测。
        # 不能用"非中性灰"当判据: 白底/灰底封面本来就该得到深灰背景, 那是正确行为。
        crel = urllib.parse.unquote(it["coverUrl"].split("/", 3)[3])
        cpath = os.path.join(ROOT, "outputs", "工作台", jid, crel)
        exp_top, exp_bot = cover_palette(Image.open(cpath))
        rgb = im.convert("RGB")
        got_top, got_bot = rgb.getpixel((5, 5)), rgb.getpixel((5, im.height - 5))
        dt = max(abs(got_top[i] - exp_top[i]) for i in range(3))
        db = max(abs(got_bot[i] - exp_bot[i]) for i in range(3))
        chk(dt <= 8 and db <= 8, "背景色跟随封面主色",
            f"顶 实测{got_top}/预测{exp_top}  底 实测{got_bot}/预测{exp_bot}")

    # --- 6) 总览 ---
    say("\n[6] 总览图")
    chk(bool(final.get("overview")), "总览已生成",
        final.get("overview") or "")
    if final.get("overview"):
        st, ov = req(final["overview"])
        chk(st == 200 and len(ov) > 10000, "总览可访问", f"{len(ov)//1024} KB")

    # --- 7) ZIP ---
    say("\n[7] ZIP 打包")
    st, z = req(f"/api/zip?id={jid}", timeout=120)
    chk(st == 200 and z[:2] == b"PK", "ZIP 下载可用", f"{len(z)//1024} KB")
    import io as _io
    import zipfile
    with zipfile.ZipFile(_io.BytesIO(z)) as zf:
        names = zf.namelist()
    chk(len([n for n in names if n.startswith("covers/")]) == 3,
        "ZIP 含 3 张封面")
    chk(len([n for n in names if n.startswith("players/") and n.endswith(".png")]) == 3,
        "ZIP 含 3 张 PNG")
    chk(len([n for n in names if n.startswith("players/") and n.endswith(".jpg")]) == 3,
        "ZIP 含 3 张 JPG")
    chk("总览.jpg" in names, "ZIP 含总览")

    # --- 8) 单曲模式 ---
    say("\n[8] 单曲模式")
    st, body = req("/api/song?name=" + urllib.parse.quote("如果呢"))
    d = json.loads(body)
    chk(len(d.get("songs", [])) > 0, "单曲搜索可用",
        f"{len(d.get('songs', []))} 个候选")
    st, body = req("/api/run", "POST",
                   {"mode": "song", "song": "如果呢 郑润泽", "comments": "auto"})
    j2 = json.loads(body)["id"]
    f2 = None
    t0 = time.time()
    while time.time() - t0 < 180:
        st, body = req(f"/api/state?id={j2}")
        s = json.loads(body)
        if s["status"] != "running":
            f2 = s
            break
        time.sleep(0.8)
    chk(f2 and f2["status"] == "done" and f2["items"],
        "单曲出图成功",
        (f2["items"][0]["name"] + " " + f2["items"][0]["mm"]) if f2 and f2["items"] else "")

    # --- 9) 上传模式 ---
    say("\n[9] 上传封面模式")
    src = os.path.join(ROOT, "outputs", "assets", "如果呢 - 郑润泽.jpg")
    if os.path.exists(src):
        with open(src, "rb") as f:
            raw = f.read()
        st, body = req("/api/upload?name=test.jpg", "POST", raw=raw)
        up = json.loads(body)
        chk(bool(up.get("upload")), "图片上传成功", up.get("size", ""))
        st, body = req("/api/run", "POST",
                       {"mode": "upload", "upload": up["upload"],
                        "title": "自定义测试", "artist": "测试歌手",
                        "duration": 257})
        j3 = json.loads(body)["id"]
        f3 = None
        t0 = time.time()
        while time.time() - t0 < 120:
            st, body = req(f"/api/state?id={j3}")
            s = json.loads(body)
            if s["status"] != "running":
                f3 = s
                break
            time.sleep(0.8)
        chk(f3 and f3["status"] == "done" and f3["items"],
            "上传封面合成成功",
            f3["items"][0]["mm"] if f3 and f3["items"] else (f3 or {}).get("error", ""))
    else:
        chk(False, "找到测试用图片", src)

    # --- 10) 异常处理 ---
    say("\n[10] 异常处理")
    try:
        req("/api/artist?name=" + urllib.parse.quote("这个歌手名字肯定不存在xyzq"))
        chk(False, "查不到歌手时应报错")
    except urllib.error.HTTPError as e:
        chk(e.code == 404, "查不到歌手返回 404")
    except Exception as e:
        chk(False, "查不到歌手应报错", str(e))
    try:
        req("/api/state?id=deadbeef")
        chk(False, "非法任务 id 应报错")
    except urllib.error.HTTPError as e:
        chk(e.code == 404, "非法任务 id 返回 404")
    try:
        req("/assets/deadbeef/../../server.py")
        chk(False, "路径穿越应被拦截")
    except urllib.error.HTTPError as e:
        chk(e.code in (403, 404), "路径穿越被拦截", f"HTTP {e.code}")

finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
    try:
        _srv.flush()
        _srv.close()
    except Exception:
        pass

say("")
say("=" * 62)
say(f"结果: {len(OK)} 项通过, {len(BAD)} 项失败")
if BAD:
    say("失败项:")
    for b in BAD:
        say("  - " + b)
say("=" * 62)
