# -*- coding: utf-8 -*-
"""
从「用户的成品参考图」反解出钥匙扣素材的真实 alpha 与颜色，生成可直接合成的 RGBA 素材。

为什么需要这一步：
    钥匙扣素材若以白底 JPG 形式传来，透明通道就丢了。直接叠加会得到一个白方块。
    本脚本用成品图反推每个像素的不透明度与真实颜色：
        ref  = base*(1-a) + color*a      （成品图 = 底层与钥匙扣的合成）
        kb   = color*a + 255*(1-a)        （素材白底照的成像）
    两式消去 color，得 a = (ref - base - kb + 255) / (255 - base)

内腔处理：
    内腔（亚克力板中部）的底层是播放界面图，与边框覆盖的区域物理条件不同，
    逐像素反解会把「旧播放图的内容」编码进素材颜色，导致合成时出现重影。
    因此内腔改用统一的不透明度常量（INNER_ALPHA），只保留"隔着亚克力看"的质感。

用法：
    python tools/keychain_solve_alpha.py --ref 成品参考图.jpg --keychain 素材原图.jpg
输出：
    assets/keychain/keychain_alpha.png  （RGBA，可直接叠加合成）
"""
import os
import sys
import argparse
import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ---------- 画布与版式（由成品图反推，1920 基准）----------
CANVAS = 1920
FRAME_OUT = 161            # 白卡纸外边距
FRAME_THICK = 53           # 白卡纸厚度
COVER_IN = FRAME_OUT + FRAME_THICK
COVER_SIZE = CANVAS - COVER_IN * 2
BG_BLUR = 24               # 底图模糊半径
BG_WHITE = 0.078           # 底图叠加白色比例

# ---------- 钥匙扣素材的落位（由壳体边框反推）----------
KB_SCALE = 1.1165
KB_X, KB_Y = 244, -26

# ---------- 播放界面图在壳内的位置（由内腔边界实测）----------
PL_X, PL_Y, PL_W, PL_H = 732, 874, 452, 753

INNER_ALPHA = 0.15         # 内腔统一不透明度（0=全透明，保留轻微亚克力感）


def log(*a):
    print(*a, flush=True)


def build_base(cover, with_player, player=None):
    bg = cover.resize((CANVAS, CANVAS), Image.LANCZOS).filter(ImageFilter.GaussianBlur(BG_BLUR))
    bb = np.asarray(bg).astype(np.float32) * (1 - BG_WHITE) + 255.0 * BG_WHITE
    im = Image.fromarray(np.clip(bb, 0, 255).astype(np.uint8))
    im.paste(Image.new("RGB", (CANVAS - FRAME_OUT * 2,) * 2, (255, 255, 255)),
             (FRAME_OUT, FRAME_OUT))
    im.paste(cover.resize((COVER_SIZE,) * 2, Image.LANCZOS), (COVER_IN, COVER_IN))
    if with_player and player is not None:
        im.paste(player.resize((PL_W, PL_H), Image.LANCZOS), (PL_X, PL_Y))
    return np.asarray(im).astype(np.float32)


