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
import re

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


def read_design(cover_im, n=6, safe_bands=None):
    """读一张封面 -> 设计语言 dict。

    ``safe_bands=(top, bottom)``：配件取景的**可用横带**（归一化 y）。
    封面自带标题占了顶部 30% 就传 ``(0.30, 1.0)`` —— 取景只会落在带内，
    标题不会被裁进补件（见 ``safe_crop``；``overlay_bands`` 给建议值）。
    不传 = 整幅取景。
    """
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
            "ink": ink_on(main), "bright": bright, "sat": float(sat.mean()),
            "safe_bands": tuple(safe_bands) if safe_bands else (0.0, 1.0)}


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


# ==========================================================================
#  v2 —— 整案设计：对齐**实体唱片设计规范**
# ==========================================================================
# v1 的部件是「色块 + 文字」，像工程图/PPT；实体唱片设计的做法是：
#   ① 照片复用（同一个 MV 的别的镜头）而不是纯色块
#   ② 三种以上字体角色共存 + 大标题带字距
#   ③ 手写体引言 + 落款
#   ④ 真实版权的信息层（厂牌 / © 行 / 版权声明 / 带数字的 EAN-13）
# v2 把这四件事补齐。所有函数**只依赖封面 + 元信息 + 可选歌词**，无网络依赖。
# ==========================================================================

try:
    import typo as _typo
except Exception:  # pragma: no cover
    _typo = None


def _t(role, size, text=None):
    if _typo is None:
        return _font(size, bold=role in ("heavy", "serif"))
    return _typo.font(role, size, text)


def tracked(d, xy, text, f, fill, tracking=0.0, anchor_x="left", limit=None):
    if _typo is None:
        d.text(xy, text, font=f, fill=fill)
        return d.textlength(text, font=f)
    return _typo.tracked(d, xy, text, f, fill, tracking, anchor_x, limit)


def fit_tracked(d, text, box_w, start, role, tracking=0.0, min_s=7):
    if _typo is None:
        return fit_font(d, text, box_w, start)
    return _typo.fit_tracked(d, text, box_w, start, role, tracking, min_s)


def wrap_tracked(d, text, f, box_w, tracking=0.0):
    """按宽度折行（见 typo.wrap_tracked）。typo 缺失时退化为原样一行。"""
    if _typo is None:
        return [str(text)]
    return _typo.wrap_tracked(d, text, f, box_w, tracking)


def kinsoku(lines):
    """行首/行尾禁则（见 typo._kinsoku）。typo 缺失时原样返回。"""
    if _typo is None or not hasattr(_typo, "_kinsoku"):
        return list(lines)
    return _typo._kinsoku(list(lines))


def hairline(d, x1, y, x2, fill, width=1):
    d.rectangle([int(x1), int(y), int(x2), int(y) + max(1, int(width)) - 1], fill=fill)


def phonogram(d, x, y, size, fill, thickness=None):
    """画 ℗（录音版权符号）—— **矢量画，不用文字**。

    实测本机 msyh / msyhbd / NotoSerifSC / Bahnschrift / 楷体 **全部没有 U+2117 字形**，
    直接打字会变成豆腐块（□ & © 周杰伦）。真唱片封底必然有这行，
    所以自己画一个：圆圈 + 内嵌 P。返回占用宽度。
    """
    r = max(3, int(size * 0.42))
    tw = thickness or max(1, int(size * 0.075))
    cy = y + int(size * 0.56)
    cx = x + r
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=fill, width=tw)
    f = _t("display", int(size * 0.66))
    pw = d.textlength("P", font=f)
    d.text((cx - pw / 2.0, cy - size * 0.36), "P", font=f, fill=fill)
    return r * 2 + int(size * 0.14)


# ---------------- 照片复用 ----------------

