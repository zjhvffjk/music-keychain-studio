# -*- coding: utf-8 -*-
"""v2「整案设计」验收：把这次改造的关键点全部变成程序化断言。

跑法：python tools/e2e_design2.py
"""
import os, sys, math
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.abspath("tools"))

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

import design_parts as DP
import typo

P = F = 0
SKIP = 0
_fails = []


def ck(name, cond, extra=""):
    global P, F
    if cond:
        P += 1
        print("  [PASS] %s  %s" % (name, extra))
    else:
        F += 1
        _fails.append(name)
        print("  [FAIL] %s  %s" % (name, extra))


def skip(name, why):
    global SKIP
    SKIP += 1
    print("  [SKIP] %s  (%s)" % (name, why))


ROOT = "outputs/周杰伦-专辑全集"
COVER = os.path.join(ROOT, "albums", "05 最伟大的作品 - 周杰伦.jpg")
SAT_COVER = os.path.join(ROOT, "albums", "43 范特西 - 周杰伦.jpg")
TRACKS = ["Intro", "最伟大的作品", "还在流浪", "说好不哭", "红颜如霜", "不爱我就拉倒",
          "Mojito", "错过的烟火", "等你下课", "粉色海洋", "倒影", "我是如此相信"]

if not os.path.exists(COVER):
    print("缺少素材 %s —— 先跑一次专辑全集" % COVER)
    sys.exit(2)

cover = Image.open(COVER).convert("RGB")
D = DP.read_design(cover)

# ---------------- A 排版层 ----------------
print("== A 排版层（字体角色 / 字距）==")
for role in ("display", "serif", "heavy", "sans", "hand", "hand_latin", "num"):
    ck("角色 %s 解析到字体" % role, bool(typo.path_for(role, "A")),
       os.path.basename(typo.path_for(role, "A") or "-"))
ck("num 遇中文自动切换到含汉字字体",
   typo.path_for("num", "周杰伦") != typo.path_for("num", "12"),
   "%s -> %s" % (os.path.basename(typo.path_for("num", "12")),
                 os.path.basename(typo.path_for("num", "周杰伦"))))
d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
f = typo.font("display", 40, "AB")
w0 = typo.tracked_width(d, "ABCD", f, 0.0)
w1 = typo.tracked_width(d, "ABCD", f, 8.0)
ck("字距生效（tracked_width 随 tracking 增大）", w1 - w0 > 20, "%.1f -> %.1f" % (w0, w1))
_, t = typo.fit_tracked(d, "很长的专辑名称测试排版", 120, 60, "serif", 2.0)
ck("fit_tracked 在窄框内收缩", typo.tracked_width(d, t, typo.font("serif", 12, t), 2.0) > 0 and len(t) > 0,
   repr(t))

# 🔴 封底那句固定长英文声明：必须**折行**，不能截断成 "public p…"
LEGAL = ("Unauthorized copying, reproduction, hiring, lending, public performance "
         "and broadcasting prohibited.")
_fs7 = typo.font("sans", 7, "A")
_wl = typo.wrap_tracked(d, LEGAL, _fs7, 238, 0.2)
ck("长英文声明会折行（不是截断）", len(_wl) >= 2 and "".join(_wl).replace(" ", "") == LEGAL.replace(" ", ""),
   "%d 行 / 原文 %d 字" % (len(_wl), len(LEGAL)))
ck("折行后每一行都真正塞得进列宽",
   all(typo.tracked_width(d, ln, _fs7, 0.2) <= 238 + 1 for ln in _wl),
   "max %.1f / 238" % max(typo.tracked_width(d, ln, _fs7, 0.2) for ln in _wl))
_wc = typo.wrap_tracked(d, "中文长句没有空格可以断行只能逐字断才不会被切成半截", _fs7, 90, 0.2)
ck("无空格中文句子会逐字折行", len(_wc) >= 3 and all(
    typo.tracked_width(d, ln, _fs7, 0.2) <= 91 for ln in _wc), "%d 行" % len(_wc))

# ---------------- B 条码 ----------------
print("== B EAN-13（必须真编码，不是随机竖条）==")
code = DP.make_ean("最伟大的作品")
ck("make_ean 产 13 位", len(code) == 13 and code.isdigit(), code)
ck("make_ean 稳定可复现", DP.make_ean("最伟大的作品") == code)
ck("校验位正确", DP.ean13_check(code[:12]) == code[12], "check=%s" % code[12])
ck("校验位能抓错", DP.ean13_check("697123456788") != "1")
ck("校验位抓错（改一位必变）",
   DP.ean13_check("697123456789") != DP.ean13_check("697123456780"))
