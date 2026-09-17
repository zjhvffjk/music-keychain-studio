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


def log(*a):
    print(*a, flush=True)


# ---------- 实测几何（改这里之前先重跑 _tmp/measure_overlay.py）----------
OBX0, OBY0, OBX1, OBY1 = 688, 232, 1233, 1687        # 钥匙扣外轮廓
IBX0, IBY0, IBX1, IBY1 = 732, 873, 1184, 1627         # 内腔
OW, OH = OBX1 - OBX0 + 1, OBY1 - OBY0 + 1             # 546 × 1456
IW, IH = IBX1 - IBX0 + 1, IBY1 - IBY0 + 1             # 453 × 755

# ---------- 画布配方（可配置）----------
#   label: 界面显示名            tag: 写进文件名的中文简称（**必须唯一**）
#   w=None: 宽度按钥匙扣比例反算（竖长画布）  h: 画布高（正整数）
#   pad: 上下各留白占画布高的比例（钥匙扣高 = 1 - 2*pad），有效范围 (0, 0.45)
#
# ⚠️ 这里改的只是「外面那层商品图画布」。卡面 players/*.png 必须保持 1:1.667
#    （卡套内腔的比例），动了就嵌不进去 —— 两者是两回事，别混。
#
# 完整清单在 config/canvas_presets.json（可增删改）；下面只是**文件缺失或损坏时的兜底**，
# 避免一个配置文件写坏就把整个商品图功能搞没。
FALLBACK_PRESETS = {
    "long":   dict(label="竖长 · 贴合钥匙扣", tag="竖长", w=None, h=2000, pad=0.060),
    "square": dict(label="方形 1920×1920",   tag="方形", w=1920, h=1920, pad=0.070),
}

PRESET_FILE = os.path.join(ROOT, "config", "canvas_presets.json")
PAD_MIN, PAD_MAX = 0.01, 0.44     # pad ≥ 0.5 会除零 / 算出负宽，必须挡在前面


def _safe_tag(tag):
    """把 tag 清洗成文件名安全的短串。

    tag 会原样拼进商品图文件名（如「01 后来-五月天商品图-淘宝-白底.jpg」）。
    必须挡掉：路径分隔符（/ \\ 会变成子目录）、头尾点号（. / .. 会目录穿越或
    在 NTFS 上退化）、全空白。NTFS 大小写不敏感，所以大小写不同但字形等价的
    tag（F / f）必须在去重阶段当成同一份 —— 这里只负责清洗，去重在 load_presets。
    """
    if tag is None:
        return ""
    t = str(tag)
    for sep in ("/", "\\", os.sep, os.altsep):
        if sep:
            t = t.replace(sep, "")
    t = t.strip().strip(".")          # 头尾去点号与空白，防 ".." /  ".foo."
    # 去掉 Windows 禁用的保留字符，避免保存失败
    for ch in ('"', ":", "*", "?", "<", ">", "|"):
        t = t.replace(ch, "")
    return t


def _norm_preset(key, raw):
    """校验并规整一条预设；非法返回 None（并说明原因，不抛异常）。"""
    if not isinstance(raw, dict):
        log("⚠ 画布预设「%s」不是对象，已忽略" % key)
        return None

    try:
        h = int(raw["h"])                    # 容忍 "1000" 这种字符串写法
        if h <= 0:
            raise ValueError
    except Exception:
        log("⚠ 画布预设「%s」缺少合法的高度 h，已忽略" % key)
        return None

    w = raw.get("w")
    if w is not None:
        try:
            w = int(w)
            if w <= 0:
                raise ValueError
        except Exception:
            log("⚠ 画布预设「%s」的宽度 w 非法（%r），改为按钥匙扣比例反算"
                % (key, raw.get("w")))
            w = None

    try:
        pad = float(raw.get("pad", 0.07))
    except Exception:
        log("⚠ 画布预设「%s」的 pad 非法，改用 0.07" % key)
        pad = 0.07
    # ⚠️ NaN/Infinity 会让 `PAD_MIN <= pad <= PAD_MAX` 恒为 False，
    # 但 min/max 夹不住它们 —— NaN 一路传到 canvas_size() 的 round() 才爆 ValueError，
    # 表现成「这个画布静默不出图 / CLI 崩」。所以先单独拦掉非有限数。
    if not math.isfinite(pad):
        log("⚠ 画布预设「%s」的 pad 不是有限数，改用 0.07" % key)
        pad = 0.07
    elif not (PAD_MIN <= pad <= PAD_MAX):
        log("⚠ 画布预设「%s」的 pad=%.3f 超出 [%.2f, %.2f]，已夹到边界"
            % (key, pad, PAD_MIN, PAD_MAX))
        pad = min(max(pad, PAD_MIN), PAD_MAX)

    # tag 会直接拼进文件名（NTFS 大小写不敏感、且含 / \\ 会变成目录），
    # 必须先把非法字符清掉；清完为空则整条预设作废。
    tag = _safe_tag(raw.get("tag") or key)
    if not tag:
        log("⚠ 画布预设「%s」的 tag 清空后为空或不合法，已忽略" % key)
        return None

    return dict(label=str(raw.get("label") or key), tag=tag, w=w, h=h, pad=pad)


