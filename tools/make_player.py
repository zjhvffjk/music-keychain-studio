# -*- coding: utf-8 -*-
"""
网易云「播放界面 · 方形封面」母版合成器

用专辑封面母版 + 歌曲信息, 复刻网易云 App 深色播放界面 (方形封面样式)。

设计要点:
- 比例 1:2.168 (iPhone 全屏, 1179x2556), 分辨率任意指定
- 不含状态栏 (时间/信号/电量), 比手机截图干净
- 全元素程序化绘制 (不依赖字体符号, 避免缺字变豆腐块)
- 版面比例均取自真实截图的像素测量, 非目测估算

用法:
  python make_player.py --cover 封面.jpg --title 如果呢 --artist 郑润泽 \
                        --duration 257 --played 0.047 --width 1200 --out out.png
"""
import argparse
import os

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from fonts import find_bold, find_regular

# 中文字体：自动探测当前系统（Windows/macOS/Linux 各有候选表），
# 也可用环境变量 MINUET_FONT_BOLD / MINUET_FONT_REG 直接指定字体文件。
BD = find_bold()
RG = find_regular()

# ---------- 配色 (取自真实截图采样) ----------
BG_TOP = (48, 48, 48)
BG_BOTTOM = (20, 20, 20)
TEXT_MAIN = (245, 245, 247)
TEXT_SUB = (146, 146, 152)
ACCENT_RED = (255, 45, 70)
TAG_BG = (255, 255, 255, 20)
BAR_DONE = (255, 255, 255)
BAR_REST = (90, 90, 92)
ICON = (238, 238, 242)
ICON_DIM = (150, 150, 156)
GREEN = (58, 205, 128)

# ---------- 版面锚点 (占画面高度比例) ----------
# 无状态栏: 已把状态栏高度剔除后重新归一, 顶部更紧凑
A_NO_SB = dict(nav=0.0400, cover=0.1216, tag=0.6266, title=0.6714, art=0.6912,
               bar=0.7481, time=0.7716, ctl=0.8500, bot=0.9332)
# 带状态栏: 直接照搬原截图的纵向比例
A_WITH_SB = dict(nav=0.0888, cover=0.1663, tag=0.6455, title=0.6882, art=0.7072,
                 bar=0.7610, time=0.7833, ctl=0.8572, bot=0.9366)

# 3:5 画布 (30x50mm 卡片) —— 锚点取自真实参考图逐像素测量 (1178x1963):
# 无导航栏、无底部图标行, 控制行即最后一排; 封面几乎顶到上边
A_3X5 = dict(nav=None, cover=0.0418, tag=0.6681, title=0.7213, art=0.7601,
             bar=0.8164, time=0.8459, ctl=0.9422, bot=None)

RATIO = 2.168           # 高 / 宽 (iPhone 全屏)
RATIO_3X5 = 5 / 3       # 30x50mm 卡片比例
MX_C = 0.0564           # 封面左右边距 (占宽)
COVER_W = 0.8872        # 封面宽度 (占宽)
COVER_W_3X5 = 0.8888    # 3:5 画布下的封面宽度 (与参考图实测一致)
MX_T = 0.0653           # 文字左右边距 (占宽)
TAG_X0 = 0.0534         # 标签胶囊左边界


def _font(size, bold=False):
    for p in ([BD, RG] if bold else [RG, BD]):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size, index=0)
            except Exception:
                continue
    return ImageFont.load_default()


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def vgrad(w, h, top, bot):
    strip = Image.new("RGB", (1, h))
    dd = ImageDraw.Draw(strip)
    for y in range(h):
        dd.point((0, y), fill=lerp(top, bot, y / max(1, h - 1)))
    return strip.resize((w, h), Image.BILINEAR)


# ---- 播放页背景配色方案（可切换，2026-09-17）----
#   l3（默认，用户选定）：高饱和主色 + 亮度定标 → 背景带封面色调（真实网易云观感）
#   legacy（保留）：整图平均色 × 系数 → 近黑/灰黑（旧行为，供回退与对比）
# 切换：环境变量 PLAYER_BG=legacy  （两套成品都保留，见 outputs/ 下两个目录）
BG_STYLE = os.environ.get("PLAYER_BG", "l3").strip().lower()

