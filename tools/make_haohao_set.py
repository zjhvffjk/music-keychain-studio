# -*- coding: utf-8 -*-
"""《好好生活》Be a Better Me —— 三段式可打印套装（对标用户参考图版式）。

① 盘面（Ø40mm / 内孔 Ø5mm）
② 封面背面＋封面（展开 82×41mm，两格 41×41）
③ 右侧封＋封底＋左侧封＋左侧封背面＋内盘底（展开 108.4×38mm）
   = 4.4 + 48 + 4 + 4 + 48 （实测装盒规格，差 1mm 装不进盒）

AI 底图（outputs/好好生活/ai/）由 ImageGen 以封面为 image1 衍生；
本脚本只做「真字合成」：标题/曲目表/真 EAN-13 条码全部压印上去。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw, ImageFilter

from design_parts import _t as F, tracked, ean13
from make_greatest_set import kill_wm, fill_crop, bleed, M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "outputs", "好好生活")
AI = os.path.join(OUT, "ai")

ALBUM_CN = "好好生活"
ALBUM_EN = "Be a Better Me"
SLOGAN_BACK = ["在平凡的日子里", "也要好好生活"]          # 封面背面
SLOGAN_TRAY = ["生活不完美", "但依然值得热爱"]              # 内盘底
LINES_EN = ["MUSIC", "CONNECTS", "A BRIGHTER", "TOMORROW."]
SCRIPT_EN = ["Music", "Connects", "a Brighter", "Tomorrow."]
COPYRIGHT = [
    "© 2026 Good Life Music Co., Ltd. All rights reserved.",
    "Unauthorized copying, reproduction, hiring, lending,",
    "public performance and broadcasting prohibited.",
]
TRACKS = [
    ("01", "早安", "03:12"), ("02", "生活练习", "03:45"),
    ("03", "普通的幸福", "04:08"), ("04", "傻留一点", "03:36"),
    ("05", "慢一点也没关系", "04:21"), ("06", "另一种自己", "03:59"),
    ("07", "城市里的花", "04:03"), ("08", "重新出发", "04:17"),
    ("09", "好好生活", "04:48"), ("10", "Outro", "02:33"),
]
EAN = "6971234567895"   # 校验位按标准算得（参考图 6971234567891 校验位不合法）

INK = (44, 84, 60)        # 深绿主墨（跟叶子走）
INK_SOFT = (72, 104, 82)
PAPER = (222, 226, 168)   # 封底浅绿纸底（从封面取样再微调）
RED = (219, 96, 74)


def draw_heart(d, cx, cy, s, fill):
    """小爱心（两圆+三角），不依赖字体里的 ♡ 字形。"""
    r = s * 0.30
    d.ellipse([cx - s * 0.5, cy - s * 0.42, cx, cy + s * 0.08], fill=fill)
    d.ellipse([cx, cy - s * 0.42, cx + s * 0.5, cy + s * 0.08], fill=fill)
    d.polygon([(cx - s * 0.48, cy - s * 0.05), (cx + s * 0.48, cy - s * 0.05),
               (cx, cy + s * 0.52)], fill=fill)


BACK_SEGS_MM = (4.4, 49.0, 4.4, 4.4, 49.0)   # 111.2 固定结构（spec_minicd 同步）


def paper_bg(w, h, cover):
    """浅绿纸底：取封面左上净空区的纹理放大铺满。"""
    patch = cover.crop((40, 30, 360, 250)).resize((w, h), Image.LANCZOS)
    return patch.convert("RGB")


def load_assets():
    cover = Image.open(os.path.join(OUT, "cover.jpg")).convert("RGB")
    ai = {}
    for name, fn in [("disc", "ai-1-盘面场景.png"),
                     ("park", "ai-2-湖景公园.png"),
                     ("vine", "ai-3-藤蔓装饰.png")]:
        im = Image.open(os.path.join(AI, fn)).convert("RGB")
        ai[name] = kill_wm(im)
    return cover, ai


# ---- ① 盘面 -------------------------------------------------------------
def p_disc(ai, ss=2):
    """Ø40mm 盘面，300dpi=472px，内部按 ss 倍超采样。"""
    D = M(40) * ss                       # 944 @ss2
    base = ai["disc"].resize((D, D), Image.LANCZOS).convert("RGB")
    im = base
    d = ImageDraw.Draw(im)

    # 标题块（左上净空区）
    f_cn = F("hand", int(D * 0.093), ALBUM_CN)
    tracked(d, (int(D * 0.135), int(D * 0.125)), ALBUM_CN, f_cn, INK, 0.06)
    f_en = F("hand_latin", int(D * 0.040), ALBUM_EN)
    tracked(d, (int(D * 0.145), int(D * 0.235)), ALBUM_EN, f_en, INK, 0.02)
    # 左中英文小字
    f_sm = F("sans", int(D * 0.023), "A")
    y = int(D * 0.50)
    for line in LINES_EN:
        tracked(d, (int(D * 0.115), y), line, f_sm, INK_SOFT, 0.14)
        y += int(D * 0.034)

    # 内孔 Ø5mm（白孔 + 细圈）
    hr = M(5) * ss // 2
    cx = cy = D // 2
    d.ellipse([cx - hr - 2, cy - hr - 2, cx + hr + 2, cy + hr + 2],
              fill=(250, 250, 246))
    d.ellipse([cx - hr, cy - hr, cx + hr, cy + hr], fill=(252, 252, 250),
              outline=(190, 192, 180), width=2)

    # 圆形裁切
    mask = Image.new("L", (D, D), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([0, 0, D - 1, D - 1], fill=255)
    out = Image.new("RGB", (D, D), (255, 255, 255))
    out.paste(im, (0, 0), mask)
    if ss > 1:
        out = out.resize((M(40), M(40)), Image.LANCZOS)
    return out


# ---- ② 封面展开 82×41 ---------------------------------------------------
def p_cover_spread(cover, ai, ss=1):
    W, H = M(82) * ss, M(41) * ss
    P = M(41) * ss
    im = Image.new("RGB", (W, H))
    # 左：封面背面（湖景天空城）
    left = fill_crop(ai["park"], P, P, fx=0.10, fy=0.42)
    im.paste(left, (0, 0))
    # 右：封面原画
    right = cover.resize((P, P), Image.LANCZOS)
    im.paste(right, (P, 0))
    d = ImageDraw.Draw(im, "RGBA")

    # 左格文字（天空区）
    f1 = F("hand", int(P * 0.098), SLOGAN_BACK[0])
    y0 = int(P * 0.115)
    tracked(d, (int(P * 0.09), y0), SLOGAN_BACK[0], f1, INK, 0.04)
    tracked(d, (int(P * 0.09), y0 + int(P * 0.135)), SLOGAN_BACK[1],
            f1, INK, 0.04)
    draw_heart(d, int(P * 0.09) + int(P * 0.52), y0 + int(P * 0.155),
               int(P * 0.075), RED)
    f2 = F("hand_latin", int(P * 0.062), "Same")
    tracked(d, (int(P * 0.34), int(P * 0.44)), "Same Heart", f2, INK_SOFT, 0.02)
    tracked(d, (int(P * 0.34), int(P * 0.53)), "Different Days.",
            f2, INK_SOFT, 0.02)

    # 右格标题（左上净空区）
    f3 = F("hand", int(P * 0.105), ALBUM_CN)
    tracked(d, (int(P * 0.055), int(P * 0.075)), ALBUM_CN, f3, INK, 0.06)
    f4 = F("hand_latin", int(P * 0.048), ALBUM_EN)
    tracked(d, (int(P * 0.065), int(P * 0.205)), ALBUM_EN + ".",
            f4, INK, 0.02)

    # 折影：右格左缘轻微暗渐变
    sh = 14 * ss
    for i in range(sh):
        a = int(70 * (1 - i / sh))
        d.line([(P + i, 0), (P + i, H)], fill=(60, 70, 50, a))
    if ss > 1:
        im = im.resize((M(82), M(41)), Image.LANCZOS)
    return im


# ---- ③ 封底条 108.4×38 --------------------------------------------------
def _vine_strip(ai, w, h, box):
    return fill_crop(ai["vine"].crop(box), w, h, fx=0.5, fy=0.5)


def p_backstrip(cover, ai, ss=1):
    W, H = M(108.4) * ss, M(38) * ss
    seg = [M(v) * ss for v in BACK_SEGS_MM]
    assert sum(seg) == W, f"分段宽度和 {sum(seg)} != {W}"
    im = Image.new("RGB", (W, H), (240, 240, 236))
    x = 0
    # 右侧封（藤蔓窄条）
    im.paste(_vine_strip(ai, seg[0], H, (10, 420, 140, 1540)), (x, 0)); x += seg[0]
    # 封底
    bx0 = x
    im.paste(paper_bg(seg[1], H, cover), (x, 0)); x += seg[1]
    # 左侧封
    im.paste(_vine_strip(ai, seg[2], H, (880, 430, 1016, 1600)), (x, 0)); x += seg[2]
    # 左侧封背面（背脊）
    sx0 = x
    im.paste(paper_bg(seg[3], H, cover), (x, 0)); x += seg[3]
    # 内盘底（湖景右段：树+长椅+猫）
    im.paste(fill_crop(ai["park"], seg[4], H, fx=0.92, fy=0.52), (x, 0))

    d = ImageDraw.Draw(im, "RGBA")
    Hs = M(38)

    # -- 封底：标题行
    f_t = F("hand", int(Hs * 0.185), ALBUM_CN)
    tracked(d, (bx0 + int(seg[1] * 0.050), int(Hs * 0.075)),
            ALBUM_CN, f_t, INK, 0.05)
    f_te = F("hand_latin", int(Hs * 0.095), ALBUM_EN)
    tracked(d, (bx0 + int(seg[1] * 0.46), int(Hs * 0.105)),
            ALBUM_EN, f_te, INK_SOFT, 0.02)

    # -- 曲目表（单列 10 行）
    f_no = F("num", int(Hs * 0.070), "0")
    f_nm = F("sans", int(Hs * 0.078), "曲")
    f_tm = F("num", int(Hs * 0.070), "0")
    y0, pitch = int(Hs * 0.315), int(Hs * 0.0525)
    tx = bx0 + int(seg[1] * 0.62)          # 时间右缘
    for i, (no, nm, tm) in enumerate(TRACKS):
        y = y0 + i * pitch
        tracked(d, (bx0 + int(seg[1] * 0.055), y), no, f_no, INK_SOFT, 0)
        tracked(d, (bx0 + int(seg[1] * 0.135), y - int(Hs * 0.006)),
                nm, f_nm, (52, 74, 62), 0.02)
        wtm = d.textlength(tm, font=f_tm)
        tracked(d, (tx - wtm, y), tm, f_tm, INK_SOFT, 0)

    # -- 右侧英文手写体 + 心
    f_sc = F("hand_latin", int(Hs * 0.115), "Music")
    sy = int(Hs * 0.30)
    for line in SCRIPT_EN:
        tracked(d, (bx0 + int(seg[1] * 0.70), sy), line, f_sc, INK, 0.02)
        sy += int(Hs * 0.128)
    draw_heart(d, bx0 + int(seg[1] * 0.79), sy + int(Hs * 0.02),
               int(Hs * 0.085), RED)

    # -- 版权小字
    f_cp = F("sans", int(Hs * 0.038), "A")
    cy = H - int(Hs * 0.185)
    for line in COPYRIGHT:
        tracked(d, (bx0 + int(seg[1] * 0.05), cy), line, f_cp,
                (110, 118, 108), 0)
        cy += int(Hs * 0.048)

    # -- 真 EAN-13 条码（白纸静区连数字一起盖）
    ean13(d, bx0 + int(seg[1] * 0.60), H - int(Hs * 0.30),
          int(seg[1] * 0.335), int(Hs * 0.20), EAN,
          ink=(20, 20, 20), paper=(255, 255, 255))

    # -- 背脊：竖排标题 + 旋转英文 + 心
    scx = sx0 + seg[3] // 2
    f_sp = F("hand", int(Hs * 0.115), ALBUM_CN)
    yy = int(Hs * 0.13)
    for ch in ALBUM_CN:
        wch = d.textlength(ch, font=f_sp)
        d.text((scx - wch / 2, yy), ch, font=f_sp, fill=INK)
        yy += int(Hs * 0.145)
    tmp = Image.new("RGBA", (260, 60), (0, 0, 0, 0))
    td = ImageDraw.Draw(tmp)
    f_se = F("hand_latin", 30, ALBUM_EN)
    tracked(td, (2, 8), ALBUM_EN, f_se, INK_SOFT + (255,), 0.02)
    tmp = tmp.rotate(90, expand=True)
    im.paste(tmp, (sx0 + seg[3] - 34, H - int(Hs * 0.42)), tmp)
    draw_heart(d, scx, int(Hs * 0.72), int(Hs * 0.07), RED)

    # -- 内盘底：slogan（左上天空区）+ 右下小字
    f_g1 = F("hand", int(Hs * 0.135), SLOGAN_TRAY[0])
    gx = x + int(seg[4] * 0.055)
    tracked(d, (gx, int(Hs * 0.10)), SLOGAN_TRAY[0], f_g1, INK, 0.04)
    tracked(d, (gx, int(Hs * 0.10) + int(Hs * 0.175)), SLOGAN_TRAY[1],
            f_g1, INK, 0.04)
    draw_heart(d, gx + int(seg[4] * 0.52),
               int(Hs * 0.10) + int(Hs * 0.20), int(Hs * 0.085), RED)
    f_g2 = F("sans", int(Hs * 0.042), "A")
    tracked(d, (x + seg[4] - int(seg[4] * 0.30), H - int(Hs * 0.14)),
            "SAME HEAT"[:9], f_g2, (240, 242, 225), 0.18)
    tracked(d, (x + seg[4] - int(seg[4] * 0.30), H - int(Hs * 0.085)),
            "DIFFERENT DAYS.", f_g2, (240, 242, 225), 0.18)

    if ss > 1:
        im = im.resize((M(108.4), M(38)), Image.LANCZOS)
    return im


# ---- 总板 ---------------------------------------------------------------
def corner_ticks(d, x0, y0, x1, y1, ink=(150, 152, 150), ln=26, off=10):
    for cx, cy, dx, dy in ((x0, y0, -1, -1), (x1, y0, 1, -1),
                           (x1, y1, 1, 1), (x0, y1, -1, 1)):
        d.line([(cx + dx * off, cy), (cx + dx * (off + ln), cy)], fill=ink, width=2)
        d.line([(cx, cy + dy * off), (cx, cy + dy * (off + ln))], fill=ink, width=2)


def dim_v(d, y1, y2, x, label, ink, size=24):
    d.line((x, y1, x, y2), fill=ink, width=2)
    for yy in (y1, y2):
        d.line((x - 12, yy, x + 12, yy), fill=ink, width=2)
    f = F("sans", size, "0")
    tmp = Image.new("RGBA", (300, 50), (0, 0, 0, 0))
    td = ImageDraw.Draw(tmp)
    tracked(td, (0, 0), label, f, ink + (255,), 0)
    tmp = tmp.rotate(90, expand=True)
    d._image.paste(tmp, (x - 20, (y1 + y2) // 2 - tmp.height // 2), tmp)


def make_board(disc, spread, strip):
    """三段式打印总板（1:1 mm，300dpi，可整板直接打印）。"""
    ink = (52, 54, 50)
    dim = (128, 130, 128)
    MG = 70
    W = MG * 2 + M(108.4) + M(38) + 60          # 条 + 左侧 38mm 标注位
    h1 = 210        # ① 头部
    h2 = 200
    h3 = 210
    H = (h1 + M(40) + 70) + (h2 + M(41) + 80) + (h3 + M(38) + 60) + 190
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    f_h = F("heavy", 40, "①")
    f_s = F("sans", 26, "外")

    # ① 盘面
    y = h1
    tracked(d, (MG, y - 150), "① 盘面（CD光盘）", f_h, ink, 0.02)
    tracked(d, (MG, y - 92), "外直径 40mm　　内直径 5mm", f_s, dim, 0.02)
    dx, dy = MG + 10, y
    corner_ticks(d, dx, dy, dx + M(40), dy + M(40))
    im.paste(disc, (dx, dy))
    d._image = im  # 保持 dim_v 可用

    # ② 封面展开
    y = h1 + M(40) + 70 + h2
    tracked(d, (MG, y - 150), "② 封面背面＋封面（展开尺寸 82mm×41mm）",
            f_h, ink, 0.02)
    x2 = MG + 10
    half = M(41)
    tracked(d, (x2 + half // 2 - 130, y - 88), "封面背面（41mm×41mm）",
            f_s, dim, 0)
    tracked(d, (x2 + half + half // 2 - 110, y - 88), "封面（41mm×41mm）",
            f_s, dim, 0)
    corner_ticks(d, x2, y, x2 + M(82), y + M(41))
    im.paste(spread, (x2, y))
    d.line([(x2 + half, y - 6), (x2 + half, y + M(41) + 6)],
           fill=(170, 172, 168), width=2)      # 折线
    dim_h2(d, x2, x2 + M(82), y + M(41) + 34, "82mm", ink)

    # ③ 封底条
    y = y + M(41) + 80 + h3
    tracked(d, (MG, y - 155),
            "③ 右侧封＋封底＋左侧封＋左侧封背面＋内盘底（展开尺寸 111.2mm×38mm）",
            f_h, ink, 0.02)
    x3 = MG + 10 + M(38) + 50
    corner_ticks(d, x3, y, x3 + M(108.4), y + M(38))
    im.paste(strip, (x3, y))
    # 分段竖线 + 顶部标签
    names = [("右侧封", "4.4mm"), ("封底", "48mm"), ("左侧封", "4mm"),
             ("左侧封背面", "4mm"), ("内盘底", "48mm")]
    bounds = [x3]
    for wmm in (4.4, 48, 4, 4, 48):
        bounds.append(bounds[-1] + M(wmm))
    f_n = F("heavy", 24, "封")
    f_m = F("sans", 20, "4")
    for i, (nm, mm) in enumerate(names):
        cx = (bounds[i] + bounds[i + 1]) // 2
        tracked(d, (cx - d.textlength(nm, font=f_n) / 2, y - 92), nm,
                f_n, ink, 0)
        tracked(d, (cx - d.textlength(mm, font=f_m) / 2, y - 56), mm,
                f_m, dim, 0)
        if 0 < i < len(names) - 1 or i in (1, 2, 3):
            d.line([(bounds[i], y - 30), (bounds[i], y + M(38) + 30)],
                   fill=(185, 187, 183), width=2)
    dim_v(d, y, y + M(38), x3 - 34, "38mm", ink)
    dim_h2(d, x3, x3 + M(108.4), y + M(38) + 34, "108.4mm", ink)

    # 50mm 校验尺 + 页脚
    ry = H - 120
    rx = MG + 10
    d.line((rx, ry, rx + M(50), ry), fill=ink, width=3)
    for i in range(11):
        xx = rx + M(5 * i)
        hh = 16 if i % 2 == 0 else 9
        d.line((xx, ry - hh, xx, ry + 4), fill=ink, width=2)
        if i % 2 == 0:
            lab = str(5 * i)
            f_rl = F("num", 22, "0")
            d.text((xx - d.textlength(lab, font=f_rl) / 2, ry - 46), lab,
                   font=f_rl, fill=ink)
    tracked(d, (rx, ry - 92), "50mm 校验尺（打印后请实测）",
            F("sans", 24, "校"), dim, 0)
    tracked(d, (MG, H - 52),
            "打印设置请选择「实际大小 / 100%」，请勿选「适应页面」。",
            F("sans", 26, "打"), ink, 0)
    return im


def dim_h2(d, x1, x2, y, label, ink):
    d.line((x1, y, x2, y), fill=ink, width=2)
    for xx in (x1, x2):
        d.line((xx, y - 10, xx, y + 10), fill=ink, width=2)
    f = F("sans", 24, "0")
    tw = d.textlength(label, font=f)
    tracked(d, ((x1 + x2 - tw) / 2, y - 34), label, f, ink, 0)


# ---- 印刷版（带 3mm 出血 + 裁切标记）--------------------------------------
def cut_marks(d, x0, y0, x1, y1, ln=30, off=14):
    corner_ticks(d, x0, y0, x1, y1, ink=(0, 0, 0), ln=ln, off=off)


def main():
    cover, ai = load_assets()
    disc = p_disc(ai)
    spread = p_cover_spread(cover, ai)
    strip = p_backstrip(cover, ai)

    assert disc.size == (M(40), M(40)), disc.size
    assert spread.size == (M(82), M(41)), spread.size
    assert strip.size == (M(108.4), M(38)), strip.size

    disc.save(os.path.join(OUT, "01-盘面.png"), dpi=(300, 300))
    spread.save(os.path.join(OUT, "02-封面展开.png"), dpi=(300, 300))
    strip.save(os.path.join(OUT, "03-封底条.png"), dpi=(300, 300))

    # 印刷版（出血 + 标记）
    b = M(3)
    pd = Image.new("RGB", (M(40) + 2 * b, M(40) + 2 * b), (255, 255, 255))
    pd.paste(disc, (b, b))
    dd = ImageDraw.Draw(pd)
    cut_marks(dd, b, b, b + M(40), b + M(40))
    pd.save(os.path.join(OUT, "01-盘面-印刷.png"), dpi=(300, 300))

    for name, art, folds in (("02-封面展开-印刷.png", spread, [M(41)]),
                             ("03-封底条-印刷.png", strip,
                              [M(4.4), M(4.4 + 48), M(4.4 + 48 + 4),
                               M(4.4 + 48 + 4 + 4)])):
        pb = bleed(art)
        w, h = art.size
        dd = ImageDraw.Draw(pb)
        cut_marks(dd, b, b, b + w, b + h)
        for fx in folds:
            dd.line([(b + fx, 0), (b + fx, 12)], fill=(0, 0, 0), width=2)
            dd.line([(b + fx, h + 2 * b - 12), (b + fx, h + 2 * b)],
                    fill=(0, 0, 0), width=2)
        pb.save(os.path.join(OUT, name), dpi=(300, 300))

    board = make_board(disc, spread, strip)
    board.save(os.path.join(OUT, "★打印总板.jpg"), quality=92)
    print("sizes:", disc.size, spread.size, strip.size, board.size)
    print("DONE ->", OUT)


if __name__ == "__main__":
    main()