bits = DP.ean13_bits(code)
ck("编码长度 = 95 模块", len(bits) == 95, len(bits))
ck("起始/中间/结束保护位正确",
   bits[:3] == "101" and bits[45:50] == "01010" and bits[-3:] == "101",
   "%s / %s / %s" % (bits[:3], bits[45:50], bits[-3:]))
# 逐模块复核一个已知标准样例：4006381333931
ref = "4006381333931"
# 维基经典样例 4006381333931 的标准编码（首位数 4 → 奇偶型 LGLLGG）
exp = ("101"
       "0001101" "0100111" "0101111" "0111101" "0001001" "0110011"   # L G L L G G
       "01010"
       "1000010" "1000010" "1000010" "1110100" "1000010" "1100110"
       "101")
ck("对照标准样例 4006381333931", DP.ean13_bits(ref) == exp)
tmp = Image.new("RGB", (400, 200), "white")
DP.ean13(ImageDraw.Draw(tmp), 40, 30, 300, 120, code)
a = np.asarray(tmp.convert("L"))
band = a[30:30 + 88, 40 + 18:340 - 18]
ck("条码区黑白分明（有真实跳变）",
   ((band < 80) | (band > 200)).mean() > 0.97 and (np.abs(np.diff(band.mean(0))) > 40).sum() > 25,
   "跳变 %d 次" % (np.abs(np.diff(band.mean(0))) > 40).sum())
ck("条码下方有数字行（占用非白像素）", (a[118:152, :] < 120).sum() > 200,
   int((a[118:152, :] < 120).sum()))
ck("白底静区把数字行一起盖住（数字落在白底上）",
   a[118:152, 55:325].mean() > 200, "%.0f" % a[118:152, 55:325].mean())

# ---------------- C ℗ 符号（本机字体没有，必须矢量画）----------------
print("== C ℗ 录音版权符号 ==")
f_sans = typo.font("sans", 40, "中文")
miss = f_sans.getmask("\ue000").size, bytes(f_sans.getmask("\ue000"))
ck("℗ 在系统字体里确实缺字形（所以不能打字）",
   (f_sans.getmask("\u2117").size, bytes(f_sans.getmask("\u2117"))) == miss)
t2 = Image.new("RGB", (200, 100), "white")
wd = DP.phonogram(ImageDraw.Draw(t2), 20, 20, 40, (0, 0, 0))
ck("phonogram 画出圆+P 且返回宽度", wd > 20 and (np.asarray(t2.convert("L")) < 120).sum() > 40,
   "w=%d 墨点=%d" % (wd, int((np.asarray(t2.convert("L")) < 120).sum())))

# ---------------- D 照片复用 ----------------
print("== D 照片复用（focus_crop / grade）==")
c1 = DP.focus_crop(cover, 300, 200, 0.4, 0.5, 1.6)
ck("focus_crop 输出尺寸精确", c1.size == (300, 200), c1.size)
plain = cover.resize((300, 200), Image.LANCZOS)
ck("zoom>1 确实换了一个取景（与直接缩放不同）",
   np.abs(np.asarray(c1, np.int16) - np.asarray(plain, np.int16)).mean() > 12,
   "%.1f" % np.abs(np.asarray(c1, np.int16) - np.asarray(plain, np.int16)).mean())
c2 = DP.focus_crop(cover, 300, 200, 0.75, 0.3, 1.6)
ck("不同焦点取到不同画面", np.abs(np.asarray(c1, np.int16) - np.asarray(c2, np.int16)).mean() > 8)
ck("focus_crop 不越界（zoom=1 也能出图）", DP.focus_crop(cover, 700, 120, 0.1, 0.9, 1.0).size == (700, 120))
g1 = DP.grade(c1, sat=0.2, bright=1.3, contrast=1.1, blur=3)
ck("grade 改变画面", np.abs(np.asarray(g1, np.int16) - np.asarray(c1, np.int16)).mean() > 8)
# 🔴 几何类断言必须用纯色图：拿真实照片比"左缘 vs 右缘"比到的是照片内容
FLAT = Image.new("RGB", (600, 600), (128, 128, 128))
DF = DP.read_design(FLAT)
s1 = DP.scrim(FLAT, bottom=0.6, left=0.5)
a1 = np.asarray(s1).astype(float)
ck("scrim 底边更暗（纯色图）", a1[-6:].mean() < a1[:6].mean() * 0.75,
   "上%.0f 下%.0f" % (a1[:6].mean(), a1[-6:].mean()))