def load_presets(path=PRESET_FILE):
    """读 config/canvas_presets.json。任何异常都退回兜底预设，**绝不抛出去**。

    ⚠️ 这个函数在模块 import 时就会被调用（`CANVAS_SPEC = load_presets()`），
    所以它只能引用**已经定义好**的东西 —— log() 必须在本文件更靠前的位置。
    否则配置文件一写坏就会 NameError，服务端 import 失败 → SHOP=None →
    整个白底商品图功能消失，而不是文档承诺的"退回兜底"。
    """
    try:
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        if not isinstance(user, dict):
            raise ValueError("顶层必须是对象")
    except FileNotFoundError:
        return {k: dict(v) for k, v in FALLBACK_PRESETS.items()}
    except Exception as e:
        log("⚠ 画布预设 %s 读不了（%s: %s），改用兜底预设"
            % (path, type(e).__name__, e))
        return {k: dict(v) for k, v in FALLBACK_PRESETS.items()}

    out, tag_owner = {}, {}
    for k, v in user.items():
        if not k or k.startswith("_"):       # _ 开头的键是注释
            continue
        p = _norm_preset(k, v)
        if p is None:
            continue
        # tag 去重按「小写化后的安全 tag」，这样 F / f 这种在 NTFS 上会互相覆盖的
        # 情况会被当成重复而跳过第二条，而不是落盘时悄悄丢一张图。
        safe = p["tag"].casefold()
        if safe in tag_owner:               # tag 重复 → 文件名会互相覆盖
            log("⚠ 画布预设「%s」的 tag「%s」与「%s」重复，已跳过（tag 必须唯一）"
                % (k, p["tag"], tag_owner[safe]))
            continue
        tag_owner[safe] = k
        out[k] = p

    if not out:
        log("⚠ %s 里没有可用预设，改用兜底预设" % path)
        return {k: dict(v) for k, v in FALLBACK_PRESETS.items()}
    return out


CANVAS_SPEC = load_presets()


def canvas_tag(kind):
    """画布 key → 文件名里用的中文简称。"""
    return (CANVAS_SPEC.get(kind) or {}).get("tag") or kind


def parse_canvases(value):
    """把 --canvas / 接口参数解析成画布 key 列表（服务端也复用这个）。

    接受 "long" / "both" / "long,square" / ["long", "square"]；
    both 展开成基础两款（竖长 + 方形）。未知 key 忽略并提示，全空退回 long。
    """
    if value is None:
        return ["long", "square"]
    if isinstance(value, (list, tuple, set)):
        parts = [str(x) for x in value]
    else:
        parts = str(value).replace(",", " ").split()
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        for k in (["long", "square"] if p == "both" else [p]):
            if k not in CANVAS_SPEC:
                log("⚠ 未知画布预设「%s」，已忽略（可选：%s）"
                    % (k, "/".join(CANVAS_SPEC)))
            elif k not in out:
                out.append(k)
    if out:
        return out
    # 全非法时兜底：优先 long，但用户可能把 long 删了，那就取第一个可用预设
    return ["long"] if "long" in CANVAS_SPEC else [next(iter(CANVAS_SPEC))]