def _local_bg(g, k):
    """沿 **x 方向**的大核中值 = 横向缓慢变化的背景（字迹会被抹掉）。"""
    H, W = g.shape
    pad = max(1, int(k) // 2)
    row = np.pad(g, ((0, 0), (pad, pad)), mode="edge")
    win = np.lib.stride_tricks.sliding_window_view(row, k, axis=1)   # (H, W+1, k)
    return np.median(win, axis=2)[:, :W]


def _ink_mask(small, k=71, thresh=34):
    """封面上的「叠加墨迹」掩膜：局部背景被打破的像素。"""
    g = np.asarray(small.convert("L")).astype(np.float32)
    res = np.abs(g - _local_bg(g, k))
    return res > thresh


def _thin_ratio(mask):
    """「细笔画」占比 —— **判别字与照片内容的关键**。

    字的笔画细：把掩膜腐蚀一下（MinFilter）就整根消失，剩下极少。
    照片主体（头发、花、书页）是一整块，腐蚀后还留一大片核心。
    所以 thin = 1 - 腐蚀后残留 / 原面积：
      笔画 ≈ 1.0；大块 ≈ 0.2 以下。
    """
    if mask.sum() == 0:
        return 0.0
    m = Image.fromarray((mask * 255).astype(np.uint8), "L")
    core = np.asarray(m.filter(ImageFilter.MinFilter(5))) > 128
    return float(1.0 - core.sum() / max(1, mask.sum()))


def overlay_bands(cover, n=200):
    """**建议**封面自带标题占的横带 —— 返回 ``(top, bottom)``，供**人工复核**。

    🔴 重要：这是**建议值，不是自动判据**。实测「这条带里有没有字」在统计上
    分不开：花的边缘/头发的轮廓和字的笔画，在「局部背景残差」「细笔画占比」
    「横向段数」这几个量上完全重叠（花 0.77~0.97 vs 字 0.88~1.00）。
    所以正确用法是：本函数给一个保守建议 → 用 ``tools/audit_covers.py``
    把掩膜叠在原图上**用眼睛确认** → 把结论写进 ``safe_bands``（CLI
    ``--safe-bands`` 或 albums.json 的 ``safe_bands`` 字段）。

    返回 ``(0.0, 1.0)`` 表示没检出／建议整幅取景。
    """
    S = cover.convert("RGB").resize((n, n), Image.LANCZOS)
    mask = _ink_mask(S, k=max(15, n * 36 // 100))
    top, bottom = 0.0, 1.0
    zones = (("top", 0.0, 0.42, "top"), ("bottom", 0.72, 1.0, "bottom"))
    for _name, lo, hi, side in zones:
        y0, y1 = int(lo * n), int(hi * n)
        sub = mask[y0:y1]
        if sub.sum() < 120:
            continue
        if _thin_ratio(sub) < 0.42:
            continue
        cols = np.where(sub.any(0))[0]
        if len(cols) == 0:
            continue
        span = (cols.max() - cols.min() + 1) / float(n)
        share = sub.mean()
        if span < 0.34 or not (0.008 <= share <= 0.55):
            continue
        rows = np.where(sub.any(1))[0]
        if len(rows) < 4:
            continue
        # 收紧到实际有墨迹的行范围，再留一点余量
        if side == "top":
            top = min(1.0, (y0 + rows.max() + 1) / float(n) + 0.015)
        else:
            bottom = max(0.0, (y0 + rows.min()) / float(n) - 0.015)
    if top >= bottom - 0.15:          # 上下都判成字，说明判据被骗了，退回整幅
        return 0.0, 1.0
    return round(top, 3), round(bottom, 3)


def safe_crop(cover, w, h, D=None, fx=0.5, fy=None, zoom=None, bands=None):
    """取景时**自动避开封面自带的标题带**（「字压两遍」的根治办法）。

    可用区 = 垂直方向 ``[safe_top, safe_bottom]``（来自 ``D["safe_bands"]``），
    在可用区里取**最大的**能放下 ``w:h`` 的窗口；``zoom`` / ``fy`` 只作偏好，
    绝不会突破可用区。
    """
    cov = cover.convert("RGB")
    cw, ch = cov.size
    if bands is None:
        bands = _bands_of(cover, D)
    t, b = bands
    avail = max(0.20, b - t)
    aspect = w / float(h)
    sy = min(avail, 1.0 / aspect)          # 最大可用高度（x 方向也要放得下）
    if zoom and zoom > 1.0:                # 偏好更紧的取景才采纳
        sy = max(0.18, min(sy, sy / float(zoom)))
    sx = min(1.0, sy * aspect)
    cy = (t + b) / 2.0 if fy is None else fy
    cy = min(max(cy, t + sy / 2.0), b - sy / 2.0)
    cy = min(max(cy, sy / 2.0), 1.0 - sy / 2.0)
    cx = min(max(fx, sx / 2.0), 1.0 - sx / 2.0)
    box = (int(round((cx - sx / 2) * cw)), int(round((cy - sy / 2) * ch)),
           int(round((cx + sx / 2) * cw)), int(round((cy + sy / 2) * ch)))
    box = (max(0, box[0]), max(0, box[1]), min(cw, box[2]), min(ch, box[3]))
    if box[2] - box[0] < 2 or box[3] - box[1] < 2:
        box = (0, 0, cw, ch)
    return cov.crop(box).resize((int(w), int(h)), Image.LANCZOS)


def _bands_of(cover, D=None):
    """从设计语言里取 ``(safe_top, safe_bottom)``；没收过就退回「整幅取景」。"""
    if isinstance(D, dict):
        got = D.get("safe_bands")
        if isinstance(got, (tuple, list)) and len(got) == 2:
            return (float(got[0]), float(got[1]))
    return (0.0, 1.0)


def focus_crop(cover, w, h, fx=0.5, fy=0.5, zoom=1.0):
    """从封面里取一个「别的镜头」：焦距点 + 放大倍数。

    ⚠️ 只看焦距点的老接口，**不避让封面自带标题**。新代码请用 ``safe_crop``；
    这个保留给明确知道自己在裁什么的场景。
    """
    cov = cover.convert("RGB")
    cw, ch = cov.size
    r = max(w / cw, h / ch) * max(1.0, float(zoom))
    nw, nh = max(w, int(round(cw * r))), max(h, int(round(ch * r)))
    im = cov.resize((nw, nh), Image.LANCZOS)
    left = int(round(fx * nw - w / 2.0))
    top = int(round(fy * nh - h / 2.0))
    left = max(0, min(nw - w, left))
    top = max(0, min(nh - h, top))
    return im.crop((left, top, left + w, top + h))


def grade(im, sat=1.0, bright=1.0, contrast=1.0, blur=0.0, tint=None, tint_k=0.0):
    """统一色阶。全套部件用同一组参数 → 整案像同一次调色。"""
    out = im.convert("RGB")
    if blur > 0:
        out = out.filter(ImageFilter.GaussianBlur(blur))
    if sat != 1.0:
        out = ImageEnhance.Color(out).enhance(sat)
    if bright != 1.0:
        out = ImageEnhance.Brightness(out).enhance(bright)
    if contrast != 1.0:
        out = ImageEnhance.Contrast(out).enhance(contrast)
    if tint is not None and tint_k > 0:
        a = np.asarray(out).astype(np.float32)
        a = a * (1.0 - tint_k) + np.array(tint, np.float32) * tint_k
        out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")
    return out


def scrim(im, bottom=0.0, top=0.0, left=0.0, right=0.0, power=1.7, veil=0.0):
    """边缘压暗（文字压在照片上时保证可读，同时保留照片感）。

    ``veil`` 是整体压暗量；四方向是渐变压暗，用来给文字让出对比度。
    """
    w, h = im.size
    a = np.asarray(im.convert("RGB")).astype(np.float32)
    mask = np.full((h, w), float(veil), np.float32)
    if bottom:
        mask = np.maximum(mask, bottom * np.linspace(0, 1, h, dtype=np.float32)[:, None] ** power)
    if top:
        mask = np.maximum(mask, top * np.linspace(1, 0, h, dtype=np.float32)[:, None] ** power)
    if left:
        mask = np.maximum(mask, left * np.linspace(1, 0, w, dtype=np.float32)[None, :] ** power)
    if right:
        mask = np.maximum(mask, right * np.linspace(0, 1, w, dtype=np.float32)[None, :] ** power)
    a *= (1.0 - np.clip(mask, 0, 0.96))[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")


def luma(im):
    a = np.asarray(im.convert("L").resize((64, 64))).astype(np.float32)
    return float(a.mean() / 255.0)


def normalize_bright(im, target=0.58, lo=0.55, hi=2.2):
    """把画面亮度归一到一个固定水平 —— 深色封面不发黑、浅色封面不糊。"""
    cur = max(1e-3, luma(im))
    k = float(np.clip(target / cur, lo, hi))
    return ImageEnhance.Brightness(im).enhance(k)


def normalize_gamma(im, target=0.60, lo=0.60, hi=2.60, sat=1.08):
    """用**伽马**提亮，而不是线性乘。

    🔴 线性乘会把「深色高饱和」封面推成黄绿：范特西（红蓝脸）实测提亮 1.45× 后
    红→橙黄，整个盘面色彩失真。伽马只抬中间调，色相基本不动，再补一点饱和度即可。
    """
    a = np.asarray(im.convert("RGB")).astype(np.float32) / 255.0
    cur = float(np.clip(a.mean(), 0.02, 1.0))
    # 🔴 指数方向：要「提亮」需要 1/g < 1 → g > 1。所以 g = log(cur)/log(target)
    #    （写反成 log(target)/log(cur) 时，暗图会算出 0.44 → 被夹到 1.0 → 一点都不亮）
    g = float(np.clip(math.log(cur) / math.log(target), lo, hi))
    a = np.power(a, 1.0 / g)
    out = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8), "RGB")
    if sat != 1.0:
        out = ImageEnhance.Color(out).enhance(sat)
    return out


# ---------------- 真实 EAN-13 ----------------
_L_CODE = ["0001101", "0011001", "0010011", "0111101", "0100011",
           "0110001", "0101111", "0111011", "0110111", "0001011"]
_G_CODE = ["0100111", "0110011", "0011011", "0100001", "0011101",
           "0111001", "0000101", "0010001", "0001001", "0010111"]
_R_CODE = ["1110010", "1100110", "1101100", "1000010", "1011100",
           "1001110", "1010000", "1000100", "1001000", "1110100"]
_PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
           "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]


def ean13_check(d12):
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d12))
    return str((10 - s % 10) % 10)


def make_ean(seed, prefix="697"):
    """由 seed 稳定生成 13 位 EAN（697 = 中国大陆前缀，与参考图一致）。"""
    import zlib
    h = zlib.crc32(str(seed).encode("utf-8"))
    d12 = (prefix + str(h).rjust(9, "0")[:9])[:12]
    return d12 + ean13_check(d12)


