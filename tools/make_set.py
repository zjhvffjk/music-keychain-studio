#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
批量套装生成器  (make_set.py)

给一个歌手名 → 取网易云热门前 N 首 → 每首自动出两张成品图：
  1. 正方形专辑封面母版（1492x1492，CDN 原图，非截图）
  2. 30x50mm 播放界面（默认 1181x1968 @1000DPI，即精确 30x50mm）

用法:
  python make_set.py 颜人中 --top 10 --out "outputs/颜人中套装"

  # 只要封面不要播放界面
  python make_set.py 颜人中 --top 10 --only cover

常用参数:
  --top N        取热门前 N 首（默认 10）
  --out  <目录>  输出目录
  --width <px>   播放界面宽度（默认 1181 = 30mm @1000DPI）
  --dpi   <n>    写入文件的 DPI 元数据（默认 1000）
  --likes <文本> 红心数文案（网易云**不公开**红心数，默认占位 "999w+"）
  --comments auto|固定值   评论数，默认 auto=取接口真实值
  --listeners    在线人数文案（不公开，默认 "999+人"）
  --playlist     顶部标题（默认 "我喜欢的音乐"）
  --allow-placeholder      保留「无封面」的歌（默认跳过并取下一首补位）

⚠️ 网易云对**缺失封面**的歌曲会返回「纯色横带」占位图（HTTP 200、能解码、尺寸正常）。
   本脚本会自动识别并跳过该曲，用排名下一位补上，保证 --top 张都是干净封面。

输出目录结构:
  <out>/covers/   01 歌名 - 歌手.jpg     正方形封面母版
  <out>/players/  01 歌名 - 歌手.png     30x50mm 播放界面（印刷级）
  <out>/players/  01 歌名 - 歌手.jpg     同上，JPG 版（传平台用）
  <out>/总览.jpg                          全部成品九宫格
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PIL import Image, ImageDraw, ImageFilter, ImageFont
import numpy as np

from fetch163 import (API, cover_url, download, get_json, get_json_ex,
                      safe_name, search)
from fetch_qq import (MAX_COVER as QQ_MAX_COVER, comment_total_q, cover_url_q,
                      download as download_q, hot_songs_q, search_singer_mid)
from fonts import find_bold
from make_player import make as make_player

# 30mm x 50mm @ 1000DPI  ->  1181 x 1968 px
W_DEFAULT = 1181
RATIO_30X50 = 1968 / 1181
# 中文字体：自动探测（可用 MINUET_FONT_BOLD 覆盖）
FONT_BD = find_bold()

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ---------------- 数据 ----------------

def norm(song: dict) -> dict:
    """把「完整字段」和「精简字段(al/ar/dt)」两种格式统一"""
    al = song.get("al") or song.get("album") or {}
    ar = song.get("ar") or song.get("artists") or []
    return {
        "id": song.get("id"),
        "name": song.get("name") or "未知",
        "artists": "/".join(x.get("name", "?") for x in ar),
        "album": al.get("name") or "",
        "pic": al.get("picUrl") or "",
        "dur_ms": song.get("dt") or song.get("duration") or 0,
    }


def hot_songs_ex(artist: str, n: int, retry: int = 2, timeout: int = 9):
    """取歌手热门前 n 首。返回 (ar, pool, err)。

    err 的三态语义（这是本文件最容易踩的坑）：
      err=None 且 pool 非空 → 正常拿到
      err=None 且 pool 为空 → **确实**没有这位歌手
      err 非空              → 接口请求失败（限流/超时/网络），
                              **不能**当成「没有版权」，否则会静默换源

    为什么要单独拆出来：`/api/artist` 需要据此决定「切源」还是「报错重试」。
    """
    res, e1 = get_json_ex(f"{API}/search/get/web",
                          {"s": artist, "type": 100, "limit": 20,
                           "offset": 0, "total": "true"},
                          retry=retry, timeout=timeout)
    if e1:
        return None, [], f"搜索接口不可用（{e1}）"
    ars = (res.get("result") or {}).get("artists") or []
    if not ars:
        return None, [], None
    ar = ars[0]
    d, e2 = get_json_ex(f"{API}/v1/artist/{ar['id']}",
                        retry=retry, timeout=timeout)
    hot = d.get("hotSongs") or []
    if not hot:
        d2, e3 = get_json_ex(f"{API}/artist/top/song", {"id": ar["id"]},
                             retry=retry, timeout=timeout)
        hot = d2.get("songs") or []
        if not hot and (e2 or e3):
            return ar, [], f"歌手详情接口不可用（{e2 or e3}）"
    return ar, [norm(s) for s in hot[:n]], None


