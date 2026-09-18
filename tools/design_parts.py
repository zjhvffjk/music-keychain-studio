"""封面衍生设计引擎 —— 从一张专辑封面，长出配套的全部部件素材。

不搜网络图（耗时且被污染），改为**基于封面做编辑设计的衍生**：
    palette  ← 从封面提色板
    mood     ← 从封面饱和度/亮度推断（dreamy / energetic / melancholic）
    style    ← 从封面边缘密度推断（minimalist / retro / bold）或手动指定
    每个部件 ← 由上述设计语言驱动版式与质感

这是小红书「album cover + genre + mood + style」公式的工程化变体：
第 1 个词 album cover 从「生成目标」变成「参考源」。

依赖：PIL / numpy / fonts（可选，缺失则退回默认字体）
import 无副作用。
"""

import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

try:
    from PIL import ImageFont

    import fonts

    def _font(size, bold=False):
        try:
            p = fonts.find_bold() if bold else fonts.find_regular()
            return ImageFont.truetype(p, max(8, int(size)))
        except Exception:
            return ImageFont.load_default()

except Exception:  # pragma: no cover
    from PIL import ImageFont

    def _font(size, bold=False):
        return ImageFont.load_default()


# ---------------- 设计语言提取 ----------------
def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def ink_on(color, dark=(24, 24, 26), light=(250, 250, 250)):
    return dark if lum(color) > 140 else light


def dim_ink(ink, bg, k=0.62):
    """次要文字色：主墨色与背景混合 —— 保证可读但不与标题抢戏。

    直接拿封面调色板的 accent 当序号色会出事：accent 可能很暗，
    落在深底上等于隐形（实测 Jay 深灰底上的序号几乎看不见）。
    """
    return tuple(int(ink[i] * k + bg[i] * (1 - k)) for i in range(3))


def palette(im, n=6):
    """提色板：量化取主要色，按占比降序。"""
    q = im.convert("RGB").resize((80, 80)).quantize(colors=n, method=2)
    pal = q.getpalette()
    cnt = sorted(q.getcolors(80 * 80) or [], reverse=True)
    out = []
    for c, i in cnt:
        out.append(tuple(pal[i * 3:i * 3 + 3]))
    return out or [(128, 128, 128)]


def _sat(c):
    mx, mn = max(c), min(c)
    return 0 if mx == 0 else (mx - mn) / mx


def read_design(cover_im, n=6):
    """读一张封面 -> 设计语言 dict。"""
    small = cover_im.convert("RGB").resize((120, 120))
    pal = palette(small, n)
    main = pal[0]

    arr = np.asarray(small).astype(float) / 255.0
    mx, mn = arr.max(2), arr.min(2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    bright = arr.mean()

    # mood 三档
    if sat.mean() < 0.18 and bright < 0.45:
        mood = "melancholic"
    elif sat.mean() > 0.35 or bright > 0.62:
        mood = "energetic"
    else:
        mood = "dreamy"

    # style：边缘密度 -> 极简 or 密集
    edges = np.asarray(small.convert("L").filter(ImageFilter.FIND_EDGES)).astype(float)
    dens = (edges > 40).mean()
    if dens < 0.05:
        style = "minimalist"
    elif dens > 0.22:
        style = "bold"
    else:
        style = "retro"

    # 深浅两个主色，用于渐变
    dark = tuple(int(main[i] * 0.42) for i in range(3))
    deep = tuple(int(main[i] * 0.68 + 12) for i in range(3))
    accent = pal[1] if len(pal) > 1 else tuple(255 - main[i] for i in range(3))

    return {"palette": pal, "main": main, "dark": dark, "deep": deep,
            "accent": accent, "mood": mood, "style": style,
            "ink": ink_on(main), "bright": bright, "sat": float(sat.mean())}


def vgrad(size, top, bottom):
    """垂直渐变底。"""
    w, h = size
    arr = np.zeros((h, w, 3), np.uint8)
    for y in range(h):
        t = y / max(1, h - 1)
        arr[y, :] = [int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)]
    return Image.fromarray(arr, "RGB")


def grain(im, amt=10, seed=0):
    """细颗粒（retro 质感）。"""
    rng = np.random.default_rng(seed)
    a = np.asarray(im).astype(np.int16)
    a = a + rng.normal(0, amt, a.shape).astype(np.int16)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")


def fit_font(d, text, box_w, start, bold=False, min_s=8):
    """在给定宽度内自动缩字号（先降号，再省略）。"""
    s = start
    while s > min_s:
        f = _font(s, bold)
        if d.textlength(text, font=f) <= box_w:
            return f, text
        s = max(min_s, int(s * 0.92))
    f = _font(min_s, bold)
    while text and d.textlength(text + "…", font=f) > box_w:
        text = text[:-1]
    return f, (text + "…" if text else "")


