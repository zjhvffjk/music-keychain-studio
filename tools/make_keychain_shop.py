# -*- coding: utf-8 -*-
"""
钥匙扣「商品图」模式（白底 / 透明底，钥匙扣当主角）

与 make_keychain.py 的分工：
    make_keychain.py  场景图（effect shot）—— 封面模糊铺满当背景 + 白卡纸相框，
                      钥匙扣缩小居中当点缀，画布固定 1920×1920。
    本模块            商品图（product shot）—— 纯白底或透明底，**没有背景大图**，
                      钥匙扣放大当主角，支持竖长 / 正方形两种画布，并支持多只拼版总览。

几何基准（2026-09-17 实测自 assets/keychain/keychain_overlay.png，非估算）：
    贴片 1920×1920 RGBA
    钥匙扣外轮廓（含金属环） x 688~1233 · y 232~1687  → 546 × 1456，比例 1:2.667
    内腔（放卡片的透明区）   x 732~1184 · y 873~1627  → 453 × 755，比例 1:1.667
    卡片源图 players/*.png = 1181×1968，比例与内腔**完全一致** → 直接缩放不变形。
    （该组数值与 make_keychain.py 的 PL_* 常量偏差为 0，两处口径一致。）

用法：
    # 整组批处理（出 4 种单只变体 + 2 种拼版）
    python tools/make_keychain_shop.py --batch outputs/周杰伦-热门前5

    # 指定输出目录 / 只出一部分变体
    python tools/make_keychain_shop.py --batch outputs/某批次 --out 某处 \\
        --canvas long --bg white

    # 单张
    python tools/make_keychain_shop.py --cover 封面.jpg --player 播放图.png --out out.jpg
"""
import os
import sys
import glob
import json
import math
import argparse
from PIL import Image

try:
    from make_set import save_retry          # 写文件重试，抗 Windows 文件锁
except Exception:
    save_retry = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "assets", "keychain")
OVERLAY = os.path.join(ASSETS, "keychain_overlay.png")
DEMO_DIR = os.path.join(ROOT, "assets", "demo")

# ---------- 实测几何（改这里之前先重跑 _tmp/measure_overlay.py）----------
OBX0, OBY0, OBX1, OBY1 = 688, 232, 1233, 1687        # 钥匙扣外轮廓
IBX0, IBY0, IBX1, IBY1 = 732, 873, 1184, 1627         # 内腔
OW, OH = OBX1 - OBX0 + 1, OBY1 - OBY0 + 1             # 546 × 1456
IW, IH = IBX1 - IBX0 + 1, IBY1 - IBY0 + 1             # 453 × 755

# ---------- 画布配方 ----------
#   pad: 上下各留白占画布高的比例（钥匙扣高 = 1 - 2*pad）
#   min_w: 画布最小宽度（避免竖长画布过窄）
CANVAS_SPEC = {
    "long":   dict(w=None, h=2000, pad=0.060),        # 竖长：宽度按钥匙扣比例反算
    "square": dict(w=1920, h=1920, pad=0.070),        # 正方形，沿用主规格
}

CARD_BLEED = 2          # 卡片每边多出 1px，防止缩放取整导致边缘露白
GRID_COLS = 5           # 拼版列数（仿样板图 5 列）
GRID_CELL_W = 360       # 拼版单元宽（高按竖长比例自动算）
GRID_GAP = 0.12         # 单元间距 = 单元宽 × 该值
GRID_MARGIN = 0.24      # 画布外边距 = 单元宽 × 该值


def log(*a):
    print(*a, flush=True)


def load_overlay_trimmed(path=OVERLAY):
    """读贴片并裁到钥匙扣外轮廓 —— 省掉四周大片透明区，缩放更省、定位更准。"""
    ov = Image.open(path).convert("RGBA")
    return ov.crop((OBX0, OBY0, OBX1 + 1, OBY1 + 1))


def canvas_size(kind):
    spec = CANVAS_SPEC[kind]
    h = spec["h"]
    target_h = round(h * (1 - 2 * spec["pad"]))
    w_need = round(OW * target_h / OH)
    w = spec["w"] or round(w_need / (1 - 2 * spec["pad"]))   # 左右也留同样比例的白
    return w, h


