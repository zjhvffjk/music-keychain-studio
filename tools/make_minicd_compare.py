#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「封面衍生设计」对照图 —— 一眼看清"一张封面长出全套部件"。

    python make_minicd_compare.py [输出路径]

横排四格（左→右）：① 原封面 → ② 盘面 → ③ 封面折件 → ④ 封底条
每格自带中文标注；每行换一张专辑，展示设计是**跟着各自封面走**的。
"""
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import fonts

    def F(sz, bold=False):
        p = fonts.find_bold() if bold else fonts.find_regular()
        from PIL import ImageFont
        return ImageFont.truetype(p, sz)
except Exception:  # pragma: no cover
    from PIL import ImageFont

    def F(sz, bold=False):
        return ImageFont.load_default()

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESIGN = os.path.join(BASE, "outputs", "迷你CD-设计")
ALBUMS = os.path.join(BASE, "outputs", "周杰伦-专辑全集", "albums")

ROWS = [
    ("Jay", "44 Jay - 周杰伦.jpg"),
    ("周杰伦的床边故事", "12 周杰伦的床边故事 - 周杰伦.jpg"),
    ("最伟大的作品", "05 最伟大的作品 - 周杰伦.jpg"),
]

CELL = 300          # 每格图宽
GAP = 36
PAD = 60
TITLE_H = 92
LBL_H = 62

BG = (247, 246, 244)
CARD = (255, 255, 255)
LINE = (226, 223, 219)
FG = (32, 30, 28)
DIM = (122, 118, 113)
ACCENT = (214, 62, 54)

HEADS = [
    ("① 原封面（素材源）", "网易云母版 · 不裁不缩"),
    ("② 盘面", "Ø40mm · 封面裁圆 + CD 沟槽 + 扇形高光"),
    ("③ 封面折件", "82×41mm · 左内页(曲目) 右封面"),
    ("④ 封底条", "108.4×38mm · 封底+内盘底+侧封"),
]


def fit(im, w, h):
    """等比缩放进 (w,h) 框，不裁切。"""
    r = min(w / im.width, h / im.height)
    return im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)


def load(path):
    return Image.open(path).convert("RGB") if os.path.exists(path) else None


def main():
    outp = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DESIGN, "对照图-封面衍生全套.jpg")
    rows = []
    for name, cov in ROWS:
        d = os.path.join(DESIGN, name)
        rows.append({
            "name": name,
            "items": [load(os.path.join(ALBUMS, cov)),
                      load(os.path.join(d, "预览-disc.jpg")),
                      load(os.path.join(d, "预览-cover.jpg")),
                      load(os.path.join(d, "预览-back.jpg"))],
        })

    row_h = CELL + LBL_H + 30
    W = PAD + CELL * 4 + GAP * 3 + PAD
    H = TITLE_H + row_h * len(rows) + PAD
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)

    d.text((PAD, 30), "封面衍生设计 —— 一张封面长出全套部件", font=F(31, True), fill=FG)
    d.text((PAD, 68), "全部部件都由 ① 的色板 / 明暗 / 边密度推导，所以摆在一起是同源的（不搜网图、不套死模板）",
           font=F(17), fill=DIM)

    for ri, row in enumerate(rows):
        y = TITLE_H + ri * row_h
        d.text((PAD, y + 4), row["name"], font=F(21, True), fill=FG)
        d.line([PAD, y + 34, W - PAD, y + 34], fill=LINE, width=1)
        for ci, im in enumerate(row["items"]):
            x = PAD + ci * (CELL + GAP)
            top = y + 46
            d.rectangle([x - 6, top - 6, x + CELL + 6, top + CELL + 6],
                        fill=CARD, outline=LINE, width=1)
            if im is None:
                d.text((x + 10, top + 10), "（缺图）", font=F(16), fill=DIM)
                continue
            im2 = fit(im, CELL, CELL)
            canvas.paste(im2, (x + (CELL - im2.width) // 2,
                               top + (CELL - im2.height) // 2))
            # 每格自带标注
            t1, t2 = HEADS[ci]
            d.text((x, top + CELL + 12), t1, font=F(17, True), fill=FG)
            d.text((x, top + CELL + 34), t2, font=F(14), fill=DIM)

    os.makedirs(os.path.dirname(outp), exist_ok=True)
    canvas.save(outp, quality=92)
    print("已生成：%s  (%dx%d)" % (outp, canvas.width, canvas.height))


if __name__ == "__main__":
    main()