def hot_songs(artist: str, n: int):
    """取歌手热门前 n 首（保持网易云的热度排序）。兼容旧调用方。"""
    ar, pool, _ = hot_songs_ex(artist, n)
    return ar, pool


LEAD_MIN = 0.5      # 主唱命中率低于此值 → 判定「版权不在网易云」，自动切 QQ


def lead_rate(pool, artist: str) -> float:
    """主唱命中率：歌曲 artists 第一位 == 目标歌手名 的占比。

    这是判断「网易云到底有没有这个歌手」的可靠信号：
      · 正常歌手（郑润泽/颜人中）→ 主唱就是本人，命中率接近 1.0
      · 版权缺失的歌手（周杰伦）→ hotSongs 只剩「他给别人写的歌 + Live 合唱」，
        前 35 首里只有零星几首署名周杰伦，命中率骤降到 ~0.23
    比「搜索结果为空」灵敏得多——网易云不会直说「没版权」，它会塞一堆别人的歌给你。
    """
    if not pool:
        return 0.0
    name = (artist or "").strip()
    if not name:
        return 0.0
    hit = sum(1 for s in pool
              if (s.get("artists") or "").split("/")[0].strip() == name)
    return hit / len(pool)


def comment_total(sid) -> int:
    """真实评论数（/comment/music 已 404，改用 v1/resource/comments）"""
    if not sid:
        return 0
    r = get_json(f"{API}/v1/resource/comments/R_SO_4_{sid}",
                 {"limit": 1, "offset": 0})
    try:
        return int(r.get("total") or 0)
    except Exception:
        return 0


def human(n: int) -> str:
    """299872 -> 30w+ ; 1200 -> 1200+"""
    if n >= 100000000:
        return f"{n / 100000000:.1f}亿+"
    if n >= 10000:
        return f"{n / 10000:.0f}w+"
    return f"{n}+"


def fmt_dur(ms) -> str:
    s = int((ms or 0) / 1000)
    return f"{s // 60:02d}:{s % 60:02d}"


def save_retry(im, path, tries=8, delay=0.35, **kw):
    """Windows 下刚创建的文件常被实时防护/索引服务短暂锁住，
    直接 im.save() 会间歇性 PermissionError（同一份代码时好时坏）。
    这里重试兜底，而不是让整批任务挂掉。"""
    last = None
    for _ in range(tries):
        try:
            im.save(path, **kw)
            return
        except PermissionError as e:
            last = e
            time.sleep(delay)
    raise last


def normalize_cover(path: str, size: int = 1492):
    """把封面统一为 size×size 正方形母版。

    ⚠️ 网易云 CDN 的 `?param=NyN` **只能降采样，不能超分**：
       源图 2000x2000 → param=1000 得 1000x1000；源图本来就 500x500 → 给 500x500。
       Live 版 / 综艺版 / 早期单曲的专辑封面源图常常只有 375~980px。
    所以统一规格必须自己动手：短边不足先 LANCZOS 等比放大，再居中裁方。

    🔴 size 默认 1492（2026-09-16 起）：1492 = 商品图里「清晰封面」那一层的边长。
       以前统一到 1000、画布却要用 1492 —— 等于每张封面都要再放大 1.49 倍，
       白白糊一层。同时抓取侧的 `?param=` 也从 1000 提到 2000（母版实测
       1400~2000），这样绝大多数封面是**缩小**到 1492，而不是放大。

    返回 (源尺寸, 是否经过放大)
    """
    im = Image.open(path).convert("RGB")
    src = im.size
    w, h = im.size
    short = min(w, h)
    upscaled = short < size
    if upscaled:                       # 短边不够 → 等比放大到短边 = size
        k = size / short
        im = im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)
        w, h = im.size
    left, top = (w - size) // 2, (h - size) // 2     # 居中裁成正方形
    im = im.crop((left, top, left + size, top + size))
    save_retry(im, path, quality=95, subsampling=0)
    return src, upscaled