def vtext(im, text, xy, size, fill, bold=False, spacing=1.12):
    """竖排文字（中文/拉丁都按字排），返回占用高度。"""
    d = ImageDraw.Draw(im)
    f = _font(size, bold)
    x, y = xy
    step = int(size * spacing)
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        y += step
    return max(0, y - xy[1])


def barcode(d, x, y, w, h, seed=0):
    """画一个 EAN-13 风格的装饰条码（非真实可扫，但视觉正确）。"""
    rng = np.random.default_rng(abs(seed) % (2 ** 31))
    d.rectangle([x - 3, y - 3, x + w + 3, y + h + 3], fill=(255, 255, 255))
    cx, guard = x, max(1, int(w * 0.012))
    while cx < x + w - guard:
        bw = int(rng.integers(1, 4)) * guard
        if cx + bw > x + w:
            bw = x + w - cx
        if rng.random() > 0.42:
            d.rectangle([cx, y, cx + bw - 1, y + h], fill=(0, 0, 0))
        cx += bw + guard
    f = _font(max(7, int(h * 0.20)))
    tag = "%012d" % (rng.integers(1, 10 ** 12))
    d.text((x, y + h + 3), tag[:4], font=f, fill=(0, 0, 0))
    d.text((x + w * 0.30, y + h + 3), tag[4:8], font=f, fill=(0, 0, 0))
    d.text((x + w * 0.62, y + h + 3), tag[8:], font=f, fill=(0, 0, 0))


# ---------------- 部件：盘面 ----------------
def design_disc(cover, d_px, hole_px, D, album="", artist=""):
    """CD 碟面：封面裁圆 + 同心读取沟槽 + 扇形高光 + 内环 + 中心孔。

    三个关键判断（都是踩过坑换来的）：
    1. 沟槽必须是**乘性暗环**。用 ImageDraw 画白线会变成"白蜘蛛网"——
       浅色封面上尤其廉价。暗环才是真实 CD 读面的样子。
    2. 高光用 cos^8 窄峰做**两道扇形**，而不是 4 个宽扇区：宽扇区会把
       整个盘面糊成一片白，窄扇形才像灯光下的一道光带。
    3. 内圈与最外圈都要处理（透明内环 + 外沿暗边），否则圆片像贴纸。
    """
    ss = 3
    big = d_px * ss
    base = cover.convert("RGB").resize((big, big), Image.LANCZOS)

    cc = np.arange(big) - big / 2.0 + 0.5
    yy, xx = np.meshgrid(cc, cc, indexing="ij")
    rr = np.sqrt(xx ** 2 + yy ** 2)
    ang = np.arctan2(yy, xx)
    r0 = rr / (big / 2.0)

    arr = np.asarray(base).astype(np.float32) / 255.0

    # 1) 同心读取沟槽：乘性暗环。真实沟槽是**密而淡**的细纹，
    #    稀而深会变成"摩尔纹"（早期版本用白线画环，直接变成蜘蛛网）。
    gro = 0.5 + 0.5 * np.cos(2.0 * np.pi * r0 * 34.0)
    gmask = ((r0 > 0.30) & (r0 < 0.95)).astype(np.float32)
    arr *= (1.0 - 0.075 * gro * gmask)[..., None]

    # 2) 两道柔和的扇形高光（光带）
    fan = np.cos(2.0 * (ang - 0.9)) ** 8
    band = np.exp(-((r0 - 0.66) ** 2) / (2 * 0.30 ** 2))
    spec = (fan * band * 0.58)
    arr = arr + (1.0 - arr) * spec[..., None]

    # 3) 外沿暗边（CD 边缘高光/暗边）
    rim = np.exp(-((r0 - 0.965) ** 2) / (2 * 0.022 ** 2))
    arr *= (1.0 - 0.45 * rim)[..., None]

    # 4) 内圈：聚碳酸酯透明区，偏冷灰
    inner = np.clip((0.24 - r0) / 0.10, 0, 1)
    arr = arr * (1 - inner[..., None]) + np.array([0.62, 0.63, 0.66]) * inner[..., None]
    arr = np.clip(arr, 0, 1)

    im = Image.fromarray((arr * 255).astype(np.uint8), "RGB")

    # 圆形遮罩 + 抗锯齿
    m = Image.new("L", (big, big), 0)
    ImageDraw.Draw(m).ellipse([0, 0, big - 1, big - 1], fill=255)
    im.putalpha(m)
    im = im.resize((d_px, d_px), Image.LANCZOS)

    out = Image.new("RGB", (d_px, d_px), (255, 255, 255))
    out.paste(im, (0, 0), im)

    # 中心孔（Ø5mm）
    c = d_px / 2.0
    ImageDraw.Draw(out).ellipse([c - hole_px / 2, c - hole_px / 2,
                                 c + hole_px / 2, c + hole_px / 2], fill=(255, 255, 255))
    return out


