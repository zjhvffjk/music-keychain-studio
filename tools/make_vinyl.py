# -*- coding: utf-8 -*-
"""
网易云「黑胶播放界面」母版合成器

用专辑封面母版 + 歌曲信息, 合成一张黑胶播放界面图。
- 比例 1:2 (竖屏手机), 分辨率任意指定
- 不含状态栏杂物 (时间/电量), 比手机截图干净
- 图层全部程序化绘制, 可批量

用法:
  python make_vinyl.py --cover <封面路径> --title 如果呢 --artist 郑润泽 \
                       --duration 257 --out out.png [--width 1200]
"""
import argparse
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from fonts import find_bold, find_regular

# 中文字体：自动探测当前系统，可用环境变量
# MINUET_FONT_BOLD / MINUET_FONT_REG 覆盖（见 tools/fonts.py）
BD = find_bold()
RG = find_regular()

# 配色 (取自网易云黑胶界面)
BG_TOP = (30, 30, 33)
BG_BOTTOM = (11, 11, 13)
DISC = (17, 17, 19)
DISC_RING = (34, 34, 38)
TEXT_MAIN = (245, 245, 247)
TEXT_SUB = (150, 150, 156)
ACCENT_RED = (255, 59, 78)
BAR_DONE = (240, 240, 242)
BAR_REST = (70, 70, 76)
TAG_BG = (40, 42, 46)


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
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=lerp(top, bot, y / max(1, h - 1)))
    return img


def draw_heart(d, cx, cy, s, color):
    """手绘心形"""
    r = s / 2
    d.ellipse([cx - r, cy - r * 0.95, cx, cy + r * 0.35], fill=color)
    d.ellipse([cx, cy - r * 0.95, cx + r, cy + r * 0.35], fill=color)
    d.polygon([(cx - r * 0.98, cy - r * 0.05), (cx + r * 0.98, cy - r * 0.05),
               (cx, cy + r * 1.15)], fill=color)


def draw_pause(d, cx, cy, s, color):
    bw, bh, gap = s * 0.22, s * 0.86, s * 0.24
    for sx in (-1, 1):
        x = cx + sx * (bw + gap) / 2
        d.rounded_rectangle([x - bw / 2, cy - bh / 2, x + bw / 2, cy + bh / 2],
                            radius=bw * 0.28, fill=color)


def draw_tri(d, cx, cy, s, color, direction):
    h = s * 0.8
    w = s * 0.62
    if direction > 0:
        pts = [(cx - w / 2, cy - h / 2), (cx - w / 2, cy + h / 2), (cx + w / 2, cy)]
    else:
        pts = [(cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy)]
    d.polygon(pts, fill=color)


def draw_bar_icon(d, cx, cy, s, color):
    bw = s * 0.75
    for i, y in enumerate((-0.3, 0.0, 0.3)):
        d.rounded_rectangle([cx - bw / 2, cy + s * y - s * 0.055,
                             cx + bw / 2, cy + s * y + s * 0.055],
                            radius=s * 0.055, fill=color)


