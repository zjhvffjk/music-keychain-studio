# -*- coding: utf-8 -*-
"""
钥匙扣素材反解器

从用户的成品参考图 + 白底素材照，产出：
  1. 播放界面图的色调曲线（tone_curve.json）—— 仅作参考/兼容 --curve 选项
  2. 钥匙扣的 RGBA 叠加层（keychain_overlay.png，1920×1920 画布对齐）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【算法模型】2026-09-16 大改：从「反解 alpha」改成「几何 alpha + 精确解色」

旧模型（已废弃）把合成拆成一层 alpha：
    素材是白底照：  kb = color·a + 255·(1-a)
    成品是叠加结果：ref = base·(1-a) + color·a
    联立消去 color：a = 1 + (ref - kb) / (255 - base)
    ⇒ 在素材纯白处退化（分母只剩 ~175），把「参考与底图之间的任何微小差异」
      放大成假 alpha：实测全画布 32.6% 的像素被算出 a>0，其中包含参考图封面
      上的文字与签名 → 换首歌就浮出一层 10~30% 的白纱。

    更致命的是：这个模型**本身就不成立**。实测（三方对照，见下）：
      · 壳左边框  ref=(146,150,149)  kb=(149,154,150)  base=(47,71,102)  |ref-kb|=2.5
      · 壳右边框  ref=(135,138,136)  kb=(134,138,137)  base=(27,60,91)   |ref-kb|=0.6
      · 壳下唇    ref=( 85, 80, 77)  kb=( 85, 80, 74)  base=(11,11,11)   |ref-kb|=1.1
      · 挂钩挂耳  ref=( 21, 26, 26)  kb=( 19, 22, 18)  base=(56,82,116)  |ref-kb|=4.9
      · 壳内腔    ref=( 53, 85,113)  kb=(164,169,165)  base=(53,86,115)  |ref-kb|=82
    ⇒ 凡是实物部件，成品色与素材色**逐像素几乎相同（差 1~5）** —— 说明亚克力壳
      与金属件是**不透明的**：alpha 只有 0 和 1 两个值，不是连续半透明。
      而内腔处 ref≈base（|ref-base|=1.2）⇒ alpha=0（完全透明窗口）。
      旧公式在这两类点上的输出是：内腔 alpha=0.58（应为 0）、环上
      alpha 均值 1.085 / std 1.020（应为 1）—— 全是错的。

新模型（本文件 · 2026-09-16 第四次修复后）：
    ① alpha **只由几何决定**，与亮度彻底解耦：
       白底照 → 非白=有物体 → 二值 + 1px 抗锯齿。
       🔴 为什么必须解耦（用户第二轮反馈「像素画质有问题 / 周边有问题」）：
         旧版按亮度算覆盖率 gate = (253-lum)/1.2，于是
           · 挂耳那条白色高光线 lum=251 → alpha 只有 0.81~0.94 → 高光被"灰化"；
           · 轮廓上的浅灰过渡像素 → alpha 却被算成 1.0，颜色留在浅灰白，
             贴在深色封面上就是一圈**白色锯齿毛刺**。
         根因：亮度是**颜色**信息，不该参与**形状**判定。
       过曝高光小孔改用「连通性 + 尺寸」判定后填回（旧版闭运算会误填轮廓亮边，
       实测每张图都多出一圈与封面无关的蓝灰锯齿）；
       内腔（卡片窗口）置 0 —— 那里物理上就是透明的。
    ② color = 素材自己的颜色（unmix_white；a=1 时就是 kb —— 产品在白光白底下的
       真身色，不携带任何封面环境光），再用 defringe 把轮廓上偏白的过渡像素换成
       物体自身的色（只换颜色，不动 alpha，形状与抗锯齿不受影响）。

【第七次修复 · 2026-09-17】白底渗色必须借参考成品剔除（用户："白斑 / 像素画质"）
    素材是白底棚拍，物体外沿挂着一圈曝到 235~255 的近白像素。它们和「产品本身
    就该白的部件（白卡边框）」「金属镜面高光」在亮度上完全一样 → 单看素材无解。
    实测：素材亮度 ≤230 的物体像素与参考成品逐档吻合（7/61/135/168/201）；
    但素材 >235 的「物体」像素 14360 个，参考那边中位亮度只有 91
    → 绝大多数不是物体，是渗色。参考拍的是同一只钥匙扣、只是背景换成了深色封面，
    所以「参考是暗的」= 「那里是背景」→ 用它剔除（REF_KILL_HI / REF_KILL_LO）。
    ⚠️ 只修遮罩、**不取参考颜色**；颜色仍一律来自素材（COLOR_SOURCE 注释里有血泪史）。

【为什么几何以素材为准，而不是参考】
    实测参考里钥匙扣的剪影比素材**略大**（左边框外沿多 2px、右边框多 7px，
    环外径 405 vs 406 基本一致 —— 应是成品图带一点透视）。取素材剪影 = 永远
    不会超出参考的实物范围，因此不存在「把底图颜色当成实物贴上去」的风险；
    代价是右边缘最多窄 7px（0.4%）—— 小于旧版已经验收通过时的误差。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

用法：
    python tools/keychain_build.py                 # 重建素材与色调曲线
    python tools/keychain_build.py --report-only   # 只输出诊断，不写文件
"""
import os
import sys
import json
import argparse
import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import make_keychain as MK      # noqa: E402  共用底图构建，避免版式常量两边漂移
ASSETS = os.path.join(ROOT, "assets", "keychain")