# ---------------- 部件：封面背面（内页）----------------
def design_inner(cover, w, h, D, album="", artist="", tracks=None):
    """封面背面：封面去色压暗作底 + 专辑信息区块。

    真专辑的内页通常不是封面原图，而是**同一套视觉语言的弱化版** ——
    所以这里用封面做底再压暗降饱和，天然保持同源感。
    """
    base = ImageOps_like(cover, w, h)
    base = ImageEnhance.Color(base).enhance(0.35)
    base = ImageEnhance.Brightness(base).enhance(0.42)
    if D["style"] == "minimalist":
        base = base.filter(ImageFilter.GaussianBlur(w / 90))
    if D["style"] == "retro":
        base = grain(base, 9, seed=7)

    over = base.copy()
    d = ImageDraw.Draw(over)
    pad = max(8, int(w * 0.055))

    # 半透明信息板，保证文字可读（不依赖封面明暗）
    by = int(h * 0.40)
    plate = Image.new("RGBA", (w, h - by), (0, 0, 0, 0))
    ImageDraw.Draw(plate).rectangle([0, 0, w, h - by],
                                    fill=(0, 0, 0, 122))
    over.paste(plate, (0, by), plate)

    fg = (248, 248, 248)
    if album:
        f, t = fit_font(d, album, w - pad * 2, int(h * 0.115), bold=True)
        d.text((pad, by + int(h * 0.025)), t, font=f, fill=fg)
    if artist:
        f, t = fit_font(d, artist, w - pad * 2, int(h * 0.068))
        d.text((pad, by + int(h * 0.155)), t, font=f, fill=(206, 206, 206))

    # 曲目列表（单列；左半只有 41mm 宽，排两列会挤）
    if tracks:
        tf = _font(max(9, int(h * 0.043)))
        lh = int(tf.size * 1.36)
        ty = by + int(h * 0.255)
        for i, s in enumerate(tracks[:9], 1):
            d.text((pad, ty), "%02d" % i, font=tf, fill=(176, 176, 182))
            f2, t2 = fit_font(d, s, w - pad * 2 - int(w * 0.11), tf.size)
            d.text((pad + int(w * 0.10), ty), t2, font=f2, fill=(232, 232, 232))
            ty += lh
            if ty + lh > h - pad // 2:
                break
    return over