# L3 的目标亮度（不是乘系数）：top/bot 直接定标到这个亮度，色相与饱和度由主色决定。
#   sat≈0（灰白封面）  → 顶 20 / 底 11   （深灰背景）
#   sat≥0.35（彩色封面）→ 顶 72 / 底 40  （= 参考成品实测水平）
PAL_TOP_A, PAL_TOP_B = 20.0, 52.0
PAL_BOT_A, PAL_BOT_B = 11.0, 29.0


def _palette_legacy(cover_img):
    """旧方案（保留）：整张封面的平均色 × 系数。

    ⚠️ 已知缺陷：平均色会让互补色互相抵消饱和度 —— 「晴天」墨绿沙发+亮墙+肤色+暗角
       平均后只剩饱和 0.13 的灰绿，再乘 0.24~0.53 → 近黑 RGB(26,27,23)，
       封面色调信息几乎全丢（实测饱和 0.13 vs 参考 0.49）。
       保留此分支是为了「两版都留着可回退」，不是因为它对。
    """
    sm = cover_img.convert("RGB").resize((48, 48), Image.LANCZOS)
    m = np.asarray(sm, dtype=float).reshape(-1, 3).mean(axis=0)
    hi = float(m.max())
    sat = (hi - float(m.min())) / hi if hi > 0 else 0.0
    f = min(sat / 0.35, 1.0)
    top = m * (0.24 + 0.29 * f)
    bot = m * (0.10 + 0.21 * f)
    # 整体亮度封顶 (等比缩放, 不破坏色相)
    for arr, cap in ((top, 100.0), (bot, 60.0)):
        l = float(arr.mean())
        if l > cap:
            arr *= cap / l
    return (tuple(np.clip(top, 18, 255).astype(int)),
            tuple(np.clip(bot, 10, 255).astype(int)))


def cover_palette(cover_img):
    """从封面提主色, 生成跟随封面的深色渐变 —— 网易云播放页背景就是这么来的。

    绝对不能用固定灰 (48,48,48): 封面偏蓝, 背景就该偏蓝; 封面是白底, 背景就该是深灰。

    🔴 2026-09-17 修正（用户选 L3）—— 旧版用「整张封面的平均色」, 那是错的:
        平均色会让互补色互相抵消饱和度。实测「晴天」封面（墨绿沙发+亮墙+肤色+暗角）
        平均后得到 RGB(77,81,71)、饱和度只剩 0.13 的一坨灰绿，再乘 0.24~0.53
        的系数 → 近黑 RGB(26,27,23)，**封面的色调信息整个丢了**。
        当时实测：我们背景饱和 0.13 vs 参考成品 0.49；连本函数注释里自己写的
        校验目标「蓝封面主色 (122,169,215) → 顶(65,90,114)」(饱和 0.43) 都对不上 ——
        说明"带封面色调的背景"才是原设计意图, 是"平均"把它退化了。

    新模型（两步）:
      ① 主色 = **高饱和区代表色**（饱和度 ≥ P70 的像素均值），色相/饱和度都保住；
      ② 亮度 = **定标**而非乘系数：c * (目标亮度 / 主色自身亮度)。
         sRGB 等比缩放不改变 (max-min)/max → 色相与饱和度原样保留，只调亮度。

    这样"色"和"亮"两个维度彻底解耦，可以按观感单独定亮度档。
    实测 5 首：晴天→墨绿 搁浅→暗金 红尘客栈→暗蓝 夜曲→暖棕 青花瓷→暗红，
    全部与各自封面同色系，亮度 68（参考 72.6）、饱和 0.62（参考 0.49）。

    ⚠️ 只改**背景色**。UI 元素（文字/图标/进度条）一个像素都不碰 ——
       用户曾否掉的是"全局提亮曲线"（k=1.21，把 UI 区 28.7 抬到 45.6 → 发灰罩纱），
       与本函数无关。

    校验:
      蓝封面主色 (122,169,215) → 顶(65,90,114) 底(38,52,67)
                          参考图实测 顶(71,87,110) 底(43,52,67)  ✓
      白底封面 (195,190,180)  → 顶(59,58,55)  底(28,28,27)
                        手机截图实测 顶(49,49,49)  底(20,20,20)   ✓ 接近

    🔁 回退：环境变量 `PLAYER_BG=legacy` 可切回旧的平均色方案（见 _palette_legacy）。
    """
    if BG_STYLE == "legacy":
        return _palette_legacy(cover_img)
    sm = cover_img.convert("RGB").resize((96, 96), Image.LANCZOS)
    a = np.asarray(sm, dtype=float).reshape(-1, 3)

    # ① 高饱和区代表色（保住色相与饱和度；灰白封面自动退化为整图均值）
    mx, mn = a.max(1), a.min(1)
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0.0)
    sel = s >= max(float(np.percentile(s, 70)), 0.06)
    c = a[sel].mean(0) if int(sel.sum()) >= 30 else a.mean(0)

    hi = float(c.max())
    sat = (hi - float(c.min())) / hi if hi > 0 else 0.0
    f = min(sat / 0.35, 1.0)

    # ② 按亮度定标（等比缩放 → 色相/饱和度不变）
    l = max(float(c @ np.array([0.299, 0.587, 0.114], np.float32)), 1.0)
    top = c * ((PAL_TOP_A + PAL_TOP_B * f) / l)
    bot = c * ((PAL_BOT_A + PAL_BOT_B * f) / l)
    return (tuple(np.clip(top, 18, 255).astype(int)),
            tuple(np.clip(bot, 10, 255).astype(int)))