REF = os.path.join(ASSETS, "sample_final.jpg")      # 成品参考（用户手工制作）
KBRAW = os.path.join(ASSETS, "keychain_raw.jpg")    # 钥匙扣素材（白底版）
COVER = os.path.join(ASSETS, "source_cover.jpg")    # 封面原图
PLAYER = os.path.join(ASSETS, "player_1152x1920.jpg")

# ---------- 版式常量（与 make_keychain.py 保持一致）----------
CANVAS = 1920
FRAME_OUT = 161
FRAME_THICK = 53
COVER_IN = FRAME_OUT + FRAME_THICK
COVER_SIZE = CANVAS - COVER_IN * 2
BG_BLUR = 20          # ← 修正：原 24
BG_WHITE = 0.0        # ← 修正：原 0.078（那是用错模糊半径的补偿）

PL_X, PL_Y, PL_W, PL_H = 732, 873, 453, 755
# 素材 → 画布 的映射。2026-09-16 重新标定：
#   旧值 1.1165 / (244,-26) 与成品参考**差了约 24px**（素材被放高了），
#   于是在参考剪影上做 IoU 最优化，IoU 从 0.6069 提到 0.8904。
#   映射后包围盒：素材 x 687~1233 y 227~1689 vs 参考 x 690~1232 y 233~1686。
#   ⚠️ 这才是「钥匙圈细节跟周边都有问题」的真根因 —— 遮罩与参考的实物根本没对齐。
KB_SCALE = 1.13850
KB_X, KB_Y = 232, -12

# ---------- 抠像参数（2026-09-16 第六次修复：白底成像模型反解覆盖率）----------
# 🔴 血泪史（三次模型迭代，别退回旧路）
#   v1 亮度当覆盖率  gate=(253-lum)/1.2   → 高光被灰化、环外沿毛刺
#   v2 几何二值 + 去污 defringe           → 保住了高光，但 defringe 把**物体自身
#      的亮边高光**也一起抹成暗色，且各段结果不一致 → 环的银色亮边**碎成白虚线**
#      （用户看到的"像素画质有问题"）。关掉 defringe 又会让边缘混合值变成灰白光晕。
#   v3（本版）用**成像模型**反解，一次同时拿到正确的抗锯齿 alpha 和干净的颜色：
#
#      素材是白光白底照：pixel = c·a + 255·(1-a)      （c=物体真色, a=覆盖率）
#      ⇒  a = (255 - pixel) / (255 - c)
#
#   c 取「邻近深度实心区的颜色」（因为边缘附近的 c 与内部一致）。
#   这个式子在**深部**退化成 a=1、color=pixel（保住内部高光），在**边缘带**才
#   给出 0~1 的真实覆盖率 → 边缘天然抗锯齿，且不含白底污染。
#   ⚠️ 只在**边缘带**用这个式子：物体内部的亮反光（如环上的镜面高光）若也这么算，
#      会被邻域暗色算成低 alpha → 高光变透明。内部一律 alpha=1、color=素材色。
T_WHITE = 252.5       # 判定「无物体」的亮度阈值（几何剪影用；物体最亮处 251）
# 🔴 v4 补丁（2026-09-17 第七次修复）：白底照的「过曝渗色」必须借**参考成品**剔除。
#    素材是白底棚拍：物体外沿挂着一圈被曝到 235~255 的近白像素。它们和
#    「产品本身就该白的部件（白卡边框）」「金属镜面高光」在亮度上**完全一样**，
#    单看素材无法区分 —— 这就是环外那些白斑的来历。
#    实测（_tmp/hl_bench.py）：
#      · 素材亮度 ≤230 的物体像素，与参考成品逐档吻合（中位 7/61/135/168/201）；
#      · 素材 >235 的「物体」像素 14360 个，参考那边**中位亮度只有 91**
#        → 它们绝大多数根本不是物体，而是白底渗色 + 过曝糊边。
#    参考成品拍的是同一只钥匙扣，只是背景换成了深色封面 —— 所以「参考是暗的」
#    就等于「那里其实是背景」。用这一条把渗色剔掉，环外白斑立刻消失
#    （_tmp/variant_ab.py 实测：环区亮实心像素 2817 → 2127，白斑清零）。
#    ⚠️ 只用来修**遮罩**，绝不拿参考的颜色 —— 参考带深色环境光（见 COLOR_SOURCE）。
REF_KILL_HI = 235.0   # 素材亮度高于此值 → 疑似渗色/过曝（需参考佐证）
REF_KILL_LO = 150.0   # 参考亮度低于此值 → 确认那儿是背景 → 剔除
LAST_BLEED_PX = 0     # 上次 silhouette() 剔掉的渗色像素数（诊断用）
MATTE_DENOM_MIN = 20.0  # (255-c) 小于此值说明物体本身很亮 → a 不可解，退回几何判定
MATTE_BAND_R = 1      # 边缘带：剪影外扩 R 像素（覆盖白底照的抗锯齿外沿）
MATTE_CORE_R = 3      # 深度实心区：剪影内缩 R 像素（既是色源，又避开边缘混合带）
MATTE_AMIN = 0.06     # 反解颜色时的最小覆盖率（再小则除法不稳定，直接留素材色）
KB_RESAMPLE = Image.BILINEAR   # 放大插值：BILINEAR 无过冲（LANCZOS 在高对比边缘有振铃）
BIG_HOLE_R = 15       # 孔洞半径 > R 算「真孔」（环心 r≈168、内腔 453）→ 保留透明
WIN_PAD = 0           # 透明窗口相对 PL 矩形的外扩量
WIN_BLUR = 1.0        # 窗口边缘羽化

