# -*- coding: utf-8 -*-
"""fetch_parts.py —— 为一张专辑搜「真实部件图」（封底/内页/碟面/侧标…）。

背景
----
网易云只有封面一张图；Discogs 中文 CD 覆盖差（台版《范特西》仅 1 张封面），
且图片被签名锁死在 600px。而实体部件图（封底/内页/碟面/侧标）散落在
淘宝商品图 / 微博 / 贴吧 / 博客里 —— 即「必应图片搜索」最能命中的内容。

用法
----
    python fetch_parts.py --artist 周杰伦 --album 范特西 --out ../outputs/部件搜索/范特西

产出
----
    candidates/    候选原图（p01.jpg, p02.jpg ...）
    候选网格.jpg    全部候选拼成带编号的网格（给视觉模型 / 人看图挑选用）
    manifest.json  编号 -> {query, url, page, w, h}
    （挑选归位由 make_minicd.py --parts 编号清单 或人工完成）

设计要点
--------
- 每个「部件」一组中文关键词，命中后带部件先验排序（同名候选优先排给对应部件）。
- 下载带 Referer（来源页）防盗链；失败/太小(<280px)/重复(md5) 丢弃。
- 网格图每格画大编号，视觉模型看一眼就能说「back 用 p07」。
"""
import argparse
import concurrent.futures as cf
import hashlib
import html
import io
import json
import os
import re
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")

try:
    import fonts

    def _font(size, bold=False):
        return __import__("PIL.ImageFont", fromlist=["ImageFont"]).truetype(
            fonts.find_bold() if bold else fonts.find_regular(), size)
except Exception:  # pragma: no cover
    from PIL import ImageFont

    def _font(size, bold=False):
        return ImageFont.load_default()

from PIL import Image, ImageDraw

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

# 部件 -> 中文搜索词组（顺序即优先级）。{a}=歌手 {b}=专辑
PART_QUERIES = {
    "back":  ["{a} {b} 专辑封底", "{a} {b} CD 背面 封底", "{a} {b} 专辑 背面 曲目"],
    "inner": ["{a} {b} 专辑内页", "{a} {b} CD 内页 写真", "{a} {b} 专辑 写真集 内页"],
    "disc":  ["{a} {b} CD 碟面", "{a} {b} 专辑 光盘 盘面", "{a} {b} CD 光碟"],
    "tray":  ["{a} {b} CD 内盘", "{a} {b} 专辑 托盘 内盘"],
    "spine": ["{a} {b} 专辑 侧标", "{a} {b} CD 侧标 obi"],
}
MIN_SIDE = 280          # 任一边小于此值丢弃
PER_QUERY = 24          # 每个搜索词最多取多少候选
DL_WORKERS = 6
DL_TIMEOUT = 15


def so360_candidates(q, pages=2, per=30):
    """360 图片 JSON 接口，返回 [(orig_url, page_url)]。

    为什么不用必应：cn.bing.com 会把「周杰伦+任意细分词」聚合成
    同一个实体图集（实测「范特西封底」和「八度空间碟面」返回完全相同
    的周姓图腾结果页），细分词被吞，不可用。
    360 接口无需 cookie、免登录，一页 30 张，字段 img/width/height/link。
    """
    out = []
    for pg in range(pages):
        got = []
        for attempt in range(3):
            try:
                r = requests.get("https://image.so.com/j",
                                 params={"q": q, "src": "srp", "pn": per, "sn": pg * per},
                                 headers=UA, timeout=20)
                d = r.json()
                lst = d.get("list") or []
            except Exception:
                lst = []
            if lst:
                got = lst
                break
            # 360 对连续请求限流：实测第 3 个 query 起全 0，必须退避
            time.sleep(2.5 * (attempt + 1))
        if not got:
            break
        for x in got:
            u = x.get("img")
            if u:
                out.append((u, x.get("link") or ""))
        if len(got) < per:
            break
        time.sleep(0.5)
    return out


def download(url, page, path):
    """下载一张候选图；失败/非图/太小返回 None，成功返回 (w,h)。"""
    try:
        h = dict(UA)
        if page:
            h["Referer"] = page
        r = requests.get(url, headers=h, timeout=DL_TIMEOUT, stream=True)
        if r.status_code != 200:
            return None
        ct = r.headers.get("Content-Type", "")
        if not ct.startswith("image"):
            return None
        data = r.content
        if len(data) < 8_000:
            return None
        im = Image.open(io.BytesIO(data))
        im.load()
        if im.width < MIN_SIDE or im.height < MIN_SIDE:
            return None
        im.convert("RGB").save(path, quality=92)
        return im.size
    except Exception:
        return None


