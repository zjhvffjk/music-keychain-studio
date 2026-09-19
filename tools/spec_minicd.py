# -*- coding: utf-8 -*-
"""迷你CD 包装 —— 唯一尺寸真源（mm）。

🔴 2026-09-19 用户拍板：封底条为 **111.2×38 固定结构**
   右侧封4.4 + 封底49 + 左侧封4.4 + 左侧封背面4.4 + 内盘底49
   （左侧封与左侧封背面相邻、中间无空白；旧 108.4 口径作废）。

合成（make_minicd.py）与打印（make_minicd_sheet / design_service）都从本模块取值，
杜绝口径漂移。内容规则：封面背面(41mm)无条码；封底(49mm)=曲目+真EAN+版权；
内盘底(49mm)=取下 CD 后的隐藏主视觉。
"""

DISC_D = 40.0        # 盘面外径
DISC_HOLE = 5.0      # 内孔直径
COVER_W = 82.0       # 封面折件展开宽
COVER_H = 41.0       # 封面折件高（对折后 41×41）
BACK_SEGS = (4.4, 49.0, 4.4, 4.4, 49.0)   # 右侧封/封底/左侧封/左侧封背面/内盘底
BACK_W = round(sum(BACK_SEGS), 2)         # 111.2
BACK_H = 38.0
BLEED = 3.0          # 印刷出血
A4L = (297.0, 210.0)  # A4 横版（4 套/页）

SEG_NAMES = ("右侧封", "封底", "左侧封", "左侧封背面", "内盘底")

MM_PER_INCH = 25.4


def mm_to_px(value_mm, dpi=300):
    """毫米 → 像素（四舍五入）。前端实尺寸画布与后端出件共用同一换算式。"""
    return int(round(value_mm * dpi / MM_PER_INCH))


# ======================================================================
# 折音 FOLD STUDIO 融合层（2026-09-19）
#
# 来源：用户另一个工作台 album-studio/src/geometry.js —— 与本模块**同一套 111.2
# 规格**，但它多出三样我们此前没有的东西：①每个分段的语义角色（这一段该放什么）
# ②A4 上三件的摆放 ③生产规格清单。此处只**新增**、不改名，design_service 与
# make_minicd 的现有调用完全不受影响。
# ======================================================================

# --- ① 分段语义角色 ---------------------------------------------------
SEG_IDS = ("right-spine", "back", "left-spine", "left-spine-back", "inner-tray")

SEG_ROLES = {
    "right-spine":     ("spine-artwork", "spine-text"),
    "back":            ("tracks", "barcode", "copyright"),
    "left-spine":      ("spine-artwork", "spine-text"),
    "left-spine-back": ("spine-artwork", "spine-text"),   # 左侧封的背面，与左封相邻无空白
    "inner-tray":      ("hidden-artwork", "copy"),
}

ROLE_NAMES = {
    "spine-artwork":  "侧封画面",
    "spine-text":     "侧封文字",
    "tracks":         "曲目",
    "barcode":        "条码",
    "copyright":      "版权声明",
    "hidden-artwork": "隐藏主视觉",
    "copy":           "文案",
    "artwork":        "画面",
    "title":          "标题",
    "artist":         "歌手",
}

# 折线位置（距封底条左边缘，mm）—— 4 道，与 BACK_SEGS 同源推导，杜绝手填漂移
SEG_FOLDS = tuple(round(sum(BACK_SEGS[:i + 1]), 1) for i in range(len(BACK_SEGS) - 1))
# = (4.4, 53.4, 57.8, 62.2)

# 封面折件：对折线在中缝，两个面各 41mm
_PANEL_W = round(COVER_W / 2, 1)
COVER_PANELS = (
    {"id": "cover-inside", "name": "封面背面 / 内页", "x": 0.0, "w": _PANEL_W,
     "roles": ("artwork", "copy")},
    {"id": "cover-front", "name": "封面正面", "x": _PANEL_W, "w": _PANEL_W,
     "roles": ("artwork", "title", "artist")},
)

# --- ② A4 拼版布局 ----------------------------------------------------
SHEET_MARGIN = 10.0
SHEET_GAP = 6.0
SHEET_COLS = ("disc", "booklet", "sleeve")     # 从左到右：盘面 / 封面折件 / 封底条
SHEET_SETS_PER_PAGE = 4                        # 列内向下叠；列高 190mm 恰好放 4 套

# --- ③ 生产规格 -------------------------------------------------------
PRINT_PROFILE = {
    "id": "minuet-minicd-a4-v1",
    "page": {"w": A4L[0], "h": A4L[1], "orientation": "landscape"},
    "resolutionDpi": 300,
    "colorMode": "RGB",
    "bleedMm": BLEED,
    "safeMm": 3.0,
    "setsPerPage": SHEET_SETS_PER_PAGE,
    "rulerMm": 50.0,
}

# 印刷辅助线图例 —— 前端画布与 PDF 档案共用同一套颜色语义
GUIDE_LEGEND = (
    {"id": "bleed", "name": "出血线", "color": (255, 0, 255), "style": "dash"},
    {"id": "cut",   "name": "裁切线", "color": (0, 0, 0),     "style": "solid"},
    {"id": "fold",  "name": "折线",   "color": (0, 110, 230), "style": "dash"},
    {"id": "safe",  "name": "安全区", "color": (0, 150, 90),  "style": "dash"},
)

OUTPUT_FILES = (
    {"id": "part-png",  "name": "三件 300DPI PNG", "format": "PNG"},
    {"id": "sheet-png", "name": "1:1 版面总览",     "format": "PNG"},
    {"id": "a4-png",    "name": "A4 拼版 PNG",      "format": "PNG"},
    {"id": "a4-pdf",    "name": "A4 印刷 PDF",      "format": "PDF"},
    {"id": "spec-json", "name": "生产规格 JSON",    "format": "JSON"},
)


def spec_dict():
    """规格快照（供前端实尺寸画布与「生产规格 JSON」导出，全部 mm）。"""
    return {
        "unit": "mm",
        "parts": {
            "disc":    {"name": "盘面",     "w": DISC_D, "h": DISC_D, "hole": DISC_HOLE},
            "booklet": {"name": "封面折件", "w": COVER_W, "h": COVER_H,
                        "folds": [_PANEL_W], "panels": [dict(p) for p in COVER_PANELS]},
            "sleeve":  {"name": "封底条",   "w": BACK_W, "h": BACK_H,
                        "segments": [
                            {"id": SEG_IDS[i], "name": SEG_NAMES[i],
                             "x": 0.0 if i == 0 else SEG_FOLDS[i - 1],
                             "w": BACK_SEGS[i], "roles": list(SEG_ROLES[SEG_IDS[i]])}
                            for i in range(len(BACK_SEGS))
                        ],
                        "folds": list(SEG_FOLDS)},
        },
        "sheet": {"page": [A4L[0], A4L[1]], "margin": SHEET_MARGIN, "gap": SHEET_GAP,
                  "cols": list(SHEET_COLS), "setsPerPage": SHEET_SETS_PER_PAGE},
        "print": PRINT_PROFILE,
        "guides": [dict(g) for g in GUIDE_LEGEND],
        "outputs": [dict(o) for o in OUTPUT_FILES],
    }
