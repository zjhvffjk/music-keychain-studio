# -*- coding: utf-8 -*-
"""白底商品图（shop）功能验收 —— 走 HTTP 接口真跑一次，再验产物与 ZIP。

定位与 ``e2e_keychain.py`` 相同：**不 import 服务端模块、不启服务**，
纯粹当一个前端客户端用，这样测出来的才是用户点「开始生成」时走的那条路。

覆盖：
    1. /api/ping 上报 shop 能力
    2. 带 shop 开关提交任务 → 轮询到完成
    3. 每首应产出「选中画布数 × 2」个变体，尺寸与预设声明完全一致
    4. 拼版总览按选中的画布种类各出一张，且**不足整行时不保留空列**
    5. 白底 JPG 四角为纯白、透明 PNG 真的透明
    6. ZIP 里含 shop/ 目录与商品图总览

断言用的画布尺寸取自 config/canvas_presets.json —— 改了预设不用回来改测试。

用法::

    python tools/e2e_shop.py             # 默认 5 首，画布 long+square
    python tools/e2e_shop.py 3           # 指定首数（顺便验证不足整行的拼版）
    E2E_CANVAS=long,taobao python tools/e2e_shop.py 3    # 指定画布预设
    MINUET_PORT=9000 python tools/e2e_shop.py
"""
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import noproxy  # noqa: E402,F401  —— 本机代理会拦 127.0.0.1，必须绕开

from PIL import Image  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "http://127.0.0.1:%s" % os.environ.get("MINUET_PORT", "8765")
ARTIST = os.environ.get("E2E_ARTIST", "五月天")

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 画布预设住在 config/canvas_presets.json —— 验收脚本按它**动态**断言，
# 这样加了新预设、或调了尺寸，不用回来改测试。
with io.open(os.path.join(ROOT, "config", "canvas_presets.json"), encoding="utf-8") as _f:
    _raw = json.load(_f)
PRESETS = {k: v for k, v in _raw.items() if not k.startswith("_") and isinstance(v, dict)}

# 本次验收用哪几种画布（默认沿用基础两款）
CANVASES = [x.strip() for x in
            os.environ.get("E2E_CANVAS", "long,square").split(",") if x.strip()]

# 竖长画布的比例 = 钥匙扣外轮廓比例 546:1456 = 0.375（左右留白与上下同比例，故与 pad 无关）;
# 不是卡片内腔的 1:1.667 —— 那个是卡面自己的比例，别混。
OW, OH = 546, 1456
OUTLINE_RATIO = OW / OH
CARD_RATIO = 1181 / 1968


def _pad_of(p):
    """与 make_keychain_shop._norm_preset 同口径：非法值夹到 [0.01, 0.44]。"""
    try:
        pad = float(p.get("pad", 0.07))
    except Exception:
        pad = 0.07
    if not (0.01 <= pad <= 0.44):
        pad = min(max(pad, 0.01), 0.44)
    return pad


def expect_size(key):
    """按 canvas_presets.json 反算某画布的成品尺寸（与 canvas_size() 同逻辑）。"""
    p = PRESETS[key]
    pad = _pad_of(p)
    h = int(p["h"])
    th = round(h * (1 - 2 * pad))
    need = round(OW * th / OH)
    w = p.get("w")
    return (int(w) if w else round(need / (1 - 2 * pad))), h


def preset_tag(key):
    return PRESETS.get(key, {}).get("tag") or key

lines = []
fails = []


def check(cond, msg):
    lines.append("  %s %s" % ("[OK]  " if cond else "[FAIL]", msg))
    if not cond:
        fails.append(msg)
    return cond


