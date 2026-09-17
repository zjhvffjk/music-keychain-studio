# -*- coding: utf-8 -*-
"""
钥匙扣商品图合成器（一键出图）

合成 5 层（自下而上）：
    1 模糊底图   —— 封面放大铺满 + 高斯模糊 20px
    2 白色卡纸   —— 四边内缩 161px，厚 53px，纯白
    3 清晰封面   —— 1492×1492 正方形
    4 播放界面图 —— 453×755（3:5）贴进壳体内腔（默认保持原样，见 CURVE_STRENGTH）
    5 钥匙扣叠加 —— RGBA 贴片（alpha 由 keychain_build.py 反解得到）

参数来源：全部由用户的成品参考图逐像素反推，画布 1920×1920。
叠加贴片由 tools/keychain_build.py 生成。

⚠️ 关于 CURVE_STRENGTH（2026-09-16 用户反馈后改）
参考成品里内腔的播放界面是**被手机 App 提亮过**的（后处理痕迹），当初把它
反解成一条曲线并默认套用 → 内腔 UI 区亮度 28.6 被抬到 45.6（+45%），
网易云那种深邃黑变成灰纱且偏暖。用户对照「播放界面商品图」原图后明确
要求原生效果，故默认强度改为 0（不套曲线）。要复现参考成品的提亮用 --curve 1。

用法：
    python tools/make_keychain.py --cover 封面.jpg --player 播放图.jpg --out 成品.jpg
    python tools/make_keychain.py --batch outputs/某某-热门前10        # 整组批处理
"""
import os
import sys
import glob
import json
import argparse
import numpy as np
from PIL import Image, ImageFilter

try:                                    # 与 make_set 同一目录，正常都能导入
    from make_set import save_retry    # 写文件重试，抗 Windows 文件锁
except Exception:                       # 单独跑本脚本时也不该炸
    save_retry = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "assets", "keychain")

# ---------- 版式常量（1920 基准，逐像素反推自成品参考图）----------
CANVAS = 1920
FRAME_OUT = 161
FRAME_THICK = 53
COVER_IN = FRAME_OUT + FRAME_THICK
COVER_SIZE = CANVAS - COVER_IN * 2
BG_BLUR = 20          # 高斯模糊半径
BG_WHITE = 0.0        # 底图不叠白

# 背景亮度上限（取背景区的 P95）：只压暗、不提亮。
# 🔴 为什么必须要有它：白卡纸是纯白 255，而背景是「封面模糊版」。
#    浅色封面的模糊底会亮到接近纯白（实测 04 美人鱼 / 05 江南 的背景 P95 = 255），
#    于是白卡与背景融成一片 —— 用户会看到「正方形白框的上下左右留白不一致」
#    （实测 01 Always Online 顶部第一行就已经是 255，上边完全看不到留白）。
#    参考成品那首是深色封面，背景 P95 只有 106，所以白框四边都很清楚。
#    这里把背景亮度的 P95 压到 BG_CAP 以内，暗封面则完全不动。
BG_CAP = 140.0

PL_X, PL_Y, PL_W, PL_H = 732, 873, 453, 755      # 播放界面图落点与尺寸

OVERLAY = os.path.join(ASSETS, "keychain_overlay.png")
CURVE_JSON = os.path.join(ASSETS, "tone_curve.json")

# 未提供 --cover/--player 时使用的演示占位素材。
# 仓库自带，抽象图形，不含第三方版权内容，可用 tools/make_demo_assets.py 重新生成。
DEMO_DIR = os.path.join(ROOT, "assets", "demo")
PLACEHOLDER_COVER = os.path.join(DEMO_DIR, "cover.jpg")
PLACEHOLDER_PLAYER = os.path.join(DEMO_DIR, "player.png")

# 播放界面色调曲线强度：0=原生（不套曲线，网易云那种深邃黑，默认）
# 1=完全复现参考成品图被 App 提亮后的样子。中间值按比例混合。
CURVE_STRENGTH = 0.0


def log(*a):
    print(*a, flush=True)