def ean13_bits(d13):
    """13 位 → 95 模块的 0/1 串（标准 EAN-13 编码）。"""
    bits = "101"
    for ch, p in zip(d13[1:7], _PARITY[int(d13[0])]):
        bits += (_L_CODE if p == "L" else _G_CODE)[int(ch)]
    bits += "01010"
    for ch in d13[7:13]:
        bits += _R_CODE[int(ch)]
    bits += "101"
    return bits


def ean13(d, x, y, w, h, code, ink=(0, 0, 0), paper=(255, 255, 255), quiet=0.06):
    """画**真实可编码**的 EAN-13（95 模块 + 数字分组），不是随机竖条。

    随机竖条一眼假；按标准编码画，配上数字分组，就有了「实体商品」的可信度。
    """
    code = "".join(c for c in str(code) if c.isdigit())
    if len(code) < 13:
        code = make_ean(code)
    code = code[:13]
    bits = ean13_bits(code)
    w, h = int(w), int(h)
    q = max(3, int(w * quiet))
    bw = w - 2 * q
    mw = bw / 95.0
    bh = int(h * 0.74)
    guard_extra = int(bh * 0.13)
    fs = max(7, int(h * 0.215))

    # 🔴 白底（静区）必须**连数字行一起盖住** —— 只盖竖条会让数字落在深色封底上，
    #    印出来是一条读不出的黑字（EAN 规范也要求静区是白的）。
    if paper is not None:
        d.rectangle([x - q, y - int(h * 0.06), x + w + q,
                     y + bh + int(fs * 1.55)], fill=paper)

    for i, b in enumerate(bits):
        if b != "1":
            continue
        x0 = int(round(x + q + i * mw))
        x1 = int(round(x + q + (i + 1) * mw))
        x1 = max(x1, x0 + 1)
        is_guard = i < 3 or 45 <= i <= 49 or i >= 92
        hh = bh + (guard_extra if is_guard else 0)
        d.rectangle([x0, y, x1 - 1, y + hh], fill=ink)

    # 数字分组 1-6-6（与参考图同款：左 1 位、中 6 位、右 6 位）
    f = _t("num", fs)
    dy = y + bh + int(h * 0.055)
    w1 = d.textlength(code[0], font=f)
    d.text((x + q - w1 - max(1, int(mw * 1.2)), dy), code[0], font=f, fill=ink)
    for grp, ctr in ((code[1:7], q + 24 * mw), (code[7:13], q + 71 * mw)):
        gw = d.textlength(grp, font=f)
        d.text((x + ctr - gw / 2.0, dy), grp, font=f, fill=ink)
    return code


# ---------------- 手写引言 / 落款 ----------------
_QUOTE_POOL = {
    "dreamy": ["把心事交给旋律，让它替我慢慢说",
               "月亮不睡，我也不睡",
               "云朵停在耳边，替我把话说完"],
    "energetic": ["把音量推到最大，世界就安静了",
                  "心跳是最诚实的节拍器",
                  "年轻的声音，盖不住也拦不下"],
    "melancholic": ["有些话说不出口，就唱成了歌",
                    "难过就放到 B 面，别占 A 面的轨",
                    "雨停之前，先把这首歌唱完"],
    "retro": ["老歌里的那束光，照到今天还没熄",
              "磁带会老，旋律不会",
              "旧时光转一圈，又回到副歌"],
    "minimalist": ["少一点声音，听懂的人自然会懂",
                   "留白不是空，是给耳朵留的位置",
                   "一首歌，记住一个字就够了"],
    "bold": ["不必解释，听见的人会明白",
             "不解释，是最响的宣言",
             "把颜色调到最满，把话说得最直"],
}

_BAD_LINE = ("作词", "作曲", "编曲", "制作人", "录音", "混音", "母带", "和声",
             "吉他", "贝斯", "鼓", "钢琴", "弦乐", "OP", "SP", "纯音乐",
             "未经", "版权", "出品", "监制", "统筹", "发行", "企划")


def pick_quote(lyric_lines, D=None):
    """从真实歌词里挑一句当「专辑金句」：取重复次数最多的那句（副歌记忆点）。

    取不到就按 mood/style 回退到通用句 —— 但宁可回退也不能空着，
    手写引言是整案里最提气的一件。
    """
    from collections import Counter
    pool = []
    for ln in (lyric_lines or []):
        t = str(ln).strip()
        if not (6 <= len(t) <= 22):
            continue
        if any(b in t for b in _BAD_LINE):
            continue
        if t.startswith("[") or ":" in t or "：" in t:
            continue
        pool.append(t)
    if pool:
        c = Counter(pool)
        top = c.most_common(3)
        top.sort(key=lambda kv: (-kv[1], len(kv[0])))
        return top[0][0]
    if D:
        key = D.get("mood") or D.get("style") or "dreamy"
        pool = _QUOTE_POOL.get(key) or _QUOTE_POOL["dreamy"]
        if isinstance(pool, str):     # 兼容旧的单句写法
            pool = [pool]
        # 无歌词回退以前固定取第一句 → 同 mood 的多张专辑批量时金句全部雷同。
        # 现在用封面主色亮度做种子在池内挑选：跨专辑自然错开，单专辑可复现。
        seed = sum(int(c) for c in (D.get("main") or (128, 128, 128))[:3])
        return pool[seed % len(pool)]
    return _QUOTE_POOL["dreamy"][0]


def hand_text(im, xy, text, size, fill, tracking=1.0, anchor_x="left",
              angle=0.0, shadow=(0, 0, 0, 120), offset=(1, 1), limit=None):
    """手写体文字（可带轻微倾斜与投影）。返回实际宽度。

    手写体（中文=楷体 / 纯拉丁=Inkfree）是「设计稿感」的关键零件：
    印刷体排不出「作者亲笔」的味道，而实体唱片内页几乎都有这么一句。
    """
    role = "hand" if any("\u2e80" <= c <= "\u9fff" for c in text) else "hand_latin"
    f = _t(role, size, text)
    x, y = xy
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    wd = tracked(measure, (x, y), text, f, fill, tracking, anchor_x, limit)
    sx = x if anchor_x == "left" else (x - wd if anchor_x == "right" else x - wd / 2.0)

    lay = Image.new("L", im.size, 0)
    tracked(ImageDraw.Draw(lay), (sx, y), text, f, 255, tracking, "left", limit)
    if angle:
        lay = lay.rotate(angle, resample=Image.BICUBIC, center=(sx, y))
        sx, y = sx + offset[0], y + offset[1]   # 视觉上仅作稳定化，不影响内容

    layers = []
    if shadow:
        sh = Image.new("RGBA", im.size, tuple(shadow[:3]) + (0,))
        a = lay.point(lambda v: int(v * (shadow[3] / 255.0)))
        sh.putalpha(a.transform(im.size, Image.AFFINE, (1, 0, -offset[0], 0, 1, -offset[1])))
        layers.append(sh)
    fg = Image.new("RGBA", im.size, tuple(fill[:3]) + (0,))
    fg.putalpha(lay)
    layers.append(fg)
    for L in layers:
        if im.mode == "RGBA":
            im.alpha_composite(L)
        else:
            im.paste(L, (0, 0), L)
    return wd


