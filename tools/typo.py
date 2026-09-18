# -*- coding: utf-8 -*-
"""排版层 —— 按「角色」解析字体 + 字距排版。

出图好看与否，八成在排字。之前的部件全用雅黑粗体画一切，
结果就是「PPT 截图感」；真正像唱片设计的做法是**同一页里出现三四种角色**
（衬线大标题 / 无衬线信息 / 手写引言 / DIN 数字），并且**大标题带字距**。

角色表：

===========  ==========================================  =========================
role         用途                                        首选（Windows 本机实测可用）
===========  ==========================================  =========================
display      拉丁大标题（衬线、字距宽）                  Georgia / Times / Palatino
serif        中文标题衬线（宋体）                        Noto Serif SC / 宋体
heavy        中文粗黑（信息主标题）                      微软雅黑 Bold / 汉仪中黑
sans         中文常规（正文、曲目）                      微软雅黑 / 等线
hand         手写引言（中文=楷体，纯拉丁=Inkfree）        楷体 / Inkfree / Segoe Print
num          序号、条码数字、版权小字（DIN 风）          Bahnschrift / Consolas
===========  ==========================================  =========================

跨平台回退：找不到首选时逐级降级，最后一律回到 ``fonts.find()``，
**绝不抛异常**（否则整套出图会挂）。
"""
from __future__ import annotations

import os
import sys

from PIL import ImageDraw, ImageFont

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import fonts as _fonts
except Exception:  # pragma: no cover
    _fonts = None


# ---------------- 字体定位 ----------------
def _win_fonts() -> str:
    return os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


