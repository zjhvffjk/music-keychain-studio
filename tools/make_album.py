# -*- coding: utf-8 -*-
"""
网易云「专辑图」合成器  (make_album.py)

输入歌手名 → 抓该歌手**全部专辑**（封面母版 + 专辑名 + 发行日期 + 曲目数），
产出三种东西：

  1) 封面母版原图   albums/          —— 每张专辑一张方形高清封面（网易云 CDN 原图）
  2) 专辑卡         album_cards/     —— 每张专辑一张方形卡：大封面 + 专辑名 + 歌手 + 日期·曲目数
  3) 专辑墙总览     总览-专辑墙.jpg   —— 全部专辑封面拼成一面墙，每格标专辑名 + 日期·曲目数

用法:
  # 单张专辑卡
  python make_album.py --cover 封面.jpg --album 范特西 --artist 周杰伦 \
        --date 2001-09-14 --tracks 10 --out card.jpg

  # 按歌手全量出图（联网）
  python make_album.py 周杰伦 --out ../outputs/周杰伦-专辑全集

  # 从工作台任务目录重出（读 albums.json，不联网）
  python make_album.py --batch ../outputs/周杰伦-专辑全集 --out ../outputs/周杰伦-专辑全集

目录约定（与 workbench 一致）：
  任务目录/
    albums/        01 范特西 - 周杰伦.jpg
    album_cards/   01 范特西 - 周杰伦.jpg
    总览-专辑墙.jpg
    albums.json    专辑元数据清单（便于重出 / 二次加工）
"""
import argparse
import json
import os
import re
import sys
import time

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from fonts import find_bold, find_regular

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 中文字体：自动探测当前系统，可用环境变量
# MINUET_FONT_BOLD / MINUET_FONT_REG 覆盖（见 tools/fonts.py）
BD = find_bold()
RG = find_regular()

# ---- 配色（深色，和项目其它成品一致）----
WALL_BG = (18, 18, 22)
TEXT_MAIN = (245, 245, 247)
TEXT_SUB = (170, 170, 178)
TEXT_DIM = (132, 132, 142)

# 卡片背景：把封面高斯模糊后**压暗**（不是提亮）。
# ⚠️ 压暗系数要够低，否则会变成"封面糊了一层纱"，文字压不住（播放页那边踩过这个坑）。
CARD_BG_DIM = 0.30

CARD_SIZES = (1200, 1500, 2000)      # 专辑卡可选边长
CARD_DEFAULT_SIZE = 1500
COVER_MAX = 2000                     # 网易云 CDN 母版上限（只能降采样，不能超分）


def _font(size, bold=False):
    for p in ([BD, RG] if bold else [RG, BD]):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size, index=0)
            except Exception:
                continue
    return ImageFont.load_default()


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n\t]', "_", str(s)).strip()[:100]


def center_square(im: Image.Image) -> Image.Image:
    """居中裁成正方形（专辑封面基本本来就是方的，防御性处理）。"""
    w, h = im.size
    s = min(w, h)
    return im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))


def fit_square(im: Image.Image, side: int) -> Image.Image:
    return center_square(im).resize((side, side), Image.LANCZOS)


def _tw(draw, text, font):
    try:
        return draw.textlength(text, font=font)
    except Exception:
        return draw.textsize(text, font=font)[0]


def ellipsize(draw, text, font, max_w):
    """单行收敛到 max_w 宽：先截断加省略号。"""
    text = str(text)
    if _tw(draw, text, font) <= max_w:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _tw(draw, text[:mid] + ell, font) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + ell) if lo > 0 else ell