# ---------------- 版式零件 ----------------
def label_line(d, x, y, h, company, artist, ink, dim):
    """厂牌 / 版权信息行 —— 真封底必须有，缺了就是「设计稿」不是「唱片」。"""
    f = _t("heavy", max(7, int(h * 0.46)))
    cx = x
    word = (company or "JVR MUSIC").upper()[:14]
    d.text((cx, y + int(h * 0.24)), word, font=f, fill=ink)
    cx += d.textlength(word, font=f) + h * 0.5
    fs = max(7, int(h * 0.28))
    f2 = _t("sans", fs, artist)
    adv = phonogram(d, cx, y + int(h * 0.26), fs, dim)
    d.text((cx + adv, y + int(h * 0.30)), " & © " + (artist or ""), font=f2, fill=dim)
    return cx + adv


def _label_credit(artist="", company=""):
    """把「厂牌名」拼成规范版权行。

    🔴 踩过两个坑：
      1. 厂牌本身就叫「JVR Music」，再套模板就成了 **"JVR Music Music
         International Ltd."**（Music 连写两遍）→ 结尾的 Music 要去重；
      2. 中文厂牌（「华策音乐（天津）有限公司」）套英文模板会变成
         「…有限公司 Music International Ltd.」四不像 → 中文走另一套写法。
    """
    label = (company or artist or "").strip()
    if not label:
        return " & © All rights reserved."
    if re.search(r"[\u4e00-\u9fff]", label):
        return " & © %s · All rights reserved." % label
    core = re.sub(r"[ \t]*music[ \t]*$", "", label, flags=re.I).strip() or label
    return " & © %s Music International Ltd. All rights reserved." % core


def _copy_lines(d, w, artist="", company=""):
    """算出「℗ & © 行 + 英文声明」折行后的实际行数与字体 —— 排版前先量高度用。"""
    fs = max(7, int(w * 0.032))
    f = _t("sans", fs, artist)
    adv_est = int(fs * 1.15)                 # ℗ 的占位宽度（矢量画，宽度≈字号）
    rest = _label_credit(artist, company)
    l2 = ("Unauthorized copying, reproduction, hiring, lending, public performance "
          "and broadcasting prohibited.")
    a = wrap_tracked(d, rest, f, max(10, w - adv_est), 0.2)
    b = wrap_tracked(d, l2, f, w, 0.2)
    return fs, f, a, b


def copyright_block(d, x, y, w, ink, dim, artist="", album="", company=""):
    """℗ & © 行 + 英文声明（未经许可不得…）。

    🔴 英文声明是**固定长句**，窄列里必须**折行**。用 ``tracked(limit=w)`` 是截断，
    印出来就是 "public p…" 这种半截话 —— 实体封底上真就是折两行的。
    返回整块实际高度，方便调用方从底部反推排版位置。
    """
    fs, f, l1, l2 = _copy_lines(d, w, artist, company)
    step = max(9, int(fs * 1.55))
    adv = phonogram(d, x, y, fs, dim)
    for i, ln in enumerate(l1):
        tracked(d, (x + (adv if i == 0 else 0), y + i * step), ln, f, dim, 0.2, "left")
    yy = y + len(l1) * step
    for i, ln in enumerate(l2):
        tracked(d, (x, yy + i * step), ln, f, dim, 0.2, "left")
    return (yy - y) + len(l2) * step


def copyright_height(d, w, artist="", company=""):
    fs, f, l1, l2 = _copy_lines(d, w, artist, company)
    return (len(l1) + len(l2)) * max(9, int(fs * 1.55))


def tracklist(d, x, y, w, h, tracks, ink, dim, cols=1, lead=None, max_lines=None,
              max_lead=None):
    """曲目表：DIN 风序号 + 无衬线歌名，行距按空间自适应。

    序号用 dim 色、歌名用主墨色 —— 层级一拉开就不像「一坨字」。

    🔴 ``max_lead`` 必须给：不封顶时，**只有 1 首**的专辑会算出
    「行距 = 整块高度」，序号字号跟着行距走 → 一个占半页的巨型「01」
    （实测《Six Degrees》单曲封底就是这个事故）。
    """
    tracks = [t for t in (tracks or []) if str(t).strip()]
    if not tracks:
        return 0
    cols = max(1, int(cols))
    per = math.ceil(len(tracks) / cols)
    avail = h
    lh = int(min([v for v in (lead or h, avail / max(1, per), max_lead or h) if v]))
    fs = max(7, int(lh * 0.60))
    fn = _t("num", max(7, int(fs * 0.86)))
    colw = (w - int(w * 0.04) * (cols - 1)) / cols if cols > 1 else w
    used = 0
    for ci in range(cols):
        cx = x + ci * (colw + int(w * 0.04))
        cy = y
        for k in range(per):
            idx = ci * per + k
            if idx >= len(tracks) or (max_lines and k >= max_lines) or cy + lh > y + h:
                break
            num = "%02d" % (idx + 1)
            tracked(d, (cx, cy + int(lh * 0.10)), num, fn, dim, 0.4)
            nx = cx + d.textlength("00", font=fn) * 1.75
            f2, t2 = fit_tracked(d, str(tracks[idx]), colw - (nx - cx), fs, "sans", 0.2)
            d.text((nx, cy), t2, font=f2, fill=ink)
            cy += lh
            used += 1
    return used


def design_notes(D, album="", artist="", tracks=None, has_lyrics=False):
    """给展示板用的「设计思路」文案 —— 由设计语言真实推导，不是写死的套话。"""
    mood_cn = {"dreamy": "梦幻柔和", "energetic": "明亮有力", "melancholic": "内敛低沉"}
    style_cn = {"minimalist": "极简留白", "retro": "复古颗粒", "bold": "强对比大色块"}
    n = len([t for t in (tracks or []) if str(t).strip()])
    out = [
        "以封面主色系（%s）贯穿全套部件，保证摆在一起是同一套视觉语言。"
        % "#%02x%02x%02x" % tuple(D.get("main", (128, 128, 128))[:3]),
        "整体调性定为「%s + %s」：内页、封底沿用封面照片的不同裁切，"
        "不引入外来素材，天然同源。"
        % (mood_cn.get(D.get("mood"), "自然"), style_cn.get(D.get("style"), "规整")),
        "标题用衬线体加字距、曲目用无衬线、序号与条码数字用 DIN 窄体，"
        "手写金句与落款单独一层 —— 三种字体角色拉开层级。",
        "封底按实体唱片规范补齐厂牌、录音版权与著作权声明行、版权声明与可编码 EAN-13 条码%s。"
        % ("，歌词页内容取自该专辑真实歌词" if has_lyrics else ""),
    ]
    if n:
        out.append("本张专辑共 %d 首，曲目表按 %s列排布，行距随曲目数自适应。"
                   % (n, "两" if n > 8 else "单"))
    return out


# ==========================================================================
#  v2 部件
# ==========================================================================
def _key_grade(D, span=1.0):
    """把封面色阶折成「同一次调色」的公共参数（全套部件共用）。"""
    bright = D.get("bright", 0.5)
    if bright < 0.35:      # 深色封面：提亮 + 稍微降饱和，避免糊成一团黑
        return dict(sat=0.92, bright=1.30 * span, contrast=1.06)
    if bright > 0.68:      # 浅色封面：压一点，避免文字压不住
        return dict(sat=0.98, bright=0.86 * span, contrast=1.08)
    return dict(sat=1.0, bright=1.0 * span, contrast=1.05)