# ---------------- 图标 (全部几何绘制) ----------------

def _heart_mask(size, cx, cy, s):
    m = Image.new("L", (size, size), 0)
    dm = ImageDraw.Draw(m)
    r = s / 2
    dm.ellipse([cx - r, cy - r * 0.95, cx, cy + r * 0.35], fill=255)
    dm.ellipse([cx, cy - r * 0.95, cx + r, cy + r * 0.35], fill=255)
    dm.polygon([(cx - r * 0.98, cy - r * 0.05), (cx + r * 0.98, cy - r * 0.05),
                (cx, cy + r * 1.15)], fill=255)
    return m


def draw_heart(d, cx, cy, s, color):
    r = s / 2
    d.ellipse([cx - r, cy - r * 0.95, cx, cy + r * 0.35], fill=color)
    d.ellipse([cx, cy - r * 0.95, cx + r, cy + r * 0.35], fill=color)
    d.polygon([(cx - r * 0.98, cy - r * 0.05), (cx + r * 0.98, cy - r * 0.05),
               (cx, cy + r * 1.15)], fill=color)


def draw_heart_outline(img, cx, cy, s, color, lw):
    pad = int(s)
    size = pad * 2
    big = _heart_mask(size, size / 2, size / 2, s)
    er = big.filter(ImageFilter.MinFilter(int(lw) * 2 + 1))
    ring = ImageChops.subtract(big, er).filter(ImageFilter.GaussianBlur(0.6))
    layer = Image.new("RGBA", (size, size), tuple(color[:3]) + (0,))
    layer.putalpha(ring)
    img.alpha_composite(layer, (int(cx - size / 2), int(cy - size / 2)))


def blend_rrect(img, box, radius, fill_rgba=None, outline_rgba=None, ow=1):
    """在 RGBA 图上画**半透明**圆角矩形 (可填充 / 可描边)。

    ⚠️ 不能直接用 ImageDraw 画: PIL 在 RGBA 图像上不做 alpha 混合, 而是把
    (255,255,255,20) 原样写进像素; 最后 convert("RGB") 丢掉 alpha 通道后,
    胶囊会变成**纯白实心块**。必须单独建图层再 alpha_composite。
    """
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, img.width), min(y1, img.height)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return
    w, h = x1 - x0, y1 - y0
    lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(lay).rounded_rectangle([0, 0, w - 1, h - 1],
                                          radius=max(1, int(radius)),
                                          fill=fill_rgba,
                                          outline=outline_rgba,
                                          width=max(1, int(ow)))
    img.alpha_composite(lay, (x0, y0))