def load_curve():
    """播放界面图的色调曲线（256 项 × 3 通道）；缺文件则返回 None"""
    if not os.path.exists(CURVE_JSON):
        return None
    with open(CURVE_JSON, "r", encoding="utf-8") as f:
        d = json.load(f)
    lut = np.array(d["lut"], dtype=np.float32)
    if lut.shape != (3, 256):
        return None
    return lut


def apply_curve(arr, lut, strength=1.0):
    """套用色调曲线；strength=0 原样返回，0~1 之间按比例与原图混合。

    曲线本身是"参考成品图里被 App 提亮"的后处理痕迹，默认不该用
    （见文件头 CURVE_STRENGTH 说明）。
    """
    if lut is None or strength is None or strength <= 0:
        return arr
    idx = np.clip(arr.astype(np.int32), 0, 255)
    out = np.dstack([lut[c][idx[..., c]] for c in range(3)]).astype(np.float32)
    if strength >= 1.0:
        return out
    return arr * (1.0 - strength) + out * strength


def load_overlay(path=OVERLAY):
    """读出钥匙扣 RGBA 贴片并统一到画布尺寸。

    贴片是 1.3MB 的 PNG，解压一次约 0.2s。批量出图（工作台整组 10~50 首）
    时逐张重读会白等十几秒，所以单独抽出来给调用方复用（见 prepare()）。
    """
    ov = Image.open(path).convert("RGBA")
    if ov.size != (CANVAS, CANVAS):
        ov = ov.resize((CANVAS, CANVAS), Image.LANCZOS)
    return ov


def prepare(overlay_path=OVERLAY, curve_path=CURVE_JSON):
    """一次性备好可复用的贴片与色调曲线，返回 (overlay_img, lut)。

    lut 为 None 表示没有曲线文件（按原样贴图，不报错）。
    """
    return load_overlay(overlay_path), load_curve()


def dim_background(canvas):
    """把背景（白卡以外）压暗到 BG_CAP 以内；只压暗，不提亮。

    压暗系数按背景亮度的 P95 算，所以封面越亮压得越多、暗封面一点都不动。
    ⚠️ 注意：这一步会让「我们的底图」与「参考成品的底图」在留白区不同。
       keychain_build.py 解算实物颜色时必须用 dim=False 的底图（那才是参考
       成品作者当时的底图），否则 1px 软边上的反解会带上压暗的色差。
    """
    if BG_CAP >= 255:
        return canvas
    m = np.ones((CANVAS, CANVAS), bool)
    m[FRAME_OUT:FRAME_OUT + COVER_SIZE + 2 * FRAME_THICK,
      FRAME_OUT:FRAME_OUT + COVER_SIZE + 2 * FRAME_THICK] = False
    lum = canvas @ np.array([.299, .587, .114], np.float32)
    p95 = float(np.percentile(lum[m], 95)) if m.any() else 255.0
    if p95 > BG_CAP:
        canvas *= (BG_CAP / p95)
    return canvas


def build_canvas(cov, player_rgb, dim=True):
    """按版式常量拼出「无钥匙扣」底图（1920×1920 float32）。

    唯一实现，生产（compose）与标定（keychain_build.build_base）共用，
    避免两边常量漂移。
    """
    bg = cov.resize((CANVAS, CANVAS), Image.LANCZOS).filter(ImageFilter.GaussianBlur(BG_BLUR))
    canvas = np.asarray(bg).astype(np.float32)
    if BG_WHITE:
        canvas = canvas * (1 - BG_WHITE) + 255.0 * BG_WHITE
    if dim:
        canvas = dim_background(canvas)

    # 白卡纸
    canvas[FRAME_OUT:FRAME_OUT + COVER_SIZE + 2 * FRAME_THICK,
           FRAME_OUT:FRAME_OUT + COVER_SIZE + 2 * FRAME_THICK] = 255.0
    # 清晰封面
    canvas[COVER_IN:COVER_IN + COVER_SIZE, COVER_IN:COVER_IN + COVER_SIZE] = \
        np.asarray(cov.resize((COVER_SIZE, COVER_SIZE), Image.LANCZOS)).astype(np.float32)
    # 播放界面图
    canvas[PL_Y:PL_Y + PL_H, PL_X:PL_X + PL_W] = player_rgb
    return canvas


