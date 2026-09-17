# -*- coding: utf-8 -*-
"""生成「专辑全集」三种产出的对照图（自带文字标注）。

用法：python make_album_compare.py [歌手名]   # 默认 周杰伦
读取 outputs/<歌手>-专辑全集/，输出同目录下「对照图-三种产出.jpg」。
左→右：封面母版原图 → 专辑卡 → 专辑墙（红框 = 最推荐的交付形态）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from fonts import find_bold, find_regular  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIST = sys.argv[1] if len(sys.argv) > 1 else "周杰伦"
SRC = os.path.join(BASE, "outputs", "%s-专辑全集" % ARTIST)
OUT = os.path.join(SRC, "对照图-三种产出.jpg")

BG = (250, 250, 251)
CARD = (255, 255, 255)
LINE = (226, 229, 234)
FG = (26, 28, 32)
DIM = (110, 116, 126)
ACCENT = (200, 16, 46)

BOLD = find_bold()
REG = find_regular()


def F(size, bold=False):
    return ImageFont.truetype(BOLD if bold else REG, size)


def pick_cover():
    """取第一张专辑封面（即兴曲）作样例。"""
    d = os.path.join(SRC, "albums")
    names = sorted(os.listdir(d))
    return os.path.join(d, names[0])


def pick_card():
    d = os.path.join(SRC, "album_cards")
    names = sorted(os.listdir(d))
    return os.path.join(d, names[0])


def fit(img, box_w, box_h):
    w, h = img.size
    s = min(box_w / w, box_h / h)
    return img.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)


def main():
    PAD = 60
    GAP = 54
    TOP = 150          # 标题区高
    LBL = 74           # 每格标签高
    CELL = 640         # 图区最大边长

    panels = []
    panels.append(("① 封面母版原图", "方形，最大 2000×2000 · 不裁不缩",
                   pick_cover(), False))
    panels.append(("② 专辑卡", "方形 1200/1500/2000 任选 · 专辑名+歌手+类别·日期·曲目数·公司",
                   pick_card(), True))
    panels.append(("③ 专辑墙总览", "全部封面拼版 · 44 张自动排 7 列",
                   os.path.join(SRC, "总览-专辑墙.jpg"), False))

    imgs = []
    for title, sub, path, rec in panels:
        im = Image.open(path).convert("RGB")
        imgs.append((title, sub, fit(im, CELL, CELL), rec))

    total_w = PAD * 2 + sum(p[2].width for p in imgs) + GAP * (len(imgs) - 1)
    body_h = max(p[2].height for p in imgs)
    total_h = PAD + TOP + LBL + body_h + PAD

    canvas = Image.new("RGB", (total_w, total_h), BG)
    d = ImageDraw.Draw(canvas)

    # 标题
    d.text((PAD, PAD - 6), "「专辑全集」三种产出 · 对照图", font=F(46, True), fill=FG)
    d.text((PAD, PAD + 58), "输入歌手名（周杰伦）→ 抓全部 44 张专辑 · 顺序：左 → 中 → 右",
           font=F(26), fill=DIM)

    x = PAD
    y0 = PAD + TOP + LBL
    for title, sub, im, rec in imgs:
        # 标签
        d.text((x, PAD + TOP - 34), title, font=F(34, True), fill=FG)
        d.text((x, PAD + TOP + 4), sub, font=F(21), fill=DIM)

        # 图片卡片
        cw, ch = im.size
        d.rectangle([x - 8, y0 - 8, x + cw + 8, y0 + ch + 8], fill=CARD, outline=LINE, width=2)
        canvas.paste(im, (x, y0))

        if rec:
            # 红框圈出推荐项；徽标挂在标题右侧，避免压住下面的说明文字
            d.rectangle([x - 18, y0 - 18, x + cw + 18, y0 + ch + 18], outline=ACCENT, width=6)
            tag = "★ 推荐交付"
            tf = F(24, True)
            tw = d.textlength(tag, font=tf)
            tx = x + d.textlength(title, font=F(34, True)) + 22
            ty = PAD + TOP - 36
            d.rectangle([tx, ty, tx + tw + 30, ty + 42], fill=ACCENT)
            d.text((tx + 15, ty + 8), tag, font=tf, fill=(255, 255, 255))

        x += cw + GAP

    # 底部说明
    foot = os.path.join(SRC, "albums")
    n_cov = len(os.listdir(foot))
    n_cad = len(os.listdir(os.path.join(SRC, "album_cards")))
    d.text((PAD, total_h - PAD + 8),
           "本次实测：封面母版 %d 张 · 专辑卡 %d 张 · 专辑墙 1 张 · albums.json 可直接离线重出"
           % (n_cov, n_cad),
           font=F(24), fill=DIM)

    canvas.save(OUT, quality=92)
    print("->", OUT, canvas.size)


if __name__ == "__main__":
    main()