# ---------- 遗留参数（保留供历史诊断脚本 import，正式流程已不用）----------
AA_BLUR = 0.4
CORE_R = 3
DEFRINGE_ROUNDS = 10

# ---------- 取色来源 ----------
# material  = 用素材白底照自己的颜色。素材是白光白底下的产品照，颜色中性，
#             这是**产品本来的样子** → 换任何封面都不会怪。
# reference = 用成品参考照片的颜色。那张是用户在**深蓝封面**背景下用美图类 App
#             导出的，金属环里映的是蓝环境光，整体还比素材暗 43 灰阶（环）/
#             13 灰阶（壳体）。用它当"产品固有色"是本文件历史上最大的错误来源
#             —— 与那条「App 提亮滤镜」是同一类错误（参考图是"那张照片"，
#             不是物理真相）。实测后果：环色在 5 张成品之间只差 0.40 灰阶
#             （死色），且 B-R=+8.5 偏蓝，放在暖金/暗红封面上明显不对。
# 注：几何**不受**此开关影响，永远以素材为准。
COLOR_SOURCE = "material"

LUM = np.array([.299, .587, .114], np.float32)
OUT_CURVE = os.path.join(ASSETS, "tone_curve.json")
OUT_OVERLAY = os.path.join(ASSETS, "keychain_overlay.png")


def gray(a):
    return a @ LUM


def log(*a):
    print(*a, flush=True)


# ============================================================
# 1) 播放图色调曲线（仅 --curve 兼容用，生产默认不套）
# ============================================================
def learn_tone_curve(P, ref, step=4, minn=250):
    """P / ref：同尺寸 RGB float32，学习逐通道映射曲线"""
    H, W = P.shape[:2]
    m = 20
    Pv = P[m:H - m, m:W - m]
    Rv = ref[m:H - m, m:W - m]
    curves = []
    for ch in range(3):
        xs = Pv[..., ch].ravel()
        ys = Rv[..., ch].ravel()
        ax, ay, an = [], [], []
        for lo in range(0, 256, step):
            k = (xs >= lo) & (xs < lo + step)
            if k.sum() < minn:
                continue
            ax.append(float(xs[k].mean()))
            ay.append(float(ys[k].mean()))
            an.append(int(k.sum()))
        if len(ax) < 4:
            curves.append(np.arange(256, dtype=np.float32))
            continue
        # 单调回归（保序）：用累积均值保证不越界
        xs2 = np.array(ax, np.float32)
        ys2 = np.array(ay, np.float32)
        ys2 = np.maximum.accumulate(ys2)
        lut = np.interp(np.arange(256), xs2, ys2).astype(np.float32)
        curves.append(lut)
    return curves, (ax, ay)


def apply_curve(arr, lut):
    idx = np.clip(arr.astype(np.int32), 0, 255)
    return np.dstack([lut[c][idx[..., c]] for c in range(3)]).astype(np.float32)


# ============================================================
# 2) 底图构建（无钥匙扣）
# ============================================================
def build_base(player_rgb, dim=False):
    """拼出「无钥匙扣」底图。

    ⚠️ 默认 dim=False —— 解实物颜色时必须用**未压暗**的底图：
       `make_keychain.build_canvas` 会把留白区的背景压暗到 BG_CAP 以内（好让白卡
       纸读得出来），但参考成品那张图是**没压暗**的。反解 c = (ref-base(1-a))/a
       依赖 base ≈ 参考当时的底图，所以这里要传 dim=False。
       生产合成走 make_keychain.compose()，它用 dim=True。
    """
    cov = Image.open(COVER).convert("RGB")
    return MK.build_canvas(cov, player_rgb, dim=dim)


def _paste_on_canvas(a, fill):
    """把素材尺寸的图/遮罩按同一变换铺到画布坐标；画布外填 fill"""
    nw, nh = a.shape[1], a.shape[0]
    if a.ndim == 3:
        canvas = np.full((CANVAS, CANVAS, a.shape[2]), fill, np.float32)
    else:
        canvas = np.full((CANVAS, CANVAS), fill, np.float32)
    sx0, sy0 = max(0, -KB_X), max(0, -KB_Y)
    dx0, dy0 = max(0, KB_X), max(0, KB_Y)
    w = min(nw - sx0, CANVAS - dx0)
    h = min(nh - sy0, CANVAS - dy0)
    canvas[dy0:dy0 + h, dx0:dx0 + w] = a[sy0:sy0 + h, sx0:sx0 + w]
    return canvas, (dx0, dy0, w, h)


