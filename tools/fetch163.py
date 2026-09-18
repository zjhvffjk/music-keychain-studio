#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
网易云音乐封面抓取工具  (fetch163.py)

用法:
  python fetch163.py search   <关键词> [--type song|album|artist]   # 搜索看看有什么
  python fetch163.py song     <歌名>   [--pick N]                    # 下这首歌的封面
  python fetch163.py album    <专辑名> [--pick N]                    # 下这张专辑的封面
  python fetch163.py artist   <歌手名> [--max N]                     # 批量下该歌手全部专辑封面
  python fetch163.py topsongs <歌手名> [--max N]                     # 批量下该歌手热门单曲封面

公共参数:
  --out  <目录>     保存目录 (默认 ./assets)
  --size <像素>     封面尺寸, 网易云单边上限 1000 (默认 1000)

注意: 网易云封面走 CDN 原图, 必须带 Referer, 否则可能被拒。
"""
import noproxy  # noqa: F401  必须在发请求之前：本地地址 + 国内音乐接口直连
import argparse
import json
import os
import re
import sys
import time

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

S = requests.Session()
S.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Referer": "https://music.163.com/",
    "Cookie": "appver=2.0.2;",
})

API = "https://music.163.com/api"
TYPE_MAP = {"song": 1, "album": 10, "artist": 100}


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n\t]', "_", str(s)).strip()[:120]


def get_json_ex(url, params=None, retry=3, timeout=12):
    """带重试的 GET。返回 (data, err)。

    ⚠️ err 存在的意义：老版本 `get_json` 失败时返回 {}，
    调用方**无法区分**「接口挂了」和「确实没有数据」——
    曾经因此把「网易云被限流」误判成「该歌手版权不在网易云」，
    静默切到 QQ 源，还谎报原因。所以要显式把失败传出来。

    err=None  → 请求成功（data 可能是空的，那是真的没数据）
    err=str   → 请求失败（网络/超时/非 200/非 JSON）
    """
    err = "请求失败"
    for i in range(max(1, retry)):
        try:
            r = S.get(url, params=params, timeout=timeout)
            if r.status_code == 200 and r.text.strip():
                try:
                    return r.json(), None
                except ValueError:
                    err = "响应不是合法 JSON"
            else:
                err = f"HTTP {r.status_code}" + ("" if r.text.strip() else "（空响应）")
        except Exception as e:
            err = type(e).__name__
        if i < retry - 1:
            time.sleep(0.4 * (i + 1))
    print(f"  [warn] 请求失败: {err}  {url}")
    return {}, err


def get_json(url, params=None, retry=3, timeout=12):
    """带重试的 GET, 返回 json dict, 失败返回 {}（兼容旧调用方）"""
    return get_json_ex(url, params=params, retry=retry, timeout=timeout)[0]


def search(kw: str, typ: str = "song", limit: int = 20):
    d = get_json(f"{API}/search/get/web",
                 {"s": kw, "type": TYPE_MAP.get(typ, 1), "limit": limit,
                  "offset": 0, "total": "true"})
    return d.get("result", {}) or {}


def cover_url(pic_url: str, size: int) -> str:
    if not pic_url:
        return ""
    base = pic_url.split("?")[0]
    return f"{base}?param={size}y{size}" if size else pic_url


def download(url: str, path: str) -> int:
    """下载封面, 返回字节数"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for i in range(3):
        try:
            r = S.get(url, timeout=40)
            if r.status_code == 200 and len(r.content) > 2000:
                with open(path, "wb") as f:
                    f.write(r.content)
                return len(r.content)
        except Exception:
            pass
        time.sleep(0.8 * (i + 1))
    return 0


# ---------- 各子命令 ----------

def cmd_search(a):
    res = search(a.keyword, a.type, 30)
    if a.type == "song":
        songs = res.get("songs", [])
        print(f"找到 {len(songs)} 首:")
        for i, s in enumerate(songs):
            arts = "/".join(x["name"] for x in s.get("artists", []))
            alb = s.get("album", {})
            print(f"  [{i:2d}] {s['name']} - {arts}  | 专辑《{alb.get('name','?')}》 id={s['id']}")
    elif a.type == "album":
        albs = res.get("albums", [])
        print(f"找到 {len(albs)} 张专辑:")
        for i, x in enumerate(albs):
            arts = "/".join(y["name"] for y in x.get("artists", []))
            print(f"  [{i:2d}] 《{x['name']}》 - {arts}  id={x['id']}")
    else:
        ars = res.get("artists", [])
        print(f"找到 {len(ars)} 位歌手:")
        for i, x in enumerate(ars):
            print(f"  [{i:2d}] {x['name']}  id={x['id']}  专辑数={x.get('albumSize','?')}")