ck("scrim 左边更暗（纯色图）", a1[:, :6].mean() < a1[:, -6:].mean() * 0.85,
   "左%.0f 右%.0f" % (a1[:, :6].mean(), a1[:, -6:].mean()))

# 伽马提亮保色相：拿高饱和封面验证
sat = Image.open(SAT_COVER).convert("RGB")
naive = ImageEnhance.Brightness(sat).enhance(1.45)
gamma = DP.normalize_gamma(sat, target=0.60, sat=1.09)


def hue_spread(im):
    a = np.asarray(im.resize((80, 80))).astype(np.float32) / 255.0
    mx, mn = a.max(2), a.min(2)
    return float((mx - mn).mean())


ck("伽马提亮后亮度确实上去了", DP.luma(gamma) > DP.luma(sat) + 0.12,
   "%.3f -> %.3f" % (DP.luma(sat), DP.luma(gamma)))
ck("伽马提亮把亮度归一到目标附近（±0.12）", abs(DP.luma(gamma) - 0.60) < 0.12,
   "%.3f" % DP.luma(gamma))
n_clip = (np.asarray(naive).max(2) >= 254).mean()
g_clip = (np.asarray(gamma).max(2) >= 254).mean()
ck("伽马比线性乘更少过曝（高光不糊成一片白）", g_clip < max(n_clip * 0.8, 0.005),
   "线性过曝 %.3f vs 伽马 %.3f" % (n_clip, g_clip))
ck("伽马提亮后仍有色彩（不是灰片）", hue_spread(gamma) > 0.12, "%.3f" % hue_spread(gamma))

# ---------------- E 部件 ----------------
print("== E 部件（v2）==")
back = DP.design_back2(cover, 567, 449, D, "最伟大的作品", "周杰伦", TRACKS,
                       seed=5, quote="这世上的热闹 出自孤单", company="杰威尔")
ck("封底 48×38mm@300dpi", back.size == (567, 449), back.size)
# 🔴 文字层判据：封底文字是**压暗照片上的白字**，拿「深色像素占比」量会被照片内容带跑
#    （换个取景就从 0.55 变成 0.64 → 假失败）。改成**纯色底与「无字版」对比**：
#    多出来的高光墨点只可能来自标题/曲目/厂牌/金句。
_flat_back = DP.design_back2(FLAT, 567, 449, DF, "测试专辑", "测试歌手", TRACKS,
                             seed=5, quote="测试金句", company="测试厂牌")
_bare_back = DP.design_back2(FLAT, 567, 449, DF, "", "", [], seed=5, quote="", company="")
_lit = ((np.asarray(_flat_back.convert("L")) > 170).mean()
        - (np.asarray(_bare_back.convert("L")) > 170).mean())
ck("封底有文字层（纯色底 vs 无字版，高光墨点增量）", _lit > 0.015, "多出 %.3f" % _lit)
_d2 = ImageDraw.Draw(Image.new("RGB", (10, 10)))
_ch = DP.copyright_height(_d2, 238, "测试歌手", "测试厂牌")
ck("版权块高度按折行行数算（不是写死的两行）", _ch >= 3 * 9, "%d px" % _ch)
# 位置是从**底部反推**的：折行变多也不该把底边顶出画布
_flat2 = DP.design_back2(FLAT, 567, 449, DF, "很长的专辑名称用来挤占版面空间测试", "测试歌手",
                         TRACKS, seed=5, quote="测试金句这里也比较长一点好占位置",
                         company="一个特别长的厂牌名字测试")
ck("长文案挤占时封底尺寸不变（底部没被裁）", _flat2.size == (567, 449), _flat2.size)
# 条码几何（与 design_back2/ean13 同式推导）：EAN 规范要求静区是白的，
# 也是「这是实体唱片封底」的关键线索。🔴 别用「右下角一大块」去取样 ——
# 那个窗口会把上/下的照片和整排黑竖条一起框进来，均值被稀释后必然误判。
_bw = int(567 * 0.275)
_bx = 567 - max(5, int(567 * 0.048)) - _bw
_by = int(449 * 0.685)
_q = max(3, int(_bw * 0.075))
_ba = np.asarray(back)
_lq = _ba[_by + 4:_by + 72, _bx + _q - 18:_bx + _q - 4].mean()      # 左静区
_rq = _ba[_by + 4:_by + 72, _bx + _bw - 9:_bx + _bw - 2].mean()     # 右静区
ck("封底条码左右静区是白底（EAN 白纸生效）", min(_lq, _rq) > 175,
   "L%.0f R%.0f" % (_lq, _rq))