def kb_on_canvas():
    """素材（白底）缩放后铺到画布坐标；画布外视为纯白（=不能被看到）"""
    kb = Image.open(KBRAW).convert("RGB")
    nw, nh = int(round(kb.width * KB_SCALE)), int(round(kb.height * KB_SCALE))
    kba = np.asarray(kb.resize((nw, nh), KB_RESAMPLE)).astype(np.float32)
    return _paste_on_canvas(kba, 255.0)


def external_region(obj, ds=4):
    """从画布四边 flood fill 出「与外界连通的空白区」（降采样加速）。

    用来区分两类"白"：
      · 连通到画布边的白 = 真背景（环外、环心、内腔、画布外）→ alpha 必须 0
      · 被物体完全包住的白 = 过曝高光小孔 → 是实体，alpha 必须 1
    这正是闭运算做不到的事 —— 闭运算只看宽度，会把环内外那两条 1~2px 的
    抗锯齿亮边一起填成不透明（旧版 3765px 的蓝灰锯齿就是这么来的）。
    """
    S = CANVAS // ds
    sm = np.asarray(Image.fromarray((obj * 255).astype(np.uint8))
                    .resize((S, S), Image.BOX)) > 200      # 整格都是物体才算物体（保守）
    nb = ~sm
    ext = np.zeros((S, S), bool)
    ext[0, :] = nb[0, :]; ext[-1, :] = nb[-1, :]
    ext[:, 0] = nb[:, 0]; ext[:, -1] = nb[:, -1]
    for _ in range(600):
        nx = np.asarray(Image.fromarray((ext * 255).astype(np.uint8))
                        .filter(ImageFilter.MaxFilter(3))) > 128
        nx &= nb
        if (nx == ext).all():
            break
        ext = nx
    return np.asarray(Image.fromarray((ext * 255).astype(np.uint8))
                      .resize((CANVAS, CANVAS), Image.NEAREST)) > 128


def propagate(color, core, rounds):
    """从 core 出发做 8 邻域色传播，返回 (传播后的色场, 是否取到色)。

    用于给边缘带提供「邻近实心区的颜色 c」。
    """
    have = core.copy()
    col = np.where(core[..., None], color, 0.0)
    for _ in range(rounds):
        nx_have = have.copy()
        nx_col = col.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)):
            sh_h = np.zeros_like(have)
            sh_c = np.zeros_like(col)
            sy = slice(max(0, dy), CANVAS + min(0, dy))
            sx = slice(max(0, dx), CANVAS + min(0, dx))
            ty = slice(max(0, -dy), CANVAS + min(0, -dy))
            tx = slice(max(0, -dx), CANVAS + min(0, -dx))
            sh_h[ty, tx] = have[sy, sx]
            sh_c[ty, tx] = col[sy, sx]
            take = sh_h & ~nx_have
            nx_have |= take
            nx_col[take] = sh_c[take]
        if not (nx_have != have).any():
            break
        have, col = nx_have, nx_col
    return col, have


def silhouette():
    """几何剪影 + 参考监督剔渗色 + 孔洞填充 + 透明窗口 → (obj, filled, box)。

    ① 非白即物体（lum < T_WHITE），开运算去孤点；
    ② ★参考监督剔渗色（见 REF_KILL_HI 注释）：删掉「素材很亮、参考却暗」的像素，
       它们不是物体，是白底渗色 —— 不删就是环外那一圈白斑；
    ③ 孔洞填充只用**连通性**（与画布边连通的空白=背景，其余=孔）区分背景与孔，
       这会连环心一起算成孔 —— 所以再加**尺寸**判据：半径 > BIG_HOLE_R 的孔
       （环心 r≈168、内腔 453）保留透明，更小的（金属上的镜面反光）填回实体。

    剔掉的像素数记在模块级 LAST_BLEED_PX，供 main() 打诊断。
    """
    global LAST_BLEED_PX
    kb = Image.open(KBRAW).convert("RGB")
    nw, nh = int(round(kb.width * KB_SCALE)), int(round(kb.height * KB_SCALE))
    kba = np.asarray(kb.resize((nw, nh), KB_RESAMPLE)).astype(np.float32)
    lum = kba @ LUM

    obj = lum < T_WHITE
    o = Image.fromarray((obj * 255).astype(np.uint8))
    o = o.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    obj = np.asarray(o) > 128

    objC, box = _paste_on_canvas(obj.astype(np.float32), 0.0)
    objC = objC > 0.5

    # ★ 参考监督剔渗色：只在**画布坐标**里做（参考与素材已对齐到 IoU 0.89）
    kbc, _ = kb_on_canvas()
    lum_c = kbc @ LUM
    refc = np.asarray(Image.open(REF).convert("RGB")).astype(np.float32)
    bleed = (lum_c > REF_KILL_HI) & ((refc @ LUM) < REF_KILL_LO)
    LAST_BLEED_PX = int((objC & bleed).sum())
    objC = objC & ~bleed

    ext = external_region(objC)
    holes = (~objC) & (~ext)
    h = Image.fromarray((holes * 255).astype(np.uint8))
    k = 2 * BIG_HOLE_R + 1
    big_hole = np.asarray(h.filter(ImageFilter.MinFilter(k))
                          .filter(ImageFilter.MaxFilter(k))) > 128
    filled = holes & ~big_hole
    obj2 = objC | filled

    # 透明窗口（卡片窗口）：物理上就是透明的
    win = np.zeros((CANVAS, CANVAS), np.float32)
    x0, y0 = PL_X - WIN_PAD, PL_Y - WIN_PAD
    x1, y1 = PL_X + PL_W + WIN_PAD, PL_Y + PL_H + WIN_PAD
    win[max(0, y0):min(CANVAS, y1), max(0, x0):min(CANVAS, x1)] = 1.0
    if WIN_BLUR > 0:
        win = np.asarray(Image.fromarray((win * 255).astype(np.uint8))
                         .filter(ImageFilter.GaussianBlur(WIN_BLUR))).astype(np.float32) / 255.0
    obj2 = obj2 & (win < 0.5)
    return obj2, filled & (win < 0.5), box


