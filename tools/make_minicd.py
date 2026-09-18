#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""迷你 CD 打印拼版生成器 —— 把一张专辑的「盒面素材」排成 A4 打印图。

流程定位：搜歌手 → 全专辑图入库(make_album) → 挑专辑配齐盒面素材 →
**本工具**：按毫米级模板排成 A4 300dpi 拼版 → 打印 → 沿灰线裁 →
折叠 → 装进迷你唱片机（实体）。

一套包含 3 个部件（侧标尺寸未定，暂不排）：
  盘面   Ø40mm（内圆 Ø5mm 留白，打穿或压孔）   ← disc.jpg
  封面   展开 82×41mm，对折后 41×41（左内页右封面）← inner.jpg + cover.jpg
  封底条 ≈108.4×38mm（右侧封4.4 + 封底48 + 左侧封4 + 背脊4 + 内盘底48）
         ← back.jpg + tray.jpg，4mm 侧封/背脊用封底边缘自动延展

缺件由**封面衍生设计引擎**(design_parts) 生成 —— 不搜网图、不套死模板，
而是先读封面的色板/明暗/边缘密度推断出 mood+style，再按这套设计语言出件：
  inner 缺 → 封面去色压暗 + 信息板 + 曲目
  back  缺 → 主色渐变 + 曲目双列 + 条码 + 版权行（样式随 style 变）
  tray  缺 → 主色渐变 + 封面小图 + 大号专辑名
  disc  缺 → 封面裁圆 + 银色径向分光 + CD 沟槽纹理（同色系，比贴白圈自然）
  spine  → 竖排专辑名

用法：
  python make_minicd.py --dir <素材文件夹> --artist 周杰伦 --album 范特西
  python make_minicd.py --cover a.jpg --inner b.jpg --back c.jpg --tray d.jpg --disc e.jpg ...
  python make_minicd.py --dir ... --preview        # 额外出每个部件的单件预览
  python make_minicd.py --dir ... --sets 2         # 只排 2 套（默认自动排满一页）
  python make_minicd.py --dir ... --page a4p       # A4 竖（默认 a4l 横，横版排得多）
  python make_minicd.py --dir ... --tracks "A;B;C" # 手动给曲目（空则自动联网反查）
  python make_minicd.py --dir ... --style retro --mood dreamy   # 手动指定设计语言