def solve(ref_path, kb_path, out_path, inner_alpha=INNER_ALPHA):
    cover_path = os.path.join(ROOT, "assets", "keychain", "source_cover.jpg")
    player_path = os.path.join(ROOT, "assets", "keychain", "player_1152x1920.jpg")
    cover = Image.open(cover_path).convert("RGB")
    player = Image.open(player_path).convert("RGB")
    kbim = Image.open(kb_path).convert("RGB")
    ref = np.asarray(Image.open(ref_path).convert("RGB")).astype(np.float32)

    base_wp = build_base(cover, True, player)

    nw, nh = int(round(kbim.width * KB_SCALE)), int(round(kbim.height * KB_SCALE))
    kbr = kbim.resize((nw, nh), Image.LANCZOS)
    kbfull = np.full((CANVAS, CANVAS, 3), 255.0, np.float32)
    sx0, sy0 = max(0, -KB_X), max(0, -KB_Y)
    dx0, dy0 = max(0, KB_X), max(0, KB_Y)
    w = min(nw - sx0, CANVAS - dx0)
    h = min(nh - sy0, CANVAS - dy0)
    kbfull[dy0:dy0 + h, dx0:dx0 + w] = np.asarray(kbr).astype(np.float32)[sy0:sy0 + h, sx0:sx0 + w]
    kbl = 0.299 * kbfull[:, :, 0] + 0.587 * kbfull[:, :, 1] + 0.114 * kbfull[:, :, 2]

    inner = np.zeros((CANVAS, CANVAS), bool)
    inner[PL_Y:PL_Y + PL_H, PL_X:PL_X + PL_W] = True

    den = 255.0 - base_wp
    good = (kbl < 248) & (den.mean(axis=2) > 30)
    num = ref - base_wp - kbfull + 255.0
    with np.errstate(invalid="ignore"):
        a_est = np.nanmedian(np.where(good[:, :, None], num / np.maximum(den, 1e-6), np.nan), axis=2)
    log("    可解像素 %.1f%%" % (100 * good.mean()))

    # 亮度兜底表（统计排除内腔，避免污染）
    lut = np.full(256, np.nan)
    kbi = np.clip(np.round(kbl).astype(int), 0, 255)
    gl = good & (~inner)
    for b in range(256):
        m = gl & (kbi == b)
        if m.sum() > 40:
            lut[b] = np.median(a_est[m])
    idx = np.where(~np.isnan(lut))[0]
    lut_f = np.clip(np.interp(np.arange(256), idx, lut[idx]), 0, 1)
    for b in range(1, 256):
        if lut_f[b] > lut_f[b - 1]:
            lut_f[b] = lut_f[b - 1]

    a_raw = lut_f[kbi].copy()
    use = good & np.isfinite(a_est)
    a_raw[use] = np.clip(a_est[use], 0, 1)
    a_raw[kbl >= 248] = 0.0
    a_raw = np.nan_to_num(a_raw, nan=0.0)
    a_canvas = np.clip(np.where(inner, inner_alpha, a_raw), 0, 1)

    # 反算物体真实颜色（素材是白底拍的，照片亮度≠物体颜色）
    a3c = a_canvas[:, :, None]
    solid = a3c > 0.06
    color_c = np.clip(np.where(solid, (kbfull - 255.0 * (1 - a3c)) / np.maximum(a3c, 1e-6), kbfull),
                      0, 255)

    uu, vv = np.meshgrid(np.arange(kbim.width), np.arange(kbim.height))
    xx = np.clip(np.round(KB_X + uu * KB_SCALE).astype(int), 0, CANVAS - 1)
    yy = np.clip(np.round(KB_Y + vv * KB_SCALE).astype(int), 0, CANVAS - 1)
    alpha_src = a_canvas[yy, xx]
    color_src = color_c[yy, xx]

    rgba = np.dstack([color_src, np.clip(alpha_src * 255, 0, 255)]).astype(np.uint8)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(out_path)
    log("    已生成 RGBA 素材: %s" % out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="反解钥匙扣素材透明通道")
    ap.add_argument("--ref", default=os.path.join(ROOT, "assets", "keychain", "sample_final.jpg"))
    ap.add_argument("--keychain", default=os.path.join(ROOT, "assets", "keychain", "keychain_raw.jpg"))
    ap.add_argument("--out", default=os.path.join(ROOT, "assets", "keychain", "keychain_alpha.png"))
    ap.add_argument("--inner-alpha", type=float, default=INNER_ALPHA)
    a = ap.parse_args()
    log("反解钥匙扣透明通道 …")
    solve(a.ref, a.keychain, a.out, a.inner_alpha)


if __name__ == "__main__":
    main()