def solve_matte():
    """解出 (alpha, color, filled, box)。

    v4 模型（见文件顶部说明）。关键事实（实测，别忘）：
      素材在白底照里，物体轮廓外还挂着**约 4~5px 的近白像素**（亮 251~254），
      它们是"物体×低覆盖率 + 白底"的混合，**不是物体**。参考成品同一位置是暗的
      （实测素材 x=760 亮 251 ↔ 参考同位置亮 68）→ 若把它们当物体，就是白边。

      ① 剪影 loose = (lum < T_WHITE)：故意"包多"，只用来定位物体在哪；
      ② core  = 剪影内缩 CORE_R  → 真·实体：alpha=1，color=素材原色（高光不丢）
      ③ band  = 剪影外扩 BAND_R 后去掉 core → 边缘混合带：
               a = (255-lum)/(255-c)，c 取「邻近 core 传播色」
               → 251 这类污染像素自然得到 a≈0.02，贴着物体的实心像素得到 a≈1
               → 边缘天然抗锯齿 + 精确剥掉白底污染（既不出白刺，也不出灰晕）
      ④ 物体本身就亮（c≈255）时 a 不可解 → 该处退回几何判定（剪影内=1，外=0）
    """
    obj2, filled, box = silhouette()
    kb, _ = kb_on_canvas()
    lum = kb @ LUM
    win = np.zeros((CANVAS, CANVAS), bool)
    win[PL_Y:PL_Y + PL_H, PL_X:PL_X + PL_W] = True

    o = Image.fromarray((obj2 * 255).astype(np.uint8))
    core = np.asarray(o.filter(ImageFilter.MinFilter(2 * MATTE_CORE_R + 1))) > 128
    core &= ~win
    grown = np.asarray(o.filter(ImageFilter.MaxFilter(2 * MATTE_BAND_R + 1))) > 128
    band = grown & ~core & ~win

    col_core, have_core = propagate(kb, core, rounds=MATTE_BAND_R + MATTE_CORE_R + 2)
    c_lum = col_core @ LUM
    denom = 255.0 - c_lum
    solvable = have_core & (denom > MATTE_DENOM_MIN)
    a = np.clip((255.0 - lum) / np.maximum(denom, 1.0), 0.0, 1.0)

    alpha = np.zeros((CANVAS, CANVAS), np.float32)
    alpha[core] = 1.0
    alpha[band] = np.where(solvable[band], a[band],
                           np.where(obj2[band], 1.0, 0.0))
    alpha *= (1.0 - win.astype(np.float32))

    color = kb.copy()
    m = band & solvable & (alpha > MATTE_AMIN)
    if m.any():
        a3 = alpha[m][..., None]
        color[m] = np.clip((kb[m] - 255.0 * (1.0 - a3)) / a3, 0.0, 255.0)
    color = fill_holes_color(color, alpha, filled)
    return np.clip(alpha, 0.0, 1.0), np.clip(color, 0.0, 255.0), filled, box


def material_alpha():
    """[兼容层] 只取 alpha。新代码请用 solve_matte()（一次拿到 alpha + color）。"""
    alpha, _, filled, box = solve_matte()
    return alpha, filled, box


def unmix_color(ref, base, alpha, amin=0.15):
    """由合成式精确解出实物颜色：c = (ref - base·(1-a)) / a

    ⚠️ 这个版本以「参考成品照片」为观测源，**只作诊断对比用**，生产不用：
       a=1 时它退化成 c = ref，等于把参考那张照片的每个像素（连同它的环境光
       反射、App 后处理）当成产品固有色 → 环色被冻在"深蓝环境"里。
    """
    color = ref.copy()
    ok = alpha > amin
    if ok.any():
        a3 = alpha[ok][..., None]
        color[ok] = np.clip((ref[ok] - base[ok] * (1.0 - a3)) / a3, 0.0, 255.0)
    return color