def design_back2(cover, w, h, D, album="", artist="", tracks=None, seed=0,
                 quote=None, company=""):
    """封底（v2）：整幅照片做底 + 左侧压暗信息栏 + 曲目 + 金句 + 版权层 + EAN-13。

    版式取实体唱片的通用解法：**照片通铺、信息分区**。硬切左右两半会显得像
    两张图拼的；用「渐变压暗让出对比度」才能真正像一张封底。
    """
    w, h = int(w), int(h)
    g = _key_grade(D)
    key = D.get("main", (128, 128, 128))
    tracks = [t for t in (tracks or []) if str(t).strip()]

    # 🔴 取景避开封面**自带的标题字**：封面标题/歌手名几乎都压在上缘，
    #    fy 偏小会把「周杰伦」这种字切一半带进来，看着像失误。压到画面中部取。
    base = grade(safe_crop(cover, w, h, D, fx=0.55, fy=0.53, zoom=1.30),
                 sat=g["sat"] * 1.0, bright=g["bright"], contrast=g["contrast"])
    base = scrim(base, left=0.70, bottom=0.46, top=0.08, power=1.6, veil=0.10)
    d = ImageDraw.Draw(base)

    ink = (248, 247, 245)
    dim = (186, 188, 194)
    pad = max(5, int(w * 0.048))
    lc = int(w * 0.42)                      # 左信息栏宽度

    # 标题块
    y = int(h * 0.070)
    f, t = fit_tracked(d, album or "", lc, int(h * 0.135), "serif", 1.6)
    tracked(d, (pad, y), t, f, ink, 1.6, "left", lc)
    y += int(f.size * 1.20)
    f2, t2 = fit_tracked(d, artist or "", lc, int(h * 0.056), "sans", 1.4)
    tracked(d, (pad, y), t2, f2, dim, 1.4, "left", lc)
    y += int(f2.size * 1.75)
    hairline(d, pad, y, pad + lc, (255, 255, 255), 1)
    y += int(h * 0.028)

    # 曲目：>10 首自动两列（单列硬塞会缩到看不清）
    cols = 2 if len(tracks) > 10 else 1
    if tracks:
        tracklist(d, pad, y, lc, int(h * 0.715) - y, tracks, ink, dim,
                  cols=cols, max_lines=14, max_lead=int(h * 0.052))
    else:
        # 🔴 以前这里再印一遍 artist：标题块 + 这行 + 金句落款 = 无曲目时歌手名
        #    出现三次（用户实测指出的重复）。实体封底这个位置通常印的是
        #    「COMPACT DISC DIGITAL AUDIO」格式标识 —— 印这个，不再重复人名。
        f3, t3 = fit_tracked(d, "COMPACT DISC DIGITAL AUDIO", lc, int(h * 0.05), "sans", 1.2)
        tracked(d, (pad, y), t3, f3, dim, 1.2, "left", lc)

    # 厂牌 / 版权层（实体封底的信息层，缺了就只是「设计稿」）
    # 🔴 从底部反推位置：版权块折行后行数不定（1~3 行），写死 ly 会让底边被裁。
    word = (company or artist or "").strip()
    fL, wL = (fit_tracked(d, word.upper(), lc * 0.94, max(8, int(h * 0.070)),
                          "heavy", 2.2, min_s=9) if word else (None, ""))
    if fL is not None and "…" in wL:
        # 缩到最小还放不下 → 拆两行（厂牌名不该出现「华策音乐（…」这种半截）
        fL = _t("heavy", max(8, int(h * 0.052)), word)
        wL = word.upper()
    blk = (int(fL.size * 1.30) if fL else 0) + copyright_height(d, lc, artist, word)
    ly = max(int(h * 0.70), h - int(h * 0.030) - blk)
    hairline(d, pad, ly - int(h * 0.030), pad + lc, (255, 255, 255), 1)
    if fL:
        for i, ln in enumerate(wrap_tracked(d, wL, fL, lc * 0.94, 2.2)):
            tracked(d, (pad, ly + i * int(fL.size * 1.30)), ln, fL, ink, 2.2, "left")
        ly += int(fL.size * 1.30) * max(1, len(wrap_tracked(d, wL, fL, lc * 0.94, 2.2)))
    copyright_block(d, pad, ly, lc, ink, dim, artist, album, word)

    # 手写金句：压在右侧亮部的中下方（左上角留出照片的呼吸）
    q = quote or pick_quote(None, D)
    if q:
        qs = max(9, int(h * 0.058))
        qw = int(w * 0.42)
        lines = _wrap_hand(d, q, qw, qs, 2)      # 限 2 行：多了会跟曲目栏抢视线
        step = int(qs * 1.34)
        y0 = int(h * 0.585) - len(lines) * step
        for i, ln in enumerate(lines):
            hand_text(base, (w - pad, y0 + i * step), ln, qs, ink, 1.2, "right",
                      shadow=(0, 0, 0, 170))
        d = ImageDraw.Draw(base)
        fq = _t("sans", max(8, int(qs * 0.56)), artist)
        tracked(d, (w - pad, y0 + len(lines) * step + int(h * 0.014)),
                "— %s" % (artist or album or ""), fq, dim, 1.0, "right")

    # 条码：右下角白底（EAN 规范要求静区）—— 右下不压字，也符合真实封底
    bw = int(w * 0.275)
    bh = int(h * 0.175)
    ean13(d, w - pad - bw, int(h * 0.685), bw, bh, make_ean(seed),
          quiet=0.075, paper=(250, 250, 250))

    # 分区细线（印刷上的一根白线，让「信息区/照片区」有分界但不硬切）
    lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(lay).rectangle([int(w * 0.515), int(h * 0.065),
                                   int(w * 0.515) + 1, int(h * 0.935)],
                                  fill=(255, 255, 255, 52))
    base = Image.alpha_composite(base.convert("RGBA"), lay).convert("RGB")
    return base


def _wrap_hand(d, text, box_w, size, max_lines=2):
    """手写引言按宽度手工折行（手写体没有 CJK 断行，得自己来）。

    🔴 折完要**重新配平**：按宽度贪心折总会把最后一行剩成单字
    （「把音量推到最大，世界就安静 / 了」—— 明信片上实测到的丑陋断行）。
    末行 ≤2 字时改成按字数均分。
    """
    f = _t("hand" if any("\u2e80" <= c <= "\u9fff" for c in text) else "hand_latin", size, text)
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=f) > box_w and cur:
            lines.append(cur)
            cur = ch
            if len(lines) >= max_lines:
                return lines
        else:
            cur += ch
    if cur:
        lines.append(cur)
    if len(lines) > 1 and 0 < len(lines[-1]) <= 2:
        n, total = len(lines), len(text)
        per = (total + n - 1) // n
        bal = [text[i * per:(i + 1) * per] for i in range(n)]
        bal = [b for b in bal if b]
        if len(bal) <= max_lines and all(
                d.textlength(b, font=f) <= box_w for b in bal):
            lines = bal
    # 🔴 逐字断必须再过一遍行首禁则，否则金句会印成
    #    「把音量推到最大 / ，世界就安静了」（实测踩过）。
    return kinsoku(lines[:max_lines])