def call(path, payload=None, timeout=30):
    url = BASE + path
    if payload is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    top = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    # ---------- 1) 能力上报 ----------
    lines.append("=== 1. /api/ping ===")
    ping = call("/api/ping")
    lines.append("  version=%s keychain=%s shop=%s"
                 % (ping.get("version"), ping.get("keychain"), ping.get("shop")))
    if not check(ping.get("shop") is True,
                 "ping 应上报 shop=true（实际 %r，原因：%s）"
                 % (ping.get("shop"), ping.get("shopWhy"))):
        return finish()

    # ---------- 2) 提交任务 ----------
    lines.append("=== 2. 提交任务（%s 前 %d 首，画布=%s）==="
                 % (ARTIST, top, ",".join(CANVASES)))
    req = {
        "mode": "artist", "artist": ARTIST, "top": top, "source": "auto",
        "keychain": True,
        "shop": True, "shopCanvas": CANVASES, "shopBg": "both", "shopGrid": True,
    }
    st = call("/api/run", req)
    jid = st["id"]
    lines.append("  job=%s" % jid)

    t0 = time.time()
    last = None
    while time.time() - t0 < 600:
        s = call("/api/state?id=%s" % jid)
        if s.get("phase") != last:
            last = s.get("phase")
            lines.append("  [%5.1fs] %s  %s/%s"
                         % (time.time() - t0, last, s.get("done"), s.get("total")))
        if s.get("status") in ("done", "error"):
            break
        time.sleep(2)
    s = call("/api/state?id=%s" % jid)
    lines.append("  status=%s elapsed=%ss error=%r"
                 % (s["status"], s.get("elapsed"), s.get("error")))
    if not check(s["status"] == "done", "任务应成功完成"):
        for l in s.get("log", [])[-20:]:
            lines.append("    %s %s" % (l.get("lv"), l.get("m")))
        return finish()

    items = s.get("items", [])
    check(len(items) == top, "应产出 %d 首（实际 %d）" % (top, len(items)))

    # ---------- 3) 每首的商品图变体 ----------
    lines.append("=== 3. 每首的商品图变体 ===")
    want = {f"{k}_{bg}" for k in CANVASES for bg in ("white", "transparent")}
    for it in items:
        su = it.get("shopUrls") or {}
        check(set(su.keys()) == want,
              "%s 应有 %d 个变体（实际 %d：%s）"
              % (it["name"], len(want), len(su), ",".join(sorted(su.keys()))))
        check(bool(it.get("keychainUrl")), "%s 的钥匙扣图应同时产出" % it["name"])

    d = os.path.join(ROOT, "outputs", "工作台", jid)
    sd = os.path.join(d, "shop")

    # ---------- 4) 尺寸（直接比对预设声明的成品尺寸）----------
    lines.append("=== 4. 落盘尺寸 ===")
    sizes = {}
    for f in sorted(os.listdir(sd)):
        p = os.path.join(sd, f)
        # tag 按长度降序匹配：否则「淘宝」会把「淘宝主图」的文件认走，断言误报
        kind = None
        for k in sorted(CANVASES, key=lambda x: -len(preset_tag(x))):
            if ("-商品图-%s" % preset_tag(k)) in f:
                kind = k
                break
        if kind is None:
            check(False, "文件名认不出是哪个画布预设：%s" % f)
            continue
        with Image.open(p) as im:
            sizes[f] = im.size
            ew, eh = expect_size(kind)
            check(im.size == (ew, eh),
                  "%-30s %dx%d（应 %dx%d）"
                  % (f[:28], im.width, im.height, ew, eh))
    want_n = top * len(CANVASES) * 2
    check(len(sizes) == want_n, "shop/ 应有 %d 个文件（实际 %d）" % (want_n, len(sizes)))
    lines.append("  （卡面本身是 1:%.3f，与内腔一致，故缩放不变形）" % (1 / CARD_RATIO))

    # ---------- 5) 白底真白 / 透明真透明 ----------
    lines.append("=== 5. 底色校验 ===")
    for f in sorted(os.listdir(sd)):
        p = os.path.join(sd, f)
        with Image.open(p) as im:
            if "透明" in f:
                a = im.convert("RGBA").getchannel("A")
                lo, hi = a.getextrema()
                check(lo == 0, "%-34s 应有全透明像素（alpha min=%d）" % (f[:32], lo))
            else:
                px = im.convert("RGB").load()
                w, h = im.size
                corners = [px[2, 2], px[w - 3, 2], px[2, h - 3], px[w - 3, h - 3]]
                check(all(c == (255, 255, 255) for c in corners),
                      "%-34s 四角应为纯白（实际 %s）" % (f[:32], corners))

    # ---------- 6) 拼版总览 ----------
    lines.append("=== 6. 拼版总览 ===")
    grids = s.get("shopGrids") or []
    check(len(grids) == len(CANVASES),
          "应出 %d 张拼版（每种画布一张），实际 %d" % (len(CANVASES), len(grids)))
    for g in grids:
        name = os.path.basename(g["url"].split("/")[-1])
        rel = urllib.parse.unquote(g["url"].split("/", 3)[-1])
        gp = os.path.join(d, rel)
        if not os.path.exists(gp):
            check(False, "拼版文件不存在：%s" % rel)
            continue
        with Image.open(gp) as im:
            gw, gh = im.size
        # 单元宽 360 + 间距 12% + 外边距 24%，列数取 min(5, 张数)
        cols = min(5, len(items))
        cells = 360 * cols + round(360 * 0.12) * (cols - 1) + round(360 * 0.24) * 2
        check(abs(gw - cells) <= 2,
              "%s 宽 %d 应约等于 %d（列数 %d，不足整行不留空列）" % (name, gw, cells, cols))

    # ---------- 7) ZIP ----------
    lines.append("=== 7. ZIP ===")
    with OPENER.open(BASE + "/api/zip?id=%s" % jid, timeout=180) as r:
        blob = r.read()
    zp = os.path.join(ROOT, "_tmp", "e2e_shop.zip")
    os.makedirs(os.path.dirname(zp), exist_ok=True)
    with open(zp, "wb") as f:
        f.write(blob)
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
    shop_in = [n for n in names if n.startswith("shop/")]
    grid_in = [n for n in names if n.startswith("总览-商品图")]
    check(len(shop_in) == want_n, "ZIP 应含 %d 个 shop/ 文件（实际 %d）"
          % (want_n, len(shop_in)))
    check(len(grid_in) == len(CANVASES),
          "ZIP 应含 %d 张商品图总览（实际 %d）" % (len(CANVASES), len(grid_in)))
    lines.append("  zip %.1fMB / %d 项" % (len(blob) / 1048576, len(names)))
    return finish(jid)


def finish(jid=None):
    lines.append("")
    lines.append("=" * 46)
    if fails:
        lines.append("结果：失败 %d 项" % len(fails))
        for m in fails:
            lines.append("  × " + m)
    else:
        lines.append("结果：全部通过")
    if jid:
        lines.append("产物：outputs/工作台/%s/" % jid)
    text = "\n".join(lines)
    with io.open(os.path.join(ROOT, "_tmp", "e2e_shop_report.txt"), "w",
                 encoding="utf-8") as f:
        f.write(text)
    print(text)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
