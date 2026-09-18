# -*- coding: utf-8 -*-
"""《最偉大的作品》整案包装 —— AI 场景扩图 + 真字合成 + 印刷档案。

对标用户给的参考（ChatGPT 5 阶段方案的成品）：
  ① 提案图（10 件带编号标注的总览）
  ② 印刷档案图（3mm 出血 / 裁切线 / 折线 / 尺寸标注 / 印刷规范）

场景扩图 = ImageGen 图生图（封面做 image1 参考），本脚本只做「真字合成」：
曲目/歌词/手写金句/真 EAN-13 条码全部用 typo 层的印刷体+楷体压上去。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from PIL import Image, ImageDraw, ImageFilter

from design_parts import (  # noqa: E402
    _t as F, tracked, hand_text, hairline, ean13, make_ean, phonogram,
    read_design, design_disc2, scrim, ink_on, dim_ink, lum,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "outputs", "最偉大的作品")
AI = os.path.join(OUT, "ai")

# ---- 印刷规格（300 DPI）-------------------------------------------------
DPI = 300
def M(mm):
    return round(mm * DPI / 25.4)

BLEED = M(3)          # 3mm 出血 = 35px
ALBUM_EN = "GREATEST WORKS OF ART"
ALBUM_CN = "最偉大的作品"
ARTIST_EN = "JAY CHOU"
ARTIST_CN = "周杰倫"
COMPANY = "JVR MUSIC"

# 真曲目（网易云专辑 147779282 顺序，转繁体以贴封面口径）
TRACKS = [
    "Intro", "最偉大的作品", "還在流浪", "說好不哭", "紅顏如霜",
    "不愛我就拉倒", "Mojito", "等你下課", "粉色海洋", "倒影",
    "我是如此相信", "錯過的煙火",
]
# 《等你下課》真歌词（网易云 1962166937，前 16 行 + 省略号）
LYRICS = [
    "你住的 巷子里", "我租了一间公寓", "为了想与你不期而遇",
    "高中三年 我为什么", "为什么不好好读书", "没考上跟你一样的大学",
    "我找了份工作", "离你宿舍很近", "当我开始学会做蛋饼",
    "才发现你 不吃早餐", "喔 你又擦肩而过", "你耳机听什么",
    "能不能告诉我", "躺在你学校的操场看星空", "教室里的灯还亮着你没走",
    "记得 我写给你的情书",
]

MANIFESTO_EN = ["Art is never far from life.", "It flows in time,",
                "lives in every memory,", "and appears in the scenery"]
TAGLINE_CN = "藝術，來自生活；也回到每一個平凡的日子。"


# ---- 素材 ---------------------------------------------------------------
def kill_wm(im):
    """抹掉右下角「AI生成 WORKBUD>」水印：用左侧同高区域平移覆盖 + 羽化。"""
    w, h = im.size
    bw, bh = int(w * 0.30), int(h * 0.09)
    x0, y0 = w - bw, h - bh
    patch = im.crop((x0 - bw - 10, y0, x0 - 10, y0 + bh)).copy()
    m = Image.new("L", (bw, bh), 0)
    md = ImageDraw.Draw(m)
    for i in range(24):
        md.rectangle((i, i, bw - 1 - i, bh - 1 - i), outline=255 - i * 10)
    md.rectangle((24, 24, bw - 25, bh - 25), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(6))
    im.paste(patch, (x0, y0), m)
    return im


def load_assets():
    cover = Image.open(os.path.join(OUT, "cover.jpg")).convert("RGB")
    ai = {}
    for name, fn in [("piano", "ai-1-钢琴.png"), ("desk", "ai-2-书桌.png"),
                     ("beach", "ai-3-海滩.png"), ("lamp", "ai-4-街灯.png"),
                     ("sunset", "ai-5-日落海报.png")]:
        p = os.path.join(AI, fn)
        im = Image.open(p).convert("RGB")
        ai[name] = kill_wm(im)
    return cover, ai


def fill_crop(im, w, h, fx=0.5, fy=0.5):
    """cover-fill 裁剪到目标比例。"""
    sw, sh = im.size
    scale = max(w / sw, h / sh)
    nw, nh = int(sw * scale + 0.5), int(sh * scale + 0.5)
    im = im.resize((nw, nh), Image.LANCZOS)
    x = int((nw - w) * fx)
    y = int((nh - h) * fy)
    return im.crop((x, y, x + w, y + h))


def bleed(art, b=BLEED):
    """印刷版：四边镜像延展出血。"""
    w, h = art.size
    cv = Image.new("RGB", (w + 2 * b, h + 2 * b))
    cv.paste(art, (b, b))
    L = art.crop((0, 0, b, h)).transpose(Image.FLIP_LEFT_RIGHT)
    R = art.crop((w - b, 0, w, h)).transpose(Image.FLIP_LEFT_RIGHT)
    T = art.crop((0, 0, w, b)).transpose(Image.FLIP_TOP_BOTTOM)
    B = art.crop((0, h - b, w, h)).transpose(Image.FLIP_TOP_BOTTOM)
    cv.paste(L, (0, b))
    cv.paste(R, (w + b, b))
    cv.paste(T, (b, 0))
    cv.paste(B, (b, h + b))
    cv.paste(T.transpose(Image.FLIP_LEFT_RIGHT), (0, 0))
    cv.paste(T.transpose(Image.FLIP_LEFT_RIGHT), (w + b, 0))
    cv.paste(B.transpose(Image.FLIP_LEFT_RIGHT), (0, h + b))
    cv.paste(B.transpose(Image.FLIP_LEFT_RIGHT), (w + b, h + b))
    return cv


# ---- 十件部件 -----------------------------------------------------------
def sky_of(cover):
    """封面天空色 → 纸色基调。"""
    sm = cover.resize((50, 50))
    px = [sm.getpixel((x, y)) for x in range(50) for y in range(6)]
    n = len(px)
    return tuple(sum(c[i] for c in px) // n for i in range(3))


def vgrad2(w, h, top, bottom):
    g = Image.new("RGB", (1, h))
    for y in range(h):
        k = y / max(1, h - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3)))
    return g.resize((w, h))


def p_cover(cover):
    """01 封面正面 142×125 —— 原封面按 1.136:1 裁。"""
    art = fill_crop(cover, M(142), M(125), fy=0.42)
    return art


def p_back(cover):
    """02 封底背面 142×125 —— 曲目 + 手写金句 + 真条码 + 版权。"""
    w, h = M(142), M(125)
    sky = sky_of(cover)
    paper = vgrad2(w, h, sky, tuple(min(255, int(c * 1.10 + 22)) for c in sky))
    art = paper.convert("RGB")
    d = ImageDraw.Draw(art)
    ink = (32, 36, 42)
    dim = (120, 126, 134)

    # 左上小标
    f0 = F("serif", 34, ALBUM_EN)
    tracked(d, (int(w * 0.14), int(h * 0.075)), ALBUM_EN, f0, ink, 2.2)
    f0c = F("serif", 34, ALBUM_CN)
    tracked(d, (int(w * 0.14), int(h * 0.075) + 46), ALBUM_CN, f0c, ink, 3.0)
    hairline(d, int(w * 0.14), int(h * 0.075) + 96, int(w * 0.40), dim)

    # 曲目单列
    y0 = int(h * 0.16)
    lead = int(h * 0.052)
    for i, t in enumerate(TRACKS):
        y = y0 + i * lead
        fn = F("num", 30, "01")
        tracked(d, (int(w * 0.14), y + 4), "%02d" % (i + 1), fn, dim, 1.0)
        ft = F("serif", 40, t)
        tracked(d, (int(w * 0.14) + 88, y), t, ft, ink, 1.2)

    # 右下手写金句
    qx, qy = int(w * 0.60), int(h * 0.50)
    hand_text(art, (qx, qy), "藝術 藏在平凡的日子裡", 54, (52, 58, 70), 2.0, angle=-2.0)
    hand_text(art, (qx + 26, qy + 78), "也能閃閃發光", 54, (52, 58, 70), 2.0, angle=-2.0)
    hand_text(art, (qx + 150, qy + 156), "Jay Chou", 44, (96, 104, 116), 1.0, angle=-2.0)

    # 条码（真 EAN-13）+ 版权
    bx, by, bw_, bh_ = int(w * 0.14), int(h * 0.815), int(w * 0.26), int(h * 0.135)
    d.rounded_rectangle((bx, by, bx + bw_, by + bh_), 10, fill=(250, 250, 250))
    code = make_ean(20220902)
    ean13(d, bx + 16, by + 12, bw_ - 32, bh_ - 44, code)
    fbc = F("num", 24, "0")
    tracked(d, (bx + 16, by + bh_ - 34), code, fbc, (40, 40, 44), 2.0)
    phonogram(d, bx + bw_ + 40, by + 10, 26, ink)
    fc = F("sans", 26, "©")
    tracked(d, (bx + bw_ + 76, by + 8), "2022 JVR Music Int'l Co., Ltd. 杰威爾音樂有限公司", fc, dim, 0.6)
    return art


def p_spine(cover):
    """03 侧标 12×125。横排渲染后转竖。"""
    w, h = M(125), M(12)
    sky = sky_of(cover)
    im = Image.new("RGB", (w, h), sky)
    d = ImageDraw.Draw(im)
    ink = ink_on(sky)
    dim = dim_ink(ink, sky)
    f1 = F("serif", 56, ALBUM_EN)
    x = 60
    x += tracked(d, (x, h // 2 - 30), ALBUM_EN, f1, ink, 2.0) + 40
    f2 = F("serif", 56, ALBUM_CN)
    x += tracked(d, (x, h // 2 - 30), ALBUM_CN, f2, ink, 4.0) + 40
    f3 = F("serif", 56, ARTIST_EN)
    tracked(d, (x, h // 2 - 30), ARTIST_EN, f3, dim, 2.0)
    fr = F("heavy", 52, "J")
    tracked(d, (w - 190, h // 2 - 28), COMPANY, fr, ink, 1.5)
    return im.rotate(-90, expand=True)


def p_disc(cover, D):
    """04 CD 盘面 Ø118 / 内圈 Ø46。"""
    return design_disc2(cover, M(118), M(46), D, album=ALBUM_CN, artist=ARTIST_CN,
                        company=COMPANY)


def p_sleeve(ai):
    """05 内封套 125×125 —— 海滩 + 英文手写。"""
    art = fill_crop(ai["beach"], M(125), M(125), fy=0.45)
    scrim(art, top=0.30, power=1.8)
    hand_text(art, (int(art.width * 0.93), int(art.height * 0.10)),
              "Different eras", 62, (252, 252, 250), 1.4, "right", angle=-2.0)
    hand_text(art, (int(art.width * 0.93), int(art.height * 0.10) + 80),
              "Same inspiration", 62, (252, 252, 250), 1.4, "right", angle=-2.0)
    hand_text(art, (int(art.width * 0.93) - 40, int(art.height * 0.10) + 170),
              "Jay Chou", 46, (240, 240, 238), 1.2, "right", angle=-2.0)
    d = ImageDraw.Draw(art)
    fs = F("serif", 30, "G")
    tracked(d, (int(art.width * 0.055), int(art.height * 0.92)),
            ALBUM_EN + "  " + ALBUM_CN, fs, (250, 250, 250), 1.8)
    return art


def p_bookcover(ai):
    """06 歌词本封面 142×125 —— 书桌场景。"""
    art = fill_crop(ai["desk"], M(142), M(125), fy=0.42)
    scrim(art, top=0.26, power=1.8)
    d = ImageDraw.Draw(art)
    f1 = F("serif", 52, ALBUM_EN)
    tracked(d, (int(art.width * 0.06), int(art.height * 0.09)), ALBUM_EN, f1,
            (252, 252, 250), 3.2)
    f2 = F("serif", 42, ALBUM_CN)
    tracked(d, (int(art.width * 0.06), int(art.height * 0.09) + 70), ALBUM_CN, f2,
            (240, 240, 238), 5.0)
    f3 = F("serif", 34, "J")
    tracked(d, (int(art.width * 0.94), int(art.height * 0.90)), ARTIST_EN + " " + ARTIST_CN,
            f3, (250, 250, 250), 2.0, "right")
    return art


def p_spread(ai):
    """07 歌词本内页 284×125 跨页 —— 左真歌词 / 右钢琴写真。"""
    w, h = M(284), M(125)
    art = Image.new("RGB", (w, h), (247, 244, 238))
    d = ImageDraw.Draw(art)
    # 右页照片
    ph = fill_crop(ai["piano"], M(142), M(125), fx=0.42)
    art.paste(ph, (M(142), 0))
    scrim(ph, bottom=0.34, power=1.8)
    art.paste(ph, (M(142), 0))
    # 中缝折影
    for i in range(-28, 29):
        k = 1 - abs(i) / 28.0
        c = tuple(int(120 * k) for _ in range(3))
        d.line((M(142) + i, 0, M(142) + i, h), fill=(max(0, 210 - int(90 * k)),) * 3)
    # 左页版式
    pad = int(M(142) * 0.105)
    fn = F("num", 46, "0")
    tracked(d, (pad, int(h * 0.10)), "06", fn, (150, 150, 156), 1.0)
    ft = F("serif", 96, "等")
    tracked(d, (pad + 110, int(h * 0.10) - 14), "等你下課", ft, (34, 34, 38), 4.0)
    hairline(d, pad, int(h * 0.10) + 110, pad + 560, (170, 170, 176))
    y0 = int(h * 0.235)
    lead = int(h * 0.0405)
    fl = F("serif", 38, "词")
    for i, ln in enumerate(LYRICS):
        tracked(d, (pad, y0 + i * lead), ln, fl, (72, 72, 78), 1.0)
    tracked(d, (pad, y0 + len(LYRICS) * lead), "⋯⋯", fl, (150, 150, 156), 2.0)
    fpg = F("num", 28, "0")
    tracked(d, (pad, int(h * 0.93)), "06 / 12", fpg, (150, 150, 156), 1.5)
    fj = F("heavy", 28, "J")
    tracked(d, (M(142) - pad, int(h * 0.93)), COMPANY, fj, (150, 150, 156), 1.5, "right")
    # 右页手写
    qx = int(w * 0.555)
    hand_text(art, (qx, int(h * 0.74)), "音樂是一首", 52, (252, 252, 250), 2.0, angle=-2.0)
    hand_text(art, (qx, int(h * 0.74) + 76), "永遠唱不完的歌", 52, (252, 252, 250), 2.0, angle=-2.0)
    hand_text(art, (qx + 10, int(h * 0.74) + 152), "Jay Chou", 42, (242, 242, 240), 1.2, angle=-2.0)
    return art


def p_postfront(ai):
    """08 明信片正面 100×148 —— 街灯 + 手写。"""
    art = fill_crop(ai["lamp"], M(100), M(148), fy=0.40)
    scrim(art, top=0.30, power=1.8)
    hand_text(art, (int(art.width * 0.09), int(art.height * 0.075)),
              "走遠的風景", 58, (252, 252, 250), 3.0, angle=-2.0)
    hand_text(art, (int(art.width * 0.09), int(art.height * 0.075) + 86),
              "都是最美的守候", 58, (252, 252, 250), 3.0, angle=-2.0)
    hand_text(art, (int(art.width * 0.09) + 6, int(art.height * 0.075) + 176),
              "Jay Chou", 44, (240, 240, 238), 1.2, angle=-2.0)
    return art


def p_postback(cover):
    """09 明信片背面 100×148 —— 明信片版式。"""
    w, h = M(100), M(148)
    art = Image.new("RGB", (w, h), (249, 246, 239))
    d = ImageDraw.Draw(art)
    ink = (58, 60, 66)
    dim = (168, 168, 172)
    # 左上标
    f1 = F("serif", 34, ALBUM_EN)
    tracked(d, (int(w * 0.07), int(h * 0.055)), ALBUM_EN, f1, ink, 2.0)
    f2 = F("serif", 30, ALBUM_CN)
    tracked(d, (int(w * 0.07), int(h * 0.055) + 44), ALBUM_CN, f2, dim, 3.0)
    # 手写（左上区）
    qx, qy = int(w * 0.07), int(h * 0.155)
    hand_text(art, (qx, qy), "把生活過成", 52, (70, 72, 80), 2.5, angle=-2.0)
    hand_text(art, (qx + 20, qy + 80), "一件藝術品", 52, (70, 72, 80), 2.5, angle=-2.0)
    hand_text(art, (qx + 40, qy + 158), "Jay Chou", 40, (120, 122, 130), 1.2, angle=-2.0)
    # 中缝分隔线
    d.line((int(w * 0.60), int(h * 0.14), int(w * 0.60), int(h * 0.88)), fill=dim, width=3)
    # 邮票（封面小图）+ 邮戳
    sw_, sh_ = int(w * 0.21), int(h * 0.16)
    sx, sy = int(w * 0.72), int(h * 0.075)
    stamp = fill_crop(cover, sw_ - 16, sh_ - 16, fy=0.35)
    d.rectangle((sx - 8, sy - 8, sx + sw_ - 8, sy + sh_ - 8), outline=(190, 190, 186), width=4)
    art.paste(stamp, (sx, sy))
    pcx, pcy = sx - int(w * 0.075), sy + sh_ - 30
    d.ellipse((pcx - 90, pcy - 90, pcx + 90, pcy + 90), outline=(180, 182, 186), width=4)
    d.ellipse((pcx - 64, pcy - 64, pcx + 64, pcy + 64), outline=(190, 192, 196), width=2)
    # 地址线
    for i in range(3):
        yy = int(h * 0.52) + i * int(h * 0.115)
        hairline(d, int(w * 0.655), yy, int(w * 0.93), dim, 3)
    # 邮编小格
    gx = int(w * 0.70)
    for i in range(6):
        d.rectangle((gx + i * int(w * 0.038), int(h * 0.895),
                     gx + i * int(w * 0.038) + int(w * 0.030), int(h * 0.925)),
                    outline=dim, width=2)
    return art


def p_poster(ai):
    """10 海报 594×210 —— 日落全景。"""
    w, h = M(594), M(210)
    src = ai["sunset"]
    sw, sh = src.size
    scale = w / sw
    nh = int(sh * scale)
    im = src.resize((w, nh), Image.LANCZOS)
    y0 = min(max(0, int(nh * 0.085)), nh - h)
    art = im.crop((0, y0, w, y0 + h))
    scrim(art, top=0.30, bottom=0.26, power=2.1)
    d = ImageDraw.Draw(art)
    f1 = F("serif", 96, "G")
    tracked(d, (int(w * 0.028), int(h * 0.16)), "GREATEST", f1, (54, 44, 36), 6.0)
    f2 = F("serif", 62, "W")
    tracked(d, (int(w * 0.028), int(h * 0.16) + 116), "WORKS OF ART", f2, (72, 62, 52), 6.0)
    f3 = F("serif", 52, ALBUM_CN)
    tracked(d, (int(w * 0.028), int(h * 0.16) + 196), "最偉大的作品", f3, (54, 44, 36), 6.0)
    f4 = F("serif", 66, "J")
    tracked(d, (int(w * 0.972), int(h * 0.16)), ARTIST_EN, f4, (54, 44, 36), 5.0, "right")
    f5 = F("serif", 52, ARTIST_CN)
    tracked(d, (int(w * 0.972), int(h * 0.16) + 92), ARTIST_CN, f5, (60, 50, 42), 6.0, "right")
    qx = int(w * 0.972)
    hand_text(art, (qx, int(h * 0.80)), "藝術 越平凡的日子", 56, (56, 46, 38), 2.0, "right", angle=-2.0)
    hand_text(art, (qx, int(h * 0.80) + 80), "越能閃閃發光", 56, (56, 46, 38), 2.0, "right", angle=-2.0)
    hand_text(art, (qx - 20, int(h * 0.80) + 160), "Jay Chou", 44, (76, 66, 56), 1.2, "right", angle=-2.0)
    fj = F("heavy", 40, "J")
    tracked(d, (int(w * 0.028), int(h * 0.86)), COMPANY, fj, (54, 44, 36), 2.5)
    return art


# ---- 标注零件（印刷图用）------------------------------------------------
def dash_rect(d, box, color, dash=16, gap=12, width=3):
    x0, y0, x1, y1 = box
    segs = []
    segs.append(((x0, y0), (x1, y0)))
    segs.append(((x1, y0), (x1, y1)))
    segs.append(((x1, y1), (x0, y1)))
    segs.append(((x0, y1), (x0, y0)))
    for (ax, ay), (bx, by) in segs:
        L = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        n = max(1, int(L // (dash + gap)))
        ux, uy = (bx - ax) / L, (by - ay) / L
        s = 0.0
        for i in range(n + 1):
            e = min(dash, L - s)
            if e <= 0:
                break
            d.line((ax + ux * s, ay + uy * s, ax + ux * (s + e), ay + uy * (s + e)),
                   fill=color, width=width)
            s += dash + gap


def dim_h(d, x1, x2, y, label, ink, size=30):
    d.line((x1, y, x2, y), fill=ink, width=2)
    for xx in (x1, x2):
        d.line((xx, y - 12, xx, y + 12), fill=ink, width=2)
    f = F("sans", size, "0")
    tw = tracked(ImageDraw.Draw(Image.new("RGB", (1, 1))), (0, 0), label, f, ink, 0)
    tracked(d, ((x1 + x2 - tw) / 2, y - size - 10), label, f, ink, 0)


# ---- 两张大图 -----------------------------------------------------------
PIECES_META = [
    ("01", "封面（正面）", "Front Cover"),
    ("02", "封底（背面）", "Back Cover"),
    ("03", "專輯側脊", "Spine"),
    ("04", "CD 光盤", "CD Disc"),
    ("05", "內封套", "Inner Sleeve"),
    ("06", "歌詞本封面", "Booklet Cover"),
    ("07", "內頁（歌詞＋寫真）", "Booklet Inside (Spread)"),
    ("08", "明信片（正面）", "Postcard Front"),
    ("09", "明信片（背面）", "Postcard Back"),
    ("10", "海報（展開效果）", "Poster"),
]


def make_board(pieces, disc):
    """提案图。"""
    BG = (233, 231, 226)
    ink = (36, 38, 42)
    dim = (128, 130, 134)
    disp_h = 560
    gap = 60
    margin = 150
    head_w = 700
    row1 = [0, 1, 2, 3, 4]
    row2 = [5, 6]
    row3 = [7, 8, 9]

    def disp_w(idx):
        if idx == 3:
            return disp_h
        im = pieces[idx]
        return int(disp_h * im.width / im.height)

    r1w = sum(disp_w(i) for i in row1) + gap * (len(row1) - 1)
    r2w = sum(disp_w(i) for i in row2) + gap * (len(row2) - 1)
    r3w = sum(disp_w(i) for i in row3) + gap * (len(row3) - 1)
    content = max(r1w, r2w, r3w)
    W = margin + head_w + gap + content + margin
    cap_h = 100
    H = margin + 760 + gap + (disp_h + cap_h + gap) * 3 + 60 + margin
    cv = Image.new("RGB", (int(W), int(H)), BG)
    d = ImageDraw.Draw(cv)
    # 页眉（左列）
    x0, y0 = margin, margin
    f1 = F("display", 110, "J")
    tracked(d, (x0, y0), ARTIST_EN, f1, ink, 4.0)
    f1c = F("serif", 72, ARTIST_CN)
    tracked(d, (x0, y0 + 140), ARTIST_CN, f1c, ink, 8.0)
    f2 = F("serif", 52, ALBUM_EN)
    tracked(d, (x0, y0 + 268), ALBUM_EN, f2, ink, 3.0)
    f2c = F("serif", 52, ALBUM_CN)
    tracked(d, (x0, y0 + 334), ALBUM_CN, f2c, dim, 5.0)
    hairline(d, x0, y0 + 420, x0 + head_w - 120, dim)
    fy = y0 + 452
    fs = F("hand_latin", 34, "A")
    for i, ln in enumerate(MANIFESTO_EN):
        tracked(d, (x0, fy + i * 46), ln, fs, dim, 0.8)
    fq = F("hand", 42, "艺")
    hand_text(cv, (x0, fy + 232), "藝術 越平凡的日子 越能閃閃發光", 42, (86, 90, 98), 1.5)
    # 三行部件
    yy = margin + 760 + gap
    for row in (row1, row2, row3):
        xx = margin + head_w + gap
        row_w = sum(disp_w(i) for i in row) + gap * (len(row) - 1)
        xx += (content - row_w) // 2
        for idx in row:
            im = disc if idx == 3 else pieces[idx]
            if idx == 3:
                cell = Image.new("RGB", (disp_h, disp_h), BG)
                dis = disc.resize((disp_h, disp_h), Image.LANCZOS)
                mask = Image.new("L", (disp_h, disp_h), 0)
                ImageDraw.Draw(mask).ellipse([0, 0, disp_h - 1, disp_h - 1], fill=255)
                cell.paste(dis, (0, 0), mask)
                cv.paste(cell, (xx, yy))
            else:
                cv.paste(im.resize((disp_w(idx), disp_h), Image.LANCZOS), (xx, yy))
            meta = PIECES_META[idx]
            fc = F("serif", 40, meta[1][0])
            lab = "%s %s" % (meta[0], meta[1])
            tw = tracked(ImageDraw.Draw(Image.new("RGB", (1, 1))), (0, 0), lab, fc, ink, 1.0)
            tracked(d, (xx + disp_w(idx) / 2 - tw / 2, yy + disp_h + 18), lab, fc, ink, 1.0)
            fe = F("sans", 27, meta[2][0])
            twe = tracked(ImageDraw.Draw(Image.new("RGB", (1, 1))), (0, 0), meta[2], fe, dim, 1.0)
            tracked(d, (xx + disp_w(idx) / 2 - twe / 2, yy + disp_h + 62), meta[2], fe, dim, 1.0)
            xx += disp_w(idx) + gap
        yy += disp_h + cap_h + gap
    # 页脚
    ft = F("serif", 30, "G")
    lab = "%s · %s   —   %s   —   2022 %s" % (ALBUM_EN, ARTIST_EN, TAGLINE_CN, COMPANY)
    tw = tracked(ImageDraw.Draw(Image.new("RGB", (1, 1))), (0, 0), lab, ft, dim, 1.0)
    tracked(d, ((cv.width - tw) / 2, cv.height - margin - 20), lab, ft, dim, 1.0)
    hairline(d, margin, cv.height - margin - 78, cv.width - margin, dim)
    return cv


def make_print_sheet(pieces, disc):
    """印刷档案图：出血/裁切线/折线/尺寸标注/规范。"""
    W = 4700
    margin = 130
    ink = (36, 38, 42)
    dim = (128, 130, 134)
    MAG = (214, 60, 150)
    BLUE = (70, 120, 200)
    disp_h = 640
    gap = 70
    cv = Image.new("RGB", (W, 2780), (255, 255, 255))
    d = ImageDraw.Draw(cv)
    # 页眉
    f1 = F("serif", 64, ARTIST_CN)
    tracked(d, (margin, 60), ARTIST_EN + " " + ARTIST_CN, f1, ink, 2.0)
    f2 = F("serif", 44, ALBUM_EN)
    tracked(d, (margin, 140), ALBUM_EN + " " + ALBUM_CN, f2, dim, 2.0)
    ft1 = F("serif", 44, "C")
    tracked(d, (margin + 1500, 60), "CD 專輯包裝印刷檔案（展開圖）", ft1, ink, 2.0)
    ft2 = F("sans", 30, "P")
    tracked(d, (margin + 1500, 128), "Print-Ready Files / 300 DPI / CMYK", ft2, dim, 1.0)
    # 图例
    lx = W - margin - 700
    ly = 66
    for col, lab, cn in [(MAG, "出血線 Bleed Line (3mm)", 1),
                         ((36, 36, 36), "裁切線 Cut Line", 0),
                         ((90, 90, 90), "折線 Fold Line", 0),
                         (BLUE, "安全區 Safe Area (內縮3mm)", 0)]:
        if cn:
            for i in range(6):
                d.line((lx + i * 36, ly + 12, lx + i * 36 + 20, ly + 12), fill=col, width=4)
        else:
            d.line((lx, ly + 12, lx + 210, ly + 12), fill=col, width=4)
        fl = F("sans", 28, "出")
        tracked(d, (lx + 230, ly - 4), lab, fl, ink, 0.5)
        ly += 52
    hairline(d, margin, 250, W - margin, dim)

    def place(pr, px, py, meta, dim_label, fold=False, no_bleed=False, circle=False):
        """放置一件印刷件 + 三层线 + 尺寸标注 + 标题。返回 (x,y,w,h) 画布区。"""
        im = pr
        if circle:
            cell = Image.new("RGB", (im.width + 8, im.height + 8), (255, 255, 255))
            if im.mode == "RGBA":
                cell.paste(im, (4, 4), im)
            else:
                cell.paste(im, (4, 4))
            im = cell
        cv.paste(im, (px, py))
        wd, ht = im.size
        b = 0 if no_bleed else BLEED
        # 裁切线（实线）
        if circle:
            dd = ImageDraw.Draw(cv)
            c = (px + wd // 2, py + ht // 2)
            r = wd // 2 - 4
            dd.ellipse((c[0] - r, c[1] - r, c[0] + r, c[1] + r), outline=(36, 36, 36), width=3)
            r2 = r - M(2)
            dd.ellipse((c[0] - r2, c[1] - r2, c[0] + r2, c[1] + r2), outline=MAG, width=2)
        else:
            dash_rect(d, (px + b, py + b, px + wd - b, py + ht - b), (36, 36, 36), width=3)
            # 出血线（品红虚线 = 画布外缘）
            dash_rect(d, (px + 2, py + 2, px + wd - 2, py + ht - 2), MAG, dash=10, gap=8, width=2)
            # 安全区（蓝细线，内缩 3mm）
            dash_rect(d, (px + b + M(3), py + b + M(3), px + wd - b - M(3), py + ht - b - M(3)),
                      BLUE, dash=8, gap=10, width=2)
            if fold:
                cx = px + wd // 2
                for yy in range(py + b, py + ht - b, 34):
                    d.line((cx, yy, cx, min(yy + 18, py + ht - b)), fill=(90, 90, 90), width=3)
        # 尺寸标注
        dim_h(d, px, px + wd, py - 44, dim_label, ink, 30)
        # 标题
        fc = F("serif", 34, meta[1][0])
        lab = "%s %s  %s" % (meta[0], meta[1], meta[2])
        tw = tracked(ImageDraw.Draw(Image.new("RGB", (1, 1))), (0, 0), lab, fc, ink, 0.8)
        tracked(d, (px + wd / 2 - tw / 2, py + ht + 16), lab, fc, ink, 0.8)
        return wd, ht

    def printed(idx):
        return bleed(pieces[idx])

    yy0 = 330
    # row1: 01 02 03 04 05
    xx = margin
    for idx in (0, 1, 2, 4):
        pr = printed(idx)
        sc = disp_h / pr.height
        pr2 = pr.resize((int(pr.width * sc), disp_h), Image.LANCZOS)
        m = PIECES_META[idx]
        dimlab = {0: "142 mm (+3mm 出血)", 1: "142 mm (+3mm 出血)",
                  2: "12 mm (+3mm 出血)", 4: "125 mm (+3mm 出血)"}[idx]
        place(pr2, xx, yy0, m, dimlab)
        xx += pr2.width + gap
    # disc
    dis = disc.resize((disp_h - 8, disp_h - 8), Image.LANCZOS)
    place(dis, xx, yy0, PIECES_META[3], "Ø118 mm (內圈 Ø46 mm)", no_bleed=True, circle=True)
    # row2: 06 07 08 09
    yy1 = yy0 + disp_h + 130
    xx = margin
    pr = printed(5)
    sc = disp_h / pr.height
    pr6 = pr.resize((int(pr.width * sc), disp_h), Image.LANCZOS)
    place(pr6, xx, yy1, PIECES_META[5], "142 mm (+3mm 出血)")
    xx += pr6.width + gap
    pr = printed(6)
    sc = disp_h / pr.height
    pr7 = pr.resize((int(pr.width * sc), disp_h), Image.LANCZOS)
    place(pr7, xx, yy1, PIECES_META[6], "284 mm（展開尺寸）(+3mm 出血)", fold=True)
    xx += pr7.width + gap
    for idx in (7, 8):
        pr = printed(idx)
        sc = disp_h / pr.height
        prx = pr.resize((int(pr.width * sc), disp_h), Image.LANCZOS)
        place(prx, xx, yy1, PIECES_META[idx], "100 mm (+3mm 出血)")
        xx += prx.width + gap
    # row3: 10 poster + 规范块
    yy2 = yy1 + disp_h + 130
    pr = printed(9)
    sc = disp_h / pr.height
    pr10 = pr.resize((int(pr.width * sc), disp_h), Image.LANCZOS)
    place(pr10, margin, yy2, PIECES_META[9], "594 mm (+3mm 出血)")
    # 规范块
    sx = margin + pr10.width + gap
    sy = yy2 - 40
    bw = W - margin - sx
    d.rectangle((sx, sy, sx + bw, sy + 620), outline=(200, 200, 200), width=3)
    fs = F("serif", 40, "印")
    tracked(d, (sx + 40, sy + 36), "印刷文件規範  Print-Ready Specs", fs, ink, 1.5)
    hairline(d, sx + 40, sy + 110, sx + bw - 40, dim)
    specs = [
        "• 顏色模式：CMYK",
        "• 解析度：300 DPI",
        "• 出血：3 mm（四邊）",
        "• 載體格式：PNG / PDF（高解析度）",
        "• 文字請轉外框或內嵌字體",
        "• 請依裁切線裁切；折線處折疊加工",
    ]
    fp = F("sans", 34, "顏")
    for i, s in enumerate(specs):
        tracked(d, (sx + 40, sy + 150 + i * 62), s, fp, (70, 72, 78), 0.5)
    hand_text(cv, (sx + 40, sy + 540), "Art is never far from life.  — Jay Chou",
              40, (110, 112, 120), 1.0, angle=-2.0)
    # 页脚
    fl = F("sans", 28, "P")
    tracked(d, (margin, cv.height - 70),
            "GREATEST WORKS OF ART · JAY CHOU — CD Packaging Print Files · 300 DPI · CMYK · Bleed 3mm",
            fl, dim, 0.8)
    return cv


# ---- main ---------------------------------------------------------------
def main():
    os.makedirs(OUT, exist_ok=True)
    cover, ai = load_assets()
    D = read_design(cover, safe_bands=(0.22, 1.0))
    disc = p_disc(cover, D)
    pieces = [
        p_cover(cover), p_back(cover), p_spine(cover), None,
        p_sleeve(ai), p_bookcover(ai), p_spread(ai),
        p_postfront(ai), p_postback(cover), p_poster(ai),
    ]
    # 单件输出
    for i, art in enumerate(pieces):
        meta = PIECES_META[i]
        if art is None:
            disc.convert("RGBA").save(os.path.join(OUT, "%s-%s.png" % (meta[0], meta[2].replace(" ", ""))))
            continue
        art.save(os.path.join(OUT, "%s-%s.jpg" % (meta[0], meta[1].replace("（", "-").replace("）", ""))),
                 quality=93)
        bleed(art).save(os.path.join(OUT, "%s-印刷.jpg" % meta[0]), quality=93)
    board = make_board(pieces, disc)
    board.save(os.path.join(OUT, "★整套提案图.jpg"), quality=92)
    sheet = make_print_sheet(pieces, disc)
    sheet.save(os.path.join(OUT, "★印刷档案图.jpg"), quality=92)
    print("BOARD", board.size, "SHEET", sheet.size)
    for i, art in enumerate(pieces):
        m = PIECES_META[i]
        print(m[0], "OK" if art is not None else "DISC-OK")


if __name__ == "__main__":
    main()