CARD_BLEED = 2          # 卡片每边多出 1px，防止缩放取整导致边缘露白
GRID_COLS = 5           # 拼版列数（仿样板图 5 列）
GRID_CELL_W = 360       # 拼版单元宽（高按竖长比例自动算）
GRID_GAP = 0.12         # 单元间距 = 单元宽 × 该值
GRID_MARGIN = 0.24      # 画布外边距 = 单元宽 × 该值


def load_overlay_trimmed(path=OVERLAY):
    """读贴片并裁到钥匙扣外轮廓 —— 省掉四周大片透明区，缩放更省、定位更准。"""
    ov = Image.open(path).convert("RGBA")
    return ov.crop((OBX0, OBY0, OBX1 + 1, OBY1 + 1))


def canvas_size(kind):
    spec = CANVAS_SPEC[kind]
    h = spec["h"]
    pad = spec.get("pad", 0.07)
    target_h = round(h * (1 - 2 * pad))
    w_need = round(OW * target_h / OH)
    w = spec.get("w") or round(w_need / (1 - 2 * pad))   # 左右也留同样比例的白
    return w, h


def build_unit(player_path, ov_trim, kind="long", bg="white", padding_rgb=None):
    """出一只钥匙扣的商品图。

    kind: long(竖长) / square(正方形)
    bg:   white(纯白底) / transparent(透明底)
    返回 RGBA Image。
    """
    spec = CANVAS_SPEC[kind]
    CW, CH = canvas_size(kind)
    pad = spec.get("pad", 0.07)
    target_h = round(CH * (1 - 2 * pad))
    scale = target_h / OH

    uw = round(OW * scale)
    ux = (CW - uw) // 2
    uy = round(CH * pad)

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
            suffix = canvas_tag(kind)
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
    grid_units = {k: {} for k in canvases}
    for i, (pl, name) in enumerate(zip(players, names), 1):
        log("  [%d/%d] %s" % (i, len(players), name))
        variants_of(name, pl, ov_trim, out_dir, canvases, bgs)
        if grid:
            for kind in canvases:
                grid_units[kind][name] = build_unit(pl, ov_trim, kind=kind, bg="white")

    if grid:
        for kind in canvases:
            order = [n for n in names if n in grid_units.get(kind, {})]
            units = [grid_units[kind][n] for n in order]
            if not units:
                continue
            tag = canvas_tag(kind)
            g = build_grid(units, bg="white")
            p = os.path.join(out_dir, "总览-商品图-%s-白底.jpg" % tag)
            save_img(g, p, bg="white")
            log("  拼版(%s) -> %s  [%dx%d]" % (kind, os.path.basename(p), g.width, g.height))
            tg = build_grid(units, bg="transparent")
            p2 = os.path.join(out_dir, "总览-商品图-%s-透明.png" % tag)
            save_img(tg, p2, bg="transparent")
            log("  拼版(%s) -> %s  [%dx%d]" % (kind, os.path.basename(p2), tg.width, tg.height))
    return names


def main():
    ap = argparse.ArgumentParser(description="钥匙扣商品图（白底/透明底）")
    ap.add_argument("--cover", default=None)
    ap.add_argument("--player", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--batch", default=None, help="对某歌手输出目录整组处理")
    ap.add_argument("--canvas", default="both",
                    help="画布预设，可用逗号给多个（both = 竖长+方形）。可选：%s"
                         % "/".join(CANVAS_SPEC))
    ap.add_argument("--bg", default="both", choices=["white", "transparent", "both"])
    ap.add_argument("--no-grid", action="store_true", help="不出拼版总览")
    ap.add_argument("--only", nargs="*", default=None, help="只处理名字含这些关键词的曲目")
    ap.add_argument("--overlay", default=OVERLAY)
    ap.add_argument("--list-canvas", action="store_true", help="列出所有画布预设后退出")
    a = ap.parse_args()

    if a.list_canvas:
        log("画布预设（%s）：" % PRESET_FILE)
        for k, v in CANVAS_SPEC.items():
            log("  %-9s %-20s %s×%s  pad=%.3f"
                % (k, v.get("label", k), v.get("w") or "自动", v["h"], v.get("pad", 0.07)))
        return

    canvases = parse_canvases(a.canvas)
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