def resolve_picurl(song: dict) -> str:
    """拿到歌曲封面的 picUrl。
    注意: 搜索接口只返回 album.picId, 不含 picUrl, 必须再查一次 song/detail。"""
    pic = (song.get("album") or {}).get("picUrl") or ""
    if pic:
        return pic
    sid = song.get("id")
    if not sid:
        return ""
    d = get_json(f"{API}/song/detail/", {"id": sid, "ids": json.dumps([sid])})
    songs = d.get("songs", [])
    if songs:
        return (songs[0].get("album") or {}).get("picUrl") or ""
    return ""


def fetch_song_cover(song: dict, out: str, size: int) -> str:
    pic = resolve_picurl(song)
    if not pic:
        return ""
    arts = "/".join(x["name"] for x in song.get("artists", []))
    fn = safe_name(f"{song['name']} - {arts}.jpg")
    p = os.path.join(out, fn)
    n = download(cover_url(pic, size), p)
    return f"{p}  ({n/1024:.0f} KB)" if n else ""


def cmd_song(a):
    res = search(a.keyword, "song", 20)
    songs = res.get("songs", [])
    if not songs:
        print("没搜到");  return
    tgt = [songs[a.pick]] if a.pick < len(songs) else [songs[0]]
    for s in tgt:
        arts = "/".join(x["name"] for x in s.get("artists", []))
        print(f"* {s['name']} - {arts}")
        r = fetch_song_cover(s, a.out, a.size)
        print("  ->", r or "封面下载失败")


def cmd_album(a):
    res = search(a.keyword, "album", 20)
    albs = res.get("albums", [])
    if not albs:
        print("没搜到");  return
    for x in ([albs[a.pick]] if a.pick < len(albs) else [albs[0]]):
        d = get_json(f"{API}/album/{x['id']}")
        alb = d.get("album", {}) or {}
        pic = alb.get("picUrl") or x.get("picUrl", "")
        arts = "/".join(y["name"] for y in alb.get("artists", x.get("artists", [])))
        name = alb.get("name", x["name"])
        print(f"* 《{name}》 - {arts}")
        if not pic:
            print("  无封面");  continue
        p = os.path.join(a.out, safe_name(f"{name} - {arts}.jpg"))
        n = download(cover_url(pic, a.size), p)
        print("  ->", f"{p}  ({n/1024:.0f} KB)" if n else "下载失败")


def artist_albums(artist_id: int, limit: int = 200):
    """拉取歌手专辑列表"""
    out, offset = [], 0
    while offset < limit:
        d = get_json(f"{API}/artist/albums/{artist_id}",
                     {"offset": offset, "limit": 50})
        batch = d.get("hotAlbums", []) or []
        if not batch:
            break
        out.extend(batch)
        if not d.get("more"):
            break
        offset += 50
        time.sleep(0.35)
    return out[:limit]


def album_detail(album_id):
    """专辑详情（含曲目列表）。

    ⚠️ 必须走 `/api/v1/album/{id}` —— 少了 `v1` 的 `/api/album/{id}` 现在会
    返回 code -462（要求绑定手机）。实测 v1 免登录，范特西 10 首完整返回。
    """
    d = get_json(f"{API}/v1/album/{album_id}")
    alb = d.get("album") or {}
    songs = d.get("songs") or alb.get("songs") or []
    return alb, songs


def _album_id_from_artist(artist: str, album_name: str):
    """从歌手专辑列表里找同名专辑 id。

    比专辑搜索可靠得多：实测搜「Jay 周杰伦」的 album 候选前 12 条**全是翻唱集**，
    真首专《Jay》根本排不进来（英文短名专辑的搜索排名劣势），
    但它一定出现在 artist/albums 列表里。
    """
    try:
        res = search(artist, "artist", 5)
        arts = res.get("artists") or []
        if not arts:
            return None
        # 优先名字完全相等的歌手（避免"周杰伦"搜到模仿者）
        hit = [a for a in arts if (a.get("name") or "") == artist]
        aid = (hit[0] if hit else arts[0]).get("id")
        for a in artist_albums(aid, 200):
            if (a.get("name") or "") == album_name:
                return a.get("id")
    except Exception:
        pass
    return None


