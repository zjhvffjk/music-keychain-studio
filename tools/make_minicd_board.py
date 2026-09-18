# -*- coding: utf-8 -*-
"""整案设计板 —— 一页看全一张专辑的全套部件。

参考图上那种「一张图看清 7 个部件 + 设计思路」的形态，是唱片设计提案的标准交付物：
甲方/自己一眼就能判断整套视觉成不成立。之前只出 A4 拼版，
等于只交了「印刷文件」，没交「设计方案」。

排布（与参考图一致）：
    01 封面(正面) ｜ 02 封面(背面) ｜ 03 专辑侧面 ｜ 04 CD 光盘
    05 内页(写真+文字) ｜ 06 歌词页 ｜ 07 内封套/展开效果
    08 明信片                                   ｜ 设计思路

用法：
    python tools/make_minicd_board.py --cover 封面.jpg --album 最伟大的作品 \
        --artist 周杰伦 --company 杰威尔音乐 --album-id 147779282 --out 输出.jpg
    python tools/make_minicd_board.py --demo          # 用本地已有的专辑跑一张
"""
from __future__ import annotations

import argparse
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import design_parts as DP
except Exception as e:  # pragma: no cover
    raise SystemExit("需要 tools/design_parts.py：%s" % e)


# ---------------- 尺寸（毫米 → 板面像素） ----------------
BOARD = 1900                 # 板面边长
MARGIN = 66
GAP_X = 38
GAP_Y = 46
BG = (237, 237, 236)
CARD = (255, 255, 255)
INK = (26, 27, 30)
DIM = (122, 124, 130)
ACCENT = (176, 42, 38)       # 参考图里标题块的那种红

RENDER_DPI = 620             # 保留给 A4 拼版的精度换算（板面不用它）
SS = 2                       # 板面部件的超采样倍数（渲染 2× 再缩，边缘才锐）

# 板面**显示尺寸**（像素）：按比例关系定，不按毫米 —— 参考图就是这么排的。
# 比例关系必须守住：封底 48:38、内封套 96:41、明信片 80:52、盘面正圆。
DISP = dict(
    cover=452,
    back_w=571, back_h=452,          # 48:38
    disc=452,
    page=424,                        # 内页 / 歌词页 41×41
    spine_w=60, spine_h=452,
    sleeve_w=868, sleeve_h=371,      # 96:41 = 2.340
    post_w=454, post_h=295,          # 80:52 = 1.538
)
CAP_H = 34


def mm2px(mm_val, dpi=RENDER_DPI):
    return max(8, int(round(mm_val / 25.4 * dpi)))


def _rt(im, w, h):
    """超采样降采样：部件先按 2× 渲染，再缩到显示尺寸（比直接低分辨率渲染锐）。"""
    return im.resize((int(w), int(h)), Image.LANCZOS)


def cap_font(size):
    return DP._t("sans", size)


# ---------------- 阴影 / 圆角 ----------------
def shadowed(im, blur=16, offset=(0, 9), alpha=58, radius=0):
    """给部件加投影，让它从浅色板上「浮」起来（参考图的观感来源之一）。"""
    if radius:
        m = Image.new("L", im.size, 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, im.size[0] - 1, im.size[1] - 1],
                                            radius=radius, fill=255)
        base_im = Image.new("RGBA", im.size, (0, 0, 0, 0))
        base_im.paste(im.convert("RGBA"), (0, 0), m)
        im = base_im
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    pad = blur * 3
    W, H = im.width + pad * 2, im.height + pad * 2
    a = im.split()[3]
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", im.size, (0, 0, 0, alpha)),
             (pad + offset[0], pad + offset[1]), a)
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)))
    canvas.alpha_composite(im, (pad, pad))
    return canvas


def disc_rgba(im):
    """盘面出图是白底方图（印刷需要），上板要挖圆 —— 否则板上出现白方块。"""
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).ellipse([0, 0, im.size[0] - 1, im.size[1] - 1], fill=255)
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.paste(im.convert("RGBA"), (0, 0), m)
    return out


