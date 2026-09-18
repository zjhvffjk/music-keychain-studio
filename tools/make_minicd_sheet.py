# -*- coding: utf-8 -*-
"""迷你 CD「印刷版面总览图」—— 1:1 实尺寸 + 裁切/折线 + 尺寸标注。

对标用户给的参考（ChatGPT 那种 ①②③ 三块版面图），但**按 300dpi 1:1 出**：
图上所有元素都是真尺寸，底部 50mm 校验尺量出来就是 50mm，可直接打印核对。

    python tools/make_minicd_sheet.py --cover <封面> --album <专辑> --artist <歌手>
                                      --out <输出目录> [--tracks "A;B;C"] [--company X]

`build_sheet(...)` 被 workbench/design_service.py 复用，避免重复标注绘制。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import fonts  # noqa: E402
import make_minicd as MC  # noqa: E402

DPI = 300


def mm(v, dpi=DPI):
    return int(round(v * dpi / 25.4))


def F(sz, bold=False):
    p = fonts.find_bold() if bold else fonts.find_regular()
    return ImageFont.truetype(p, sz)


INK = (30, 29, 27)
DIM = (124, 120, 115)
LINE = (150, 146, 141)
FOLD = (108, 104, 100)
CUT = (20, 20, 20)
WHITE = (255, 255, 255)


def tick(d, x, y, h=16, col=CUT, w=3):
    d.line([x, y - h // 2, x, y + h // 2], fill=col, width=w)


def dim_h(d, x1, x2, y, col=LINE):
    """横向尺寸线：细线 + 两端刻度。"""
    d.line([x1, y, x2, y], fill=col, width=2)
    tick(d, x1, y, 14, col, 2)
    tick(d, x2, y, 14, col, 2)


def ctext(d, cx, y, s, f, col=INK):
    w = d.textlength(s, font=f)
    d.text((cx - w / 2, y), s, font=f, fill=col)
    return w


def corner_crosses(d, x, y, w, h, arm=22, gap=8, col=CUT, lw=3):
    """四角十字裁切对位标记（放在框外）。"""
    for (cx, cy, sx, sy) in ((x, y, -1, -1), (x + w, y, 1, -1),
                             (x, y + h, -1, 1), (x + w, y + h, 1, 1)):
        d.line([cx + sx * gap, cy, cx + sx * (gap + arm), cy], fill=col, width=lw)
        d.line([cx, cy + sy * gap, cx, cy + sy * (gap + arm)], fill=col, width=lw)


def ruler50(d, x, y, f, col=INK, lbl=DIM):
    """50mm 校验尺 —— 打印后拿尺子量，不足 50mm 说明被缩放了。"""
    L = mm(50)
    d.line([x, y, x + L, y], fill=col, width=max(3, mm(0.6)))
    for i in range(6):
        tx = x + mm(i * 10.0)
        d.line([tx, y - mm(2), tx, y + mm(2)], fill=col, width=max(2, mm(0.4)))
    d.text((x + L + mm(4), y - f.size // 2), "50mm 校验尺（打印后实测）", font=f, fill=lbl)


def build_sheet(cover, album, artist, D, tracks, company, out_path, dpi=DPI, png=False):
    """画 1:1 实尺寸印刷版面总览（①②③ 三件 + 尺寸标注 + 裁切/折线 + 50mm 校验尺）。

    `cover` 为已打开的 PIL Image（RGB）；`D` 为 design_parts.read_design 结果；
    `out_path` 为输出文件（按扩展名决定 png/jpg）。返回输出路径。
    被 design_service 复用，避免重复整套标注绘制。
    """
    parts = {"cover": (cover, False)}
    page, sets, prev = MC.build_page(parts, dpi, "a4l", 1, artist, album, D, tracks, 0, company)
    disc, fold, strip = prev["disc"], prev["cover"], prev["back"]
    print("部件尺寸:", disc.size, fold.size, strip.size)

    # ---------------- 版面尺寸（全部真尺寸） ----------------
    M = max(60, int(round(110 * dpi / 300)))
    G = max(40, int(round(80 * dpi / 300)))
    W = M * 2 + disc.width + G + fold.width + G + strip.width
    YB = int(round(880 * dpi / 300))                      # 三块底边对齐线
    H = int(round(1290 * dpi / 300))

    cv = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(cv)

    # ---------------- 页眉 ----------------
    t = "《%s》%s" % (album or "（未命名）", (" · " + artist) if artist else "")
    d.text((M, int(round(74 * dpi / 300))), t + "　迷你CD 印刷版面（展开图）",
           font=F(int(round(58 * dpi / 300)), True), fill=INK)
    d.text((M, int(round(168 * dpi / 300))),
           "300 DPI · 1:1 实尺寸 · 黑线裁切 / 灰虚线折线 / 十字为对位标记 · "
           "标注尺寸未含出血，需要出血请按各边 +3mm 外扩",
           font=F(int(round(28 * dpi / 300))), fill=DIM)
    leg = [("裁切线", CUT), ("折线", FOLD), ("尺寸线", LINE)]
    lx = W - M
    for name, col in reversed(leg):
        f = F(int(round(26 * dpi / 300)))
        tw = d.textlength(name, font=f)
        lx -= tw
        d.text((lx, int(round(172 * dpi / 300))), name, font=f, fill=DIM)
        lx -= 46
        d.line([lx, int(round(186 * dpi / 300)), lx + 34, int(round(186 * dpi / 300))],
               fill=col, width=4 if name != "折线" else 3)
        lx -= 40
    d.line([M, int(round(232 * dpi / 300)), W - M, int(round(232 * dpi / 300))],
           fill=(222, 219, 215), width=2)

    # ---------------- 区块标题 ----------------
    def head(x, w, no, name, spec):
        d.text((x, int(round(276 * dpi / 300))), "%s %s" % (no, name),
               font=F(int(round(40 * dpi / 300)), True), fill=INK)
        d.text((x, int(round(328 * dpi / 300))), spec, font=F(int(round(26 * dpi / 300))),
               fill=DIM)

    xd = M
    xf = xd + disc.width + G
    xs = xf + fold.width + G
    head(xd, disc.width, "①", "盘面（CD 光盘）", "外径 Ø40mm · 内孔 Ø5mm（打穿）")
    head(xf, fold.width, "②", "封面背面 ＋ 封面（展开）", "82mm × 41mm · 中缝对折成 41×41")
    head(xs, strip.width, "③", "右侧封＋封底＋左侧封＋背脊＋内盘底（展开）",
         "111.2mm × 38mm · 四道折线")

    # ---------------- 放件（底边对齐） ----------------
    cv.paste(disc, (xd, YB - disc.height))
    cv.paste(fold, (xf, YB - fold.height))
    cv.paste(strip, (xs, YB - strip.height))

    # ① 盘面：裁切圆 + 内孔示意 + 中心十字
    cx, cy = xd + disc.width // 2, YB - disc.height // 2
    r = disc.width // 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=CUT, width=3)
    rh = mm(5, dpi) // 2
    d.ellipse([cx - rh, cy - rh, cx + rh, cy + rh], outline=LINE, width=2)
    d.line([cx - rh - 26, cy, cx - rh - 8, cy], fill=LINE, width=2)
    d.line([cx + rh + 8, cy, cx + rh + 26, cy], fill=LINE, width=2)
    corner_crosses(d, xd, YB - disc.height, disc.width, disc.height)

    # ② 折件：外框 + 中缝折线
    d.rectangle([xf, YB - fold.height, xf + fold.width - 1, YB - 1], outline=CUT, width=3)
    fx = xf + fold.width // 2
    for yy in range(YB - fold.height, YB, max(10, int(round(34 * dpi / 300)))):
        d.line([fx, yy, fx, min(yy + 18, YB)], fill=FOLD, width=3)
    corner_crosses(d, xf, YB - fold.height, fold.width, fold.height)

    # ③ 封底条：外框 + 四道折线
    d.rectangle([xs, YB - strip.height, xs + strip.width - 1, YB - 1], outline=CUT, width=3)
    segs = MC.BACK_SEGS
    acc = 0
    segx = [xs]
    for s in segs:
        acc += mm(s, dpi)
        segx.append(xs + acc)
    for bx in segx[1:-1]:
        for yy in range(YB - strip.height, YB, max(10, int(round(34 * dpi / 300)))):
            d.line([bx, yy, bx, min(yy + 18, YB)], fill=FOLD, width=3)
    corner_crosses(d, xs, YB - strip.height, strip.width, strip.height)

    # ---------------- 尺寸标注带 ----------------
    yA = YB + max(20, int(round(44 * dpi / 300)))
    fs = F(int(round(26 * dpi / 300)))
    fn = F(int(round(24 * dpi / 300)), True)

    dim_h(d, xd, xd + disc.width, yA)
    ctext(d, xd + disc.width / 2, yA + 14, "Ø40mm", fn)

    dim_h(d, xf, xf + fold.width, yA)
    for i in range(2):
        seg_c = xf + fold.width / 2 * (i + 0.5)
        ctext(d, seg_c, yA + 14, "41mm", fn)
    tick(d, xf + fold.width // 2, yA, 22, LINE, 2)

    dim_h(d, xs, xs + strip.width, yA)
    for i in range(len(segs)):
        seg_c = (segx[i] + segx[i + 1]) / 2
        ctext(d, seg_c, yA + 14, ("%g" % segs[i]), fn)
    # 竖标（41mm / 38mm）不单独画 —— ② 与 ③ 之间只有 80px 间隙，
    # 竖标必然压到相邻区块（实测踩过）。高度信息放进各块副标题与 ③ 的说明行。

    # ---------------- 说明段 ----------------
    yL = yA + max(30, int(round(66 * dpi / 300)))
    d.line([M, yL, W - M, yL], fill=(222, 219, 215), width=2)
    fl = F(int(round(26 * dpi / 300)))

    d.text((xd, yL + 22), "① 沿黑圆裁切；中心 Ø5mm 打穿（贴片轴）", font=fl, fill=INK)
    d.text((xd, yL + 58), "盘面图案由封面推导（%s / %s）" % (D["mood"], D["style"]),
           font=fl, fill=DIM)

    d.text((xf, yL + 22), "② 左＝封面背面（金句页）／右＝封面正面", font=fl, fill=INK)
    d.text((xf, yL + 58), "沿中缝对折 → 41×41mm 折成卡套", font=fl, fill=DIM)

    d.text((xs, yL + 22), "③ 分段（左→右）：%s"
           % " ｜ ".join("%s %gmm" % (n, s) for n, s in
                        zip(("右侧封", "封底", "左侧封", "背脊", "内盘底"), segs)),
           font=fl, fill=INK)
    d.text((xs, yL + 58), "合计展开 111.2mm × 38mm ｜ 沿四道灰虚线对折后包裹盒身",
           font=fl, fill=DIM)

    # ---------------- 页脚 ----------------
    yF = yL + max(60, int(round(122 * dpi / 300)))
    d.line([M, yF, W - M, yF], fill=(222, 219, 215), width=2)
    ff = F(int(round(26 * dpi / 300)))
    who = " · ".join([s for s in (artist, album) if s]) or "（未填歌手/专辑）"
    foot = ("%s ｜ 迷你CD 印刷版面总览 ｜ 300dpi ｜ 打印设置选「实际大小 / 100%%」，"
            "不要选「适应页面」 ｜ 打印后先量左下校验尺是否 = 50mm" % who)
    d.text((M, yF + 26), foot, font=ff, fill=(120, 117, 113))
    ruler50(d, M, yF + 92, F(int(round(24 * dpi / 300))))

    ext = "png" if png else "jpg"
    cv.save(out_path, **({"quality": 95} if ext == "jpg" else {}))
    print("已生成：%s  (%dx%d)  = %.1f × %.1f mm"
          % (out_path, cv.width, cv.height, cv.width / dpi * 25.4, cv.height / dpi * 25.4))
    return out_path


def main():
    ap = argparse.ArgumentParser(description="迷你CD 印刷版面总览图（1:1）")
    ap.add_argument("--cover", required=True)
    ap.add_argument("--artist", default="")
    ap.add_argument("--album", default="")
    ap.add_argument("--tracks", default="")
    ap.add_argument("--company", default="")
    ap.add_argument("--mood", default="", choices=["", "dreamy", "energetic", "melancholic"])
    ap.add_argument("--style", default="", choices=["", "minimalist", "retro", "bold"])
    ap.add_argument("--out", default="outputs/迷你CD")
    ap.add_argument("--png", action="store_true", help="无损 PNG（默认 JPEG q95）")
    a = ap.parse_args()

    cover = Image.open(a.cover).convert("RGB")
    D = MC.resolve_design(cover, a)
    tracks = [t.strip() for t in a.tracks.replace("；", ";").split(";") if t.strip()] or None
    os.makedirs(a.out, exist_ok=True)
    tag = a.album or "album"
    ext = "png" if a.png else "jpg"
    outp = os.path.join(a.out, "★印刷版面总览-1比1-%s.%s" % (tag, ext))
    build_sheet(cover, a.album, a.artist, D, tracks, a.company, outp, DPI, a.png)


if __name__ == "__main__":
    main()