def unmix_white(kb, alpha, amin=0.15, white=255.0):
    """由「白底素材照」的成像式解出实物颜色：kb = c·a + 255·(1-a)
    ⇒  c = (kb - 255·(1-a)) / a

    a=1 时退化为 c = kb —— 也就是"产品在白光白底下的真身颜色"，
    颜色中性、不携带任何封面环境光，因此换任何封面都不会怪。
    """
    color = kb.copy()
    ok = alpha > amin
    if ok.any():
        a3 = np.where(ok, alpha, 1.0)[..., None]
        color[ok] = np.clip((kb[ok] - white * (1.0 - a3[ok])) / a3[ok], 0.0, 255.0)
    return color


def fill_holes_color(color, alpha, filled, reach=10, lo=0.5):
    """过曝高光小孔在素材里是纯 255（信息已丢失）→ 取邻近实心件的局部最亮值。

    理由：那是不锈钢环上的镜面反光，物理上不会比周围漫反射更暗；而素材里
    它被曝到纯白，只能用邻域的金属色去补，绝不能去参考照片里取（那取到的是
    环境色）。
    """
    if not filled.any():
        return color
    src = (alpha > lo) & ~filled
    if not src.any():
        return color
    chans = []
    for c in range(3):
        ch = np.where(src, color[..., c], 0.0).astype(np.uint8)
        mx = np.asarray(Image.fromarray(ch).filter(
            ImageFilter.MaxFilter(2 * reach + 1))).astype(np.float32)
        chans.append(mx)
    fill = np.dstack(chans)
    use = filled & (fill.max(-1) > 1.0)     # 邻域找不到实心件就别乱填
    return np.where(use[..., None], fill, color)


def defringe(color, alpha, protect=None, core_r=CORE_R, rounds=DEFRINGE_ROUNDS):
    """边缘去污：把轮廓附近像素的颜色换成「最近实心区的颜色」，alpha 保持不动。

    🔴 为什么必须做（2026-09-16 第四次修复的核心）
        素材是白底照，轮廓上有 1~2px 的过渡像素，颜色是"物体色 + 白底"的混合
        （实测挂耳边缘亮度从 253 一路降到 76，中间值 154 就是浅灰白）。
        几何 alpha 把它们判成「物体」(alpha=1)、颜色却仍是浅灰白 →
        贴在深色封面上就是一圈**白色锯齿毛刺**。必须把颜色换成物体自身的色。

    🔴 为什么旧的 decontaminate_edge 没救回来
        它的目标区是 alpha < 0.98 —— 而恰恰是这些"被算成 alpha=1.0 的浅灰过渡
        像素"在制造白刺，它们**整个落在目标区之外**，一个都没被处理。
        实测：旧版边缘带(alpha∈[0.98,1)) 平均亮度 181.0，比实心区 120 亮 61
        → 白边；新版降到 111.0，与实心区一致。

    做法：① 取 alpha≥0.995 再腐蚀 core_r=3 px 得到「深度实心区」（既是色源、
             又避开轮廓自身）；② 从它出发做 8 邻域色传播，覆盖整条边缘带；
          ③ 只改颜色，不动 alpha（覆盖率保持原样 → 形状与抗锯齿不变）。

    protect 里的像素（填回的过曝高光小孔）保留自己的颜色 —— 那是不锈钢的镜面
    反光，本来就该亮，不该被邻域平均色抹掉。
    """
    core = alpha >= 0.995
    if not core.any():
        return color
    k = 2 * core_r + 1
    core = np.asarray(Image.fromarray((core * 255).astype(np.uint8))
                      .filter(ImageFilter.MinFilter(k))) > 128
    if not core.any():
        return color
    tgt = (alpha > 0.02) & ~core
    if protect is not None:
        tgt = tgt & ~protect
    if not tgt.any():
        return color
    have = core.copy()
    col = np.where(core[..., None], color, 0.0)
    for _ in range(rounds):
        nx_have = have.copy()
        nx_col = col.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)):
            sh_h = np.zeros_like(have)
            sh_c = np.zeros_like(col)
            sy = slice(max(0, dy), CANVAS + min(0, dy))
            sx = slice(max(0, dx), CANVAS + min(0, dx))
            ty = slice(max(0, -dy), CANVAS + min(0, -dy))
            tx = slice(max(0, -dx), CANVAS + min(0, -dx))
            sh_h[ty, tx] = have[sy, sx]
            sh_c[ty, tx] = col[sy, sx]
            take = sh_h & ~nx_have
            nx_have |= take
            nx_col[take] = sh_c[take]
        if not (nx_have != have).any():
            break
        have, col = nx_have, nx_col
    out = color.copy()
    good = tgt & have            # 只改真正取到色的像素（避免留下黑点）
    out[good] = col[good]
    return out