def album_tracks(album_name: str, artist: str = "", album_id=None, limit: int = 60):
    """取某专辑的曲目列表。

    定位顺序（可靠性从高到低）：
      A. 已知 album_id（批量模式走这条，albums.json 里带 id）→ 直接查详情
      B. 歌手专辑列表里找同名专辑 id（最可靠的兜底）
      C. 专辑搜索候选 + 详情复核
      D. search(song) 反查（覆盖可能不全）
    返回 (曲目名列表, 专辑名)；拿不到返回 ([], "")。

    ⚠️ 单张模式**必须**复核候选的 name/artists：只按搜索结果盲取第一个会拿错
    ——实测专辑名 "Jay" 命中山寨翻唱集，返回「菊花台（Cover 周杰伦）」这种脏数据。
    """
    def _by_id(aid, fallback_name):
        try:
            alb, songs = album_detail(aid)
            names = [s.get("name") for s in songs if s.get("name")]
            if names:
                return names[:limit], (alb.get("name") or fallback_name)
        except Exception:
            pass
        return None

    # A. 已知 id
    if album_id is not None:
        got = _by_id(album_id, album_name)
        if got:
            return got

    # B. 歌手专辑列表反查 id
    if album_name and artist:
        aid = _album_id_from_artist(artist, album_name)
        if aid is not None:
            got = _by_id(aid, album_name)
            if got:
                return got

    # C. 专辑搜索候选 + 详情复核
    if album_name:
        try:
            res = search(f"{album_name} {artist}".strip(), "album", 20)
            fallback = None
            for cand in (res.get("albums") or [])[:8]:
                try:
                    alb, songs = album_detail(cand.get("id"))
                except Exception:
                    continue
                names = [s.get("name") for s in songs if s.get("name")]
                if not names:
                    continue
                nm = alb.get("name") or cand.get("name") or album_name
                arts = " ".join(a.get("name", "") for a in (alb.get("artists") or []))
                name_ok = (nm == album_name)
                art_ok = (not artist) or (artist in arts)
                if name_ok and art_ok:
                    return names[:limit], nm
                if fallback is None and name_ok:
                    fallback = (names[:limit], nm)
            if fallback:
                return fallback
        except Exception:
            pass

    # D. 最后兜底：search(song) 反查
    return _album_tracks_by_search(album_name, artist, album_id, limit)


def _album_tracks_by_search(album_name: str, artist: str = "", album_id=None,
                            limit: int = 60):
    """兜底：search(song) 的每条结果都带 album.id/album.name，按 id 归组还原专辑。

    实测搜索结果的顺序**就是专辑曲序**（范特西 10 首顺序全对），故不额外排序。
    """
    kw = f"{album_name} {artist}".strip()
    groups = {}          # album_id -> {"name":..., "songs":[...]}
    offset = 0
    while offset < 120:
        try:
            d = get_json(f"{API}/search/get/web",
                         {"s": kw, "type": 1, "limit": 30, "offset": offset,
                          "total": "true"})
        except Exception:
            break
        songs = (d.get("result") or {}).get("songs") or []
        if not songs:
            break
        for s in songs:
            alb = s.get("album") or {}
            aid = alb.get("id")
            if aid is None:
                continue
            g = groups.setdefault(aid, {"name": alb.get("name") or "", "songs": []})
            nm = s.get("name")
            if nm and nm not in g["songs"]:
                g["songs"].append(nm)
        if len(songs) < 30:
            break
        offset += 30
        time.sleep(0.3)

    if not groups:
        return [], ""

    # 优先级：显式 album_id > 专辑名完全相等 > 名字包含 > 曲目最多
    pick = None
    if album_id is not None:
        for aid, g in groups.items():
            if str(aid) == str(album_id):
                pick = g
                break
    if pick is None:
        for aid, g in groups.items():
            if g["name"] == album_name:
                pick = g
                break
    if pick is None:
        for aid, g in groups.items():
            if album_name and album_name in g["name"]:
                pick = g
                break
    if pick is None:
        pick = max(groups.values(), key=lambda g: len(g["songs"]))
    return pick["songs"][:limit], pick["name"]