# ---------------- 板面组装 ----------------
class Board:
    def __init__(self, w=BOARD, h=BOARD):
        self.im = Image.new("RGB", (w, h), BG)
        self.d = ImageDraw.Draw(self.im)
        self.w, self.h = w, h
        self._cap_h = 34          # 说明文字占高（每格预留）

    def paste_center(self, im, cx, top):
        self.im.paste(im, (int(cx - im.width / 2), int(top)),
                      im if im.mode == "RGBA" else None)
        return im.width, im.height

    def row(self, items, top, content_w=None, gap=GAP_X):
        """把一组 (图, 说明) 在同一行内**均分间距**摆好，返回行高。"""
        content_w = content_w or (self.w - MARGIN * 2)
        n = len(items)
        total = sum(im.width for im, _ in items)
        if n > 1 and total + gap * (n - 1) > content_w:
            k = max(0.30, (content_w - gap * (n - 1)) / float(total))
            items = [(im.resize((max(8, int(im.width * k)), max(8, int(im.height * k))),
                                Image.LANCZOS), cap) for im, cap in items]
            total = sum(im.width for im, _ in items)
        g = gap if n > 1 else 0
        if total + g * (n - 1) > content_w:
            g = max(6, (content_w - total) // max(1, n - 1))
        free = content_w - total - g * (n - 1)
        x = MARGIN + free // 2
        H = 0
        for im, cap in items:
            self.im.paste(im, (int(x), int(top)),
                          im if im.mode == "RGBA" else None)
            if cap:
                f = cap_font(25)
                tw = self.d.textlength(cap, font=f)
                self.d.text((int(x + im.width / 2 - tw / 2),
                             int(top + im.height + 12)), cap, font=f, fill=DIM)
            x += im.width + g
            H = max(H, im.height)
        return H + self._cap_h

    def text_block(self, xy, lines, card=True, w=None):
        """设计思路文字块（参考图左下角那种灰底卡片）。"""
        x, y = xy
        f_h = DP._t("heavy", 30)
        f_b = DP._t("sans", 24)
        pad = 26
        lh = 42
        wrapped = []
        w = w or 900
        for ln in lines:
            cur = ""
            for ch in ln:
                if self.d.textlength(cur + ch, font=f_b) > w - pad * 2 and cur:
                    wrapped.append(cur)
                    cur = ch
                else:
                    cur += ch
            if cur:
                wrapped.append(cur)
        hh = pad * 2 + int(lh * 1.5) + len(wrapped) * lh
        if card:
            self.d.rounded_rectangle([x, y, x + w, y + hh], radius=18, fill=CARD)
        ty = y + pad
        self.d.text((x + pad, ty), "设计思路", font=f_h, fill=INK)
        ty += int(lh * 1.35) + 12
        for ln in wrapped:
            self.d.text((x + pad, ty), ln, font=f_b, fill=(74, 76, 82))
            ty += lh
        return hh


def part_sizes():
    """板面显示尺寸（DISP 的副本，便于外部覆盖）。"""
    return dict(DISP)


def build_board(cover, album, artist, company="", tracks=None, quote=None,
                lyrics=None, lyric_song="", seed=0, w=BOARD, h=None, title_note="",
                safe_bands=None):
    """渲染一张完整的整案设计板，返回 PIL Image。

    ``safe_bands=(top, bottom)``：封面**自带标题**占掉的横带（归一化 y）。
    配件取景会避开这一段，否则封底/盘面/内页会把封面标题裁一半搬进来，
    和自己的排版叠成「字压两遍」（实测《Six Degrees》《你是迟来的欢喜》）。
    """
    S, ss = DISP, SS
    D = DP.read_design(cover, safe_bands=safe_bands)
    tr = [t for t in (tracks or []) if str(t).strip()]

    # ---- 部件：按 2× 超采样渲染后缩到显示尺寸 ----
    P = {}
    P["cover"] = _rt(cover.convert("RGB"), S["cover"], S["cover"])
    P["back"] = _rt(DP.design_back2(cover, S["back_w"] * ss, S["back_h"] * ss, D,
                                    album, artist, tr, seed=seed,
                                    quote=quote, company=company),
                    S["back_w"], S["back_h"])
    P["spine"] = _rt(DP.design_spine2(S["spine_w"] * ss, S["spine_h"] * ss, D,
                                      album, artist, company),
                     S["spine_w"], S["spine_h"])
    P["disc"] = _rt(DP.design_disc2(cover, S["disc"] * ss, S["disc"] * ss // 8, D,
                                    album, artist, company),
                    S["disc"], S["disc"])
    P["inner"] = _rt(DP.design_inner2(cover, S["page"] * ss, S["page"] * ss, D,
                                      album, artist, tr, quote=quote),
                     S["page"], S["page"])
    P["lyrics"] = _rt(DP.design_lyrics(cover, S["page"] * ss, S["page"] * ss, D,
                                       album, artist, lyric_song, lyrics, 2,
                                       max(3, len(tr) or 3), company),
                      S["page"], S["page"])
    P["sleeve"] = _rt(DP.design_sleeve(cover, S["sleeve_w"] * ss, S["sleeve_h"] * ss, D,
                                       album, artist, quote, company),
                      S["sleeve_w"], S["sleeve_h"])
    P["card"] = _rt(DP.design_postcard(cover, S["post_w"] * ss, S["post_h"] * ss, D,
                                       album, artist, quote),
                    S["post_w"], S["post_h"])
    CAP = {"cover": "01 封面（正面）", "back": "02 封面（背面）",
           "spine": "03 专辑侧面（厚度示意）", "disc": "04 CD 光盘",
           "inner": "05 内页（写真 + 文字）", "lyrics": "06 歌词页",
           "sleeve": "07 内封套／展开效果", "card": "08 明信片"}

    # ---- 先算行高，再定板高（不然底部会留一截空白） ----
    row1 = [shadowed(P["cover"]), shadowed(P["back"]), shadowed(P["spine"]),
            shadowed(disc_rgba(P["disc"]), blur=18, alpha=52)]
    row2 = [shadowed(P["inner"]), shadowed(P["lyrics"]), shadowed(P["sleeve"])]
    post = shadowed(P["card"])
    h1 = max(i.height for i in row1) + CAP_H
    h2 = max(i.height for i in row2) + CAP_H
    h3 = max(post.height, 330) + CAP_H
    header_h = 44 + int(74 * 1.22) + int(34 * 1.5) + 34 + 24
    total_h = MARGIN + header_h + h1 + GAP_Y + h2 + GAP_Y + h3 + 78
    h = h or total_h
    b = Board(w, h)

    # ---- 页眉 ----
    y = MARGIN
    b.d.text((MARGIN, y), "ALBUM ARTWORK  /  DESIGN PROPOSAL",
             font=DP._t("num", 26, "ALBUM ARTWORK"), fill=ACCENT)
    y += 44
    f_a = DP._t("serif", 74, album)
    b.d.text((MARGIN, y), album or "", font=f_a, fill=INK)
    y += int(f_a.size * 1.22)
    f_b = DP._t("sans", 34, artist)
    b.d.text((MARGIN, y), artist or "", font=f_b, fill=(70, 72, 78))
    tw = max(b.d.textlength(album or "", font=f_a), 220)
    b.d.rectangle([MARGIN, y + int(f_b.size * 1.5), MARGIN + int(tw),
                   y + int(f_b.size * 1.5) + 3], fill=ACCENT)
    y += int(f_b.size * 1.5) + 34
    if title_note:
        b.d.text((MARGIN, y), title_note, font=DP._t("sans", 26), fill=DIM)
    top = MARGIN + header_h

    # ---- 三行排布 ----
    b.row([(im, CAP[k]) for im, k in
           zip(row1, ("cover", "back", "spine", "disc"))], top)
    top += h1 + GAP_Y
    b.row([(im, CAP[k]) for im, k in zip(row2, ("inner", "lyrics", "sleeve"))], top)
    top += h2 + GAP_Y

    b.im.paste(post, (MARGIN, int(top)), post)
    f = cap_font(25)
    b.d.text((MARGIN + post.width // 2 - b.d.textlength(CAP["card"], font=f) / 2,
              int(top + post.height + 12)), CAP["card"], font=f, fill=DIM)
    tx = MARGIN + post.width + 46
    bw = max(430, w - MARGIN - tx)
    b.text_block((tx, int(top)), DP.design_notes(D, album, artist, tr, bool(lyrics)),
                 card=True, w=bw)

    # ---- 页脚 ----
    foot = ("全部部件由《%s》封面单向推导生成 ｜ 配色取自封面色板、照片取自封面裁切 ｜ "
            "标题衬线体 / 曲目无衬线 / 序号与条码 DIN / 金句手写" % (album or ""))
    b.d.text((MARGIN, h - 54), foot, font=DP._t("num", 20, foot), fill=(152, 154, 160))
    return b.im

# ---------------- 数据准备 ----------------
def _tracks_and_lyrics(album, artist, album_id, want_lyrics=True):
    """曲目 + 真实歌词（拿不到就返回空，由设计引擎降级到「金句页」）。"""
    tracks, lyric_song, lyric_lines = [], "", []
    try:
        import noproxy  # noqa: F401
        import fetch163 as F
    except Exception:
        return tracks, lyric_song, lyric_lines
    try:
        names, _ = F.album_tracks(album, artist, album_id)
        tracks = [n for n in (names or []) if n]
    except Exception:
        tracks = []
    if want_lyrics:
        try:
            got = F.album_lyrics(album, artist, album_id, max_songs=3)
            for name, lines in got:
                body = [l for l in lines if len(l) >= 4]
                if len(body) >= 6:
                    lyric_song, lyric_lines = name, lines
                    break
        except Exception:
            pass
    return tracks, lyric_song, lyric_lines


def main():
    ap = argparse.ArgumentParser(description="整案设计板（一张图看全全套部件）")
    ap.add_argument("--cover")
    ap.add_argument("--album", default="")
    ap.add_argument("--artist", default="")
    ap.add_argument("--company", default="")
    ap.add_argument("--album-id", type=int, default=None)
    ap.add_argument("--tracks", default="", help="分号分隔；不给则联网抓")
    ap.add_argument("--no-lyrics", action="store_true", help="不抓歌词（离线/加速）")
    ap.add_argument("--quote", default="", help="手写金句；不给则从歌词里自动挑")
    ap.add_argument("--out", default="")
    ap.add_argument("--size", type=int, default=BOARD)
    ap.add_argument("--safe-bands", default="",
                    help='配件取景的可用横带 "top,bottom"，如标题占顶部 30% 则 "0.30,1.0"；'
                         "不给=整幅取景。先用 tools/audit_covers.py 出体检图肉眼定")
    ap.add_argument("--demo", action="store_true",
                    help="用本地已有的《最伟大的作品》跑一张（联网抓曲目/歌词）")
    a = ap.parse_args()
    bands = None
    if a.safe_bands:
        try:
            t, b = [float(x) for x in a.safe_bands.split(",")[:2]]
            bands = (t, b)
        except Exception:
            raise SystemExit('--safe-bands 格式应为 "0.37,0.94"')

    cover_path, album, artist, company = a.cover, a.album, a.artist, a.company
    album_id = a.album_id
    if a.demo or not cover_path:
        import json
        base = "outputs/周杰伦-专辑全集"
        js = json.load(open(os.path.join(base, "albums.json"), encoding="utf-8"))
        alb = js["albums"] if isinstance(js, dict) else js
        pick = None
        for x in alb:
            if x.get("name") == (a.album or "最伟大的作品"):
                pick = x
                break
        if pick is None:
            raise SystemExit("albums.json 里没有《%s》" % a.album)
        album = pick["name"]
        artist = artist or "周杰伦"
        company = company or pick.get("company", "")
        album_id = album_id or pick.get("id")
        cover_path = os.path.join(base, "albums",
                                  "%02d %s - %s.jpg" % (alb.index(pick) + 1, album, artist))
    if not cover_path or not os.path.exists(cover_path):
        raise SystemExit("找不到封面：%s" % cover_path)

    cover = Image.open(cover_path).convert("RGB")
    tracks = [t.strip() for t in a.tracks.split(";") if t.strip()]
    lyric_song, lyric_lines = "", []
    if not tracks or not a.no_lyrics:
        got_t, ls, ll = _tracks_and_lyrics(album, artist, album_id,
                                           want_lyrics=not a.no_lyrics)
        tracks = tracks or got_t
        lyric_song, lyric_lines = ls, ll
    print("曲目 %d 首 ｜ 歌词 %d 行（%s）" % (len(tracks), len(lyric_lines),
                                             lyric_song or "无"))

    img = build_board(cover, album, artist, company, tracks,
                      quote=a.quote or None, lyrics=lyric_lines,
                      lyric_song=lyric_song, seed=abs(hash(album)) % 9991,
                      w=a.size, safe_bands=bands)
    out = a.out or "outputs/迷你CD-整案设计板/%s-整案设计板.jpg" % album
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out, quality=94)
    print("saved", out, img.size)


if __name__ == "__main__":
    main()