def shrink_to_fit(draw, text, size, max_w, bold=True, floor=0.55):
    """按字号从 size 往下降到 floor*size，找第一个放得下的；都不行交给 ellipsize。

    返回 (font, text)。专辑名长短差异极大（《Jay》 vs 《周杰伦地表最强世界巡回演唱会》），
    固定字号必炸，所以先降号、再截断。
    """
    text = str(text)
    for k in range(0, 8):
        s = int(round(size * (1 - 0.055 * k)))
        if s < int(size * floor):
            break
        f = _font(s, bold)
        if _tw(draw, text, f) <= max_w:
            return f, text
    f = _font(max(int(size * floor), 10), bold)
    return f, ellipsize(draw, text, f, max_w)


def fmt_tracks(n):
    try:
        return f"{int(n)} 首"
    except Exception:
        return ""


# ---------------------------------------------------------------- 专辑卡

def make_card(cover_path, out_path, album, artist,
              date_str="", tracks=None, size=CARD_DEFAULT_SIZE,
              kind="", company="", bg="blur"):
    """单张专辑 → 一张方形卡。

    版式（自上而下）：大封面 → 专辑名 → 歌手 → 类别 · 发行日期 · 曲目数 · 唱片公司
    背景 = 封面高斯模糊后压暗到 30%（有纹理、不被冲淡、文字压得住）。
    """
    size = int(size) if int(size) in CARD_SIZES else CARD_DEFAULT_SIZE
    S = size
    im = Image.open(cover_path).convert("RGB")

    if bg == "dark":
        canvas = Image.new("RGB", (S, S), WALL_BG)
    else:
        b = fit_square(im, S).filter(ImageFilter.GaussianBlur(max(2, int(S * 0.055))))
        canvas = ImageEnhance.Brightness(b).enhance(CARD_BG_DIM)

    pad = int(round(S * 0.070))
    text_h = int(round(S * 0.158))
    side = S - 2 * pad - text_h
    cover = fit_square(im, side)
    canvas.paste(cover, (pad, pad))

    d = ImageDraw.Draw(canvas)
    ty = pad + side + int(round(S * 0.032))
    max_w = S - 2 * pad

    f_name, name = shrink_to_fit(d, album, int(S * 0.060), max_w, bold=True)
    d.text((pad, ty), name, font=f_name, fill=TEXT_MAIN)

    y = ty + int(round(S * 0.066))
    if artist:
        f_ar = _font(int(S * 0.035), False)
        d.text((pad, y), ellipsize(d, artist, f_ar, max_w), font=f_ar, fill=TEXT_SUB)
        y += int(round(S * 0.048))

    meta = " · ".join(str(x) for x in
                      (kind, date_str, fmt_tracks(tracks), company) if x)
    if meta:
        f_meta = _font(int(S * 0.029), False)
        d.text((pad, y), ellipsize(d, meta, f_meta, max_w), font=f_meta, fill=TEXT_DIM)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    canvas.save(out_path, quality=95, subsampling=0)
    return out_path


# ---------------------------------------------------------------- 专辑墙

def wall_cols(n):
    """按专辑数量挑列数：让墙既不过宽也不过长（44 张 → 7 列）。"""
    if n <= 4:
        return max(1, n)
    if n <= 12:
        return 4
    if n <= 24:
        return 5
    if n <= 40:
        return 6
    if n <= 56:
        return 7
    return 8