def is_placeholder(path: str) -> bool:
    """网易云对**缺失封面**的歌曲返回「占位图」——若干条纯色横带，
    部分还叠了胶片噪点伪装成有纹理的样子。

    这种图 HTTP 200、能正常解码、尺寸（1000×1000）也正常，
    小缩略图上几乎看不出问题，**但放进商品图就是一块脏色块**。

    判据（实测分离度极高，全部样本无一误判）：
      1) **水平方向边缘密度 ≈ 0** —— 纯横带在水平方向完全没有梯度
         实测：占位图 = 0.00000；真实封面最低 = 0.00543（极简白底那张）
      2) 兜底 —— 模糊去噪后「每行几乎是常数」的占比 > 0.995
         实测：占位图 = 1.000；真实封面最高 = 0.722

    仅用「行标准差」不行：带噪点的占位图行内标准差约 5，会漏判。
    """
    try:
        g = np.asarray(
            Image.open(path).convert("L").filter(ImageFilter.GaussianBlur(2.0)),
            dtype=float)
        if g.ndim != 2 or g.shape[0] < 8 or g.shape[1] < 8:
            return False
        he = float((np.abs(np.diff(g, axis=1)) > 4).mean())
        row_flat = float((g.std(axis=1) < 3.0).mean())
        return he < 0.001 or row_flat > 0.995
    except Exception:
        return False


# ---------------- 总览九宫格 ----------------