def grid(paths, out_path, cell=340, cols=6):
    """候选网格：每格画大编号，供看图挑选。"""
    rows = (len(paths) + cols - 1) // cols
    W, H = cols * cell + (cols + 1) * 10, rows * cell + 56
    canvas = Image.new("RGB", (W, H), (24, 24, 28))
    d = ImageDraw.Draw(canvas)
    d.text((12, 12), f"候选图 {len(paths)} 张 —— 引用编号 p01…p{len(paths):02d}",
           font=_font(30, True), fill=(240, 240, 240))
    for i, p in enumerate(paths, 1):
        x = 10 + (i - 1) % cols * (cell + 10)
        y = 56 + (i - 1) // cols * (cell + 10)
        try:
            im = Image.open(p).convert("RGB")
            im.thumbnail((cell, cell - 44))
            canvas.paste(im, (x + (cell - im.width) // 2, y + (cell - 44 - im.height) // 2))
        except Exception:
            pass
        tag = f"p{i:02d}"
        d.rectangle([x + 4, y + cell - 40, x + 74, y + cell - 6], fill=(220, 60, 60))
        d.text((x + 12, y + cell - 36), tag, font=_font(26, True), fill=(255, 255, 255))
    canvas.save(out_path, quality=90)
    return canvas.size


def main():
    ap = argparse.ArgumentParser(description="为一张专辑搜真实部件图候选")
    ap.add_argument("--artist", required=True)
    ap.add_argument("--album", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--parts", default="back,inner,disc,tray,spine",
                    help="要搜哪些部件（逗号分隔），默认全部")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    cand_dir = os.path.join(args.out, "candidates")
    os.makedirs(cand_dir, exist_ok=True)

    # 1. 搜
    pool = {}          # url -> {"page":…, "parts":set(), "rank":int}
    for part in [p.strip() for p in args.parts.split(",") if p.strip()]:
        qs = PART_QUERIES.get(part, [])
        for qi, q in enumerate(qs):
            qq = q.format(a=args.artist, b=args.album)
            got = so360_candidates(qq)
            print(f"[search] {part:<5} 「{qq}」 候选 {len(got)}", flush=True)
            if not got:
                time.sleep(3)   # 连续限流时多歇一会再进下一个 query
            for rank, (u, page) in enumerate(got):
                e = pool.setdefault(u, {"page": page, "parts": set(), "rank": 999})
                e["parts"].add(part)
                e["rank"] = min(e["rank"], qi * 100 + rank)
            time.sleep(1.5)          # 对 360 客气点（实测连续快查会限流）

    urls = sorted(pool.items(), key=lambda kv: kv[1]["rank"])
    print(f"\n合并去重后候选 {len(urls)} 个 URL，开始下载…")

    # 2. 下载
    results = []       # (path, url, page, w, h)
    md5s = set()

    def job(item):
        i, (u, meta) = item
        p = os.path.join(cand_dir, f"p{i:02d}.jpg")
        sz = download(u, meta["page"], p)
        return i, u, meta, p, sz

    with cf.ThreadPoolExecutor(DL_WORKERS) as ex:
        for i, u, meta, p, sz in ex.map(job, enumerate(urls, 1)):
            if sz is None:
                if os.path.exists(p):
                    os.remove(p)
                continue
            hsh = hashlib.md5(open(p, "rb").read()).hexdigest()
            if hsh in md5s:
                os.remove(p)
                continue
            md5s.add(hsh)
            results.append({"file": f"p{i:02d}.jpg", "url": u, "page": meta["page"],
                            "w": sz[0], "h": sz[1],
                            "query_parts": sorted(meta["parts"])})
            print(f"  [ok] p{i:02d}.jpg  {sz[0]}x{sz[1]}  parts={sorted(meta['parts'])}"
                  f"  {u[:70]}")

    # 3. 网格 + manifest
    paths = [os.path.join(cand_dir, r["file"]) for r in results]
    if paths:
        gs = grid(paths, os.path.join(args.out, "候选网格.jpg"))
        print(f"\n候选网格 -> {os.path.join(args.out, '候选网格.jpg')} {gs}")
    mf = {"artist": args.artist, "album": args.album,
          "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
          "count": len(results), "items": results}
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(mf, f, ensure_ascii=False, indent=1)
    print(f"manifest -> {args.out}/manifest.json   共 {len(results)} 张有效候选")


if __name__ == "__main__":
    main()
