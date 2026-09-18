# -*- coding: utf-8 -*-
"""封面体检图 —— 肉眼定 ``safe_bands``（封面自带标题占的横带）用。

``safe_bands=(top, bottom)`` 喂给 make_minicd_board.py / make_minicd.py 后，
配件取景会自动避开这条带，不然封面自带的标题字会被切一半搬进补件里，
和自己的排版叠成「字压两遍」。带的数值**别猜**——先出这张体检图看：

    python tools/audit_covers.py covers/six.jpg covers/ost.jpg --bands 0.30 0.32
    python tools/audit_covers.py covers/six.jpg                # 只画网格，不带试裁

输出 ``outputs/封面体检/<名>-体检.jpg``：
  左 = 封面 + 归一化 y 标尺（每 10% 一根线）+ 已定带的红色半透明遮罩
  右 = 按 (band, 1.0) 试裁的三种部件比例（盘面 1:1 / 封底 1.26:1 / 明信片 1.54:1）
"""
from __future__ import annotations

import argparse
import os
import sys

from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import design_parts as DP  # noqa: E402

TILE = 460          # 单格显示边长
GRID_STEP = 0.10    # 标尺线间隔（归一化 y）


def audit(cover_path, band_bottom=None, out_dir="outputs/封面体检"):
    cover = Image.open(cover_path).convert("RGB")
    tag = os.path.splitext(os.path.basename(cover_path))[0]
    D = DP.read_design(cover)

    # ---- 左格：封面 + y 标尺 + 遮罩 ----
    left = cover.resize((TILE, TILE), Image.LANCZOS).convert("RGBA")
    d = ImageDraw.Draw(left, "RGBA")
    for i in range(1, int(1 / GRID_STEP)):
        y = int(TILE * i * GRID_STEP)
        col = (255, 60, 50, 150) if band_bottom and abs(i * GRID_STEP - band_bottom) < 0.005 \
            else (255, 255, 255, 90)
        d.line([(0, y), (TILE, y)], fill=col, width=2)
        d.text((4, y + 2), "%.1f" % (i * GRID_STEP), fill=(255, 255, 255, 220))
    if band_bottom:
        d.rectangle([0, 0, TILE, int(TILE * band_bottom)], fill=(255, 40, 40, 46))

    # ---- 右格：按 (0, band) 试裁三种比例 ----
    ratios = [("盘面 1:1", 1.0), ("封底 1.26:1", 1.263), ("明信片 1.54:1", 1.538)]
    tiles = [left]
    for name, ar in ratios:
        if band_bottom:
            D["safe_bands"] = (float(band_bottom), 1.0)
            im = DP.safe_crop(cover, TILE, int(TILE / ar), D, fx=0.5, fy=0.6, zoom=1.15)
        else:
            im = DP.focus_crop(cover, TILE, int(TILE / ar), fx=0.5, fy=0.55, zoom=1.15)
        t = im.convert("RGBA")
        ImageDraw.Draw(t).text((6, 6), name, fill=(255, 255, 255))
        tiles.append(t)

    W = TILE * len(tiles) + 12 * (len(tiles) + 1)
    H = TILE + 92
    sheet = Image.new("RGB", (W, H), (240, 240, 239))
    x = 12
    dd = ImageDraw.Draw(sheet)
    for t in tiles:
        sheet.paste(t.convert("RGB"), (x, 12), t if t.mode == "RGBA" else None)
        x += TILE + 12
    note = ("%s ｜ 红罩=标题带 (0, %s) ｜ 右三格=避开标题带后的试裁 —— "
            "标题字若仍被裁进试裁格，把 --bands 调大" % (tag, band_bottom))
    dd.text((12, H - 52), note, fill=(90, 92, 98))
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "%s-体检.jpg" % tag)
    sheet.save(out, quality=93)
    print("saved", out, sheet.size)


def main():
    ap = argparse.ArgumentParser(description="封面体检图（定 safe_bands 用）")
    ap.add_argument("covers", nargs="+", help="封面图片路径")
    ap.add_argument("--bands", default="",
                    help="逗号分隔的每张封面标题带下缘，如 0.30,0.32（上缘固定 0）；"
                         "给一个值则所有封面共用")
    ap.add_argument("--out", default="outputs/封面体检")
    a = ap.parse_args()
    raw = [x for x in a.bands.split(",") if x.strip()] if a.bands else []
    for i, p in enumerate(a.covers):
        if not os.path.exists(p):
            print("跳过（不存在）:", p)
            continue
        v = None
        if raw:
            v = float(raw[0] if len(raw) == 1 else raw[min(i, len(raw) - 1)])
        audit(p, v, a.out)


if __name__ == "__main__":
    main()