def ImageOps_like(im, w, h):
    """等比填满后居中裁切（保证不变形）。"""
    r = max(w / im.width, h / im.height)
    nw, nh = max(1, int(im.width * r)), max(1, int(im.height * r))
    im = im.convert("RGB").resize((nw, nh), Image.LANCZOS)
    return im.crop(((nw - w) // 2, (nh - h) // 2, (nw - w) // 2 + w, (nh - h) // 2 + h))


# ---------------- 部件：封底 ----------------
def design_back(cover, w, h, D, album="", artist="", tracks=None, seed=0):
    """封底：主色渐变底 + 曲目双列 + 条码 + 版权行。

    这是信息量最大的一件，版式按 style 变：
      minimalist → 大量留白、细分隔线
      retro      → 颗粒 + 双线边框
      bold       → 顶部粗色块 + 高对比
    """
    if D["style"] == "minimalist":
        bg = Image.new("RGB", (w, h), (250, 250, 250))
    else:
        bg = vgrad((w, h), D["deep"], D["dark"])
    base = bg.copy()
    d = ImageDraw.Draw(base)
    pad = max(6, int(w * 0.045))
    ink = ink_on(palette(base, 4)[0])

    if D["style"] == "retro":
        d.rectangle([pad // 2, pad // 2, w - pad // 2, h - pad // 2],
                    outline=ink, width=1)
        d.rectangle([pad // 2 + 3, pad // 2 + 3, w - pad // 2 - 3, h - pad // 2 - 3],
                    outline=ink, width=1)

    # 顶部标题区
    if D["style"] == "bold":
        d.rectangle([0, 0, w, int(h * 0.20)], fill=D["dark"])
        top_ink = ink_on(D["dark"])
    else:
        top_ink = ink
    ty = int(h * 0.035)
    if album:
        f, t = fit_font(d, album, w - pad * 2, int(h * 0.115), bold=True)
        d.text((pad, ty), t, font=f, fill=top_ink)
    if artist:
        f, t = fit_font(d, artist, w - pad * 2, int(h * 0.065))
        d.text((pad, ty + int(h * 0.13)), t, font=f, fill=top_ink)

    # 曲目：双列
    if tracks:
        cols = 2 if len(tracks) > 6 else 1
        per = math.ceil(len(tracks) / cols)
        colw = (w - pad * 2 - int(w * 0.03)) // cols
        tf0 = max(8, int(h * 0.052))
        lh = int(tf0 * 1.42)
        y0 = int(h * 0.30)
        num_fill = dim_ink(ink, palette(base, 3)[0])
        for ci in range(cols):
            cx = pad + ci * (colw + int(w * 0.03))
            cy = y0
            for k in range(per):
                idx = ci * per + k
                if idx >= len(tracks):
                    break
                if cy + lh > int(h * 0.80):
                    break
                f2, tt = fit_font(d, tracks[idx], colw - int(w * 0.075), tf0)
                d.text((cx, cy), "%02d" % (idx + 1), font=_font(tf0), fill=num_fill)
                d.text((cx + int(w * 0.065), cy), tt, font=f2, fill=ink)
                cy += lh
    else:
        # 没曲目时别重复专辑名（顶部已经写过了），给一行版权小字 ——
        # 真 CD 封底都有这行，比空着或重复都自然。
        line = "℗ & © JVR Music International Ltd.   All rights reserved."
        f, t = fit_font(d, line, w - pad * 2, int(h * 0.046))
        d.text((pad, int(h * 0.44)), t, font=f,
               fill=dim_ink(ink, palette(base, 3)[0], 0.5))

    # 条码（右下）
    bw = int(w * 0.30)
    bh = int(h * 0.13)
    barcode(d, int(w - pad - bw), int(h - pad - bh - int(h * 0.055)),
            bw, bh, seed=seed)
    return base


# ---------------- 部件：内盘底 ----------------
def design_tray(cover, w, h, D, album="", artist=""):
    """内盘底：托盘 tleмин 面的那一版 —— 主色 + 大号排版 + 封面小图。"""
    base = vgrad((w, h), D["main"], D["dark"])
    if D["style"] == "retro":
        base = grain(base, 8, seed=3)
    d = ImageDraw.Draw(base)
    pad = max(6, int(w * 0.06))
    ink = ink_on(palette(base, 4)[0])

    # 封面小图（左上），让托盘一眼认出是哪张专辑
    ts = int(h * 0.42)
    th = ImageOps_like(cover, ts, ts)
    base.paste(th, (pad, pad))

    tx = pad
    ty = pad + ts + int(h * 0.07)
    if album:
        f, t = fit_font(d, album, w - pad * 2, int(h * 0.155), bold=True)
        d.text((tx, ty), t, font=f, fill=ink)
        ty += int(f.size * 1.15)
    if artist:
        f, t = fit_font(d, artist, w - pad * 2, int(h * 0.09))
        d.text((tx, ty), t, font=f, fill=ink)

    # 底部装饰条
    d.rectangle([pad, int(h * 0.90), pad + int(w * 0.26), int(h * 0.90) + max(2, int(h * 0.014))],
                fill=D["accent"])
    return base


# ---------------- 部件：书脊 / 侧标 ----------------
def design_spine(w, h, D, album="", artist=""):
    """书脊窄条：竖排专辑名 + 歌手，环绕 dado 色块。"""
    base = Image.new("RGB", (w, h), D["dark"])
    d = ImageDraw.Draw(base)
    ink = ink_on(D["dark"])
    fs = int(min(w * 0.62, h * 0.055))
    fs = max(7, fs)
    y = int(h * 0.10)

    txt = (album or "") + ("  " + artist if artist else "")
    if txt.strip():
        f = _font(fs, bold=True)
        # 逐字竖排，超长自动截断
        avail = int(h * 0.80)
        chars, used = [], 0
        for ch in txt:
            if used + fs * 1.12 > avail:
                chars.append("…")
                break
            chars.append(ch)
            used += fs * 1.12
        cy = y
        for ch in chars:
            cw = d.textlength(ch, font=f)
            d.text(((w - cw) / 2, cy), ch, font=f, fill=ink)
            cy += int(fs * 1.12)
    else:
        cy = 0

    # 底部色块（真书脊常见的出版社标记位）
    d.rectangle([0, int(h * 0.93), w, h], fill=D["accent"])
    return base


def design_flap(w, h, D, cover=None, seed=0):
    """左/右封（折进去的耳页）：纯色 + 细装饰。"""
    if cover is not None and D["style"] != "minimalist":
        base = ImageOps_like(cover, w, h)
        base = ImageEnhance.Color(base).enhance(0.5)
        base = ImageEnhance.Brightness(base).enhance(0.7)
        base = base.filter(ImageFilter.GaussianBlur(w / 12))
    else:
        base = vgrad((w, h), D["deep"], D["dark"])
    if D["style"] == "retro":
        base = grain(base, 7, seed=seed)
    d = ImageDraw.Draw(base)
    d.rectangle([0, int(h * 0.08), w, int(h * 0.08) + max(1, int(h * 0.006))],
                fill=(*ink_on(palette(base, 3)[0]), ))
    return base
