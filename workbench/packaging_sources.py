"""Public cover lookup; only server-resolved candidates may be downloaded."""
import io
import time
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps
from fetch163 import API, get_json_ex

MAX_IMAGE = 16 * 1024 * 1024


def clean_image(raw):
    if not raw or len(raw) > MAX_IMAGE:
        raise ValueError("图片为空或超过 16 MB")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.width * im.height > 32_000_000 or min(im.size) < 100:
                raise ValueError("图片需至少 100×100，且不超过 3200 万像素")
            im.load()
            out = ImageOps.exif_transpose(im).convert("RGB")
            out.thumbnail((1600, 1600))
            return out
    except (OSError, Image.DecompressionBombError) as e:
        raise ValueError("无法读取这张图片，请使用 PNG、JPG 或 WebP") from e


def allowed_cover(url):
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return (u.scheme in ("https", "http") and not u.username and not u.password
            and u.port in (None, 80, 443)
            and (host.endswith(".music.126.net") or host == "y.gtimg.cn"))


def fetch_cover(url):
    if not allowed_cover(url):
        raise ValueError("封面来源地址不受支持")
    # Never follow a source redirect into arbitrary local or external services.
    referer = "https://y.qq.com/" if urlparse(url).hostname == "y.gtimg.cn" else "https://music.163.com/"
    with requests.get(url, headers={"Referer": referer},
                      stream=True, timeout=(8, 30), allow_redirects=False) as r:
        if r.status_code != 200:
            raise ValueError("封面下载失败，请换一张或上传本地封面")
        raw = bytearray()
        for chunk in r.iter_content(65536):
            raw.extend(chunk)
            if len(raw) > MAX_IMAGE:
                raise ValueError("封面超过 16 MB")
    return clean_image(raw)


def _get(path, params=None):
    data, err = get_json_ex(API + path, params, retry=1, timeout=12)
    if err or data.get("code", 200) != 200:
        raise ValueError("音乐来源暂时不可用，请稍后重试，或上传封面")
    return data


def _qq_albums(query):
    """Search QQ Music's public album index and return safe cover candidates."""
    response = requests.get("https://c.y.qq.com/soso/fcgi-bin/client_search_cp", params={
        "w": query, "format": "json", "n": 24, "p": 1, "t": 8, "new_json": 1,
        "aggr": 1, "cr": 1, "lossless": 0, "platform": "yqq.json", "needNewCode": 0,
    }, headers={"Referer": "https://y.qq.com/", "User-Agent": "Mozilla/5.0"}, timeout=(8, 18))
    response.raise_for_status()
    data = response.json()
    if data.get("code") != 0:
        raise ValueError("QQ 音乐暂时不可用")
    albums = ((data.get("data") or {}).get("album") or {}).get("list") or []
    rows, seen = [], set()
    for album in albums:
        mid = str(album.get("albumMID") or "")
        if not mid or mid in seen:
            continue
        seen.add(mid)
        pic = "https://y.gtimg.cn/music/photo_new/T002R800x800M000" + mid + ".jpg"
        rows.append({"albumId": "qq:" + mid, "album": str(album.get("albumName") or "未命名专辑")[:160],
                     "artist": str(album.get("singerName") or "")[:160], "coverSource": pic,
                     "source": "QQ 音乐", "sourceUrl": "https://y.qq.com/n/ryqq/albumDetail/" + mid,
                     "date": str(album.get("publicTime") or "")[:10]})
    return rows


def search_covers(query, kind="album", source="netease"):
    query = str(query).strip()[:120]
    if not query:
        raise ValueError("请输入歌手名或专辑名")
    if kind not in ("album", "artist"):
        raise ValueError("不支持的搜索类型")
    if source not in ("all", "netease", "qq"):
        raise ValueError("不支持的音乐来源")
    result = _get("/search/get/web", {"s": query, "type": 100 if kind == "artist" else 10,
                                        "limit": 24, "offset": 0}).get("result") or {} if source != "qq" else {}
    artists = result.get("artists") or []
    matched = None
    if kind == "artist" and artists:
        a = next((a for a in artists if a.get("name") == query), artists[0])
        matched = a.get("name", "")
        albums = _get("/artist/albums/" + str(int(a["id"])),
                      {"limit": 60, "offset": 0}).get("hotAlbums") or []
    else:
        albums = result.get("albums") or []
    items, seen = [], set()
    for a in albums:
        aid, url = a.get("id"), a.get("picUrl") or a.get("blurPicUrl") or ""
        if not aid or aid in seen or not allowed_cover(url):
            continue
        seen.add(aid)
        artist = (a.get("artist") or {}).get("name") or matched or ""
        date = a.get("publishTime") or 0
        items.append({"albumId": int(aid), "album": str(a.get("name") or "未命名专辑")[:160],
                      "artist": str(artist)[:160], "coverSource": url,
                      "source": "网易云音乐", "sourceUrl": f"https://music.163.com/#/album?id={int(aid)}",
                      "date": time.strftime("%Y", time.gmtime(date / 1000)) if date > 0 else ""})
    if source in ("all", "qq"):
        try:
            items.extend(_qq_albums(query))
        except (requests.RequestException, ValueError):
            if source == "qq" and not items:
                raise ValueError("QQ 音乐暂时不可用，请稍后重试或改用网易云音乐")
    return items, matched