def cmd_artist(a):
    res = search(a.keyword, "artist", 20)
    ars = res.get("artists", [])
    if not ars:
        print("没搜到");  return
    ar = ars[0]
    print(f"歌手: {ar['name']} (id={ar['id']})")
    albums = artist_albums(ar["id"], a.max)
    print(f"共 {len(albums)} 张专辑, 开始下载...\n")
    ok = 0
    seen = set()
    for i, x in enumerate(albums, 1):
        name = x.get("name", "?")
        if name in seen:
            continue
        seen.add(name)
        pic = x.get("picUrl", "")
        if not pic:
            continue
        fn = safe_name(f"{name} - {ar['name']}.jpg")
        p = os.path.join(a.out, fn)
        if os.path.exists(p):
            print(f"  [{i:3d}] 已存在, 跳过: {name}")
            ok += 1
            continue
        n = download(cover_url(pic, a.size), p)
        print(f"  [{i:3d}] {'✔' if n else '✘'} {name}  ({n/1024:.0f} KB)" if n else f"  [{i:3d}] ✘ {name}")
        if n:
            ok += 1
        time.sleep(0.25)
    print(f"\n完成: {ok}/{len(albums)} 张 -> {os.path.abspath(a.out)}")


def cmd_topsongs(a):
    """下载歌手的热门歌曲封面 (每首单曲封面可能各不相同)"""
    res = search(a.keyword, "artist", 20)
    ars = res.get("artists", [])
    if not ars:
        print("没搜到该歌手");  return
    ar = ars[0]
    print(f"歌手: {ar['name']} (id={ar['id']})")
    d = get_json(f"{API}/v1/artist/{ar['id']}")
    hot = d.get("hotSongs", []) or []
    if not hot:
        d2 = get_json(f"{API}/artist/top/song", {"id": ar["id"]})
        hot = d2.get("songs", []) or []
    if not hot:
        print("拿不到热门歌曲列表");  return
    hot = hot[:a.max]
    print(f"热门歌曲 {len(hot)} 首, 开始下载...\n")
    ok = 0
    for i, s in enumerate(hot, 1):
        arts = "/".join(x["name"] for x in s.get("artists", []))
        fn = safe_name(f"{s['name']} - {arts}.jpg")
        p = os.path.join(a.out, fn)
        if os.path.exists(p):
            print(f"  [{i:3d}] 已存在, 跳过: {s['name']}")
            ok += 1
            continue
        pic = resolve_picurl(s)
        if not pic:
            print(f"  [{i:3d}] ✘ {s['name']} (无封面)")
            continue
        n = download(cover_url(pic, a.size), p)
        print(f"  [{i:3d}] {'✔' if n else '✘'} {s['name']}  ({n/1024:.0f} KB)" if n
              else f"  [{i:3d}] ✘ {s['name']}")
        if n:
            ok += 1
        time.sleep(0.25)
    print(f"\n完成: {ok}/{len(hot)} 张 -> {os.path.abspath(a.out)}")


def main():
    p = argparse.ArgumentParser(description="网易云音乐封面抓取工具")
    p.add_argument("action", choices=["search", "song", "album", "artist", "topsongs"])
    p.add_argument("keyword")
    p.add_argument("--type", default="song", choices=["song", "album", "artist"])
    p.add_argument("--pick", type=int, default=0, help="搜索结果第几条(从0开始)")
    p.add_argument("--max", type=int, default=200, help="artist 模式最多下几张")
    p.add_argument("--out", default="./assets")
    p.add_argument("--size", type=int, default=2000,
                   help="封面像素。CDN 只降采样不超分，实测母版 1040~2000；"
                        "给 2000 才能拿到该专辑的最大母版")
    a = p.parse_args()
    a.out = os.path.abspath(a.out)
    {"search": cmd_search, "song": cmd_song, "album": cmd_album,
     "artist": cmd_artist, "topsongs": cmd_topsongs}[a.action](a)


if __name__ == "__main__":
    main()
