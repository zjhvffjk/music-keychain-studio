# -*- coding: utf-8 -*-
"""生成仓库自带的**抽象示例素材**（不含任何第三方版权内容）。

用途有两个：
1. 作为 README 的效果展示图；
2. 作为 ``make_keychain.py`` 在没传 ``--cover/--player`` 时的占位素材。

产出（``assets/demo/``）::

    cover.jpg      抽象封面 1492x1492（程序绘制）
    player.png     播放界面 1181x1968（由 tools/make_player.py 真实产出）
    keychain.png   钥匙扣成品 1920x1920（由 tools/make_keychain.py 真实产出）
    player.jpg     上面两张的轻量 JPG 版，供 README 展示
    keychain.jpg
"""
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "demo")


def make_abstract_cover(size=1492):
    """画一张斜向渐变 + 几何图形的抽象封面。"""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    t = np.clip((xx * 0.72 + yy * 0.28) / size, 0.0, 1.0)
    c1 = np.array([70, 40, 118], np.float32)     # 深紫
    c2 = np.array([244, 142, 84], np.float32)    # 暖橙
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


def main():
    os.makedirs(OUT, exist_ok=True)
    py = sys.executable

    cover_path = os.path.join(OUT, "cover.jpg")
    make_abstract_cover().save(cover_path, quality=95)
    print("[1/3] 抽象封面   ->", cover_path)

    player_png = os.path.join(OUT, "player.png")
    subprocess.run([py, os.path.join(ROOT, "tools", "make_player.py"),
                    "--cover", cover_path,
                    "--title", "示例曲目", "--artist", "示例歌手",
                    "--duration", "257", "--played", "0.35",
                    "--width", "1181", "--ratio", "1.6667",
                    "--out", player_png], check=True)
    print("[2/3] 播放界面   ->", player_png)

    keychain_png = os.path.join(OUT, "keychain.png")
    subprocess.run([py, os.path.join(ROOT, "tools", "make_keychain.py"),
                    "--cover", cover_path,
                    "--player", player_png,
                    "--out", keychain_png], check=True)
    print("[3/3] 钥匙扣成品 ->", keychain_png)

    # README 用的轻量 JPG
    Image.open(player_png).convert("RGB").save(
        os.path.join(OUT, "player.jpg"), quality=92)
    Image.open(keychain_png).convert("RGB").save(
        os.path.join(OUT, "keychain.jpg"), quality=92)
    print("完成：assets/demo/ 下的 player.jpg 与 keychain.jpg 可直接用于文档展示。")


if __name__ == "__main__":
    main()