尺寸规格：111.2 固定结构（用户 2026-09-19 拍板，唯一真源 tools/spec_minicd.py）。
毫米级差 1mm 就装不进盒，**试装后用 --scale 微调**（如 --scale 1.02 放大 2%）。
"""
import argparse
import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

import spec_minicd as SP   # 尺寸唯一真源

sys.stdout.reconfigure(encoding="utf-8")

try:
    import fonts

    def _font(size, bold=False):
        path = fonts.find_bold() if bold else fonts.find_regular()
        return ImageFont.truetype(path, size)
except Exception:  # pragma: no cover
    def _font(size, bold=False):
        return ImageFont.load_default()

# 封面衍生设计引擎（可选 —— 缺了退回旧的纯色补件，不影响主流程）
try:
    import design_parts as DP
except Exception as _e:  # pragma: no cover
    DP, _DP_ERR = None, str(_e)
else:
    _DP_ERR = ""


# ---------------- 规格（毫米） ----------------
DISC_D = 40.0          # 盘面直径
DISC_HOLE = 5.0        # 中心孔直径
COVER_W, COVER_H = 82.0, 41.0
BACK_SEGS = tuple(SP.BACK_SEGS)   # 右侧封/封底/左侧封/左侧封背面/内盘底（spec 真源）
BACK_W = sum(BACK_SEGS)                    # 111.2
BACK_H = 38.0

PAGES = {"a4l": (297.0, 210.0), "a4p": (210.0, 297.0)}
MARGIN = 10.0
GAP = 6.0

LINE = (150, 150, 150)     # 裁切线
LINE_SOFT = (190, 190, 190)


def mm(v, dpi):
    return int(round(v * dpi / 25.4))


# ---------------- 基础图像操作 ----------------
def cover_crop(im, w, h):
    """等比缩放后居中裁到 (w,h)。"""
    im = im.convert("RGB")
    sw, sh = im.size
    scale = max(w / sw, h / sh)
    nw, nh = max(w, int(round(sw * scale))), max(h, int(round(sh * scale)))
    im = im.resize((nw, nh), Image.LANCZOS)
    l, t = (nw - w) // 2, (nh - h) // 2
    return im.crop((l, t, l + w, t + h))


def dominant(im):
    """取封面主色（量化取最大色块，比平均色饱和）。"""
    q = im.convert("RGB").resize((64, 64)).quantize(colors=8)
    counts = sorted(q.getcolors(64 * 64) or [], reverse=True)
    idx = counts[0][1]
    pal = q.getpalette()
    r, g, b = pal[idx * 3: idx * 3 + 3]
    return (r, g, b)


def circle_mask(d_px, ss=4):
    m = Image.new("L", (d_px * ss, d_px * ss), 0)
    ImageDraw.Draw(m).ellipse([0, 0, d_px * ss - 1, d_px * ss - 1], fill=255)
    return m.resize((d_px, d_px), Image.LANCZOS)


def disc_face(img, d_px, hole_px):
    """方形素材 → 圆盘，中心孔留白（白纸打印后打穿/压孔）。"""
    sq = cover_crop(img, d_px, d_px)
    out = Image.new("RGB", (d_px, d_px), "white")
    out.paste(sq, (0, 0), circle_mask(d_px))
    hm = circle_mask(hole_px)
    hole = Image.new("RGB", (hole_px, hole_px), "white")
    out.paste(hole, ((d_px - hole_px) // 2, (d_px - hole_px) // 2), hm)
    return out


# ---------------- 缺件自动补 ----------------
def ink_on(color):
    """按底色亮度选黑/白字 —— 浅色封面(如 Jay 的米棕)补出来的底也是浅的，
    写死白字会完全看不见。"""
    lum = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
    return (26, 26, 26) if lum > 140 else (255, 255, 255)


def fb_inner(cover_im, w, h):
    im = cover_crop(cover_im, w, h).filter(ImageFilter.GaussianBlur(w // 30))
    return ImageEnhance.Brightness(im).enhance(0.55)


def fb_tray(cover_im, w, h, album, artist):
    bg = dominant(cover_im)
    base = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(base)
    label = f"{album or ''} · {artist or ''}".strip(" ·")
    if label:
        f = _font(max(18, h // 14))
        tw = d.textlength(label, font=f)
        d.text((w - tw - h // 12, h - h // 8), label, font=f, fill=ink_on(bg))
    return base


def fb_back(cover_im, w, h, album, artist):
    bg = dominant(cover_im)
    base = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(base)
    label = f"{album or ''}  {artist or ''}".strip()
    if label:
        f = _font(max(20, h // 6), bold=True)
        tw = d.textlength(label, font=f)
        d.text(((w - tw) // 2, h - h // 5), label, font=f, fill=ink_on(bg))
    return base


# ---------------- 三大部件 ----------------
def make_cover_fold(inner_im, cover_im, w_px, h_px):
    """左内页 + 右封面，中间有对折线。"""
    half = w_px // 2
    out = Image.new("RGB", (w_px, h_px), "white")
    out.paste(cover_crop(inner_im, half, h_px), (0, 0))
    out.paste(cover_crop(cover_im, w_px - half, h_px), (half, 0))
    return out


def _edge_stretch(src_im, w_px, h_px, band=24):
    """取图像左缘内侧窄条，压窄+强模糊后拉伸成侧封条。

    直接拉伸 1~2px 边缘会把条码/文字等高频细节拉成刺眼竖纹，
    所以取样一小段(默认24px)并模糊，得到干净的渐变色条。
    """
    band = min(band, max(2, src_im.width // 8))
    strip = src_im.crop((0, 0, band, src_im.height))
    strip = strip.resize((max(2, w_px // 5), h_px), Image.LANCZOS)
    strip = strip.filter(ImageFilter.GaussianBlur(max(2, w_px // 10)))
    return strip.resize((w_px, h_px), Image.LANCZOS)


def _solid_block(cover_im, w_px, h_px, album, artist):
    """DP 不可用时的最简兜底：主色纯底 + 一行字。"""
    color = dominant(cover_im) if cover_im is not None else (120, 120, 120)
    seg = Image.new("RGB", (w_px, h_px), color)
    label = f"{album or ''}  {artist or ''}".strip()
    if label:
        d = ImageDraw.Draw(seg)
        f = _font(max(20, h_px // 6), bold=True)
        d.text((24, h_px - h_px // 5), label, font=f, fill=ink_on(color))
    return seg


def make_back_strip(back_im, tray_im, w_px, h_px, cover_im, album, artist,
                    D=None, tracks=None, seed=0, company=""):
    """[右侧封][封底][左侧封][背脊][内盘底] 一条连续展开图。

    封底与内盘底缺件时走**封面衍生设计**（design_back / design_tray）；
    4mm 级侧封条从相邻段的边缘延展 —— 这样整条展开图色彩是连贯的，
    像一张真实印刷展开图，而不是几块拼贴。
    """
    p = [mm(s, _dpi[0]) for s in BACK_SEGS]
    total = sum(p)
    out = Image.new("RGB", (total, h_px), "white")
    use_dp = DP is not None and D is not None and cover_im is not None

    # --- 封底段 ---
    if back_im is not None:
        b = cover_crop(back_im, p[1], h_px)
    elif use_dp:
        b = DP.design_back2(cover_im, p[1], h_px, D, album, artist, tracks,
                            seed, company=company)
    else:
        b = _solid_block(cover_im, p[1], h_px, album, artist)
    out.paste(b, (p[0], 0))

    # --- 内盘底段 ---
    if tray_im is not None:
        t = cover_crop(tray_im, p[4], h_px)
    elif use_dp:
        t = DP.design_tray2(cover_im, p[4], h_px, D, album, artist, company)
    else:
        t = _solid_block(cover_im, p[4], h_px, album, artist)
    out.paste(t, (p[0] + p[1] + p[2] + p[3], 0))

    # --- 侧封 / 背脊（各 4mm 级）：从相邻件边缘延展 ---
    out.paste(_edge_stretch(b, p[0], h_px), (0, 0))                  # 右侧封 ← 封底左缘
    out.paste(_edge_stretch(t, p[2] + p[3], h_px), (p[0] + p[1], 0))  # 左侧封+背脊 ← 内盘底左缘

    # 各段逐 0.1mm 四舍五入后求和可能与 BACK_W 取整差 ±1px（如 111.2mm：
    # sum(各段)=1314 vs round(111.2)=1313）。统一对齐到调用方给的 w_px，避免断言崩。
    if out.width != w_px or out.height != h_px:
        out = out.resize((w_px, h_px), Image.LANCZOS)
    return out


# ---------------- 素材解析 ----------------
KEYWORDS = {
    "disc": ("盘面", "碟面", "cd面", "disc"),
    "cover": ("封面正", "封面", "front", "cover"),
    "inner": ("封面背", "内页", "背面", "inner", "booklet"),
    "back": ("封底", "back"),
    "tray": ("内盘底", "盘底", "tray"),
    "spine": ("侧标", "书脊", "spine"),
}


def guess_part(path):
    name = os.path.splitext(os.path.basename(path))[0].lower()
    best, score = None, 0
    for part, kws in KEYWORDS.items():
        for i, kw in enumerate(kws):
            if kw in name:
                s = (len(part) == 5) + (10 - i)  # 越靠前的关键词分越高
                if s > score:
                    best, score = part, s
    return best


# ---------------- 拼版 ----------------
_dpi = [300]


def build_page(parts_meta, dpi, page="a4l", max_sets=0, artist="", album="",
               D=None, tracks=None, seed=0, company=""):
    """parts_meta: {part: (Image, is_fallback)}，缺 key 视为完全缺失。

    D = design_parts.read_design(cover) 得到的设计语言；给了它，缺件走衍生设计。
    """
    _dpi[0] = dpi
    pw_mm, ph_mm = PAGES.get(page, PAGES["a4l"])
    W, H = mm(pw_mm, dpi), mm(ph_mm, dpi)
    m, g = mm(MARGIN, dpi), mm(GAP, dpi)
    page_im = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(page_im)

    # 列定义: (部件, 内容物毫米宽, 成品图)
    cover_im = (parts_meta.get("cover") or (None,))[0]

    # --- 盘面 ---
    disc_d = mm(DISC_D, dpi)
    hole_d = mm(DISC_HOLE, dpi)
    src = parts_meta.get("disc", (None, False))[0]
    if src is not None:
        disc = disc_face(src, disc_d, hole_d)
    elif cover_im is not None and DP is not None and D is not None:
        # 封面裁圆 + 银色径向分光（同色系，比贴个白圈自然）
        disc = DP.design_disc2(cover_im, disc_d, hole_d, D, album, artist, company)
    elif cover_im is not None:
        disc = disc_face(cover_im, disc_d, hole_d)
    else:
        disc = disc_face(Image.new("RGB", (400, 400), (40, 40, 40)), disc_d, hole_d)

    # --- 封面对折 ---
    fold_w, fold_h = mm(COVER_W, dpi), mm(COVER_H, dpi)
    inner_im = (parts_meta.get("inner") or (None,))[0]
    if inner_im is None and cover_im is not None:
        if DP is not None and D is not None:
            inner_im = DP.design_inner2(cover_im, fold_w // 2, fold_h, D,
                                        album, artist, tracks)
        else:
            inner_im = fb_inner(cover_im, fold_w // 2, fold_h)
    if cover_im is None:
        raise SystemExit("缺少封面 cover —— 它是主素材，缺了无法自动补")
    fold = make_cover_fold(inner_im, cover_im, fold_w, fold_h)

    # --- 封底条 ---
    strip_w, strip_h = mm(BACK_W, dpi), mm(BACK_H, dpi)
    back_im = (parts_meta.get("back") or (None,))[0]
    tray_im = (parts_meta.get("tray") or (None,))[0]
    strip = make_back_strip(back_im, tray_im, strip_w, strip_h, cover_im,
                            album, artist, D, tracks, seed, company)

    # --- 三列布局，列内叠 N 个，成套取 min ---
    cols = [(disc, disc_d), (fold, fold_w), (strip, strip_w)]
    caps = []
    for im, colw in cols:
        caps.append(max(0, int((H - 2 * m + g) // (im.height + g))))
    sets = min(caps) if not max_sets else min(min(caps), max_sets)
    if sets < 1:
        raise SystemExit("页面放不下一整套，检查 dpi / page")

    total_w = m + sum(im.width for im, _ in cols) + g * (len(cols) - 1)
    if total_w > W - m:
        over = (total_w - (W - m)) / dpi * 25.4
        raise SystemExit(f"三列总宽超出页面约 {over:.1f}mm —— 请用 --page a4l（横版）或降低 --dpi")

    x = m
    for im, colw in cols:
        y = m
        for _ in range(sets):
            page_im.paste(im, (x, y))
            # 裁切标记
            if im is disc:
                cx, cy = x + im.width // 2, y + im.height // 2
                draw.ellipse([x, y, x + im.width - 1, y + im.height - 1],
                             outline=LINE, width=2)
                # 内孔虚线示意（打穿参考）
                r = hole_d // 2 + mm(1.2, dpi)
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=LINE_SOFT, width=1)
                # 十字对位
                draw.line([cx - 8, cy, cx + 8, cy], fill=LINE_SOFT, width=1)
                draw.line([cx, cy - 8, cx, cy + 8], fill=LINE_SOFT, width=1)
            else:
                draw.rectangle([x, y, x + im.width - 1, y + im.height - 1],
                               outline=LINE, width=1)
                if im is fold:  # 对折线
                    draw.line([x + im.width // 2, y, x + im.width // 2, y + im.height],
                              fill=LINE_SOFT, width=1)
                if im is strip:  # 段分隔线（折线参考）
                    px = 0
                    for s in BACK_SEGS[:-1]:
                        px += mm(s, dpi)
                        draw.line([x + px, y, x + px, y + im.height], fill=LINE_SOFT, width=1)
            y += im.height + g
        x += colw + g

    # 页脚
    foot = (f"{artist or ''} · {album or ''} ｜ 迷你CD打印拼版 ｜ {page} {dpi}dpi ｜ "
            f"本页 {sets} 套 ｜ 沿灰线剪裁 ｜ 盘面内孔 Ø{DISC_HOLE:.0f}mm 打穿 ｜ "
            f"打印设置选「实际大小」，并实测左下校验尺 = 50mm").strip("｜ ")
    f = _font(max(16, mm(3, dpi)))
    draw.text((m, H - m - f.size), foot, font=f, fill=(120, 120, 120))

    # 50mm 校验尺：家庭打印常默认「缩放到可打印区域」导致整体变小装不进盒，
    # 打印后用尺子量这条线，不足 50mm 就在打印设置关掉缩放，或用 --scale 补偿。
    ruler_y = H - mm(6.5, dpi)
    ruler_w = mm(50.0, dpi)
    lw = max(3, mm(0.6, dpi))
    draw.line([m, ruler_y, m + ruler_w, ruler_y], fill=(0, 0, 0), width=lw)
    for i in range(6):
        tx = m + mm(i * 10.0, dpi)
        draw.line([tx, ruler_y - mm(2, dpi), tx, ruler_y + mm(2, dpi)],
                  fill=(0, 0, 0), width=max(2, mm(0.4, dpi)))
    draw.text((m + ruler_w + mm(3, dpi), ruler_y - f.size // 2),
              "50mm 校验尺", font=f, fill=(120, 120, 120))
    return page_im, sets, {"disc": disc, "cover": fold, "back": strip}


# ---------------- 批量 ----------------
def _safe_name(s):
    """文件名清洗：tag 会拼进路径，不清洗会被 NTFS 分隔符拆成子目录。"""
    for ch in '/\\:*?"<>|':
        s = s.replace(ch, "_")
    return s.strip(". ").strip() or "album"


def _find_cover(covers, idx, name):
    """封面目录里按「序号前缀」或「专辑名包含」匹配。"""
    try:
        files = sorted(os.listdir(covers))
    except OSError:
        return None
    pref = f"{idx:02d}"
    for f in files:
        if f.startswith(pref) and os.path.splitext(f)[0].endswith(name):
            return os.path.join(covers, f)
    for f in files:
        if pref in os.path.splitext(f)[0][:4] or name in f:
            return os.path.join(covers, f)
    return None


# ---------------- 设计语言 & 曲目 ----------------
def auto_tracks(album, artist, album_id=None):
    """联网反查专辑曲目；抓不到返回 None（不阻断出图）。

    走 search 反查而非 /album/{id}（后者现在要登录）。给了 album_id 就用它
    精确归组，避免「范特西」撞上「依然范特西」。
    """
    try:
        import noproxy  # noqa: F401  绕过本机代理
        import fetch163 as F
    except Exception:
        return None
    try:
        songs, _ = F.album_tracks(album, artist, album_id=album_id)
    except Exception as e:
        print(f"    (曲目反查失败：{type(e).__name__}，封底不含曲目)")
        return None
    return songs or None


def resolve_tracks(args, album, artist, album_id=None):
    if args.tracks:
        return [t.strip() for t in args.tracks.replace("；", ";").split(";") if t.strip()]
    if args.no_tracks or not album:
        return None
    return auto_tracks(album, artist, album_id)


def resolve_design(cover_im, args):
    """读封面 -> 设计语言（mood/style 可命令行覆盖）。"""
    if DP is None or cover_im is None:
        return None
    D = DP.read_design(cover_im)
    if args.mood:
        D["mood"] = args.mood
    if args.style:
        D["style"] = args.style
        D["ink"] = ink_on(D["main"])
    return D


def run_batch(args):
    with open(args.batch, encoding="utf-8") as f:
        data = json.load(f)
    jd = os.path.dirname(os.path.abspath(args.batch))
    covers = args.covers or os.path.join(jd, "albums")
    artist = args.artist or data.get("artist", "")
    items = data.get("albums", [])
    if args.limit:
        items = items[: args.limit]
    _dpi[0] = args.dpi
    os.makedirs(args.out, exist_ok=True)

    made, missing = [], []
    for i, a in enumerate(items, 1):
        name = a.get("name") or f"album{i}"
        cov = _find_cover(covers, i, name)
        if not cov:
            missing.append(name)
            continue
        _dpi[0] = args.dpi
        with Image.open(cov) as im:
            cov_im = im.convert("RGB")     # 复制一份，及时释放文件句柄
        D = resolve_design(cov_im, args, bands=(a.get("safe_bands")
                                                or args_safe_bands(args)))
        tr = resolve_tracks(args, name, artist, a.get("id"))
        page_im, sets, _ = build_page(
            {"cover": (cov_im, False)},
            args.dpi, args.page, args.sets, artist, name, D, tr, i,
            a.get("company") or getattr(args, "company", ""))
        fn = f"打印拼版-{i:02d}-{_safe_name(name)}.jpg"
        page_im.save(os.path.join(args.out, fn), quality=93)
        made.append({"file": fn, "album": name, "sets": sets, "cover": cov,
                     "style": (D or {}).get("style", ""),
                     "mood": (D or {}).get("mood", ""),
                     "tracks": len(tr) if tr else 0})
        extra = f" · {len(tr)} 曲 · {D['style']}/{D['mood']}" if tr and D else ""
        print(f"  [{len(made)}/{len(items)}] {name}{extra}")

    with open(os.path.join(args.out, "batch.json"), "w", encoding="utf-8") as f:
        json.dump({"artist": artist, "dpi": args.dpi, "page": args.page,
                   "made": made, "missing": missing}, f, ensure_ascii=False, indent=2)
    print(f"\n批量完成：{len(made)} 张成功，{len(missing)} 张缺封面 → {args.out}")
    if missing:
        print("缺封面：", ", ".join(missing[:10]))


# ---------------- CLI ----------------
def main():
    ap = argparse.ArgumentParser(description="迷你 CD 打印拼版生成器")
    ap.add_argument("sources", nargs="*", help="部件图片（配合 --cover/--back 等显式指定时不用）")
    ap.add_argument("--dir", help="素材文件夹，按文件名关键词自动识别部件")
    ap.add_argument("--artist", default="")
    ap.add_argument("--album", default="")
    ap.add_argument("--out", default="outputs/迷你CD")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--page", default="a4l", choices=list(PAGES))
    ap.add_argument("--sets", type=int, default=0, help="0 = 自动排满一页")
    ap.add_argument("--scale", type=float, default=1.0, help="整体尺寸微调系数（试装后用）")
    ap.add_argument("--preview", action="store_true", help="额外输出单部件预览")
    ap.add_argument("--batch", help="albums.json 路径：批量为每张专辑各出一套拼版")
    ap.add_argument("--covers", help="封面目录（配合 --batch，默认取 albums.json 同级 albums/）")
    ap.add_argument("--limit", type=int, default=0, help="批量最多处理前 N 张（0=全部）")
    ap.add_argument("--cover", help="封面正面素材路径")
    ap.add_argument("--inner", help="封面背面/内页素材路径")
    ap.add_argument("--back", help="封底素材路径")
    ap.add_argument("--tray", help="内盘底素材路径")
    ap.add_argument("--disc", help="盘面素材路径")
    ap.add_argument("--tracks", default="",
                    help="手动指定曲目，分号分隔（如 \"A;B;C\"）；留空则联网反查")
    ap.add_argument("--no-tracks", action="store_true",
                    help="不联网反查曲目（离线/批量加速用）")
    ap.add_argument("--company", default="",
                    help="厂牌名（印在封底/侧标；批量模式自动取 albums.json 的 company）")
    ap.add_argument("--safe-bands", default="",
                    help='配件取景的可用横带 "top,bottom"，如标题占顶部 30% 则 "0.30,1.0"'
                         "（先跑 tools/audit_covers.py 肉眼定）；"
                         "批量模式可改在 albums.json 每张专辑加 safe_bands 字段覆盖")
    ap.add_argument("--style", default="",
                    choices=["", "minimalist", "retro", "bold"],
                    help="设计风格覆盖（默认从封面自动推断）")
    ap.add_argument("--mood", default="",
                    choices=["", "dreamy", "energetic", "melancholic"],
                    help="情绪覆盖（默认从封面自动推断）")
    args = ap.parse_args()

    global DISC_D, DISC_HOLE, COVER_W, COVER_H, BACK_SEGS, BACK_W, BACK_H
    if args.scale != 1.0:
        s = args.scale
        DISC_D *= s; DISC_HOLE = max(3.0, DISC_HOLE * s)
        COVER_W *= s; COVER_H *= s
        BACK_SEGS = tuple(v * s for v in BACK_SEGS)
        BACK_W = sum(BACK_SEGS); BACK_H *= s

    _dpi[0] = args.dpi

    if args.batch:
        run_batch(args)
        return

    # 收集素材
    found = {}   # part -> path
    for part in ("cover", "inner", "back", "tray", "disc"):
        path = getattr(args, part, None)
        if not path:
            continue
        if not os.path.exists(path):
            raise SystemExit(f"文件不存在：{path}")
        found[part] = path
    pool = list(args.sources)
    if args.dir:
        pool += [os.path.join(args.dir, f) for f in sorted(os.listdir(args.dir))]
    for p in pool:
        if not os.path.isfile(p):
            continue
        part = guess_part(p)
        if part and part not in found:
            found[part] = p

    print("素材识别：")
    for part in ("cover", "inner", "back", "tray", "disc", "spine", "spine_back"):
        mark = found.get(part)
        print(f"  {part:<10} {'-' if not mark else os.path.basename(mark)}"
              + ("   (暂不参与拼版)" if part.startswith("spine") and mark else ""))

    need_imgs = {}
    fallbacks = []
    for part in ("cover", "inner", "back", "tray", "disc"):
        p = found.get(part)
        if p:
            need_imgs[part] = Image.open(p)
        elif part != "cover":
            fallbacks.append(part)
    if fallbacks:
        print("自动补件：", ", ".join(fallbacks))
    if found.get("spine"):
        print("提示：侧标尺寸未定，本版不排进 A4（确认尺寸后加 --with-spine）")

    # ---- 封面衍生设计：读设计语言 + 反查曲目 ----
    if DP is None:
        print(f"提示：设计引擎不可用（{_DP_ERR}），缺件退回纯色补件")
    D = resolve_design(need_imgs.get("cover"), args)
    if D:
        print(f"设计语言  mood={D['mood']} · style={D['style']} · 主色={D['main']}")
    tr = resolve_tracks(args, args.album, args.artist)
    if tr:
        print(f"曲目 {len(tr)} 首：{' / '.join(tr[:4])}"
              + (" ..." if len(tr) > 4 else ""))

    page_im, sets, previews = build_page(
        {k: (v, False) for k, v in need_imgs.items()},
        args.dpi, args.page, args.sets, args.artist, args.album, D, tr, 0,
        args.company)

    os.makedirs(args.out, exist_ok=True)
    tag = f"{args.album or 'album'}"
    out_page = os.path.join(args.out, f"打印拼版-A4-{tag}.jpg")
    page_im.save(out_page, quality=93)
    print(f"\n已生成：{out_page}  ({page_im.width}x{page_im.height}, {sets} 套/页)")

    if args.preview:
        for name, im in previews.items():
            pp = os.path.join(args.out, f"预览-{name}.jpg")
            im.save(pp, quality=93)
            print("  预览:", pp, im.size)

    meta = {
        "artist": args.artist, "album": args.album,
        "dpi": args.dpi, "page": args.page, "sets": sets,
        "scale": args.scale,
        "spec_mm": {"disc": DISC_D, "hole": DISC_HOLE,
                    "cover": [COVER_W, COVER_H], "back": list(BACK_SEGS)},
        "parts": {k: os.path.abspath(v) for k, v in found.items()},
        "fallbacks": fallbacks,
        "design": ({"mood": D["mood"], "style": D["style"],
                    "main": list(D["main"])} if D else None),
        "tracks": tr or [],
    }
    with open(os.path.join(args.out, "mini_cd.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("参数已记入 mini_cd.json（下次可离线重排）")


if __name__ == "__main__":
    main()
