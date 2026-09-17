# -*- coding: utf-8 -*-
"""给「本地地址 + 国内音乐接口」关闭代理。

为什么需要这个
--------------
本机的 `HTTP_PROXY` / `HTTPS_PROXY` 指向一个本地代理端口（如
`http://127.0.0.1:60155`），而且每次启动端口都可能变化。urllib 会老老实实
按它走代理，于是：

1. **访问自家工作台**（`http://127.0.0.1:8765`）被送去代理 → 代理不认识
   这个地址 → 返回 **502 Bad Gateway** 或**空的 404**。
   前端拿不到 JSON，只能显示「返回不是合法 JSON / 没有反应」。
   浏览器不走这个环境变量，所以**「浏览器能用、脚本不能用」或反之**都可能出现，
   这就是「刚才还好好的」的来源。

2. **访问网易云 / QQ 音乐**也走代理 → 请求从代理出口出去（多为海外 IP）
   → 网易云更容易**限流**。这正是之前「同一个查询时好时坏、跑久了的进程
   查不到」的可疑来源之一。

对策
----
在发起任何请求**之前**设置 `NO_PROXY`，把这些地址列为直连：
本地回环地址 + 国内音乐相关域名。对外网的其它请求仍走代理（不受影响）。

用法：在 `fetch163.py` / `fetch_qq.py` / `server.py` 顶部
    import noproxy   # noqa: F401
放在 import urllib 之前或之后都可以，只要在**真正发请求之前**执行即可。
"""
import os

# 必须直连的目标：本地回环 + 国内音乐接口域名
_DIRECT = [
    "127.0.0.1",
    "localhost",
    "::1",
    "0.0.0.0",
    "music.163.com",
    "163.com",
    "126.net",
    "y.qq.com",
    "c.y.qq.com",
    "u.y.qq.com",
    "i.y.qq.com",
    "qq.com",
    "gtimg.cn",
    "y.gtimg.cn",
]


def install():
    """把直连清单并入 NO_PROXY（大小写都写，不同库读法不一致）。"""
    need = ",".join(_DIRECT)
    for key in ("NO_PROXY", "no_proxy"):
        cur = (os.environ.get(key) or "").strip()
        if not cur:
            os.environ[key] = need
            continue
        have = {x.strip().lower() for x in cur.split(",") if x.strip()}
        add = [d for d in _DIRECT if d.lower() not in have]
        if add:
            os.environ[key] = cur + "," + ",".join(add)
    return os.environ.get("NO_PROXY", "")


install()
