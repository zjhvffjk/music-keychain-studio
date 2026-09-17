# -*- coding: utf-8 -*-
"""跨平台中文字体探测。

出图需要一款中文字体（粗体、常规各一）。本模块按以下顺序查找：

1. **环境变量显式指定**（最优先，任何平台都适用）
   - ``MINUET_FONT_BOLD`` —— 粗体字体文件路径
   - ``MINUET_FONT_REG``  —— 常规字体文件路径
2. 当前平台的常见字体路径候选
3. 扫描系统字体目录，按关键词匹配（微软雅黑 / 苹方 / 思源黑体 / 文泉驿…）

定位不到时抛出带解决步骤的 :class:`RuntimeError`，
而不是让上层画出一堆「豆腐块」（□□□）却不知道为什么。
"""
from __future__ import annotations

import glob
import os
import sys

# 关键词按优先级排列（越靠前越优先）。扫描字体目录时用文件名匹配。
_BOLD_KEYWORDS = [
    "msyhbd",              # 微软雅黑 Bold (Windows)
    "pingfang",            # 苹方 (macOS)
    "sourcehansanssc-bold", "sourcehansanssc_bold",
    "notosanscjk-bold", "notosanscjksc-bold",
    "sourcehansans-bold",
    "msyh", "simhei",      # 退而求其次
    "wqy-zenhei", "wqy-microhei",
    "simsun",
]
_REG_KEYWORDS = [
    "msyh",
    "pingfang",
    "sourcehansanssc-regular", "sourcehansanssc_regular",
    "notosanscjk-regular", "notosanscjksc-regular",
    "sourcehansans-regular",
    "simhei",
    "wqy-zenhei", "wqy-microhei",
    "simsun",
]

_cache: dict[str, str] = {}


def _search_dirs():
    """产出当前平台值得扫描的字体目录。"""
    if sys.platform.startswith("win"):
        win = os.environ.get("WINDIR", r"C:\Windows")
        yield os.path.join(win, "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            yield os.path.join(local, "Microsoft", "Windows", "Fonts")
    elif sys.platform == "darwin":
        yield "/System/Library/Fonts"
        yield "/Library/Fonts"
        yield os.path.expanduser("~/Library/Fonts")
    else:
        yield "/usr/share/fonts"
        yield "/usr/local/share/fonts"
        yield os.path.expanduser("~/.fonts")
        yield os.path.expanduser("~/.local/share/fonts")


def find(bold: bool = True) -> str:
    """返回一个可用的中文字体文件路径。

    :param bold: True 取粗体，False 取常规体
    :raises RuntimeError: 找不到任何可用字体时
    """
    key = "bold" if bold else "reg"
    if key in _cache:
        return _cache[key]

    env_name = "MINUET_FONT_BOLD" if bold else "MINUET_FONT_REG"
    env_val = os.environ.get(env_name)
    if env_val:
        if os.path.exists(env_val):
            _cache[key] = env_val
            return env_val
        raise RuntimeError(
            f"环境变量 {env_name} 指向的字体文件不存在：{env_val}"
        )

    keywords = _BOLD_KEYWORDS if bold else _REG_KEYWORDS
    hits: list[tuple[int, str]] = []
    for d in _search_dirs():
        if not os.path.isdir(d):
            continue
        for ext in ("*.ttc", "*.ttf", "*.otf", "*.otc"):
            for path in glob.glob(os.path.join(d, "**", ext), recursive=True):
                name = os.path.basename(path).lower()
                for rank, kw in enumerate(keywords):
                    if kw in name:
                        hits.append((rank, path))
                        break

    if hits:
        # 关键词优先级优先；同优先级取路径较短的（通常是正体，不是变体）
        hits.sort(key=lambda t: (t[0], len(t[1])))
        _cache[key] = hits[0][1]
        return _cache[key]

    raise RuntimeError(
        "找不到可用的中文字体，出图会因为缺字变成方块。请任选一种方式解决：\n"
        "  1) 指定字体文件（推荐）\n"
        "     Windows:      set MINUET_FONT_BOLD=C:\\Windows\\Fonts\\msyhbd.ttc\n"
        "                   set MINUET_FONT_REG=C:\\Windows\\Fonts\\msyh.ttc\n"
        "     macOS/Linux:  export MINUET_FONT_BOLD=/path/to/font.ttc\n"
        "                   export MINUET_FONT_REG=/path/to/font.ttc\n"
        "  2) 安装中文字体后重试\n"
        "     Debian/Ubuntu:  sudo apt install fonts-noto-cjk\n"
        "     CentOS/RHEL:    sudo yum install wqy-zenhei-fonts\n"
        "     macOS 自带苹方，通常无需安装"
    )


def find_bold() -> str:
    return find(bold=True)


def find_regular() -> str:
    return find(bold=False)


if __name__ == "__main__":
    print("粗体:", find(bold=True))
    print("常规:", find(bold=False))