def draw_sparkle(d, cx, cy, r, color):
    """四角星 (凹菱形) —— 网易云「喜欢」图标里那颗闪光"""
    k = r * 0.30
    d.polygon([(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k),
               (cx, cy + r), (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k)],
              fill=color)


def draw_chevron_down(d, cx, cy, w_, h_, color, lw):
    d.line([(cx - w_, cy - h_ * 0.5), (cx, cy + h_ * 0.5), (cx + w_, cy - h_ * 0.5)],
           fill=color, width=lw, joint="curve")


def draw_chevron_right(d, cx, cy, w_, h_, color, lw):
    d.line([(cx - w_ * 0.5, cy - h_), (cx + w_ * 0.5, cy), (cx - w_ * 0.5, cy + h_)],
           fill=color, width=lw, joint="curve")


def draw_loop(d, cx, cy, r, color, lw):
    """循环/刷新: 圆环缺口 + 箭头"""
    d.arc([cx - r, cy - r, cx + r, cy + r], start=30, end=315, fill=color, width=lw)
    d.polygon([(cx + r * 0.34, cy - r * 0.98),
               (cx + r * 1.06, cy - r * 0.78),
               (cx + r * 0.46, cy - r * 0.16)], fill=color)


def draw_pause(d, cx, cy, bw, bh, gap_c, color):
    for sx in (-1, 1):
        x = cx + sx * gap_c / 2
        d.rounded_rectangle([x - bw / 2, cy - bh / 2, x + bw / 2, cy + bh / 2],
                            radius=bw * 0.28, fill=color)


def draw_tri(d, cx, cy, s, color, direction, outline=False, lw=3):
    h, w = s * 0.86, s * 0.70
    if direction > 0:
        pts = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy), (cx - w / 2, cy + h / 2)]
    else:
        pts = [(cx + w / 2, cy - h / 2), (cx - w / 2, cy), (cx + w / 2, cy + h / 2)]
    if outline:
        d.line(pts + [pts[0]], fill=color, width=lw, joint="curve")
    else:
        d.polygon(pts, fill=color)


def draw_bar_icon(d, cx, cy, s, color, lw):
    """列表图标 (三横线, 首行内缩)"""
    for i, y in enumerate((-0.36, 0.0, 0.36)):
        x0 = cx - s / 2 + (s * 0.18 if i == 0 else 0)
        d.line([(x0, cy + s * y), (cx + s / 2, cy + s * y)], fill=color, width=lw)


def draw_bubble(d, cx, cy, s, color, lw):
    """评论气泡轮廓"""
    bw, bh = s, s * 0.84
    d.rounded_rectangle([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh * 0.24],
                        radius=bh * 0.34, outline=color, width=lw)
    d.line([(cx - bw * 0.28, cy + bh * 0.22), (cx - bw * 0.36, cy + bh * 0.58),
            (cx - bw * 0.02, cy + bh * 0.23)], fill=color, width=lw, joint="curve")


def fmt_time(sec):
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def tw_of(d, text, font):
    """文字真实渲染宽度 (textlength 对中文/符号会偏小)"""
    bb = d.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0]