def make_wall(items, out_path, cols=0, cell=300, title="",
              pad=46, gap=30):
    """全部专辑封面拼成一面墙。

    items: [{"cover": 路径, "name": 专辑名, "date": "2025-06-06", "tracks": 1}, ...]
           也接受 ("路径", "标签") 这种二元组（此时只有一行标签）。
    """
    if not items:
        return ""
    cols = int(cols) if int(cols or 0) > 0 else wall_cols(len(items))
    cols = max(1, min(cols, len(items)))
    rows = (len(items) + cols - 1) // cols

    cell = max(120, int(cell))
    f_title = _font(int(cell * 0.115), True)
    f_name = _font(int(cell * 0.072), True)
    f_meta = _font(int(cell * 0.062), False)

    gap_cover_label = int(cell * 0.045)
    name_h = int(cell * 0.115)
    meta_h = int(cell * 0.098)
    label_h = gap_cover_label + name_h + meta_h
    title_h = (int(cell * 0.20) + 14) if title else 0
    row_h = cell + label_h

    W = pad * 2 + cols * cell + (cols - 1) * gap
    H = pad * 2 + title_h + rows * row_h + (rows - 1) * gap
    canvas = Image.new("RGB", (W, H), WALL_BG)
    d = ImageDraw.Draw(canvas)

    if title:
        d.text((W // 2, pad + int(cell * 0.10)), title,
               font=f_title, fill=TEXT_MAIN, anchor="mm")

    y0 = pad + title_h
    for i, it in enumerate(items):
        if isinstance(it, dict):
            cover, name = it.get("cover"), it.get("name", "")
            date_str, tracks = it.get("date", ""), it.get("tracks")
            meta = " · ".join(x for x in (date_str, fmt_tracks(tracks)) if x)
        else:
            cover, name, meta = it[0], it[1], (it[2] if len(it) > 2 else "")
        r, c = divmod(i, cols)
        x = pad + c * (cell + gap)
        y = y0 + r * (row_h + gap)
        try:
            with Image.open(cover) as f:
                thumb = fit_square(f.convert("RGB"), cell)
            canvas.paste(thumb, (x, y))
        except Exception:
            d.rectangle([x, y, x + cell, y + cell], fill=(38, 38, 44))
        ly = y + cell + gap_cover_label
        d.text((x + cell // 2, ly + name_h // 2),
               ellipsize(d, name, f_name, cell - 4),
               font=f_name, fill=TEXT_MAIN, anchor="mm")
        if meta:
            d.text((x + cell // 2, ly + name_h + meta_h // 2),
                   ellipsize(d, meta, f_meta, cell - 4),
                   font=f_meta, fill=TEXT_DIM, anchor="mm")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    canvas.save(out_path, quality=94, subsampling=0)
    return out_path


# ---------------------------------------------------------------- 联网取数

def plan_albums(artist_name, limit=0):
    """歌手名 → (歌手dict, 专辑列表)。每项：id/name/pic/date/tracks/type/company。

    全部专辑（含单曲 / EP / 演唱会 Live / Remix），按发行时间**新 → 旧**。
    接口已实测：周杰伦 44 张，name/picUrl/publishTime/size 无缺失。
    """
    import fetch163
    res = fetch163.search(artist_name, "artist", 20)
    ars = (res.get("artists") or [])
    if not ars:
        return None, []
    ar = ars[0]
    raw = fetch163.artist_albums(ar["id"], 400)
    out, seen = [], set()
    for x in raw:
        name = (x.get("name") or "").strip()
        pic = x.get("picUrl") or ""
        if not name or not pic:
            continue
        if name in seen:            # 同名重发（Live / 重制）只留最新那张
            continue
        seen.add(name)
        ts = x.get("publishTime") or 0
        date_str = time.strftime("%Y-%m-%d", time.localtime(ts / 1000)) if ts else ""
        out.append({
            "id": x.get("id"), "name": name, "pic": pic,
            "date": date_str, "tracks": x.get("size"),
            "type": x.get("type") or "", "company": x.get("company") or "",
        })
        if limit and len(out) >= int(limit):
            break
    return ar, out


def fetch_cover(pic_url, out_path, size=COVER_MAX):
    """下载封面母版原图（网易云 CDN 原图，不裁不缩）。失败返回 0。"""
    import fetch163
    url = fetch163.cover_url(pic_url, size)
    return fetch163.download(url, out_path)


def build_all(artist_name, out_dir, card=True, wall=True,
              card_size=CARD_DEFAULT_SIZE, limit=0,
              log=None, on_item=None):
    """按歌手出「全部专辑」：封面母版 + 专辑卡 + 专辑墙。

    log(msg, level)      进度日志；level ∈ info/ok/warn/err
    on_item(item)        每张专辑出一份后回调（工作台用它推进度条）

    返回 summary dict。任何单张专辑失败只跳过它，不中断整批。
    """
    def _log(m, lv="info"):
        if log:
            log(m, lv)

    ar, albums = plan_albums(artist_name, limit)
    if not ar:
        return {"ok": False, "error": f"没搜到歌手「{artist_name}」", "items": []}
    if not albums:
        return {"ok": False, "error": f"「{ar['name']}」没有可用的专辑封面", "items": []}
    _log(f"歌手 {ar['name']}（id={ar.get('id')}）· 共 {len(albums)} 张专辑")

    a_dir = os.path.join(out_dir, "albums")
    c_dir = os.path.join(out_dir, "album_cards")
    os.makedirs(a_dir, exist_ok=True)
    if card:
        os.makedirs(c_dir, exist_ok=True)

    made, wall_items = [], []
    for i, alb in enumerate(albums, 1):
        base = safe_name(f"{i:02d} {alb['name']} - {ar['name']}")
        cpath = os.path.join(a_dir, base + ".jpg")
        got = fetch_cover(alb["pic"], cpath)
        if not got:
            _log(f"  [{i:02d}] 封面下载失败，跳过：{alb['name']}", "warn")
            continue
        item = {
            "rank": i, "name": alb["name"], "artist": ar["name"],
            "date": alb["date"], "tracks": alb["tracks"],
            "type": alb["type"], "company": alb["company"],
            "albumUrl": cpath, "albumPath": cpath,
            "cardUrl": None, "cardPath": None,
        }
        if card:
            kpath = os.path.join(c_dir, base + ".jpg")
            try:
                make_card(cpath, kpath, alb["name"], ar["name"],
                          date_str=alb["date"], tracks=alb["tracks"],
                          size=card_size, kind=alb["type"], company=alb["company"])
                item["cardUrl"], item["cardPath"] = kpath, kpath
            except Exception as e:
                _log(f"  [{i:02d}] 专辑卡失败（{type(e).__name__}: {e}）：{alb['name']}", "warn")
        wall_items.append({"cover": cpath, "name": alb["name"],
                           "date": alb["date"], "tracks": alb["tracks"]})
        made.append(item)
        _log(f"  [{i:02d}] {alb['name']}"
             + (f"  {alb['date']}" if alb["date"] else "")
             + (f"  {fmt_tracks(alb['tracks'])}" if alb["tracks"] else ""), "ok")
        if on_item:
            on_item(item)
        time.sleep(0.18)

    if not made:
        return {"ok": False, "error": "全部专辑封面都下载失败", "items": []}

    wall_path = ""
    if wall:
        wall_path = make_wall(wall_items, os.path.join(out_dir, "总览-专辑墙.jpg"),
                              title=f"{ar['name']} · 专辑全集（{len(made)} 张）")
        _log(f"专辑墙总览已生成（{len(made)} 张）", "ok")

    meta = {"artist": ar["name"], "artistId": ar.get("id"),
            "count": len(made), "albums": made}
    try:
        meta_path = os.path.join(out_dir, "albums.json")
        tmp = meta_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"artist": ar["name"], "albums": albums}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, meta_path)
    except Exception as e:
        _log(f"albums.json 落盘失败：{type(e).__name__}: {e}", "warn")

    return {"ok": True, "artist": ar["name"], "items": made,
            "wall": wall_path, "count": len(made), "meta": meta}


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description="网易云专辑图：封面母版 + 专辑卡 + 专辑墙")
    ap.add_argument("artist", nargs="?", default="", help="歌手名（联网抓全部专辑）")
    ap.add_argument("--out", default="", help="输出目录")
    ap.add_argument("--limit", type=int, default=0, help="最多取前 N 张（0=全部）")
    ap.add_argument("--card-size", type=int, default=CARD_DEFAULT_SIZE,
                    choices=list(CARD_SIZES), help="专辑卡边长")
    ap.add_argument("--no-card", dest="card", action="store_false", help="不出专辑卡")
    ap.add_argument("--no-wall", dest="wall", action="store_false", help="不出专辑墙")
    # 单张卡片模式
    ap.add_argument("--cover", default="", help="单张模式：封面路径")
    ap.add_argument("--album", default="", help="单张模式：专辑名")
    ap.add_argument("--date", default="", help="单张模式：发行日期")
    ap.add_argument("--tracks", type=int, default=0, help="单张模式：曲目数")
    ap.add_argument("--size", type=int, default=CARD_DEFAULT_SIZE, help="单张模式：卡片边长")
    ap.add_argument("--bg", default="blur", choices=["blur", "dark"],
                    help="单张模式：卡片背景")
    ap.add_argument("--artist-name", dest="artist_name", default="",
                    help="单张模式：歌手名")
    ap.add_argument("--kind", default="", help="单张模式：专辑类别（专辑/单曲/EP）")
    ap.add_argument("--company", default="", help="单张模式：唱片公司")
    ap.add_argument("--batch", default="", help="从任务目录（读 albums.json）重出")
    ap.set_defaults(card=True, wall=True)
    a = ap.parse_args()

    # --- 单张卡片 ---
    if a.cover:
        out = a.out or os.path.join("out", safe_name(a.album or "album") + ".jpg")
        p = make_card(a.cover, out, a.album or "专辑", a.artist_name or "",
                      date_str=a.date, tracks=a.tracks or None,
                      size=a.size, kind=a.kind, company=a.company, bg=a.bg)
        print("->", os.path.abspath(p))
        return

    # --- 从任务目录重出 ---
    if a.batch:
        src = a.batch
        out_dir = a.out or src
        jf = os.path.join(src, "albums.json")
        if not os.path.exists(jf):
            print("没有 albums.json：", jf);  return
        data = json.load(open(jf, encoding="utf-8"))
        ar_name = data.get("artist", "")
        albums = data.get("albums", [])
        a_dir = os.path.join(src, "albums")
        c_dir = os.path.join(out_dir, "album_cards")
        os.makedirs(c_dir, exist_ok=True)
        wall_items = []
        for i, alb in enumerate(albums, 1):
            base = safe_name(f"{i:02d} {alb['name']} - {ar_name}")
            cp = os.path.join(a_dir, base + ".jpg")
            if not os.path.exists(cp):
                print(f"  [{i:02d}] 缺封面，跳过：{alb['name']}");  continue
            if a.card:
                make_card(cp, os.path.join(c_dir, base + ".jpg"), alb["name"], ar_name,
                          date_str=alb.get("date", ""), tracks=alb.get("tracks"),
                          size=a.card_size, kind=alb.get("type", ""),
                          company=alb.get("company", ""))
            wall_items.append({"cover": cp, "name": alb["name"],
                               "date": alb.get("date", ""), "tracks": alb.get("tracks")})
        if a.wall and wall_items:
            make_wall(wall_items, os.path.join(out_dir, "总览-专辑墙.jpg"),
                      title=f"{ar_name} · 专辑全集（{len(wall_items)} 张）")
        print(f"重出完成：{len(wall_items)} 张 -> {os.path.abspath(out_dir)}")
        return

    # --- 按歌手全量 ---
    if not a.artist:
        ap.print_help();  return
    out_dir = a.out or os.path.join("out", safe_name(a.artist + "-专辑全集"))
    r = build_all(a.artist, out_dir, card=a.card, wall=a.wall,
                  card_size=a.card_size, limit=a.limit, log=lambda m, lv="info": print(m))
    if not r["ok"]:
        print("失败：", r["error"]);  return
    print(f"\n完成：{r['count']} 张 -> {os.path.abspath(out_dir)}")
    if r.get("wall"):
        print("专辑墙：", os.path.abspath(r["wall"]))


if __name__ == "__main__":
    main()