def contact_sheet(players, out_path, cols=5, thumb_w=300, title="", ratio=None):
    """缩略图总览。ratio 缺省按 30×50mm（3:5）；钥匙扣商品图是 1:1，传 1.0。"""
    if not players:
        return ""
    rows = (len(players) + cols - 1) // cols
    th = int(thumb_w * (RATIO_30X50 if ratio is None else ratio))
    gap, pad, cap = 22, 40, 34
    W = pad * 2 + cols * thumb_w + (cols - 1) * gap
    H = pad * 2 + (60 if title else 0) + rows * (th + cap) + (rows - 1) * gap
    canvas = Image.new("RGB", (W, H), (18, 18, 22))
    d = ImageDraw.Draw(canvas)
    if title:
        d.text((W // 2, pad + 14), title,
               font=ImageFont.truetype(FONT_BD, 30, index=0),
               fill=(235, 235, 242), anchor="mm")
    y0 = pad + (60 if title else 0)
    for i, (p, label) in enumerate(players):
        r, c = divmod(i, cols)
        x = pad + c * (thumb_w + gap)
        y = y0 + r * (th + cap + gap)
        im = Image.open(p).convert("RGB").resize((thumb_w, th), Image.LANCZOS)
        canvas.paste(im, (x, y))
        d.text((x + thumb_w // 2, y + th + cap // 2), label,
               font=ImageFont.truetype(FONT_BD, 19, index=0),
               fill=(150, 150, 160), anchor="mm")
    canvas.save(out_path, quality=94)
    return out_path


# ---------------- 主流程 ----------------

def main():
    ap = argparse.ArgumentParser(description="歌手热门前 N 首 → 批量出图")
    ap.add_argument("artist", help="歌手名")
    ap.add_argument("--top", type=int, default=10, help="取热门前 N 首")
    ap.add_argument("--out", default="", help="输出目录")
    ap.add_argument("--width", type=int, default=W_DEFAULT)
    ap.add_argument("--dpi", type=int, default=1000)
    ap.add_argument("--likes", default="999w+", help="红心数文案（接口不提供）")
    ap.add_argument("--comments", default="auto",
                    help="评论数: auto=取真实值, 或直接给文案")
    ap.add_argument("--listeners", default="999+人")
    ap.add_argument("--quality-txt", dest="quality", default="极高音质")
    ap.add_argument("--playlist", default="我喜欢的音乐")
    ap.add_argument("--played", type=float, default=0.0)
    ap.add_argument("--no-vip", dest="vip", action="store_false",
                    help="歌名后不加 VIP 标签（默认加，跟模板一致）")
    ap.add_argument("--no-follow", dest="follow", action="store_false",
                    help="歌手后不加「关注」按钮（默认加）")
    ap.add_argument("--video-tag", action="store_true",
                    help="显示「视频」标签（仅原曲有 MV 时）")
    ap.set_defaults(vip=True, follow=True, video_tag=False)
    ap.add_argument("--only", choices=["both", "cover", "player"], default="both")
    ap.add_argument("--ratio", type=float, default=RATIO_30X50)
    ap.add_argument("--allow-placeholder", action="store_true",
                    help="保留无封面的歌（默认跳过并用下一首补位）")
    ap.add_argument("--no-dedupe", dest="dedupe", action="store_false",
                    help="不按歌名去重（默认去重：同名只留热度最高的那版）")
    ap.add_argument("--cover-size", type=int, default=1492,
                    help="正方形封面母版边长（默认 1492 = 商品图里「清晰封面」那层的边长）")
    ap.add_argument("--source", choices=["auto", "163", "qq"], default="auto",
                    help="数据源：auto=网易云优先，版权缺失自动切 QQ（默认）；"
                         "163=只走网易云；qq=只走 QQ音乐")
    ap.set_defaults(dedupe=True)
    a = ap.parse_args()

    out = a.out or os.path.join("outputs", f"{safe_name(a.artist)}-套装")
    cdir = os.path.join(out, "covers")
    pdir = os.path.join(out, "players")
    os.makedirs(cdir, exist_ok=True)
    os.makedirs(pdir, exist_ok=True)

    # ---- 选源：auto = 网易云优先，判定版权缺失则自动切 QQ ----
    src_used, ar, pool = None, None, []
    want = a.top + 25                  # 多取一些做缓冲：无封面的歌要能补位

    if a.source in ("auto", "163"):
        print(f"=== 搜索歌手: {a.artist}   [网易云] ===")
        ar, pool = hot_songs(a.artist, want)
        if pool:
            rate = lead_rate(pool, a.artist)
            print(f"    主唱命中率 {rate:.0%}（前 {len(pool)} 首里以其为主唱的占比）")
            if a.source == "163" or rate >= LEAD_MIN:
                src_used = "163"
            else:
                print(f"    ⚠ 低于 {LEAD_MIN:.0%} —— 该歌手版权不在网易云"
                      f"（榜单混入大量他人作品 / Live 合唱），自动改用 QQ音乐")
                ar, pool = None, []
        else:
            print("    网易云没有该歌手或无可用歌曲")

    if not pool and a.source in ("auto", "qq"):
        print(f"=== 搜索歌手: {a.artist}   [QQ音乐] ===")
        qmid, qname = search_singer_mid(a.artist)
        if qmid:
            ar = {"id": qmid, "name": qname}
            pool = hot_songs_q(qmid, want)
            if pool:
                src_used = "qq"
            else:
                print("    QQ音乐该歌手没有歌曲")
        else:
            print("    QQ音乐没找到该歌手")

    if not pool:
        print("✘ 网易云和 QQ音乐均无可用结果")
        return
    print(f"歌手: {ar['name']} (id={ar['id']})   数据源: "
          f"{'QQ音乐' if src_used == 'qq' else '网易云'}")
    print(f"热门池 {len(pool)} 首 → 目标 {a.top} 首（无封面自动跳过补位）\n")

    made, skipped, failed = [], [], []
    seen_names = set()
    rank = 0
    for s in pool:
        if rank >= a.top:
            break
        tag = f"[{rank + 1:02d}]"

        # 同名去重：榜单里同一首歌常被不同版本反复刷上来
        if a.dedupe and s["name"] in seen_names:
            print(f"{tag} ↻ 同名重复，跳过: {s['name']}")
            skipped.append(f"{s['name']}（重复版本）")
            continue

        if a.comments == "auto":
            n = comment_total_q(s["id"]) if src_used == "qq" else comment_total(s["id"])
        else:
            n = 0
        cmt = human(n) if (a.comments == "auto" and n) else (
            "0+" if a.comments == "auto" else a.comments)

        # --- 1) 正方形封面母版 ---
        tmp = os.path.join(cdir, safe_name(f"_probe {s['name']} - {s['artists']}.jpg"))
        if src_used == "qq":
            got = download_q(cover_url_q(s["pic"], QQ_MAX_COVER), tmp)
        else:
            got = download(cover_url(s["pic"], 2000), tmp)   # 母版实测 1400~2000
        if not got:
            print(f"{tag} ✘ 封面下载失败，跳过: {s['name']}")
            skipped.append(f"{s['name']}（下载失败）")
            continue
        if not a.allow_placeholder and is_placeholder(tmp):
            os.remove(tmp)
            print(f"{tag} ⚠ 封面缺失（CDN 返回占位色带），跳过补位: {s['name']}")
            skipped.append(f"{s['name']}（无封面）")
            time.sleep(0.2)
            continue

        rank += 1
        seen_names.add(s["name"])
        base = safe_name(f"{rank:02d} {s['name']} - {s['artists']}")
        cpath = os.path.join(cdir, base + ".jpg")
        os.replace(tmp, cpath)
        src_size, upscaled = normalize_cover(cpath, a.cover_size)
        cim = Image.open(cpath)
        up = f"  源{src_size[0]}x{src_size[1]} 已放大" if upscaled else ""
        print(f"{tag} {s['name']} - {s['artists']}  {fmt_dur(s['dur_ms'])}  "
              f"评论 {cmt}  封面 {cim.size[0]}x{cim.size[1]}{up}")
        if a.only == "cover":
            time.sleep(0.2)
            continue

        # --- 2) 30x50mm 播放界面 ---
        ppath = os.path.join(pdir, base + ".png")
        try:
            make_player(
                cpath, ppath, s["name"], s["artists"], int(s["dur_ms"] / 1000),
                width=a.width, played_ratio=a.played, playlist=a.playlist,
                likes=a.likes, comments=cmt, listeners=a.listeners,
                quality=a.quality, statusbar=False, ratio=a.ratio,
                vip=a.vip, follow=a.follow,
                video_tag=a.video_tag, fav_loop=True,
            )
        except Exception as e:
            print(f"      ✘ 播放界面合成失败，跳过: {type(e).__name__}: {e}")
            skipped.append(f"{s['name']}（合成失败）")
            continue
        with Image.open(ppath) as _f:
            im = _f.convert("RGB")
        save_retry(im, ppath, dpi=(a.dpi, a.dpi))
        save_retry(im, os.path.join(pdir, base + ".jpg"), quality=96,
                   dpi=(a.dpi, a.dpi), subsampling=0)
        mm = (im.size[0] / a.dpi * 25.4, im.size[1] / a.dpi * 25.4)
        print(f"      ✔ 播放界面 {im.size[0]}x{im.size[1]} → "
              f"{mm[0]:.1f}x{mm[1]:.1f}mm")
        made.append((ppath, f"{rank:02d} {s['name']}"))
        time.sleep(0.25)

    # --- 总览 ---
    if made:
        grid = contact_sheet(made, os.path.join(out, "总览.jpg"),
                             title=f"{ar['name']} · 热门前 {len(made)} 首 · 30×50mm"
                                   f" · {'QQ音乐' if src_used == 'qq' else '网易云'}")
        print(f"\n总览: {grid}")

    print(f"\n完成: 产出 {len(made)} 首")
    if skipped:
        print(f"跳过 {len(skipped)} 首: " + "; ".join(skipped))
    print(f"输出目录: {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