def design_disc2(cover, d_px, hole_px, D, album="", artist="", company=""):
    """盘面（v2）：先做**亮度归一**再去糊 —— v1 最大的毛病就是盘面发灰发闷。

    实体盘面的观感 = 主图够亮够透 + 银色聚碳酸酯内环 + 细密勾槽 +
    一道窄扇形高光 + 外沿暗边。缺了「银色内环」就会像贴纸；
    内环画得**太大太白**又会变成「白甜甜圈」（实测踩过）。
    """
    ss = 3
    big = max(240, int(d_px) * ss)
    g = _key_grade(D, span=1.12)
    art = safe_crop(cover, big, big, D, fx=0.5, fy=0.55, zoom=1.12)
    art = grade(art, sat=g["sat"] * 1.06, bright=1.0, contrast=1.04,
                blur=big / 420.0)              # 先轻微模糊，压住勾槽的摩尔纹
    art = normalize_gamma(art, target=0.60, sat=1.09)

    cc = np.arange(big) - big / 2.0 + 0.5
    yy, xx = np.meshgrid(cc, cc, indexing="ij")
    rr = np.sqrt(xx ** 2 + yy ** 2)
    ang = np.arctan2(yy, xx)
    r0 = rr / (big / 2.0)

    arr = np.asarray(art).astype(np.float32) / 255.0
    rnd = np.random.default_rng(abs(int(D.get("bright", 0.5) * 1000)) % 9973)

    # 1) 勾槽：乘性暗环（密而淡）。亮底封面要**更淡**，否则出现彩色摩尔纹。
    gstr = 0.075 * float(np.clip(1.25 - D.get("bright", 0.5) * 1.2, 0.30, 1.0))
    gro = 0.5 + 0.5 * np.cos(2.0 * np.pi * r0 * 36.0)
    gmask = ((r0 > 0.235) & (r0 < 0.955)).astype(np.float32)
    arr *= (1.0 - gstr * gro * gmask)[..., None]

    # 1b) 磨砂噪点（盘面不是镜面）
    arr += rnd.normal(0, 0.005, arr.shape).astype(np.float32)

    # 2) 一道窄扇形高光（cos^8）；宽扇区会把整盘糊白
    fan = np.cos(2.0 * (ang - 0.95)) ** 8
    band = np.exp(-((r0 - 0.60) ** 2) / (2 * 0.24 ** 2))
    arr = arr + (1.0 - arr) * (fan * band * 0.36)[..., None]

    # 3) 外沿暗边
    rim = np.exp(-((r0 - 0.968) ** 2) / (2 * 0.020 ** 2))
    arr *= (1.0 - 0.42 * rim)[..., None]

    # 4) 内环：银色聚碳酸酯（径向金属渐变 + 方向性光泽），
    #    范围收到 r0∈[0.125, 0.215]（= 孔径 5mm 到约 8.6mm），太大就成白甜甜圈。
    edge = np.clip((0.215 - r0) / 0.030, 0, 1)
    t = np.clip((0.215 - r0) / 0.090, 0, 1)
    met = 0.86 - 0.26 * t
    gloss = 0.14 * (0.5 + 0.5 * np.cos(ang - 0.9)) ** 2
    hub = np.clip(met + gloss, 0, 1)[..., None] * np.array([0.975, 0.985, 1.0], np.float32)
    arr = arr * (1 - edge[..., None]) + np.broadcast_to(hub, (big, big, 3)) * edge[..., None]

    # 5) 叠盘环（真盘才有的那圈细亮线）
    stk = np.exp(-((r0 - 0.232) ** 2) / (2 * 0.0055 ** 2))
    arr = arr + (1.0 - arr) * (stk * 0.32)[..., None]
    arr = np.clip(arr, 0, 1)

    im = Image.fromarray((arr * 255).astype(np.uint8), "RGB")
    m = Image.new("L", (big, big), 0)
    ImageDraw.Draw(m).ellipse([0, 0, big - 1, big - 1], fill=255)
    im.putalpha(m)
    im = im.resize((int(d_px), int(d_px)), Image.LANCZOS)
    out = Image.new("RGB", (int(d_px), int(d_px)), (255, 255, 255))
    out.paste(im, (0, 0), im)

    # 盘面文字：标题在上半区、厂牌在下半区（真盘都这么排）。
    # 文字压在照片上 → 一律带投影，深浅底都读得出来。
    tw = int(d_px * 0.52)
    ink = white_ink = (250, 250, 250)
    fs, tt = fit_tracked(ImageDraw.Draw(out), album or "", tw,
                         max(7, int(d_px * 0.078)), "serif", 1.2)
    fs2, tt2 = fit_tracked(ImageDraw.Draw(out), artist or "", tw,
                           max(6, int(d_px * 0.044)), "sans", 1.2)
    fL = _t("num", max(6, int(d_px * 0.032)), company or artist)
    lay = Image.new("L", (int(d_px), int(d_px)), 0)
    dl = ImageDraw.Draw(lay)
    tracked(dl, (d_px / 2.0, int(d_px * 0.135)), tt, fs, 255, 1.2, "center", tw)
    tracked(dl, (d_px / 2.0, int(d_px * 0.135) + int(fs.size * 1.22)), tt2, fs2,
            255, 1.2, "center", tw)
    tracked(dl, (d_px / 2.0, int(d_px * 0.785)), (company or artist or "")[:12],
            fL, 255, 1.4, "center", tw)
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    sh.putalpha(lay.transform(out.size, Image.AFFINE, (1, 0, -1, 0, 1, -1))
                .point(lambda v: int(v * 0.55)))
    fg = Image.new("RGBA", out.size, white_ink + (0,))
    fg.putalpha(lay)
    out = out.convert("RGBA")
    out.alpha_composite(sh)
    out.alpha_composite(fg)
    out = out.convert("RGB")

    # 中心孔（Ø5mm，打穿）
    c = d_px / 2.0
    ImageDraw.Draw(out).ellipse([c - hole_px / 2, c - hole_px / 2,
                                 c + hole_px / 2, c + hole_px / 2], fill=(255, 255, 255))
    return out


def design_inner2(cover, w, h, D, album="", artist="", tracks=None, quote=None):
    """内页左半（折进盒里的那一面）：整幅写真 + 手写金句 + 落款。

    v1 这里是「压暗的封面 + 一坨曲目」，等于把封面又印了一遍；
    真唱片内页放的是**同一次拍摄的另一张照片**，所以这里改用高倍裁切。
    """
    g = _key_grade(D)
    base = grade(safe_crop(cover, w, h, D, fx=0.38, zoom=1.40),
                 sat=g["sat"] * 0.86, bright=g["bright"] * 0.96,
                 contrast=g["contrast"] * 1.04,
                 tint=tuple(int(c * 0.55 + 26) for c in D.get("main", (90, 90, 90))),
                 tint_k=0.22)                       # 偏主色的冷调版本
    # 🔴 顶部压暗必须够狠：标题（白色衬线）落在 y≈0.075h 处，top 太小的话
    #    浅色封面（白背景写真）上标题直接隐形。0.24 实测只有 21% 压暗 → 提到 0.42
    #    （同 power 下标题行压暗 ~39%），压到中部才归零，不影响照片主体。
    base = scrim(base, bottom=0.62, top=0.42, power=1.5)
    d = ImageDraw.Draw(base)
    pad = max(4, int(w * 0.075))
    q = quote or pick_quote(None, D)
    if q:
        qs = max(9, int(h * 0.070))
        lines = _wrap_hand(d, q, w - pad * 2, qs, 3)
        y0 = int(h * 0.66)
        for i, ln in enumerate(lines):
            hand_text(base, (pad, y0 + int(i * qs * 1.35)), ln, qs,
                      (250, 250, 248), 1.2, "left", shadow=(0, 0, 0, 160))
        d = ImageDraw.Draw(base)
        if artist:                       # 没填歌手就别印一根孤零零的「—」
            fs = max(8, int(h * 0.062))
            fm = _t("sans", fs, artist)
            tracked(d, (pad, y0 + int(len(lines) * qs * 1.35) + int(h * 0.035)),
                    "— %s" % artist, fm, (222, 224, 228), 1.0, "left")

    # 顶部极细标题（内页也要能被认出来是哪张）
    fs2, tt = fit_tracked(d, album or "", w - pad * 2, int(h * 0.072), "serif", 1.4)
    tracked(d, (pad, pad), tt, fs2, (250, 250, 248), 1.4, "left", w - pad * 2)
    return base


