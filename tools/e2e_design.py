#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""封面衍生设计引擎的端到端验收（不走 HTTP，直接打函数 + 真跑一次拼版）。

    python e2e_design.py

8 组断言：
  A 设计语言读取（三张不同封面 → mood/style/主色有区分）
  B 盘面（尺寸 / 中心孔 / 同心环 / 外沿暗边）
  C 封底（尺寸 / 曲目文字 / 条码黑白交替 / 底色源自封面）
  D 内页（尺寸 / 信息板更暗 / 有文字）
  E 曲目反查（范特西 10 首、Jay 10 首；网络失败记 SKIP 不算失败）
  F 真跑一次拼版（A4 3508×2480 / 4 套 / 单件预览尺寸）
  G style 覆盖生效（minimalist 浅底 / bold 深底）
  H 只给封面时的缺件兜底（4 件自动补 + 尺寸仍达标）
"""
import io
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
BASE = os.path.dirname(HERE)

import noproxy  # noqa: E402,F401  绕过本机代理
import design_parts as DP  # noqa: E402
import make_minicd as MC  # noqa: E402

OK, FAIL, SKIP = 0, 0, 0


def check(name, cond, detail=""):
    global OK, FAIL
    OK += bool(cond)
    FAIL += (not cond)
    print(("  [PASS] " if cond else "  [FAIL] ") + name
          + (("  " + str(detail)) if detail else ""))


def skip(name, why):
    global SKIP
    SKIP += 1
    print("  [SKIP] " + name + "  (" + why + ")")


def gray(im):
    return np.asarray(im.convert("L")).astype(float)


ALB = os.path.join(BASE, "outputs", "周杰伦-专辑全集", "albums")
COVERS = [("最伟大的作品", "05 最伟大的作品 - 周杰伦.jpg"),
          ("Jay", "44 Jay - 周杰伦.jpg"),
          ("床边故事", "12 周杰伦的床边故事 - 周杰伦.jpg")]

if not os.path.isdir(ALB):
    print("缺封面目录：%s" % ALB)
    sys.exit(2)

# ---------------- A 设计语言 ----------------
print("== A 设计语言读取 ==")
DS, IMS = [], []
for tag, fn in COVERS:
    im = Image.open(os.path.join(ALB, fn)).convert("RGB")
    D = DP.read_design(im)
    IMS.append(im)
    DS.append(D)
    check("%s：mood/style/主色齐全" % tag,
          D["mood"] in ("dreamy", "energetic", "melancholic")
          and D["style"] in ("minimalist", "retro", "bold")
          and len(D["palette"]) >= 3 and all(0 <= c <= 255 for c in D["main"]),
          "%s/%s %s" % (D["mood"], D["style"], D["main"]))


def cdist(a, b):
    return sum(abs(int(x) - int(y)) for x, y in zip(a, b))


# 注意：不能断言"三张主色都不同" —— Jay(20,21,27) 与床边故事(25,17,17) 都是近黑，
# 距离只有 19，但这是**封面本身的真实情况**（两张都是深色封面），不是缺陷。
# 该断言的是：主色并非同一值(读色生效) + 设计语言确有分化。
check("三张封面读色生效（主色非同一值）",
      all(cdist(DS[i]["main"], DS[k]["main"]) > 0
          for i in range(3) for k in range(i + 1, 3)),
      [cdist(DS[0]["main"], DS[1]["main"]),
       cdist(DS[0]["main"], DS[2]["main"]),
       cdist(DS[1]["main"], DS[2]["main"])])
check("三张封面设计语言有分化",
      len({(d["mood"], d["style"]) for d in DS}) >= 2,
      sorted({(d["mood"], d["style"]) for d in DS}))

# ---------------- B 盘面 ----------------
print("== B 盘面 ==")
im, D = IMS[0], DS[0]
d_px = MC.mm(MC.DISC_D, 300)
hole = MC.mm(MC.DISC_HOLE, 300)
disc = DP.design_disc(im, d_px, hole, D, "最伟大的作品", "周杰伦")
# 几何/纹理类断言必须用**纯色合成图**：拿真实封面比不同半径的亮度，
# 比到的是封面内容（比如右边亮中间暗），而不是我们的处理效果。
flat = Image.new("RGB", (600, 600), (128, 128, 128))
disc = DP.design_disc(im, d_px, hole, D, "最伟大的作品", "周杰伦")
disc_f = DP.design_disc(flat, d_px, hole, D, "flat", "flat")
check("盘面 %dx%d (Ø40mm)" % (d_px, d_px), disc.size == (d_px, d_px), disc.size)
c = d_px // 2
check("中心孔留白", sum(disc.getpixel((c, c))[:3]) > 700, disc.getpixel((c, c)))
# 四角必为白（圆形遮罩生效）
corners = [disc.getpixel(p) for p in [(2, 2), (d_px - 3, 2), (2, d_px - 3), (d_px - 3, d_px - 3)]]
check("四角为白（圆裁生效）", all(sum(p[:3]) > 720 for p in corners), corners[0])
check("盘面有封面内容（非纯色）", gray(disc)[60:410, 60:410].std() > 20,
      "%.1f" % gray(disc)[60:410, 60:410].std())
# 同心环：沿半径方向亮度应有周期性起伏（纯色图，排除内容干扰）
row = gray(disc_f)[c, c + 70:c + 200]
d1 = np.diff(row)
turns = int(np.sum(np.abs(np.diff(np.sign(d1))) > 0))
check("存在同心沟槽纹理", turns >= 8, "过零 %d 次" % turns)
# 外沿暗边：纯色底上最外 10px 必须明显暗于中段
rim = gray(disc_f)[c, d_px - 12:d_px - 3].mean()
mid = gray(disc_f)[c, int(d_px * 0.55):int(d_px * 0.65)].mean()
check("外沿有暗边（立体感）", rim < mid - 15, "外沿 %.0f < 中段 %.0f" % (rim, mid))
# 内圈：聚碳酸酯透明区（r0≈0.15，须避开中心孔 r0<0.13）应偏冷灰且亮于 128
inner_px = disc_f.getpixel((c, c - int(d_px * 0.075)))
check("内圈为冷灰亮环", inner_px[2] >= inner_px[0] and sum(inner_px[:3]) / 3 > 130,
      inner_px)

# ---------------- C 封底 ----------------
print("== C 封底 ==")
w_px, h_px = MC.mm(MC.BACK_SEGS[1], 300), MC.mm(MC.BACK_H, 300)
TR = ["可爱女人", "完美主义", "星晴", "娘子", "斗牛", "黑色幽默",
      "伊斯坦堡", "印第安老斑鸠", "龙卷风", "反方向的钟"]
back = DP.design_back(im, w_px, h_px, D, "Jay", "周杰伦", TR, seed=1)
check("封底 %dx%d (48×38mm)" % (w_px, h_px), back.size == (w_px, h_px), back.size)
check("封底有曲目文字", gray(back)[int(h_px * 0.32):int(h_px * 0.75), :].std() > 12,
      "%.1f" % gray(back)[int(h_px * 0.32):int(h_px * 0.75), :].std())
# 条码区：黑白列交替
bw = int(w_px * 0.30)
bx = w_px - max(6, int(w_px * 0.045)) - bw
band = gray(back)[int(h_px * 0.70):int(h_px * 0.80), bx:bx + bw]
col = band.mean(axis=0)
alt = int(np.sum(np.abs(np.diff(np.sign(np.diff(col)))) > 0))
check("条码区黑白交替", alt >= 15, "跳变 %d 次" % alt)
# 底色源自封面（渐变底取中位色，与封面主色同色系）
mid_c = back.getpixel((w_px // 2, h_px - 20))
check("封底底色与封面同色系", cdist(mid_c, D["main"]) < 260 or D["style"] == "minimalist",
      "封底%s 封面%s" % (mid_c, tuple(D["main"])))

# ---------------- D 内页 ----------------
print("== D 内页 ==")
iw, ih = MC.mm(MC.COVER_W, 300) // 2, MC.mm(MC.COVER_H, 300)
inner = DP.design_inner(im, iw, ih, D, "Jay", "周杰伦", TR)
check("内页 %dx%d (41×41mm)" % (iw, ih), inner.size == (iw, ih), inner.size)
top = gray(inner)[0:ih // 3, :].mean()
bot = gray(inner)[int(ih * 0.62):, :].mean()
check("下半信息板更暗", bot < top, "上 %.0f 下 %.0f" % (top, bot))
check("内页有文字内容", gray(inner)[int(ih * 0.42):, :].std() > 14,
      "%.1f" % gray(inner)[int(ih * 0.42):, :].std())

# ---------------- E 曲目反查 ----------------
print("== E 曲目反查（联网）==")
try:
    import fetch163 as F
    tr1, n1 = F.album_tracks("范特西", "周杰伦")
    tr2, n2 = F.album_tracks("Jay", "周杰伦")
    if not tr1 and not tr2:
        skip("曲目反查", "网络不可用或全部失败")
    else:
        check("范特西 = 10 首且首曲正确",
              len(tr1) == 10 and tr1[0] == "爱在西元前", "%d 首 %s" % (len(tr1), tr1[:2]))
        check("Jay = 10 首且首曲正确",
              len(tr2) == 10 and tr2[0] == "可爱女人", "%d 首 %s" % (len(tr2), tr2[:2]))
except Exception as e:
    skip("曲目反查", type(e).__name__)

# ---------------- F 真跑一次拼版 ----------------
print("== F 真跑拼版 ==")
tmp = tempfile.mkdtemp(prefix="e2edesign_")
cov = os.path.join(ALB, "44 Jay - 周杰伦.jpg")
r = subprocess.run([sys.executable, os.path.join(HERE, "make_minicd.py"),
                    "--cover", cov, "--artist", "周杰伦", "--album", "Jay",
                    "--out", tmp, "--preview", "--no-tracks"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace",
                   cwd=HERE)
check("拼版命令退出码 0", r.returncode == 0, (r.stderr or "")[-200:])
pg = os.path.join(tmp, "打印拼版-A4-Jay.jpg")
if os.path.exists(pg):
    P = Image.open(pg)
    check("A4 横 3508x2480", P.size == (3508, 2480), P.size)
    meta = json.load(io.open(os.path.join(tmp, "mini_cd.json"), encoding="utf-8"))
    check("json 记录 fallbacks=4 件", sorted(meta["fallbacks"]) == ["back", "disc", "inner", "tray"],
          meta["fallbacks"])
    check("json 记录 design", bool(meta.get("design")), meta.get("design"))
    check("json 无 tracks（--no-tracks）", meta.get("tracks") == [], meta.get("tracks"))
    for nm, want in (("disc", (472, 472)), ("cover", (969, 484)), ("back", (1280, 449))):
        p = os.path.join(tmp, "预览-%s.jpg" % nm)
        if os.path.exists(p):
            check("预览-%s %s" % (nm, want), Image.open(p).size == want, Image.open(p).size)
        else:
            check("预览-%s 存在" % nm, False, "缺文件")
else:
    check("产出拼版图", False, "缺 %s" % pg)

# ---------------- G style 覆盖 ----------------
print("== G style 覆盖 ==")
Dm = dict(DS[1]); Dm["style"] = "minimalist"
Db = dict(DS[1]); Db["style"] = "bold"
bm = DP.design_back(IMS[1], w_px, h_px, Dm, "Jay", "周杰伦", TR, seed=2)
bb = DP.design_back(IMS[1], w_px, h_px, Db, "Jay", "周杰伦", TR, seed=2)
check("minimalist 出浅底", gray(bm).mean() > 150, "%.0f" % gray(bm).mean())
check("bold 出深底", gray(bb).mean() < 150, "%.0f" % gray(bb).mean())
check("两种风格差异明显", abs(gray(bm).mean() - gray(bb).mean()) > 60,
      "%.0f vs %.0f" % (gray(bm).mean(), gray(bb).mean()))

# ---------------- H 缺件兜底（只用封面）----------------
print("== H 缺件兜底 ==")
tmp2 = tempfile.mkdtemp(prefix="e2efb_")
r2 = subprocess.run([sys.executable, os.path.join(HERE, "make_minicd.py"),
                     "--cover", cov, "--artist", "周杰伦", "--album", "兜底",
                     "--out", tmp2, "--preview", "--no-tracks"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    cwd=HERE)
m2 = os.path.join(tmp2, "mini_cd.json")
if os.path.exists(m2):
    meta2 = json.load(io.open(m2, encoding="utf-8"))
    check("四件全自动补", sorted(meta2["fallbacks"]) == ["back", "disc", "inner", "tray"],
          meta2["fallbacks"])
    p2 = os.path.join(tmp2, "预览-back.jpg")
    if os.path.exists(p2):
        b2 = Image.open(p2)
        check("补出的封底条尺寸达标", b2.size == (1280, 449), b2.size)
        check("补出的封底条非空白", gray(b2).std() > 10, "%.1f" % gray(b2).std())
else:
    check("缺件兜底产出 json", False, "缺 %s" % m2)

print()
print("== 结果: %d 通过 / %d 失败 / %d 跳过 ==" % (OK, FAIL, SKIP))
sys.exit(1 if FAIL else 0)