def build_unit(player_path, ov_trim, kind="long", bg="white", padding_rgb=None):
    """出一只钥匙扣的商品图。

    kind: long(竖长) / square(正方形)
    bg:   white(纯白底) / transparent(透明底)
    返回 RGBA Image。
    """
    spec = CANVAS_SPEC[kind]
    CW, CH = canvas_size(kind)
    target_h = round(CH * (1 - 2 * spec["pad"]))
    scale = target_h / OH

    uw = round(OW * scale)
    ux = (CW - uw) // 2
    uy = round(CH * spec["pad"])

    if bg == "white":
        base = Image.new("RGBA", (CW, CH), (255, 255, 255, 255))
    elif bg == "transparent":
        base = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    elif bg == "padding":                      # 用封面主色做衬底（备用）
        base = Image.new("RGBA", (CW, CH), tuple(padding_rgb or (255, 255, 255)) + (255,))
    else:
        raise ValueError("未知 bg: %s" % bg)

    # 卡片：按内腔等比缩放，四周各多 1px 藏进卡套边框底下
    card_w = round(IW * scale) + CARD_BLEED
    card_h = round(IH * scale) + CARD_BLEED
    card_x = ux + round((IBX0 - OBX0) * scale) - CARD_BLEED // 2
    card_y = uy + round((IBY0 - OBY0) * scale) - CARD_BLEED // 2
    card = Image.open(player_path).convert("RGB").resize((card_w, card_h), Image.LANCZOS)
    base.paste(card, (card_x, card_y))

    # 贴片盖在上面（内腔透明，卡片正好透出来）
    base.alpha_composite(ov_trim.resize((uw, target_h), Image.LANCZOS), (ux, uy))
    return base


def build_grid(units, cols=None, cell_w=GRID_CELL_W, bg="white",
               gap_ratio=GRID_GAP, margin_ratio=GRID_MARGIN):
    """把若干只单只商品图排成网格总览（仿样板：等距、白底、整体留白）。

    cols 传 None 表示用默认列数，但**不足一整行时按实际数量收窄** ——
    否则 3 只会按 5 列排版，右边空出两格，画布也跟着变宽。
    """
    if not units:
        raise ValueError("没有可拼版的单元")
    cols = min(cols or GRID_COLS, len(units))
    uw, uh = units[0].size
    cell_h = round(cell_w * uh / uw)
    rows = math.ceil(len(units) / cols)
    gap = round(cell_w * gap_ratio)
    margin = round(cell_w * margin_ratio)
    CW = margin * 2 + cols * cell_w + (cols - 1) * gap
    CH = margin * 2 + rows * cell_h + (rows - 1) * gap
    fill = (255, 255, 255, 255) if bg == "white" else (0, 0, 0, 0)
    base = Image.new("RGBA", (CW, CH), fill)
    for i, im in enumerate(units):
        r, c = divmod(i, cols)
        x = margin + c * (cell_w + gap)
        y = margin + r * (cell_h + gap)
        base.alpha_composite(im.resize((cell_w, cell_h), Image.LANCZOS), (x, y))
    return base


def save_img(im, path, bg="white"):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    if path.lower().endswith(".png"):
        im.save(path)
    else:
        out = im.convert("RGB") if im.mode == "RGBA" else im
        if save_retry:
            save_retry(out, path, quality=95)
        else:
            out.save(path, quality=95)
    return path


def variants_of(name, player_path, ov_trim, out_dir, canvases, bgs, log_each=True):
    """给一首歌出全部变体，返回 {变体键: 路径}。"""
    made = {}
    for kind in canvases:
        for bg in bgs:
            im = build_unit(player_path, ov_trim, kind=kind, bg=bg)
            suffix = {"long": "竖长", "square": "方形"}[kind]
            ext = ".png" if bg == "transparent" else ".jpg"
            tag = "" if bg == "white" else "-透明"
            p = os.path.join(out_dir, "%s-商品图-%s%s%s" % (name, suffix, tag, ext))
            save_img(im, p, bg=bg)
            made[(kind, bg)] = p
            if log_each:
                log("    %s%s  ->  %s" % (suffix, tag, os.path.basename(p)))
    return made