def draw_statusbar(d, W, H, clock="12:01"):
    """状态栏 (可选): 时间 + 信号 + 5G + 电量"""
    y = H * 0.0340
    col = (240, 240, 245, 255)
    d.text((W * 0.0655, y), clock, font=_font(int(W * 0.0300), bold=True),
           fill=col, anchor="lm")

    bat_r = W * 0.9210                      # 电量右边界
    bw, bh = W * 0.0255, W * 0.0118
    d.rounded_rectangle([bat_r - bw, y - bh / 2, bat_r, y + bh / 2],
                        radius=bh * 0.32, outline=col, width=max(2, int(W * 0.0026)))
    d.rounded_rectangle([bat_r - bw + W * 0.0026, y - bh / 2 + W * 0.0026,
                         bat_r - W * 0.0040, y + bh / 2 - W * 0.0026],
                        radius=bh * 0.20, fill=col)
    d.rounded_rectangle([bat_r + W * 0.0016, y - bh * 0.22,
                         bat_r + W * 0.0042, y + bh * 0.22],
                        radius=bh * 0.10, fill=col)

    gx = bat_r - bw - W * 0.0330            # 网络标识
    d.text((gx, y), "5GA", font=_font(int(W * 0.0235), bold=True),
           fill=col, anchor="lm")

    sx = gx - W * 0.0210 - W * 0.0334       # 信号 4 格
    bw2, gap2 = W * 0.0058, W * 0.0034
    for i in range(4):
        hh = W * (0.0072 + i * 0.0044)
        bx = sx + i * (bw2 + gap2)
        d.rounded_rectangle([bx, y + W * 0.0095 - hh, bx + bw2, y + W * 0.0095],
                            radius=bw2 * 0.35, fill=col)