def _candidates(role: str) -> list[str]:
    """按优先级给出候选字体文件（不检查存在性）。"""
    win = _win_fonts()
    mac = "/System/Library/Fonts"
    if role == "display":
        return [os.path.join(win, x) for x in
                ("georgia.ttf", "times.ttf", "pala.ttf", "constan.ttf", "cambria.ttc")] + [
                os.path.join(mac, "Times New Roman.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]
    if role == "serif":                       # 中文衬线（专辑标题的高级感来源）
        return [os.path.join(win, "NotoSerifSC-VF.ttf"), os.path.join(win, "simsun.ttc"),
                os.path.join(win, "SimsunExtG.ttf"),
                "/System/Library/Fonts/Songti.ttc",
                "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"]
    if role == "heavy":                       # 中文粗黑
        return [os.path.join(win, x) for x in
                ("msyhbd.ttc", "HYZhongHeiTi-197.ttf", "simhei.ttf", "Dengb.ttf")] + [
                "/System/Library/Fonts/PingFang.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
    if role == "sans":                        # 中文常规黑
        return [os.path.join(win, x) for x in
                ("msyh.ttc", "Deng.ttf", "NotoSansSC-VF.ttf", "simhei.ttf")] + [
                "/System/Library/Fonts/PingFang.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    if role == "hand":                        # 手写：中文用楷体（有书法味且字库全）
        return [os.path.join(win, x) for x in
                ("simkai.ttf", "STKAITI.TTF", "Inkfree.ttf", "segoepr.ttf")] + [
                "/System/Library/Fonts/Kaiti.ttc", "/System/Library/Fonts/Supplemental/Kaiti.ttf"]
    if role == "hand_latin":                  # 纯拉丁手写
        return [os.path.join(win, x) for x in ("Inkfree.ttf", "segoepr.ttf", "simkai.ttf")] + [
                "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf"]
    if role == "num":                         # DIN 风数字（Bahnschrift 是本机自带的窄体）
        return [os.path.join(win, x) for x in
                ("bahnschrift.ttf", "consola.ttf", "cour.ttf", "framd.ttf", "calibri.ttf")] + [
                "/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf"]
    return []


_ENV = {"display": "MINUET_FONT_DISPLAY", "serif": "MINUET_FONT_SERIF",
        "hand": "MINUET_FONT_HAND", "num": "MINUET_FONT_NUM"}

_cache: dict[tuple, object] = {}

# 某些角色天生没有汉字（DIN 数字体 / Georgia / Inkfree）—— 一旦文本里出现汉字
# 必须换角色，否则画出来是一排「豆腐块」。踩过：封底的「℗ & © 周杰伦」全成 □。
_CJK_REDIRECT = {"num": "sans", "display": "serif", "hand_latin": "hand"}
_missing_cjk_warned: set = set()


def _has_cjk(s: str) -> bool:
    for ch in s or "":
        if "\u2e80" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef":
            return True
    return False


def font(role: str, size: int, text: str | None = None):
    """按角色取字体，字体对象按 (角色, 字号, 有无中文) 缓存。"""
    if text and _has_cjk(text) and role in _CJK_REDIRECT:
        role = _CJK_REDIRECT[role]
    size = max(6, int(size))
    key = (role, size, bool(text and _has_cjk(text)))
    got = _cache.get(key)
    if got is not None:
        return got
    f = _load(role, size)
    _cache[key] = f
    return f


def _load(role: str, size: int):
    p = path_for(role, None)
    f = None
    if p:
        try:
            f = ImageFont.truetype(p, size)
        except Exception:
            f = None
    if f is None and _fonts is not None:
        try:
            f = ImageFont.truetype(_fonts.find(bold=role in ("heavy", "serif")), size)
        except Exception:
            f = None
    return f if f is not None else ImageFont.load_default()


def path_for(role: str, text: str | None = None) -> str | None:
    """给出该角色实际可用的字体文件路径（找不到返回 None）。"""
    if text is not None and _has_cjk(text) and role in _CJK_REDIRECT:
        role = _CJK_REDIRECT[role]
    env = _ENV.get(role)
    if env:
        v = os.environ.get(env)
        if v and os.path.exists(v):
            return v
    for p in _candidates(role):
        if os.path.exists(p):
            return p
    return None


def vary(f, name: str):
    """尝试把可变字体（NotoSerifSC-VF 等）切到指定字重实例；失败原样返回。"""
    for n in (name, name.capitalize(), name.lower()):
        try:
            f.set_variation_by_name(n)
            return f
        except Exception:
            continue
    return f


# ---------------- 字距排版 ----------------
def tracked_width(d, text: str, f, tracking: float = 0.0) -> float:
    return sum(d.textlength(ch, font=f) for ch in text) + tracking * max(0, len(text) - 1)


def tracked(d, xy, text: str, f, fill, tracking: float = 0.0,
            anchor_x: str = "left", limit: float | None = None) -> float:
    """带字距的绘制（PIL 原生没有 letter-spacing，只能逐字画）。

    ``limit`` 给定时超出宽度自动截断加省略号，返回实际宽度。
    """
    x, y = xy
    if not text:
        return 0.0
    if limit is not None and tracked_width(d, text, f, tracking) > limit:
        ell = "…"
        while text and tracked_width(d, text + ell, f, tracking) > limit:
            text = text[:-1]
        text = (text + ell) if text else ""
        if not text:
            return 0.0
    w = tracked_width(d, text, f, tracking)
    if anchor_x == "center":
        x -= w / 2.0
    elif anchor_x == "right":
        x -= w
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        x += d.textlength(ch, font=f) + tracking
    return w


def fit_tracked(d, text: str, box_w: float, start: int, role: str,
                tracking: float = 0.0, min_s: int = 7):
    """字号自适应：在 box_w 内塞下 text（带字距）。返回 (font, text)。"""
    s = max(min_s, int(start))
    while s > min_s:
        f = font(role, s, text)
        if tracked_width(d, text, f, tracking) <= box_w:
            return f, text
        s = max(min_s, int(s * 0.93))
    f = font(role, min_s, text)
    t = text
    while t and tracked_width(d, t + "…", f, tracking) > box_w:
        t = t[:-1]
    return f, ((t + "…") if t else "")


# 行首/行尾禁则（CJK 排版）：中文逐字断会把「，」甩到下一行行首，
# 视觉上像排版事故（踩过：金句印成「把音量推到最大 / ，世界就安静了」）。
_NO_LINE_START = "，。、；：！？）」』】》〉”’…‥·％%,.!?;:)]}>%"
_NO_LINE_END = "（「『【《〈“‘([{<"


def _kinsoku(lines: list[str]) -> list[str]:
    """行首/行尾禁则修正 —— 把不该开头的标点拽回上一行（允许标点悬挂）。"""
    out = list(lines)
    for i in range(1, len(out)):              # 行首禁则
        while out[i] and out[i][0] in _NO_LINE_START:
            out[i - 1] += out[i][0]
            out[i] = out[i][1:]
    for i in range(len(out) - 1):             # 行尾禁则
        while out[i] and out[i][-1] in _NO_LINE_END:
            out[i + 1] = out[i][-1] + out[i + 1]
            out[i] = out[i][:-1]
    res = [ln for ln in out if ln]
    return res or [""]


def wrap_tracked(d, text: str, f, box_w: float, tracking: float = 0.0):
    """按实测宽度**折行**（不是截断）。

    🔴 `tracked(limit=…)` 是截断，长句会变成「public p…」这种半截话。
    封底版权行那种固定长英文声明必须折行 —— 唱片封底上真就是折两行的。
    优先按空格断（英文），单词本身超宽时再逐字断（中文/长单词）；
    最后过一遍 ``_kinsoku``，保证标点不在行首、开括号不在行尾。
    """
    out: list[str] = []
    for para in str(text).split("\n"):
        cur = ""
        for wd in para.split(" "):
            trial = (cur + " " + wd) if cur else wd
            if tracked_width(d, trial, f, tracking) <= box_w:
                cur = trial
                continue
            if cur:
                out.append(cur)
                cur = ""
            piece = ""                      # 单词本身超宽 → 逐字断
            for ch in wd:
                if piece and tracked_width(d, piece + ch, f, tracking) > box_w:
                    out.append(piece)
                    piece = ch
                else:
                    piece += ch
            cur = piece
        if cur:
            out.append(cur)
    return _kinsoku(out) if out else [""]


# ---------------- 小工具 ----------------
def rule(d, x1, y, x2, fill, width: int = 1):
    """细分隔线（真封底上那根 hairline）。"""
    d.rectangle([x1, y, x2, y + max(1, width) - 1], fill=fill)


def text_size(d, text: str, f):
    try:
        b = d.textbbox((0, 0), text, font=f)
        return b[2] - b[0], b[3] - b[1]
    except Exception:
        return int(d.textlength(text, font=f)), int(getattr(f, "size", 12))


def shadow_text(im, xy, text, f, fill, tracking=0.0, shadow=(0, 0, 0, 130),
                off=(1, 1), anchor_x="left"):
    """照片底上写字用的带投影文字（保证不改底色也能读）。"""
    from PIL import Image

    lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    dx, dy = off
    tracked(d, (xy[0] + dx, xy[1] + dy), text, f, shadow, tracking, anchor_x)
    tracked(d, xy, text, f, fill, tracking, anchor_x)
    im.alpha_composite(lay) if im.mode == "RGBA" else im.paste(
        lay, (0, 0), lay)


def roles_available() -> dict:
    """诊断用：各角色实际解析到的字体文件。"""
    out = {}
    for r in ("display", "serif", "heavy", "sans", "hand", "hand_latin", "num"):
        out[r] = path_for(r, "中" if r != "hand_latin" else "A")
    return out


if __name__ == "__main__":
    for k, v in roles_available().items():
        print("%-11s %s" % (k, v))