def batch(folder, out_dir=None, canvases=("long", "square"), bgs=("white", "transparent"),
          grid=True, only=None):
    covers = sorted(glob.glob(os.path.join(folder, "covers", "*.*")))
    players = sorted(glob.glob(os.path.join(folder, "players", "*.png"))) or \
        sorted(glob.glob(os.path.join(folder, "players", "*.jpg")))
    if not players:
        log("目录里没找到 players/：" + folder)
        return []
    cmap = {os.path.splitext(os.path.basename(c))[0]: c for c in covers}
    out_dir = out_dir or os.path.join(folder, "shop")
    ov_trim = load_overlay_trimmed()

    names = [os.path.splitext(os.path.basename(p))[0] for p in players]
    if only:
        keep = [i for i, n in enumerate(names) if any(k in n for k in only)]
        players = [players[i] for i in keep]
        names = [names[i] for i in keep]
        if not players:
            log("--only 没匹配到任何曲目")
            return []

    log("共 %d 首 → %s" % (len(players), out_dir))
    grid_units = {"long": {}, "square": {}}
    for i, (pl, name) in enumerate(zip(players, names), 1):
        log("  [%d/%d] %s" % (i, len(players), name))
        variants_of(name, pl, ov_trim, out_dir, canvases, bgs)
        if grid:
            for kind in canvases:
                grid_units[kind][name] = build_unit(pl, ov_trim, kind=kind, bg="white")

    if grid and grid_units["long"]:
        order = [n for n in names if n in grid_units["long"]]
        for kind in canvases:
            units = [grid_units[kind][n] for n in order]
            if not units:
                continue
            g = build_grid(units, bg="white")
            p = os.path.join(out_dir, "总览-商品图-%s-白底.jpg" % {"long": "竖长", "square": "方形"}[kind])
            save_img(g, p, bg="white")
            log("  拼版(%s) -> %s  [%dx%d]" % (kind, os.path.basename(p), g.width, g.height))
            tg = build_grid(units, bg="transparent")
            p2 = os.path.join(out_dir, "总览-商品图-%s-透明.png" % {"long": "竖长", "square": "方形"}[kind])
            save_img(tg, p2, bg="transparent")
            log("  拼版(%s) -> %s  [%dx%d]" % (kind, os.path.basename(p2), tg.width, tg.height))
    return names


def main():
    ap = argparse.ArgumentParser(description="钥匙扣商品图（白底/透明底）")
    ap.add_argument("--cover", default=None)
    ap.add_argument("--player", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--batch", default=None, help="对某歌手输出目录整组处理")
    ap.add_argument("--canvas", default="both", choices=["long", "square", "both"])
    ap.add_argument("--bg", default="both", choices=["white", "transparent", "both"])
    ap.add_argument("--no-grid", action="store_true", help="不出拼版总览")
    ap.add_argument("--only", nargs="*", default=None, help="只处理名字含这些关键词的曲目")
    ap.add_argument("--overlay", default=OVERLAY)
    a = ap.parse_args()

    canvases = ("long", "square") if a.canvas == "both" else (a.canvas,)
    bgs = ("white", "transparent") if a.bg == "both" else (a.bg,)

    if not os.path.exists(a.overlay):
        log("缺少贴片：%s" % a.overlay)
        sys.exit(1)

    if a.batch:
        batch(a.batch, a.out, canvases, bgs, grid=not a.no_grid, only=a.only)
        return

    if not a.player:
        a.player = os.path.join(DEMO_DIR, "player.png")
        log("未提供 --player，用占位素材：%s" % a.player)
    out_dir = a.out or os.path.join(ROOT, "outputs", "keychain_shop_test")
    os.makedirs(out_dir, exist_ok=True)
    ov_trim = load_overlay_trimmed()
    variants_of("demo", a.player, ov_trim, out_dir, canvases, bgs)


if __name__ == "__main__":
    main()