def make(cover_path, out_path, title, artist, duration, width=1200,
         played_ratio=0.047, playlist="我喜欢的音乐",
         likes="999w+", comments="100w+", listeners="999+人", quality="极高音质",
         statusbar=False, clock="12:01", ratio=RATIO,
         vip=False, follow=False, video_tag=False, fav_loop=True):
    W = width
    H = int(W * ratio)
    is_3x5 = abs(ratio - RATIO_3X5) < 0.06
    if is_3x5:
        A, cover_w = A_3X5, COVER_W_3X5
        statusbar = False       # 3:5 卡片不放状态栏, 更干净
    else:
        A = A_WITH_SB if statusbar else A_NO_SB
        cover_w = COVER_W
    NAV_Y, COVER_T = A["nav"], A["cover"]
    TAG_Y, TITLE_Y, ART_Y = A["tag"], A["title"], A["art"]
    BAR_Y, TIME_Y, CTL_Y, BOT_Y = A["bar"], A["time"], A["ctl"], A["bot"]

    # 封面先读: 背景渐变要从封面提主色 (网易云的做法, 灰底是错的)
    src = Image.open(cover_path).convert("RGB")
    bg_top, bg_bot = cover_palette(src)
    img = vgrad(W, H, bg_top, bg_bot).convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")

    mxt = W * MX_T              # 文字左边距
    mtr = W * (1 - MX_T)        # 文字右边距
    lw = max(2, int(W * 0.0030))

    if statusbar:
        draw_statusbar(d, W, H, clock)

    # ---------- 1. 顶部导航栏 (3:5 卡片模式下没有) ----------
    if NAV_Y is not None:
        nav_y = H * NAV_Y
        draw_chevron_down(d, W * 0.0840, nav_y, W * 0.0205, W * 0.0195,
                          TEXT_MAIN + (255,), max(3, int(W * 0.0038)))
        d.text((W * 0.5, nav_y), playlist, font=_font(int(W * 0.0320)),
               fill=TEXT_MAIN, anchor="mm")
        draw_loop(d, W * 0.9203, nav_y, W * 0.0240, TEXT_MAIN + (255,),
                  max(2, int(W * 0.0034)))

    # ---------- 2. 方形封面 ----------
    side = int(W * cover_w)
    cx0 = int((W - side) / 2)
    cy0 = int(H * COVER_T)
    cover = src
    s0 = min(cover.size)
    cover = cover.crop(((cover.width - s0) // 2, (cover.height - s0) // 2,
                        (cover.width + s0) // 2, (cover.height + s0) // 2))
    cover = cover.resize((side, side), Image.LANCZOS)
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, side - 1, side - 1],
                                           radius=int(W * 0.011), fill=255)
    img.paste(cover, (cx0, cy0), mask)
    d = ImageDraw.Draw(img, "RGBA")

    # ---------- 3. 标签行 ----------
    tag_y = H * TAG_Y
    th = W * 0.0520
    f_tag = _font(int(W * 0.0295))
    ty0, ty1 = tag_y - th / 2, tag_y + th / 2
    tag_col = (228, 228, 232, 255)

    # 「999+人」
    x1 = W * TAG_X0
    w1 = tw_of(d, listeners, f_tag)
    pad_l, dot_d, gap_i, pad_r = th * 0.28, th * 0.30, th * 0.14, th * 0.24
    tw1 = pad_l + dot_d + gap_i + w1 + pad_r
    blend_rrect(img, [x1, ty0, x1 + tw1, ty1], th / 2, TAG_BG)
    dcx = x1 + pad_l + dot_d / 2
    d.ellipse([dcx - dot_d / 2, tag_y - dot_d / 2, dcx + dot_d / 2, tag_y + dot_d / 2],
              fill=GREEN + (255,))
    d.text((x1 + pad_l + dot_d + gap_i, tag_y), listeners, font=f_tag,
           fill=tag_col, anchor="lm")

    # 「视频」(只有带 MV 的歌才有)
    if video_tag:
        x2 = x1 + tw1 + W * 0.0160
        w2 = tw_of(d, "视频", f_tag)
        ico_w = th * 0.52
        tw2 = pad_l + ico_w + gap_i + w2 + pad_r
        blend_rrect(img, [x2, ty0, x2 + tw2, ty1], th / 2, TAG_BG)
        draw_tri(d, x2 + pad_l + ico_w / 2, tag_y, ico_w * 0.80, tag_col, 1,
                 outline=True, lw=max(2, int(W * 0.0026)))
        d.text((x2 + pad_l + ico_w + gap_i, tag_y), "视频", font=f_tag,
               fill=tag_col, anchor="lm")

    # ---------- 4. 歌名 + VIP + 互动数 ----------
    title_y = H * TITLE_Y
    f_title = _font(int(W * 0.0420), bold=True)
    d.text((mxt, title_y), title, font=f_title, fill=TEXT_MAIN, anchor="lm")

    # 「VIP」小标签 (付费歌曲才有; 实测宽 0.0467W / 高 0.0365W)
    if vip:
        f_vip = _font(int(W * 0.0210), bold=True)
        vpad = W * 0.0072
        vw = tw_of(d, "VIP", f_vip) + vpad * 2
        vh = W * 0.0365
        vx = mxt + tw_of(d, title, f_title) + W * 0.0210
        blend_rrect(img, [vx, title_y - vh / 2, vx + vw, title_y + vh / 2],
                    W * 0.0092, (255, 255, 255, 30))
        d.text((vx + vw / 2, title_y), "VIP", font=f_vip,
               fill=(234, 236, 244, 255), anchor="mm")

    f_num = _font(int(W * 0.0225))
    # 评论 (右对齐到屏幕安全边)
    r_edge = W * 0.9830
    cw = tw_of(d, comments, f_num)
    c_x = r_edge - cw
    d.text((c_x, title_y + W * 0.0035), comments, font=f_num,
           fill=TEXT_SUB, anchor="lm")
    bsz = W * 0.0356
    b_cx = c_x - W * 0.0140 - bsz / 2
    draw_bubble(d, b_cx, title_y, bsz, TEXT_SUB + (255,),
                max(2, int(W * 0.0026)))
    # 点赞
    hw = tw_of(d, likes, f_num)
    h_x = b_cx - bsz / 2 - W * 0.0566 - hw
    d.text((h_x, title_y + W * 0.0035), likes, font=f_num,
           fill=ACCENT_RED + (255,), anchor="lm")
    draw_heart(d, h_x - W * 0.0255, title_y, W * 0.0520, ACCENT_RED + (255,))

    # ---------- 5. 歌手 (+ 「关注」按钮 或 > 箭头) ----------
    art_y = H * ART_Y
    f_art = _font(int(W * 0.0325))
    d.text((mxt, art_y), artist, font=f_art, fill=TEXT_SUB, anchor="lm")
    aw = tw_of(d, artist, f_art)

    if follow:
        # 「关注」胶囊描边按钮 (实测宽 0.0713W / 高 0.0382W)
        f_fl = _font(int(W * 0.0240))
        fpad = W * 0.0130
        fw = tw_of(d, "关注", f_fl) + fpad * 2
        fh = W * 0.0382
        bx = mxt + aw + W * 0.0212
        blend_rrect(img, [bx, art_y - fh / 2, bx + fw, art_y + fh / 2],
                    fh / 2, None, (255, 255, 255, 62), max(2, int(W * 0.0022)))
        d.text((bx + fw / 2, art_y), "关注", font=f_fl,
               fill=(204, 209, 220, 255), anchor="mm")
    else:
        draw_chevron_right(d, mxt + aw + W * 0.0220, art_y, W * 0.0075, W * 0.0100,
                           TEXT_SUB + (255,), max(2, int(W * 0.0026)))

    # ---------- 6. 进度条 ----------
    bar_y = H * BAR_Y
    bh = max(3, int(W * 0.0042))
    d.rounded_rectangle([mxt, bar_y - bh / 2, mtr, bar_y + bh / 2],
                        radius=bh / 2, fill=BAR_REST + (255,))
    kx = mxt + (mtr - mxt) * max(0.0, min(1.0, played_ratio))
    d.rounded_rectangle([mxt, bar_y - bh / 2, kx, bar_y + bh / 2],
                        radius=bh / 2, fill=BAR_DONE + (255,))
    kr = W * 0.0080
    d.ellipse([kx - kr, bar_y - kr, kx + kr, bar_y + kr], fill=(255, 255, 255, 255))

    # ---------- 7. 时间行 ----------
    tm_y = H * TIME_Y
    f_tm = _font(int(W * 0.0240))
    d.text((mxt, tm_y), fmt_time(duration * played_ratio), font=f_tm,
           fill=TEXT_SUB, anchor="lm")
    d.text((W * 0.5, tm_y), quality, font=f_tm, fill=TEXT_SUB, anchor="mm")
    d.text((mtr, tm_y), fmt_time(duration), font=f_tm, fill=TEXT_SUB, anchor="rm")

    # ---------- 8. 播放控制 ----------
    ctl_y = H * CTL_Y
    lw_i = max(3, int(W * 0.0042))
    # 第一个图标: 新版是「循环」(参考模板), 旧版是「心形+闪光」
    if fav_loop:
        draw_loop(d, W * 0.0968, ctl_y, W * 0.0272, ICON_DIM + (255,),
                  max(3, int(W * 0.0042)))
    else:
        draw_heart_outline(img, W * 0.0958, ctl_y, W * 0.0509, ICON_DIM + (255,),
                           max(2, int(W * 0.0032)))
        d = ImageDraw.Draw(img, "RGBA")
        draw_sparkle(d, W * 0.0962, ctl_y + W * 0.0026, W * 0.0125, ICON_DIM + (255,))
    # 上一首  |◀
    draw_tri(d, W * 0.2981, ctl_y, W * 0.0424, ICON + (255,), -1)
    d.rounded_rectangle([W * 0.2714, ctl_y - W * 0.0210,
                         W * 0.2777, ctl_y + W * 0.0210],
                        radius=W * 0.0032, fill=ICON + (255,))
    # 暂停
    draw_pause(d, W * 0.4992, ctl_y, W * 0.0237, W * 0.0763, W * 0.0458,
               (250, 250, 252, 255))
    # 下一首  ▶|
    draw_tri(d, W * 0.7002, ctl_y, W * 0.0424, ICON + (255,), 1)
    d.rounded_rectangle([W * 0.7222, ctl_y - W * 0.0210,
                         W * 0.7285, ctl_y + W * 0.0210],
                        radius=W * 0.0032, fill=ICON + (255,))
    # 列表
    draw_bar_icon(d, W * 0.9042, ctl_y, W * 0.0475, ICON_DIM + (255,), lw_i)

    # ---------- 9. 底部图标 (3:5 卡片模式画到画面外, 等效不显示) ----------
    bot_y = H * BOT_Y if BOT_Y is not None else -H
    icol = (128, 128, 136, 255)
    lw2 = max(2, int(W * 0.0030))
    BX0, BSTEP = 0.0891, 0.27393

    x = W * BX0                                    # 手机
    d.rounded_rectangle([x - W * 0.0170, bot_y - W * 0.0225,
                         x + W * 0.0170, bot_y + W * 0.0225],
                        radius=W * 0.0075, outline=icol, width=lw2)
    d.line([(x - W * 0.0056, bot_y + W * 0.0160),
            (x + W * 0.0056, bot_y + W * 0.0160)], fill=icol, width=lw2)

    x = W * (BX0 + BSTEP)                          # 灯泡
    d.ellipse([x - W * 0.0169, bot_y - W * 0.0225, x + W * 0.0169, bot_y + W * 0.0113],
              outline=icol, width=lw2)
    d.line([(x - W * 0.0080, bot_y + W * 0.0170), (x + W * 0.0080, bot_y + W * 0.0170)],
           fill=icol, width=lw2)
    d.line([(x - W * 0.0080, bot_y + W * 0.0225), (x + W * 0.0080, bot_y + W * 0.0225)],
           fill=icol, width=lw2)

    x = W * (BX0 + BSTEP * 2)                      # info
    d.ellipse([x - W * 0.0220, bot_y - W * 0.0220, x + W * 0.0220, bot_y + W * 0.0220],
              outline=icol, width=lw2)
    d.line([(x, bot_y - W * 0.0020), (x, bot_y + W * 0.0125)], fill=icol, width=lw2)
    dr = W * 0.0030
    d.ellipse([x - dr, bot_y - W * 0.0130 - dr, x + dr, bot_y - W * 0.0130 + dr],
              fill=icol)

    x = W * (BX0 + BSTEP * 3)                      # 更多
    for off in (-W * 0.0153, 0, W * 0.0153):
        dr = W * 0.0034
        d.ellipse([x + off - dr, bot_y - dr, x + off + dr, bot_y + dr], fill=icol)

    img.convert("RGB").save(out_path, quality=96)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cover", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--artist", default="")
    ap.add_argument("--duration", type=float, default=0, help="秒")
    ap.add_argument("--played", type=float, default=0.047, help="已播放比例 0~1")
    ap.add_argument("--playlist", default="我喜欢的音乐")
    ap.add_argument("--likes", default="999w+")
    ap.add_argument("--comments", default="100w+")
    ap.add_argument("--listeners", default="999+人")
    ap.add_argument("--quality", default="极高音质")
    ap.add_argument("--statusbar", action="store_true",
                    help="绘制状态栏(时间/信号/电量); 不传则留空, 更干净")
    ap.add_argument("--clock", default="12:01", help="状态栏时间")
    ap.add_argument("--width", type=int, default=1200)
    ap.add_argument("--ratio", type=float, default=RATIO,
                    help="高/宽. 2.168=iPhone全屏; 1.6667=30x50mm卡片")
    ap.add_argument("--vip", action="store_true", help="歌名后加 VIP 标签")
    ap.add_argument("--follow", action="store_true", help="歌手后改用「关注」按钮")
    ap.add_argument("--video-tag", action="store_true", help="显示「视频」标签(有MV的歌)")
    ap.add_argument("--fav", action="store_true",
                    help="第一个控制图标用心形+闪光(旧版); 默认是循环(新版)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    p = make(a.cover, a.out, a.title, a.artist, a.duration, a.width, a.played,
             a.playlist, a.likes, a.comments, a.listeners, a.quality,
             a.statusbar, a.clock, a.ratio,
             a.vip, a.follow, a.video_tag, not a.fav)
    print("saved:", p)


if __name__ == "__main__":
    main()
