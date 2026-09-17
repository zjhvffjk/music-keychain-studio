# -*- coding: utf-8 -*-
"""白底商品图（shop）功能验收 —— 走 HTTP 接口真跑一次，再验产物与 ZIP。

定位与 ``e2e_keychain.py`` 相同：**不 import 服务端模块、不启服务**，
纯粹当一个前端客户端用，这样测出来的才是用户点「开始生成」时走的那条路。

覆盖：
    1. /api/ping 上报 shop 能力
    2. 带 shop 开关提交任务 → 轮询到完成
    3. 每首应产出 4 个变体（竖长/方形 × 白底/透明），尺寸与比例正确
    4. 拼版总览按选中的画布种类各出一张，且**不足整行时不保留空列**
    5. 白底 JPG 四角为纯白、透明 PNG 真的透明
    6. ZIP 里含 shop/ 目录与商品图总览

用法::

    python tools/e2e_shop.py            # 默认用 5 首
    python tools/e2e_shop.py 3          # 指定首数（顺便验证不足整行的拼版）
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

# 竖长画布的比例 = 钥匙扣外轮廓比例 546:1456 = 0.375（左右留白与上下同比例，故与 pad 无关）;
# 不是卡片内腔的 1:1.667 —— 那个是卡面自己的比例，别混。
OUTLINE_RATIO = 546 / 1456
CARD_RATIO = 1181 / 1968

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
    lines.append("=== 2. 提交任务（%s 前 %d 首，含两个商品图开关）===" % (ARTIST, top))
    req = {
        "mode": "artist", "artist": ARTIST, "top": top, "source": "auto",
        "keychain": True,
        "shop": True, "shopCanvas": "both", "shopBg": "both", "shopGrid": True,
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

    # ---------- 3) 每首 4 个变体 ----------
    lines.append("=== 3. 每首的商品图变体 ===")
    want = {"long_white", "long_transparent", "square_white", "square_transparent"}
    for it in items:
        su = it.get("shopUrls") or {}
        check(set(su.keys()) == want,
              "%s 应有 4 个变体（实际 %d：%s）"
              % (it["name"], len(su), ",".join(sorted(su.keys()))))
        check(bool(it.get("keychainUrl")), "%s 的钥匙扣图应同时产出" % it["name"])

    d = os.path.join(ROOT, "outputs", "工作台", jid)
    sd = os.path.join(d, "shop")

    # ---------- 4) 尺寸与比例 ----------
    lines.append("=== 4. 落盘尺寸 / 比例 ===")
    sizes = {}
    for f in sorted(os.listdir(sd)):
        p = os.path.join(sd, f)
        with Image.open(p) as im:
            sizes[f] = im.size
            tag = ("竖长" if "竖长" in f else "方形") + \
                  ("透明" if "透明" in f else "白底")
            r = im.size[0] / im.size[1]
            exp = OUTLINE_RATIO if tag.startswith("竖长") else 1.0
            check(abs(r - exp) < 0.002,
                  "%-34s %-11s 画布比 %.3f（应 %.3f）"
                  % (f[:32], "%dx%d" % im.size, r, exp))
    check(len(sizes) == top * 4, "shop/ 应有 %d 个文件（实际 %d）"
          % (top * 4, len(sizes)))
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
    check(len(grids) == 2, "应出 2 张拼版（竖长 + 方形），实际 %d" % len(grids))
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
    check(len(shop_in) == top * 4, "ZIP 应含 %d 个 shop/ 文件（实际 %d）"
          % (top * 4, len(shop_in)))
    check(len(grid_in) == 2, "ZIP 应含 2 张商品图总览（实际 %d）" % len(grid_in))
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