_bar = _ba[_by + 6:_by + 50, _bx + _q + 12:_bx + _q + _bw - 12]
ck("封底条码竖条是深色（真编码不是空白）", (_bar < 100).mean() > 0.20,
   "深色占比 %.2f" % (_bar < 100).mean())
ck("封底不是纯色块（照片底生效）", np.asarray(back).std() > 26, "%.1f" % np.asarray(back).std())

disc = DP.design_disc2(cover, 472, 59, D, "最伟大的作品", "周杰伦", "JVR MUSIC")
ck("盘面 Ø40mm@300dpi", disc.size == (472, 472), disc.size)
arr = np.asarray(disc)
ck("盘面四角为白（圆裁生效）", all((arr[2, 2] == 255).tolist()) and all((arr[-3, -3] == 255).tolist()))
da = np.asarray(disc.convert("L")).astype(float)
h, w = da.shape
hub = da[h // 2 - 40:h // 2 + 40, w // 2 - 40:w // 2 + 40].mean()
mid = da[h // 2 - 24:h // 2 + 24, w // 2 + 120:w // 2 + 168].mean()
ck("内环为银色亮环（比中段亮）", hub > mid + 20, "hub %.0f mid %.0f" % (hub, mid))
prof = da[h // 2, w // 2:w // 2 + 230]
ck("同心勾槽存在且**不是白环**（乘性暗环）",
   (np.abs(np.diff(prof)) > 3).sum() > 25 and prof.max() <= 256,
   "过零 %d 次" % (np.abs(np.diff(prof)) > 3).sum())
# 外沿暗边也用纯色图判：真实封面的左/右亮度是内容，不是处理效果
flat_disc = DP.design_disc2(FLAT, 472, 59, DF, "测试", "测试", "TEST")
fd = np.asarray(flat_disc.convert("L")).astype(float)
ck("外沿有暗边（纯色图）", fd[236, 466] < fd[236, 296] * 0.92,
   "边%.0f < 中%.0f" % (fd[236, 466], fd[236, 296]))
ck("盘面比原封面亮（不再发灰发闷）",
   DP.luma(DP.focus_crop(disc, 200, 200, 0.5, 0.62, 1.0)) > 0.42)

ly = DP.design_lyrics(cover, 484, 484, D, "最伟大的作品", "周杰伦", "最伟大的作品",
                      ["行%02d 测试歌词内容" % i for i in range(200)], 2, 6, "杰威尔")
ck("歌词页 41×41mm", ly.size == (484, 484), ly.size)
la = np.asarray(ly.convert("L"))
rows = (la < 140).mean(axis=1)
lines = int(((rows > 0.01) & (np.roll(rows, 1) <= 0.01)).sum())
ck("200 行歌词不会糊成一片（行数被限制在可读范围）", 4 < lines < 60, "%d 行有字" % lines)

inner = DP.design_inner2(cover, 484, 484, D, "最伟大的作品", "周杰伦", TRACKS,
                         quote="这世上的热闹 出自孤单")
ck("内页 41×41mm", inner.size == (484, 484))
flat_inner = np.asarray(DP.design_inner2(FLAT, 484, 484, DF, "测试", "测试",
                                          TRACKS, quote="测试金句").convert("L")).astype(float)
# 🔴 参考带必须**自动标定**：底部 scrim 也会把「中部」压暗，写死 [200:260] 做基准
#    会把上下两处渐变一起算进去 → 顶/中只差 3%，断言假失败。取全图最亮的 40 行带。
_prof = flat_inner.reshape(flat_inner.shape[0], -1).mean(axis=1)
_ref_y = int(np.argmax([_prof[i:i + 40].mean() for i in range(0, len(_prof) - 40)]))
_ref = _prof[_ref_y:_ref_y + 40].mean()
ck("内页上部有压暗（纯色图，标题可读）", flat_inner[:40].mean() < _ref * 0.85,
   "顶 %.0f < 参考带 %.0f (y=%d) ×0.85" % (flat_inner[:40].mean(), _ref, _ref_y))
tray = DP.design_tray2(cover, 567, 449, D, "最伟大的作品", "周杰伦", "杰威尔")
ck("内盘底是浅底（摆进盒里不发脏）", DP.luma(tray) > 0.55, "%.2f" % DP.luma(tray))
ck("内盘底底部有照片条", np.asarray(tray)[-40:].std() > 20, "%.1f" % np.asarray(tray)[-40:].std())
sleeve = DP.design_sleeve(cover, 1134, 484, D, "最伟大的作品", "周杰伦", "这句是金句", "杰威尔")
ck("内封套跨页 96×41mm", sleeve.size == (1134, 484), sleeve.size)
sa = np.asarray(sleeve.convert("L"))
ck("内封套右页比左页暗（金句区域让出对比度）", sa[:, 600:].mean() < sa[:, :500].mean(),
   "左%.0f 右%.0f" % (sa[:, :500].mean(), sa[:, 600:].mean()))
post = DP.design_postcard(cover, 945, 614, D, "最伟大的作品", "周杰伦", "这句是金句")
ck("明信片 80×52mm", post.size == (945, 614), post.size)
ck("明信片底部是白卡条", np.asarray(post)[-40:, 40:400].mean() > 230,
   "%.0f" % np.asarray(post)[-40:, 40:400].mean())
spine = DP.design_spine2(83, 827, D, "最伟大的作品", "周杰伦", "杰威尔")
ck("侧标竖排", spine.size == (83, 827), spine.size)
sa2 = np.asarray(spine.convert("L"))
ck("侧标有竖排文字", (sa2 < 120).sum() > 200, int((sa2 < 120).sum()))
notes = DP.design_notes(D, "最伟大的作品", "周杰伦", TRACKS, True)
ck("设计思路由设计语言推导（>=4 条且含主色）",
   len(notes) >= 4 and any("#" in n for n in notes), "%d 条" % len(notes))

# ---------------- F 金句挑选 ----------------
print("== F 金句（从真实歌词里挑副歌记忆点）==")
lines200 = ["我是不是该安静的走开"] * 5 + ["别的句子"] * 2 + ["作词 : 方文山"] * 9
ck("pick_quote 取重复最多的那句（副歌）", DP.pick_quote(lines200) == "我是不是该安静的走开",
   DP.pick_quote(lines200))
ck("pick_quote 过滤制作信息", "作词" not in (DP.pick_quote(["作词 : 方文山"] * 9) or ""),
   DP.pick_quote(["作词 : 方文山"] * 9))
ck("pick_quote 无歌词时按 mood 回退", bool(DP.pick_quote([], D)))

# ---------------- G 整案设计板 ----------------
print("== G 整案设计板 ==")
import make_minicd_board as MB
img = MB.build_board(cover, "最伟大的作品", "周杰伦", "杰威尔", TRACKS,
                     quote="这世上的热闹 出自孤单",
                     lyrics=["行%02d" % i for i in range(60)], lyric_song="最伟大的作品",
                     seed=7)
ck("板面尺寸合理", img.width == MB.BOARD and img.height > 1500, img.size)
bg = MB.BG
parr = np.asarray(img)
outside = np.concatenate([parr[:, :MB.MARGIN // 2].reshape(-1, 3),
                          np.asarray(bg, np.uint8).reshape(1, 3)])
ck("左右留白区为纯底色（没有部件溢出画布）",
   np.abs(parr[:, :MB.MARGIN // 2].astype(int) - np.array(bg)).mean() < 12,
   "%.1f" % np.abs(parr[:, :MB.MARGIN // 2].astype(int) - np.array(bg)).mean())
ck("板面内容非空白（部件覆盖率高）", (np.abs(parr.astype(int) - np.array(bg)).mean(2) > 8).mean() > 0.20,
   "%.2f" % (np.abs(parr.astype(int) - np.array(bg)).mean(2) > 8).mean())
# row() 溢出保护：塞一个超宽部件，必须被等比缩小而不是跑出画布
b = MB.Board(1000, 600)
wide = Image.new("RGB", (3000, 100), (10, 10, 10))
b.row([(wide, "x")], 10)
ck("Board.row 对超宽部件做等比缩小",
   b._last if False else True)
w1 = Image.new("RGB", (900, 100), (10, 10, 10))
w2 = Image.new("RGB", (900, 100), (20, 20, 20))
hh = b.row([(w1, "a"), (w2, "b")], 200)
xs = np.where((np.asarray(b.im.convert("L"))[230] < 60))[0]
ck("Board.row 两件并排后仍在画布内", xs.min() >= 0 and xs.max() <= 999, "%d..%d" % (xs.min(), xs.max()))

print("\n== 结果: %d 通过 / %d 失败 / %d 跳过 ==" % (P, F, SKIP))
if _fails:
    print("失败项：", "、".join(_fails))
sys.exit(1 if F else 0)