def fmt_time(sec):
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def make(cover_path, out_path, title, artist, duration, width=1200,
         played_ratio=0.10):
    W = width
    H = W * 2

    img = vgrad(W, H, BG_TOP, BG_BOTTOM).convert("RGBA")

    # ---------- 1. 导航栏 ----------
    d = ImageDraw.Draw(img, "RGBA")
    nav_y = int(H * 0.072)
    chev = _font(int(W * 0.048))
    d.text((W * 0.085, nav_y), "﹀", font=chev, fill=TEXT_MAIN, anchor="mm")
    f_nav = _font(int(W * 0.036))
    d.text((W * 0.5, nav_y), "我喜欢的音乐", font=f_nav, fill=TEXT_MAIN, anchor="mm")
    # 右上角刷新图标
    rx, ry, rr = W * 0.912, nav_y, W * 0.019
    d.arc([rx - rr, ry - rr, rx + rr, ry + rr], start=40, end=330,
          fill=TEXT_MAIN, width=max(2, int(W * 0.0035)))
    d.polygon([(rx + rr * 0.95, ry - rr * 0.55), (rx + rr * 0.2, ry - rr * 0.95),
               (rx + rr * 0.75, ry - rr * 1.45)], fill=TEXT_MAIN)

    # ---------- 2. 黑胶唱片 ----------
    cx, cy = W * 0.5, H * 0.29
    R = W * 0.40

    disc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(disc)
    dd.ellipse([cx - R, cy - R, cx + R, cy + R], fill=DISC + (255,))
    # 同心纹理
    n = 46
    for i in range(n):
        rr = R * (0.44 + 0.55 * i / n)
        dd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                   outline=DISC_RING + (110,), width=1)
    # 外缘亮边
    dd.ellipse([cx - R, cy - R, cx + R, cy + R],
               outline=(60, 60, 66, 200), width=max(2, int(W * 0.003)))

    # 环状高光 (模拟黑胶反光)
    hl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dh = ImageDraw.Draw(hl)
    dh.ellipse([cx - R * 0.88, cy - R * 0.88, cx + R * 0.88, cy + R * 0.88],
               outline=(135, 138, 152, 52), width=int(R * 0.34))
    dh.ellipse([cx - R * 0.58, cy - R * 0.58, cx + R * 0.58, cy + R * 0.58],
               outline=(135, 138, 152, 34), width=int(R * 0.18))
    # 左上柔光, 让盘面有方向感
    dh.ellipse([cx - R * 0.82, cy - R * 1.00, cx + R * 0.06, cy - R * 0.18],
               fill=(255, 255, 255, 15))
    hl = hl.filter(ImageFilter.GaussianBlur(R * 0.13))
    disc = Image.alpha_composite(disc, hl)

    # 中心封面 (圆形裁切)
    cover = Image.open(cover_path).convert("RGB")
    side = min(cover.size)
    cover = cover.crop(((cover.width - side) // 2, (cover.height - side) // 2,
                        (cover.width + side) // 2, (cover.height + side) // 2))
    cr = int(R * 0.415)
    cover = cover.resize((cr * 2, cr * 2), Image.LANCZOS)
    mask = Image.new("L", (cr * 2, cr * 2), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, cr * 2 - 1, cr * 2 - 1], fill=255)
    dd.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=(250, 250, 250, 255))
    disc.paste(cover, (int(cx - cr), int(cy - cr)), mask)
    # 封面外圈细环
    dd.ellipse([cx - cr, cy - cr, cx + cr, cy + cr],
               outline=(255, 255, 255, 90), width=max(1, int(W * 0.0018)))

    img = Image.alpha_composite(img, disc)

    # ---------- 3. 唱臂 ----------
    arm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    da = ImageDraw.Draw(arm)
    piv = (cx + R * 0.05, cy - R * 0.74)          # 支点 (唱片内上方)
    tip = (cx + R * 0.46, cy + R * 0.33)          # 唱头落点
    da.line([piv, tip], fill=(238, 238, 242, 255), width=max(3, int(W * 0.0045)))
    pr = W * 0.011
    da.ellipse([piv[0] - pr, piv[1] - pr, piv[0] + pr, piv[1] + pr],
               fill=(245, 245, 248, 255))
    hw, hh = W * 0.028, W * 0.020
    da.rounded_rectangle([tip[0] - hw / 2, tip[1] - hh / 2,
                          tip[0] + hw / 2, tip[1] + hh / 2],
                         radius=hh * 0.30, fill=(248, 248, 250, 255))
    da.ellipse([tip[0] - pr * 0.5, tip[1] + hh * 0.2,
                tip[0] + pr * 0.5, tip[1] + hh * 1.2],
               fill=(230, 230, 234, 255))
    img = Image.alpha_composite(img, arm)
    d = ImageDraw.Draw(img, "RGBA")

    # ---------- 4. 标签行 ----------
    tag_y = int(H * 0.552)
    th = int(W * 0.042)
    f_tag = _font(int(W * 0.026))
    tw = d.textlength("999+人", font=f_tag)
    tag_x = W * 0.085
    d.rounded_rectangle([tag_x, tag_y - th / 2, tag_x + tw + th * 1.5, tag_y + th / 2],
                        radius=th / 2, fill=TAG_BG + (255,))
    d.ellipse([tag_x + th * 0.34, tag_y - th * 0.16,
               tag_x + th * 0.34 + th * 0.32, tag_y + th * 0.16],
              fill=(60, 200, 130, 255))
    d.text((tag_x + th * 0.86, tag_y), "999+人", font=f_tag,
           fill=(225, 225, 228), anchor="lm")

    # 视频标签
    vx = tag_x + tw + th * 2.1
    d.rounded_rectangle([vx, tag_y - th / 2, vx + th * 3.5, tag_y + th / 2],
                        radius=th / 2, fill=TAG_BG + (255,))
    vs = th * 0.30
    d.rounded_rectangle([vx + th * 0.42, tag_y - vs, vx + th * 0.42 + vs * 1.25,
                         tag_y + vs * 0.75], radius=vs * 0.22,
                        fill=(225, 225, 228, 255))
    d.polygon([(vx + th * 0.42 + vs * 0.42, tag_y - vs * 0.35),
               (vx + th * 0.42 + vs * 0.42, tag_y + vs * 0.35),
               (vx + th * 0.42 + vs * 1.0, tag_y)], fill=TAG_BG + (255,))
    d.text((vx + th * 1.95, tag_y), "视频", font=f_tag, fill=(225, 225, 228), anchor="lm")

    # ---------- 5. 歌名 / 歌手 ----------
    mx = W * 0.085
    title_y = int(H * 0.607)
    f_title = _font(int(W * 0.062), bold=True)
    d.text((mx, title_y), title, font=f_title, fill=TEXT_MAIN, anchor="lm")

    ar_y = int(H * 0.655)
    f_art = _font(int(W * 0.034))
    d.text((mx, ar_y), artist, font=f_art, fill=TEXT_SUB, anchor="lm")
    aw = d.textlength(artist, font=f_art)
    cxx = mx + aw + W * 0.022
    d.line([(cxx - W * 0.011, ar_y - W * 0.011), (cxx, ar_y),
            (cxx + W * 0.011, ar_y - W * 0.011)],
           fill=TEXT_SUB, width=max(2, int(W * 0.0028)), joint="curve")

    # 右侧: 红心 + 播放量
    hcx, hcy = W * 0.80, title_y
    draw_heart(d, hcx, hcy, W * 0.042, ACCENT_RED + (255,))
    f_like = _font(int(W * 0.028))
    d.text((hcx + W * 0.036, hcy + W * 0.010), "999w+", font=f_like,
           fill=ACCENT_RED, anchor="lm")
    # 歌手头像圆
    av = W * 0.040
    acx, acy = W * 0.925, ar_y
    d.ellipse([acx - av, acy - av, acx + av, acy + av], fill=(52, 54, 60, 255))
    d.ellipse([acx - av * 0.42, acy - av * 0.55,
               acx + av * 0.42, acy + av * 0.25], fill=(130, 132, 140, 255))
    d.pieslice([acx - av * 0.72, acy + av * 0.05,
                acx + av * 0.72, acy + av * 1.35], 180, 360,
               fill=(130, 132, 140, 255))

    # ---------- 6. 进度条 ----------
    bar_y = int(H * 0.726)
    bar_x0, bar_x1 = W * 0.085, W * 0.915
    bh = max(3, int(W * 0.005))
    d.rounded_rectangle([bar_x0, bar_y - bh / 2, bar_x1, bar_y + bh / 2],
                        radius=bh / 2, fill=BAR_REST + (255,))
    kx = bar_x0 + (bar_x1 - bar_x0) * played_ratio
    d.rounded_rectangle([bar_x0, bar_y - bh / 2, kx, bar_y + bh / 2],
                        radius=bh / 2, fill=BAR_DONE + (255,))
    kr = W * 0.011
    d.ellipse([kx - kr, bar_y - kr, kx + kr, bar_y + kr], fill=(255, 255, 255, 255))

    # ---------- 7. 时间行 ----------
    tm_y = int(H * 0.762)
    f_tm = _font(int(W * 0.028))
    played = duration * played_ratio
    d.text((bar_x0, tm_y), fmt_time(played), font=f_tm, fill=TEXT_SUB, anchor="lm")
    d.text((W * 0.5, tm_y), "极高音质", font=f_tm, fill=TEXT_SUB, anchor="mm")
    d.text((bar_x1, tm_y), fmt_time(duration), font=f_tm, fill=TEXT_SUB, anchor="rm")

    # ---------- 8. 播放控制 ----------
    ctl_y = int(H * 0.836)
    ic = W * 0.075
    # 收藏
    draw_heart(d, W * 0.135, ctl_y, W * 0.046, (225, 225, 228, 255))
    d.ellipse([W * 0.135 - W * 0.040, ctl_y - W * 0.040,
               W * 0.135 + W * 0.040, ctl_y + W * 0.040],
              outline=(90, 90, 98, 200), width=max(2, int(W * 0.003)))
    # 上一首
    draw_tri(d, W * 0.385, ctl_y, ic, (245, 245, 248, 255), -1)
    d.rounded_rectangle([W * 0.350, ctl_y - ic * 0.40, W * 0.362, ctl_y + ic * 0.40],
                        radius=W * 0.005, fill=(245, 245, 248, 255))
    # 暂停 (主键)
    draw_pause(d, W * 0.5, ctl_y, ic * 1.30, (250, 250, 252, 255))
    # 下一首
    draw_tri(d, W * 0.615, ctl_y, ic, (245, 245, 248, 255), 1)
    d.rounded_rectangle([W * 0.638, ctl_y - ic * 0.40, W * 0.650, ctl_y + ic * 0.40],
                        radius=W * 0.005, fill=(245, 245, 248, 255))
    # 列表
    draw_bar_icon(d, W * 0.865, ctl_y, W * 0.052, (200, 200, 206, 255))

    # ---------- 9. 底部图标 (几何绘制, 不用字体符号以免缺字) ----------
    bot_y = int(H * 0.925)
    icol = (118, 118, 126, 255)
    lw = max(2, int(W * 0.0028))
    g = W * 0.052

    # 手机
    x = W * 0.16
    d.rounded_rectangle([x - g * 0.46, bot_y - g * 0.78,
                         x + g * 0.46, bot_y + g * 0.78],
                        radius=g * 0.20, outline=icol, width=lw)
    d.line([(x - g * 0.16, bot_y + g * 0.56), (x + g * 0.16, bot_y + g * 0.56)],
           fill=icol, width=lw)

    # 灯泡
    x = W * 0.385
    d.ellipse([x - g * 0.42, bot_y - g * 0.78, x + g * 0.42, bot_y + g * 0.26],
              outline=icol, width=lw)
    d.line([(x - g * 0.20, bot_y + g * 0.42), (x + g * 0.20, bot_y + g * 0.42)],
           fill=icol, width=lw)
    d.line([(x - g * 0.20, bot_y + g * 0.64), (x + g * 0.20, bot_y + g * 0.64)],
           fill=icol, width=lw)

    # 信息 (圆环 + i)
    x = W * 0.615
    d.ellipse([x - g * 0.62, bot_y - g * 0.62, x + g * 0.62, bot_y + g * 0.62],
              outline=icol, width=lw)
    d.line([(x, bot_y - g * 0.04), (x, bot_y + g * 0.36)], fill=icol, width=lw)
    dr = g * 0.075
    d.ellipse([x - dr, bot_y - g * 0.30 - dr, x + dr, bot_y - g * 0.30 + dr],
              fill=icol)

    # 更多
    x = W * 0.84
    for off in (-g * 0.32, 0, g * 0.32):
        dr = g * 0.075
        d.ellipse([x + off - dr, bot_y - dr, x + off + dr, bot_y + dr], fill=icol)

    img.convert("RGB").save(out_path, quality=96)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cover", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--artist", default="")
    ap.add_argument("--duration", type=float, default=0, help="秒")
    ap.add_argument("--played", type=float, default=0.10, help="已播放比例 0~1")
    ap.add_argument("--width", type=int, default=1200)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    p = make(a.cover, a.out, a.title, a.artist, a.duration, a.width, a.played)
    print("saved:", p)


if __name__ == "__main__":
    main()
