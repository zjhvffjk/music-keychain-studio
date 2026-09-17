# -*- coding: utf-8 -*-
"""生成仓库自带的**抽象示例素材**（不含任何第三方版权内容）。

用途有两个：
1. 作为 README 的效果展示图；
2. 作为 ``make_keychain.py`` 在没传 ``--cover/--player`` 时的占位素材。

产出（``assets/demo/``）::

    cover.jpg      抽象封面 1492x1492（程序绘制）
    player.png     播放界面 1181x1968（由 tools/make_player.py 真实产出）
    keychain.png   钥匙扣成品 1920x1920（由 tools/make_keychain.py 真实产出）
    shop.png       白底商品图 750x2000（由 tools/make_keychain_shop.py 真实产出）
    shop-grid.png  三只商品图拼版总览
    player.jpg     上面几张的轻量 JPG 版，供 README 展示
    keychain.jpg
    shop.jpg
    shop-grid.jpg
"""
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "demo")

# 拼版演示用的三张（配色不同，便于看出「每张卡面跟着封面走」）
GRID_DEMO = [
    ("示例曲目", (70, 40, 118), (244, 142, 84)),      # 深紫 → 暖橙
    ("夜行列车", (14, 58, 88), (126, 206, 186)),      # 深蓝 → 青绿
    ("夏日回声", (132, 28, 58), (250, 188, 92)),      # 酒红 → 暖黄
]


def make_abstract_cover(size=1492, c1=(70, 40, 118), c2=(244, 142, 84)):
    """画一张斜向渐变 + 几何图形的抽象封面。"""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    t = np.clip((xx * 0.72 + yy * 0.28) / size, 0.0, 1.0)
    c1 = np.array(c1, np.float32)
    c2 = np.array(c2, np.float32)
    rgb = c1[None, None, :] * (1 - t[..., None]) + c2[None, None, :] * t[..., None]
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")

    d = ImageDraw.Draw(img, "RGBA")
    d.ellipse([size * 0.16, size * 0.16, size * 0.84, size * 0.84],
              fill=(255, 255, 255, 16))
    d.ellipse([size * 0.29, size * 0.29, size * 0.71, size * 0.71],
              outline=(255, 255, 255, 160), width=max(1, int(size * 0.011)))
    for i in range(4):
        for j in range(4):
            cx = size * 0.735 + i * size * 0.048
            cy = size * 0.115 + j * size * 0.048
            r = size * 0.007
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 105))
    return img.filter(ImageFilter.GaussianBlur(size * 0.0009))


def _jpg(im, name, quality=92):
    """存一份轻量 JPG 供 README 展示（PNG 版留全尺寸）"""
    p = os.path.join(OUT, name)
    im.convert("RGB").save(p, quality=quality)
    return p


def shop_demo(player_png):
    """用真实代码再产一套**白底商品图**：单只一张 + 三只拼版总览。

    拼版用三张配色不同的抽象封面，能顺带看出「卡面配色跟着封面走」。
    """
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import make_keychain_shop as SHOP

    ov = SHOP.load_overlay_trimmed()
    units = []
    for i, (title, c1, c2) in enumerate(GRID_DEMO):
        cp = os.path.join(OUT, "_demo_cover_%d.jpg" % i)
        pp = os.path.join(OUT, "_demo_player_%d.png" % i)
        make_abstract_cover(c1=c1, c2=c2).save(cp, quality=95)
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_player.py"),
                        "--cover", cp, "--title", title, "--artist", "示例歌手",
                        "--duration", "257", "--played", "0.35",
                        "--width", "1181", "--ratio", "1.6667",
                        "--out", pp], check=True)
        units.append(SHOP.build_unit(pp, ov, kind="long", bg="white"))
        # 中间产物不进仓库
        os.remove(cp)
        os.remove(pp)

    one = os.path.join(OUT, "shop.png")
    SHOP.save_img(units[0], one, bg="white")
    _jpg(units[0], "shop.jpg")
    print("[4/4] 白底商品图   ->", one)

    grid = SHOP.build_grid(units, bg="white")
    gp = os.path.join(OUT, "shop-grid.png")
    SHOP.save_img(grid, gp, bg="white")
    _jpg(grid, "shop-grid.jpg")
    print("      三只拼版     ->", gp)


def main():
    os.makedirs(OUT, exist_ok=True)
    py = sys.executable

    cover_path = os.path.join(OUT, "cover.jpg")
    make_abstract_cover().save(cover_path, quality=95)
    print("[1/4] 抽象封面   ->", cover_path)

    player_png = os.path.join(OUT, "player.png")
    subprocess.run([py, os.path.join(ROOT, "tools", "make_player.py"),
                    "--cover", cover_path,
                    "--title", "示例曲目", "--artist", "示例歌手",
                    "--duration", "257", "--played", "0.35",
                    "--width", "1181", "--ratio", "1.6667",
                    "--out", player_png], check=True)
    print("[2/4] 播放界面   ->", player_png)

    keychain_png = os.path.join(OUT, "keychain.png")
    subprocess.run([py, os.path.join(ROOT, "tools", "make_keychain.py"),
                    "--cover", cover_path,
                    "--player", player_png,
                    "--out", keychain_png], check=True)
    print("[3/4] 钥匙扣成品 ->", keychain_png)

    # README 用的轻量 JPG
    Image.open(player_png).convert("RGB").save(
        os.path.join(OUT, "player.jpg"), quality=92)
    Image.open(keychain_png).convert("RGB").save(
        os.path.join(OUT, "keychain.jpg"), quality=92)

    shop_demo(player_png)

    print("完成：assets/demo/ 下的 *.jpg 可直接用于文档展示。")


if __name__ == "__main__":
    main()
