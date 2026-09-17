# -*- coding: utf-8 -*-
"""
钥匙扣素材 → 画布 的落位标定器（IoU 最优化）

用途：**换钥匙扣素材 / 改画布尺寸后必跑**，标出 KB_SCALE / KB_X / KB_Y 三个常量。

为什么不能用估算（两种都实测踩过坑）：
  · 饱和度分离法（扫壳体左右边框 x 再相除）—— 只知道宽度、不知道纵向落点，
    本次算出 (244,-26)，实测**偏了 24px**
  · 模板匹配 NCC —— 被亮边框带偏，NCC=0.956 却偏了 18px
偏差 24px 的后果：遮罩和参考里的实物根本没对齐 → 环看起来又细又浅、
环外一圈白雾。**这是"钥匙圈细节有问题"的真根因，不是 alpha 算法的问题。**

原理：把「素材剪影」（白底照 lum<250）按候选 (scale, dx, dy) 映射到画布，
与「参考剪影」（|ref-base|>25，即参考里确实压着实物的地方）求 IoU，取最大。
只在上半部（环 + 挂耳，对比度最高）搜索 —— 那里两种剪影都可靠。

用法：
    python tools/keychain_fit.py            # 粗搜 + 精搜，打印最优参数
    python tools/keychain_fit.py --apply    # 搜完直接把新值写回 keychain_build.py
"""
import os
import re
import sys
import argparse
import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import noproxy            # noqa: F401  直连补丁（绕过本机 HTTP_PROXY）
import keychain_build as KB

BUILD = os.path.join(HERE, "keychain_build.py")
# 搜索范围（可按素材微调；本次最优值落在 1.13850 / 232 / -12）
SC_RANGE = (1.090, 1.190, 0.005)      # scale 粗搜
SC_FINE = 0.0015                      # scale 精搜步长
DX_RANGE = (215, 280, 4)              # dx 粗搜
DY_RANGE = (-70, 45, 4)               # dy 粗搜
BAND = (slice(190, 900), slice(640, 1290))    # 只在上半部打分


def silhouettes():
    """返回 (参考剪影 bool 画布坐标, 素材剪影 PIL 原图坐标, base)"""
    ref = np.asarray(Image.open(KB.REF).convert("RGB")).astype(np.float32)
    P = np.asarray(Image.open(KB.PLAYER).convert("RGB")
                   .resize((KB.PL_W, KB.PL_H), Image.LANCZOS)).astype(np.float32)
    base = KB.build_base(P, dim=False)      # 参考成品那张图没压暗过背景
    d = np.abs(ref - base).max(-1)
    rsil = d > 25.0
    # 开运算去孤立噪点（底图与参考在封面细节处也会有小差异）
    ri = Image.fromarray((rsil * 255).astype(np.uint8))
    ri = ri.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    rsil = np.asarray(ri) > 127

    kb = Image.open(KB.KBRAW).convert("RGB")
    ksil = (np.asarray(kb).astype(np.float32) @ KB.LUM) < 250.0
    return ref, rsil, Image.fromarray((ksil * 255).astype(np.uint8))


def make_score(rsil, ksil_img):
    target = rsil[BAND]

    def score(s, dx, dy):
        m = ksil_img.transform(
            (KB.CANVAS, KB.CANVAS), Image.AFFINE,
            (1.0 / s, 0, -dx / s, 0, 1.0 / s, -dy / s),
            resample=Image.NEAREST, fillcolor=0)
        a = np.asarray(m)[BAND] > 127
        return np.logical_and(a, target).sum() / max(1, np.logical_or(a, target).sum())
    return score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="把最优值写回 keychain_build.py")
    a = ap.parse_args()

    ref, rsil, ksil_img = silhouettes()
    score = make_score(rsil, ksil_img)

    cur = score(KB.KB_SCALE, KB.KB_X, KB.KB_Y)
    print("当前 IoU = %.4f   (scale=%.5f dx=%d dy=%d)"
          % (cur, KB.KB_SCALE, KB.KB_X, KB.KB_Y))
    if cur < 0.85:
        print("  ⚠️ 低于 0.85 —— 遮罩与参考实物没对齐，必须先重标定再谈 alpha")

    best = (cur, KB.KB_SCALE, KB.KB_X, KB.KB_Y)
    s0, s1, ds = SC_RANGE
    for s in np.arange(s0, s1 + 1e-9, ds):
        for dx in range(DX_RANGE[0], DX_RANGE[1], DX_RANGE[2]):
            for dy in range(DY_RANGE[0], DY_RANGE[1], DY_RANGE[2]):
                v = score(s, dx, dy)
                if v > best[0]:
                    best = (v, s, dx, dy)
    print("粗搜 -> IoU %.4f  scale=%.5f dx=%d dy=%d" % best)

    _, bs, bdx, bdy = best
    for s in np.arange(bs - 2 * ds, bs + 2 * ds + 1e-9, SC_FINE):
        for dx in range(bdx - DX_RANGE[2], bdx + DX_RANGE[2] + 1):
            for dy in range(bdy - DY_RANGE[2], bdy + DY_RANGE[2] + 1):
                v = score(s, dx, dy)
                if v > best[0]:
                    best = (v, s, dx, dy)
    iou, s, dx, dy = best
    print("精搜 -> IoU %.4f  scale=%.5f dx=%d dy=%d" % best)

    kb = np.asarray(Image.open(KB.KBRAW).convert("RGB")).astype(np.float32)
    yy, xx = np.where((kb @ KB.LUM) < 250)
    ys, xs = np.where(rsil)
    print("")
    print("映射后包围盒  素材 x %.0f~%.0f  y %.0f~%.0f"
          % (dx + xx.min() * s, dx + xx.max() * s, dy + yy.min() * s, dy + yy.max() * s))
    print("参考          参考 x %d~%d  y %d~%d" % (xs.min(), xs.max(), ys.min(), ys.max()))
    print("→ 建议写回：KB_SCALE = %.5f   KB_X, KB_Y = %d, %d" % (s, dx, dy))

    if not a.apply:
        print("\n（加 --apply 可直接写回 keychain_build.py）")
        return
    # 护栏：IoU 涨幅 <0.01 且当前值已经达标时不要动 —— 实测 0.8904→0.8922 这种
    # 微涨对成品 MAE 毫无影响（1.901 vs 1.898，噪声级），改了反而要重跑整条链路。
    if cur >= 0.85 and (iou - cur) < 0.01:
        print("⚠️ IoU 仅涨 %.4f（当前已达标 %.4f）—— 不值得改，保持现值。" % (iou - cur, cur))
        return
    src = open(BUILD, encoding="utf-8").read()
    src2 = re.sub(r"KB_SCALE = [0-9.]+", "KB_SCALE = %.5f" % s, src, count=1)
    src2 = re.sub(r"KB_X, KB_Y = -?\d+, -?\d+", "KB_X, KB_Y = %d, %d" % (dx, dy),
                  src2, count=1)
    if src2 == src:
        print("⚠️ 没匹配到常量行，请手动改")
        return
    open(BUILD, "w", encoding="utf-8").write(src2)
    print("已写回 %s —— 记得重跑 keychain_build.py 重建贴片" % BUILD)


if __name__ == "__main__":
    main()