def design_tray2(cover, w, h, D, album="", artist="", company=""):
    """内盘底（v2）：浅色纸面 + 居中衬线标题 + 底部照片条。

    托盘不该跟封面抢戏 —— v1 用深色渐变把整块压成一坨糊，摆进盒里像脏了。
    """
    g = _key_grade(D)
    key = D.get("main", (120, 120, 120))
    tint = tuple(int(c * 0.20 + 196) for c in key)      # 由封面主色调出的浅纸色
    base = grade(safe_crop(cover, w, h, D, fx=0.5, fy=0.5, zoom=1.45),
                 sat=0.30, bright=1.0, contrast=1.0, blur=max(1.0, w / 34.0),
                 tint=tint, tint_k=0.66)
    base = scrim(base, veil=0.02, top=0.10, bottom=0.06)
    d = ImageDraw.Draw(base)
    sw = palette(base, 3)[0]
    ink = ink_on(sw)
    dim = dim_ink(ink, sw, 0.62)

    # 底部照片条（3:1 裁切，给块留口气）
    bh = int(h * 0.24)
    ph = grade(safe_crop(cover, w, bh, D, fx=0.5, fy=0.42, zoom=1.40),
               sat=g["sat"], bright=g["bright"], contrast=g["contrast"])
    base.paste(ph, (0, h - ph.height))
    d = ImageDraw.Draw(base)

    pad = max(6, int(w * 0.09))
    fs, tt = fit_tracked(d, album or "", w - pad * 2, int(h * 0.125), "serif", 1.6)
    ty = int(h * 0.40)
    tracked(d, (int(w * 0.5), ty), tt, fs, ink, 1.6, "center", w - pad * 2)
    fs2, tt2 = fit_tracked(d, artist or "", w - pad * 2, int(h * 0.056), "sans", 1.4)
    tracked(d, (int(w * 0.5), ty + int(fs.size * 1.30)), tt2, fs2, dim, 1.4,
            "center", w - pad * 2)
    hairline(d, int(w * 0.40), ty + int(fs.size * 1.30) + int(fs2.size * 2.1),
             int(w * 0.60), ink, 1)
    if company:
        fL = _t("num", max(6, int(h * 0.038)), company)
        tracked(d, (int(w * 0.5), ty + int(fs.size * 1.30) + int(fs2.size * 2.9)),
                company.upper(), fL, dim, 1.6, "center", w - pad * 2)
    return base


def design_lyrics(cover, w, h, D, album="", artist="", song="", lines=None,
                  page=1, total=1, company=""):
    """歌词页：浅色纸面 + 衬线标题 + 歌词正文（版面留白按行数自适应）。"""
    g = _key_grade(D)
    key = D.get("main", (128, 128, 128))
    paper = tuple(int(c * 0.18 + 232) for c in key)
    base = Image.new("RGB", (w, h), paper)
    d = ImageDraw.Draw(base)
    ink = (34, 34, 38)
    dim = tuple(int(ink[i] * 0.55 + paper[i] * 0.45) for i in range(3))
    pad = max(6, int(w * 0.075))

    # 顶部：右侧一条照片（同一视觉语言），左侧标题
    ps = int(h * 0.20)
    ph = grade(safe_crop(cover, int(w * 0.30), ps, D, fx=0.48, zoom=1.45),
               sat=g["sat"], bright=max(g["bright"], 0.9), contrast=g["contrast"])
    base.paste(ph, (w - pad - ph.width, pad))
    fs, tt = fit_tracked(d, ("%02d " % page) + (song or album or ""),
                         w - pad * 2 - ph.width - int(w * 0.05),
                         int(h * 0.095), "serif", 1.2)
    tracked(d, (pad, pad + int(h * 0.012)), tt, fs, ink, 1.2, "left")
    f2, t2 = fit_tracked(d, "%s · %s" % (artist or "", album or ""),
                         w - pad * 2 - ph.width, int(h * 0.048), "sans", 0.8)
    tracked(d, (pad, pad + int(h * 0.115)), t2, f2, dim, 0.8, "left")
    y = pad + ph.height + int(h * 0.055)
    hairline(d, pad, y - int(h * 0.028), w - pad, dim, 1)

    body = [l.strip() for l in (lines or []) if l and l.strip()]
    avail = h - y - int(h * 0.11)
    if body:
        # 🔴 关键：行高有**下限**。按 avail/len 均分会把 88 行压到 7px 全糊成一片灰，
        # 宁可只印得下前十几行（真歌词本也是一页一页翻的）。
        lh = int(max(max(9, int(h * 0.040)), min(avail / max(1, len(body)), int(h * 0.085))))
        fs3 = max(8, int(lh * 0.64))
        f3 = _t("sans", fs3)
        for i, ln in enumerate(body):
            yy = y + i * lh
            if yy + lh > h - int(h * 0.09):
                break
            d.text((pad, yy), ln, font=f3, fill=ink)
    else:
        # 🔴 无歌词（单曲 / 纯音乐）时**不能留一大片空白** —— 实测《Six Degrees》
        #    这一格几乎全白，看着像没做完。改成「金句页」：
        #    手写金句（按宽度折行，不截断）+ 落款 + 底部一条同源照片 + 版权行。
        q = pick_quote(None, D) or ""
        qs = max(10, int(h * 0.072))
        fq = _t("hand", qs, q)
        ql = wrap_tracked(d, q, fq, w - pad * 2, 1.5)
        qy = y + int(h * 0.018)
        for i, ln in enumerate(ql[:3]):
            tracked(d, (pad, qy + int(i * qs * 1.36)), ln, fq, ink, 1.5, "left",
                    w - pad * 2)
        qy += int(len(ql[:3]) * qs * 1.36) + int(h * 0.022)
        # 底部一条同源照片，补齐下半个版面
        strip_h = int(h * 0.24)
        st = grade(safe_crop(cover, w - pad * 2, strip_h, D, fx=0.5, zoom=1.5),
                   sat=g["sat"], bright=max(g["bright"], 0.94), contrast=g["contrast"])
        base.paste(st, (pad, h - pad - int(h * 0.055) - strip_h))
        # 🔴 落款（左）与 INSTRUMENTAL 标签（右）同处一条横带：长艺人名会撞上
        #    右侧标签（实测 Jay Chou & Patrick Brasca 叠成「Bra…NSTRUMENTAL」）
        #    —— 先量标签宽，落款 fit 进剩余宽度（字号缩到底才截断）。
        fL0 = _t("num", max(6, int(h * 0.032)))
        tag = ("INSTRUMENTAL / %s" % ("%02d" % total)) if total else ""
        tag_w = (d.textlength(tag, font=fL0) + 1.2 * max(0, len(tag) - 1)) if tag else 0
        fsa, ta = fit_tracked(d, "— %s" % (artist or album or ""),
                              w - pad * 2 - tag_w - int(w * 0.05),
                              max(8, int(h * 0.042)), "sans", 1.4)
        tracked(d, (pad, qy), ta, fsa, dim, 1.4, "left")
        tracked(d, (w - pad, h - pad - int(h * 0.055) - strip_h - int(h * 0.050)),
                tag, fL0, dim, 1.2, "right")
    fL = _t("num", max(6, int(h * 0.032)))
    tracked(d, (pad, h - int(h * 0.065)), "%s / %s" % (page, total), fL, dim, 1.0)
    tracked(d, (w - pad, h - int(h * 0.065)), (company or "JVR MUSIC").upper()[:12],
            _t("sans", fL.size, company), dim, 1.4, "right")
    return base