def decontaminate_edge(color, alpha, lo=0.98, reach=5):
    """【已废弃 · 仅为兼容历史脚本保留】新代码请用 defringe()。

    这个版本的目标区是 alpha<0.98，漏掉了"被算成 alpha=1 的浅灰过渡像素"，
    而那正是白刺的来源 —— 所以它当年没能解决问题。
    """
    return defringe(color, alpha, core_r=2, rounds=reach)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--color-from", choices=["material", "reference"], default=COLOR_SOURCE,
                    help="取色来源（默认 material=素材白底照的真实产品色）")
    ap.add_argument("--out", default=None, help="覆盖贴片输出路径（A/B 对比用）")
    a = ap.parse_args()

    ref = np.asarray(Image.open(REF).convert("RGB")).astype(np.float32)
    P = np.asarray(Image.open(PLAYER).convert("RGB")
                   .resize((PL_W, PL_H), Image.LANCZOS)).astype(np.float32)

    # ---- 1) 学色调曲线（保留给 --curve 选项；生产默认不套）----
    log("[1] 学习播放图色调曲线（仅诊断 / 兼容 --curve）")
    ref_pl = ref[PL_Y:PL_Y + PL_H, PL_X:PL_X + PL_W]
    curves, dbg = learn_tone_curve(P, ref_pl)
    before = np.abs(gray(P) - gray(ref_pl)).mean()
    after = np.abs(gray(apply_curve(P, curves)) - gray(ref_pl)).mean()
    log("    播放图区 MAE: 原样 %.2f → 套曲线 %.2f" % (before, after))
    os.makedirs(os.path.join(ROOT, "_tmp"), exist_ok=True)
    np.save(os.path.join(ROOT, "_tmp", "lut_play.npy"), curves)

    # ---- 2) 白底成像模型反解（alpha 与 color 一次解出）----
    log("[2] 解抠像（白底成像模型：pixel = c·a + 255(1-a) ⇒ a=(255-pixel)/(255-c)）")
    kb, _ = kb_on_canvas()
    kb_lum = (kb * LUM).sum(-1)
    alpha, color, filled, box = solve_matte()
    log("    物体剪影覆盖画布 %.1f%%" % (100.0 * (alpha > 0.5).mean()))
    log("    ★参考监督剔渗色 %d px（素材>%.0f 且参考<%.0f = 白底渗色，非物体）"
        % (LAST_BLEED_PX, REF_KILL_HI, REF_KILL_LO))
    log("    过曝高光小孔填回 %d px（环带镜面反光，属实体）" % filled.sum())
    log("    内腔 alpha 均值 = %.4f（应为 0）"
        % alpha[PL_Y + 20:PL_Y + PL_H - 20, PL_X + 20:PL_X + PL_W - 20].mean())

    # ---- 3) 底图（解色与生产各一套；部件区都在清晰封面之上，取值相同）----
    base = build_base(P, dim=False)
    base_prod = build_base(P, dim=True)
    log("[3] 底图已建（来源 = %s）" % a.color_from)
    if a.color_from == "reference":
        color = defringe(unmix_color(ref, base, alpha), alpha, protect=filled)
    else:
        solid_m = alpha > 0.98
        log("    ★取色 vs 素材照：实心区 |Δ| 均值 = %.2f（应 ≈0）"
            % np.abs(color[solid_m] - kb[solid_m]).mean())

    # ---- 4) 诊断 ----
    cx0, cy0, cx1, cy1 = box[0], box[1], box[2], box[3]
    cx0, cy0 = max(0, cx0), max(0, cy0)
    cx1, cy1 = min(CANVAS, cx1), min(CANVAS, cy1)
    sub_a = alpha[cy0:cy1, cx0:cx1]
    log("[3] 诊断")
    log("    alpha: 均值=%.3f  >0.5 占比=%.1f%%  >0.9 占比=%.1f%%"
        % (sub_a.mean(), 100 * (sub_a > 0.5).mean(), 100 * (sub_a > 0.9).mean()))

    # 幽灵层：物体轮廓外 40px 之外必须完全没有 alpha
    objimg = Image.fromarray(((alpha > 0.5) * 255).astype(np.uint8))
    grown = np.asarray(objimg.filter(ImageFilter.MaxFilter(81))).astype(np.float32) > 128
    far_zone = ~grown
    log("    ★幽灵层：远处 alpha>0.02 占比 = %.4f%%（应 = 0）"
        % (100.0 * (alpha[far_zone] > 0.02).mean()))
    log("    全画布 alpha>0.02 占比 = %.2f%%（旧版 32.6%%，全是假 alpha）"
        % (100.0 * (alpha > 0.02).mean()))

    # 白描边：半透明像素只该出现在轮廓那 1px 上。
    # 旧版把遮罩外扩 3px，那条环带位于物体之外、反解色接近 255 → 环外一圈白描边。
    soft = (alpha > 0.02) & (alpha < 0.98)
    log("    ★白描边：半透明边缘 px = %d（应 ≈ 轮廓周长那 1px）" % soft.sum())

    # ★★ 本次修复的头号验收指标：轮廓带颜色亮度必须与实心区一致。
    #    旧版轮廓带(alpha∈[0.98,1)) 平均亮度 181.0 vs 实心区 120 → 亮出 61 灰阶，
    #    叠在深色封面上就是一圈白色毛刺（用户说的"周边有问题"）。
    #    新版应 ~111，与实心区同量级（差 ≤ 10）。
    solid_a = alpha >= 0.995
    edge_a = (alpha > 0.02) & ~solid_a
    if solid_a.any() and edge_a.any():
        lc = gray(color)
        ls, le = float(lc[solid_a].mean()), float(lc[edge_a].mean())
        log("    ★★轮廓带亮度 = %.1f   实心区 = %.1f   差 = %+.1f（应 ≈0；旧版 +61）"
            % (le, ls, le - ls))
    # ★★ 高光保真：素材里亮度>200（且<252.5，排除纯白背景）的物体像素必须仍然不透明。
    #    旧版用亮度算 alpha，把它们压到 0.678 → 高光被"灰化"。
    #    ⚠️ 2026-09-17 起这条不再是"应 ≈1"：其中有一部分是白底渗色，被参考监督剔除了，
    #       它们的 alpha 正确地变成 0。所以改看**留下来的那部分**是否仍然实心。
    hi = (kb_lum > 200) & (kb_lum < T_WHITE) & (alpha > 0.02)
    if hi.any():
        log("    ★★高光保真：素材亮度 200~252.5 的 px alpha 均值 = %.3f（旧版 0.678）"
            % alpha[hi].mean())

    # ★过曝高光填回：素材里纯白（kb≥253）＝**没有颜色数据**，但它可能是实体
    #   （不锈钢环上的镜面反光）。判据必须靠**连通性 + 尺寸**，不能靠亮度：
    #     · 连通到画布边的白 = 背景 → alpha=0
    #       （旧版闭运算在此误填 3765px，每张图与封面无关地多一圈蓝灰锯齿）
    #     · 被物体包住、且半径 < BIG_HOLE_R 的白 = 高光小孔 → alpha=1（填回）
    #   所以这个数字**不再要求为 0**（填回是故意的），要看的是它落在哪里：
    #   全在金属件内部 = 正常；成片出现在环的外沿 = 误填。
    no_info = (kb_lum > 253.0) & (alpha > 0.9)
    log("    ★过曝高光填回 = %d px（应全落在金属件内部；旧版在此多填 3765px 蓝灰锯齿）"
        % no_info.sum())
    if no_info.any():
        objm = Image.fromarray(((alpha > 0.5) * 255).astype(np.uint8))
        outside = np.asarray(objm.filter(ImageFilter.MaxFilter(5))) > 128
        outside &= ~(np.asarray(objm.filter(ImageFilter.MinFilter(5))) > 128)
        log("       落在轮廓外沿 2px 内的（= 误填）= %d px（应 = 0）"
            % (no_info & outside).sum())

    # 重建校验：只算「实物区」（排除透明内腔，那里故意不还原参考的卡片）
    rgba = np.dstack([color, alpha * 255.0]).astype(np.uint8)
    ca = np.asarray(Image.fromarray(rgba, "RGBA")).astype(np.float32)
    ov = ca[..., 3:4] / 255.0
    rebuilt = base_prod * (1 - ov) + ca[..., :3] * ov
    hw = np.zeros((CANVAS, CANVAS), bool)
    hw[cy0:cy1, cx0:cx1] = True
    hw[PL_Y + 8:PL_Y + PL_H - 8, PL_X + 8:PL_X + PL_W - 8] = False   # 排除内腔
    d = np.abs(gray(rebuilt) - gray(ref))
    log("    实物区 vs 参考 MAE = %.2f    差异>30 占比 = %.2f%%    差异>60 占比 = %.2f%%"
        % (d[hw].mean(), 100 * (d[hw] > 30).mean(), 100 * (d[hw] > 60).mean()))
    if a.color_from == "material":
        log("      ⚠️ 这条 MAE 现在**不再是验收指标**：参考那只钥匙扣整体比素材暗")
        log("         （环暗 43、壳体暗 13 灰阶，且环 B-R=+8.8 偏蓝），是那张照片的")
        log("         环境光 + App 后处理。刻意不复现它，MAE 自然变大。")
        log("         验收看的是下面两条：取色 vs 素材照 ≈0、假不透明 ≈0。")
    else:
        log("      取色源自参考 → 这条 MAE 会很小，但那是「抄参考」抄出来的假象。")

    # 内腔必须等于底图（透明）
    win_d = np.abs(gray(rebuilt) - gray(base_prod))
    wi = np.zeros((CANVAS, CANVAS), bool)
    wi[PL_Y + 12:PL_Y + PL_H - 12, PL_X + 12:PL_X + PL_W - 12] = True
    log("    内腔与底图偏差 |Δ| 均值 = %.3f（应 = 0，说明真的透明）" % win_d[wi].mean())

    Image.fromarray((alpha * 255).astype(np.uint8)).save(
        os.path.join(ROOT, "_tmp", "obj_mask.png"))
    Image.fromarray(rgba, "RGBA").save(os.path.join(ROOT, "_tmp", "ov_preview.png"))

    if a.report_only:
        return

    # ---- 5) 落盘 ----
    with open(OUT_CURVE, "w", encoding="utf-8") as f:
        json.dump({"note": "播放界面图色调曲线（从成品参考图逐通道实测；生产默认不套）",
                   "points": [[float(x) for x in dbg[0]], [float(y) for y in dbg[1]]],
                   "lut": [[round(float(v), 2) for v in c] for c in curves]}, f,
                  ensure_ascii=False, indent=1)
    out_overlay = a.out or OUT_OVERLAY
    Image.fromarray(rgba, "RGBA").save(out_overlay)
    log("[4] 已写出")
    log("    色调曲线 -> %s" % OUT_CURVE)
    log("    叠加贴片 -> %s  (1920×1920 RGBA)" % out_overlay)


if __name__ == "__main__":
    main()
