#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
QQ音乐抓取工具  (fetch_qq.py)

**为什么需要第二个数据源**
  周杰伦 / 五月天等歌手的版权在腾讯，**网易云完全没有**。
  在网易云搜「晴天 周杰伦」返回的全是翻唱（Lucky小爱、RyaVocal…），
  artist 页面的 hotSongs 也只剩「他给别人写的歌 + Live 合唱」，
  同一首歌还会被不同版本反复刷榜（刀马旦刷 7 次）。

  所以：**要谁的歌，先看版权在哪个平台。**

接口（均为公开 web 接口，无需登录）
  搜索歌曲  c.y.qq.com/soso/fcgi-bin/client_search_cp
  歌手歌曲  u.y.qq.com/cgi-bin/musicu.fcg
            module=music.web_singer_info_svr / get_singer_detail_info
  封面      y.gtimg.cn/music/photo_new/T002R{size}M000{albummid}.jpg
            ⚠️ 最大只有 800x800（1000x1000 返回 404），且必须用 y.gtimg.cn 域名
  评论数    c.y.qq.com/base/fcgi-bin/fcg_global_comment_h5.fcg  (cmd=8 只取数量)

用法:
  python fetch_qq.py singer "周杰伦"
  python fetch_qq.py top "周杰伦" --n 10
"""
import noproxy  # noqa: F401  必须在发请求之前：本地地址 + 国内音乐接口直连
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Referer": "https://y.qq.com/",
}
MUSICU = "https://u.y.qq.com/cgi-bin/musicu.fcg"
SEARCH = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
COMMENT = "https://c.y.qq.com/base/fcgi-bin/fcg_global_comment_h5.fcg"
COVER = "https://y.gtimg.cn/music/photo_new/T002R{size}M000{amid}.jpg"

MAX_COVER = 800          # 实测上限，别改 1000（404）


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()


def _json(url):
    return json.loads(_get(url).decode("utf-8", "replace"))


def musicu(payload):
    data = urllib.parse.quote(json.dumps(payload, ensure_ascii=False))
    return _json(f"{MUSICU}?format=json&data={data}")


def search_song(kw, n=10):
    q = urllib.parse.quote(kw)
    j = _json(f"{SEARCH}?p=1&n={n}&w={q}&format=json"
              "&inCharset=utf8&outCharset=utf-8&platform=yqq")
    return (((j.get("data") or {}).get("song") or {}).get("list")) or []


def search_singer_mid(name):
    """搜歌手名 → 拿 singer_mid。

    QQ音乐没有好用的「歌手搜索」接口（search_type=1 返回空），
    所以退一步：搜单曲，从结果的 singer 数组里挑与查询名一致的 mid。
    同名歌手用出现频次兜底。
    """
    songs = search_song(name, 15)
    votes = Counter()
    for s in songs:
        for sg in (s.get("singer") or []):
            n = (sg.get("name") or "").strip()
            mid = sg.get("mid")
            if not mid:
                continue
            if n == name:
                votes[mid] += 10            # 完全同名，权重最高
            elif name and (name in n or n in name):
                votes[mid] += 2
    if not votes:
        return None, ""
    mid = votes.most_common(1)[0][0]
    # 回查名字
    for s in songs:
        for sg in (s.get("singer") or []):
            if sg.get("mid") == mid:
                return mid, sg.get("name") or name
    return mid, name


def hot_songs_q(singer_mid, n=10, sort=5):
    """歌手热门歌曲。sort=5 按热度，sort=1 按时间。"""
    j = musicu({"comm": {"ct": 24, "cv": 0},
                "req": {"module": "music.web_singer_info_svr",
                        "method": "get_singer_detail_info",
                        "param": {"sort": sort, "singermid": singer_mid,
                                  "sin": 0, "num": min(max(n, 10), 80)}}})
    d = j.get("req", {}).get("data", {})
    lst = d.get("songlist") or d.get("list") or []
    out = []
    for it in lst:
        m = it.get("track_info") or it.get("musicData") or it
        alb = m.get("album") or {}
        out.append({
            "id": m.get("id") or m.get("songid"),
            "mid": m.get("mid") or m.get("songmid"),
            "name": m.get("name") or m.get("songname") or "未知",
            "artists": "/".join(x.get("name", "?") for x in (m.get("singer") or [])),
            "album": alb.get("name") or m.get("albumname") or "",
            "pic": alb.get("mid") or m.get("albummid") or "",   # = albummid
            "dur_ms": (m.get("interval") or 0) * 1000,
        })
    return out[:n]


def cover_url_q(album_mid, size=MAX_COVER):
    if not album_mid:
        return ""
    size = min(size, MAX_COVER)
    return COVER.format(size=f"{size}x{size}", amid=album_mid)


def comment_total_q(song_id):
    """QQ音乐评论总数。

    ⚠️ 必须带 `biztype=1`，否则接口照样 code=0 但 commenttotal 恒为 0，
       看起来像「这首歌没评论」，极难发现。实测《晴天》= 230665 条。
    拿不到返回 0（不阻塞出图）。
    """
    if not song_id:
        return 0
    try:
        j = _json(f"{COMMENT}?g_tk=5381&biztype=1&topid={song_id}&type=1&cmd=8"
                  "&pagenum=0&pagesize=1&format=json"
                  "&inCharset=utf8&outCharset=utf-8")
        c = j.get("comment") or {}
        return int(c.get("commenttotal") or 0)
    except Exception:
        return 0


def download(url, path, tries=4):
    if not url:
        return False
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    for i in range(tries):
        try:
            data = _get(url, timeout=30)
            if len(data) < 1500:            # 占位/错误页
                return False
            with open(path, "wb") as f:
                f.write(data)
            return True
        except Exception:
            time.sleep(0.6 * (i + 1))
    return False


def singer_top(name, n=10):
    mid, real = search_singer_mid(name)
    if not mid:
        return None, []
    return {"id": mid, "name": real}, hot_songs_q(mid, n)


def main():
    ap = argparse.ArgumentParser(description="QQ音乐抓取")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("singer", help="查歌手")
    p1.add_argument("name")

    p2 = sub.add_parser("top", help="歌手热门前N首")
    p2.add_argument("name")
    p2.add_argument("--n", type=int, default=10)

    p3 = sub.add_parser("cover", help="下载某专辑封面")
    p3.add_argument("albummid")
    p3.add_argument("--out", default="cover.jpg")
    p3.add_argument("--size", type=int, default=MAX_COVER)

    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if a.cmd == "singer":
        mid, real = search_singer_mid(a.name)
        print(f"singer_mid={mid}  name={real}")
    elif a.cmd == "top":
        ar, songs = singer_top(a.name, a.n)
        if not ar:
            print("✘ 没找到该歌手")
            return
        print(f"歌手: {ar['name']}  mid={ar['id']}")
        for i, s in enumerate(songs, 1):
            print(f"{i:02d}. {s['name']} [{s['artists']}]《{s['album']}》 "
                  f"albummid={s['pic']}  评论={comment_total_q(s['id'])}")
    elif a.cmd == "cover":
        u = cover_url_q(a.albummid, a.size)
        ok = download(u, a.out)
        print(("✔ " if ok else "✘ ") + u)


if __name__ == "__main__":
    main()