def design_sleeve(cover, w, h, D, album="", artist="", quote=None, company=""):
    """内封套展开（跨页）：左页写真、右页手写金句 + 落款。

    这是「整案」里最能体现设计完整度的一件，参考图里排第 07/06 位。
    """
    g = _key_grade(D)
    half = w // 2
    left = grade(safe_crop(cover, half, h, D, fx=0.36, fy=0.45, zoom=1.35),
                 sat=g["sat"] * 1.04, bright=g["bright"] * 1.02,
                 contrast=g["contrast"], tint=(58, 68, 94), tint_k=0.12)
    left = scrim(left, bottom=0.30, left=0.10)
    right = grade(safe_crop(cover, w - half, h, D, fx=0.60, fy=0.50, zoom=1.35),
                  sat=g["sat"] * 0.60, bright=g["bright"] * 0.86, contrast=g["contrast"],
                  blur=max(1.0, w / 220.0))
    right = scrim(right, top=0.30, bottom=0.30, right=0.14, veil=0.50)
    base = Image.new("RGB", (w, h))
    base.paste(left, (0, 0))
    base.paste(right, (half, 0))
    d = ImageDraw.Draw(base)

    q = quote or pick_quote(None, D)
    ink = (250, 250, 248)
    if q:
        qs = max(10, int(h * 0.088))
        lines = _wrap_hand(d, q, half - int(w * 0.09), qs, 4)
        y0 = int(h * 0.30)
        for i, ln in enumerate(lines):
            hand_text(base, (half + int(w * 0.045), y0 + int(i * qs * 1.42)), ln,
                      qs, ink, 1.4, "left", shadow=(0, 0, 0, 170))
        d = ImageDraw.Draw(base)
        fs = max(9, int(h * 0.062))
        tracked(d, (half + int(w * 0.045), y0 + int(len(lines) * qs * 1.42) + int(h * 0.05)),
                "— %s" % (artist or album or ""), _t("sans", fs, artist), (216, 218, 222), 1.2, "left")
    fsT, tT = fit_tracked(d, album or "", half - int(w * 0.09), int(h * 0.105), "serif", 1.4)
    tracked(d, (half + int(w * 0.045), int(h * 0.78)), tT, fsT, ink, 1.4, "left")
    hairline(d, half + int(w * 0.045), int(h * 0.755), half + int(w * 0.045) + int(w * 0.10),
             (255, 255, 255), 1)
    fL = _t("sans", max(7, int(h * 0.034)), company)
    tracked(d, (half + int(w * 0.045), int(h * 0.895)),
            (company or "JVR MUSIC").upper()[:14], fL, (190, 192, 198), 1.6, "left")
    return base


def design_postcard(cover, w, h, D, album="", artist="", quote=None):
    """明信片：整幅照片 + 底部白卡条（标题/落款），手写金句压在照片右下。

    🔴 金句**不能画进白卡条**：白条里标题（左）与金句（右）同一行域，
    标题一长就叠字/出界（《Six Degrees》《Something Great》《你是迟来的欢喜》
    三张实测板全部翻车）。白卡条只放 标题+落款，金句归照片区（scrim 压底 + 投影）。
    """
    g = _key_grade(D)
    bw = int(h * 0.30)                        # 白卡条高度
    ph = grade(safe_crop(cover, w, h - bw, D, fx=0.5, zoom=1.28),
               sat=g["sat"] * 1.06, bright=max(g["bright"], 1.0) * 1.06,
               contrast=g["contrast"] * 1.03, tint=(238, 226, 206), tint_k=0.10)
    ph = scrim(ph, bottom=0.30, top=0.06)     # 底部压暗：给手写金句让对比度
    base = Image.new("RGB", (w, h), (246, 245, 243))
    base.paste(ph, (0, 0))
    d = ImageDraw.Draw(base)
    ink = (38, 38, 42)
    dim = (140, 142, 148)
    pad = max(5, int(w * 0.045))
    fs, tt = fit_tracked(d, album or "", w * 0.82, int(bw * 0.34), "serif", 1.4)
    tracked(d, (pad, h - bw + int(bw * 0.22)), tt, fs, ink, 1.4, "left", w * 0.82)
    f2, t2 = fit_tracked(d, artist or "", w * 0.82, int(bw * 0.20), "sans", 1.0)
    tracked(d, (pad, h - bw + int(bw * 0.64)), t2, f2, dim, 1.0, "left", w * 0.82)
    q = quote or pick_quote(None, D)
    if q:
        qs = max(9, int(h * 0.055))
        step = int(qs * 1.34)
        qlines = _wrap_hand(d, q, int(w * 0.56), qs, 2)
        y0 = (h - bw) - int(h * 0.035) - len(qlines) * step
        for i, ln in enumerate(qlines):
            hand_text(base, (w - pad, y0 + i * step), ln, qs,
                      (252, 252, 250), 1.0, "right", shadow=(0, 0, 0, 160))
    return base


def design_spine2(w, h, D, album="", artist="", company=""):
    """侧标 / 书脊（v2）：竖排 + 字距 + 底部厂牌块（真书脊的排法）。"""
    w, h = int(w), int(h)
    key = D.get("main", (120, 120, 120))
    base = Image.new("RGB", (w, h), tuple(int(c * 0.34) for c in key))
    d = ImageDraw.Draw(base)
    ink = ink_on(palette(base, 3)[0])
    dim = dim_ink(ink, palette(base, 3)[0], 0.66)

    txt = " ".join(x for x in ((album or ""), (artist or "")) if x)
    fs = max(7, int(min(w * 0.60, h * 0.048)))
    f = _t("serif", fs, txt)
    avail = int(h * 0.84)
    chars, used = [], 0.0
    for ch in txt:
        adv = fs * 1.18
        if used + adv > avail:
            chars.append("…")
            break
        chars.append(ch)
        used += adv
    used = len(chars) * fs * 1.18
    cy = int(h * 0.07 + max(0.0, (int(h * 0.78) - used) / 2.0))   # 垂直居中
    for ch in chars:
        cw = d.textlength(ch, font=f)
        d.text(((w - cw) / 2, cy), ch, font=f, fill=ink)
        cy += int(fs * 1.18)
    hairline(d, int(w * 0.22), int(h * 0.90), int(w * 0.78), ink, 1)
    lab = (company or artist or "").strip()
    fL, lab = fit_tracked(d, lab, w * 0.82, max(7, int(w * 0.40)), "sans", 0.4)
    tracked(d, (w / 2.0, int(h * 0.925)), lab, fL, dim, 0.4, "center", w * 0.82)
    return base