def compose(cover_path, player_path, out_path, overlay=OVERLAY, lut=None, curve=None):
    """合成一张钥匙扣商品图。

    curve：播放界面曲线强度 0~1。None = 用模块默认 CURVE_STRENGTH（0，原生效果）。
    """
    strength = CURVE_STRENGTH if curve is None else float(curve)
    cov = Image.open(cover_path).convert("RGB")

    # 播放界面图（默认原样贴入；曲线强度由 CURVE_STRENGTH / --curve 决定）
    pl = np.asarray(Image.open(player_path).convert("RGB")
                    .resize((PL_W, PL_H), Image.LANCZOS)).astype(np.float32)
    if lut is not None and strength > 0:
        pl = apply_curve(pl, lut, strength)

    canvas = build_canvas(cov, pl)

    # 钥匙扣叠加（overlay 可以是路径，也可以是已经加载好的 RGBA 图）
    base = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8)).convert("RGBA")
    ov = overlay if isinstance(overlay, Image.Image) else load_overlay(overlay)
    out = Image.alpha_composite(base, ov).convert("RGB")

    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)
    if save_retry:
        save_retry(out, out_path, quality=95)
    else:
        out.save(out_path, quality=95)
    return out


def find_first(patterns):
    for pat in patterns:
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


def batch(folder, overlay, lut, curve=None):
    covers = sorted(glob.glob(os.path.join(folder, "covers", "*.*")))
    players = sorted(glob.glob(os.path.join(folder, "players", "*.png"))) or \
        sorted(glob.glob(os.path.join(folder, "players", "*.jpg")))
    if not covers or not players:
        log("目录里没找到 covers/ 或 players/：" + folder)
        return
    # ⚠️ 以前这里只取第一张封面，整组都用它当底图 —— 多曲目时全错。
    #    现在按 basename 与播放图配对（同名去掉扩展名），配不上才回退按序号。
    cmap = {os.path.splitext(os.path.basename(c))[0]: c for c in covers}
    outs = []
    for i, pl in enumerate(players, 1):
        name = os.path.splitext(os.path.basename(pl))[0]
        cov = cmap.get(name) or covers[(i - 1) % len(covers)]
        out = os.path.join(folder, "keychain", "%s-钥匙扣.jpg" % name)
        compose(cov, pl, out, overlay, lut, curve)
        outs.append(out)
        log("  [%d/%d] %s" % (i, len(players), os.path.basename(out)))
    log("完成，共 %d 张 -> %s" % (len(outs), os.path.join(folder, "keychain")))


def main():
    ap = argparse.ArgumentParser(description="钥匙扣商品图合成")
    ap.add_argument("--cover", default=None, help="封面图（1:1 最佳）")
    ap.add_argument("--player", default=None, help="30×50mm 播放界面图（3:5）")
    ap.add_argument("--overlay", default=OVERLAY, help="钥匙扣 RGBA 叠加贴片")
    ap.add_argument("--out", default=os.path.join(ROOT, "outputs", "keychain_test", "final.jpg"))
    ap.add_argument("--batch", default=None, help="对某歌手输出目录整组批处理")
    ap.add_argument("--curve", type=float, default=None,
                    help="播放界面色调曲线强度 0~1（默认 %s，即原生不套曲线）" % CURVE_STRENGTH)
    a = ap.parse_args()

    if not os.path.exists(a.overlay):
        log("缺少叠加贴片：%s\n请先运行 tools/keychain_build.py" % a.overlay)
        sys.exit(1)

    overlay, lut = prepare(a.overlay)
    eff = CURVE_STRENGTH if a.curve is None else a.curve
    log("色调曲线: %s（强度 %.2f）"
        % ("已加载" if lut is not None else "未找到（按原样贴图）", eff))

    if a.batch:
        batch(a.batch, overlay, lut, a.curve)
        return

    if a.cover and a.player:
        compose(a.cover, a.player, a.out, overlay, lut, a.curve)
        log("已输出: %s" % a.out)
    elif a.cover or a.player:
        log("--cover 与 --player 必须同时提供")
        sys.exit(1)
    else:
        compose(PLACEHOLDER_COVER, PLACEHOLDER_PLAYER, a.out, overlay, lut, a.curve)
        log("已用占位素材输出: %s" % a.out)


if __name__ == "__main__":
    main()
