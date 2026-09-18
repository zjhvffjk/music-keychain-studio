# -*- coding: utf-8 -*-
"""歌词清洗验收（离线判据 + 在线抽样）。

背景：网易云的 LRC 开头常带一整块**制作名单**（词/曲/编曲/制作人/录音师/母带…），
这些行冒号后面有内容，只按「整行以冒号结尾」过滤根本拦不住 ——
实测《蓄谋已久的爱》《昨天》前 10~13 行全是名单，会被当歌词印上歌词页，
还可能被 pick_quote 挑去当「手写金句」。

本脚本只用**纯函数**做主判据（不依赖网络），再补一轮在线抽样。

用法：python tools/e2e_lyrics.py            # 判据 + 在线（失败不致命）
      python tools/e2e_lyrics.py --offline  # 只跑判据
"""
from __future__ import annotations

import argparse
import os
import sys

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.abspath("tools"))

import fetch163 as F  # noqa: E402

PASS = FAIL = 0
FAILS: list[str] = []


def ck(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [ OK ] %s" % name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s   %s" % (name, detail))


# (原文, 期望是否判为「制作名单/署名」)
CASES = [
    # ---- 真名单：必须丢 ----
    ("词：林乔/黄然", True),
    ("曲：都智文", True),
    ("制作人：林乔", True),
    ("编曲：都智文", True),
    ("人声编辑：耿潇微", True),
    ("配唱：张格/田默忱", True),
    ("和声：谢汶宸", True),
    ("吉他：KenChan陈恩健", True),
    ("贝斯：赵伟鑫", True),
    ("鼓：陈柏州", True),
    ("混音/母带：龚耀华Chris", True),
    ("录音师 : 杨瑞代", True),            # 半角冒号 + 空格（结构判据）
    ("混音师 : 黄雨勋", True),
    ("小提琴 : 陈锐", True),
    ("长号 : 鄧世伟", True),
    ("录音室 : JVR Studio", True),
    ("录音室：JVR Studio", True),         # 全角冒号（后缀归一化判据）
    ("录音棚：顾潇予音乐工作室", True),
    ("音乐监制：连雅雯", True),            # 「音乐」前缀（字段名 endswith 判据）
    ("音乐统筹：张安琪/李爽", True),
    ("音乐发行：张安琪", True),
    ("音乐出品：华策音乐（天津）有限公司", True),
    ("制作团队：VNTA", True),
    ("和声演唱：小雪人", True),
    ("制作公司：仁溪音乐", True),
    ("SCRATCH：郭正男", True),            # 英文缩写字段名
    ("With : 阿信@五月天", True),
    ("班卓琴 : 周杰伦", True),
    ("蓄谋已久的爱 (《你是迟来的欢喜》电视剧片头曲) - 颜人中", True),
    ("纯音乐，请欣赏", True),
    ("此歌曲为没有填词的纯音乐", True),
    # ---- 真歌词：绝不能丢 ----
    ("窗台的花 绽放开", False),
    ("古巴比伦王颁布了汉谟拉比法典", False),
    ("哥穿着复古西装", False),
    ("曲终人散：都是你", False),           # 单字关键字只能精确匹配
    ("她说：我不爱你了", False),           # 中文名+冒号+中文 → 不是对唱标注
    ("I love you - but I don't know", False),  # 英文歌词里的 " - " 不能当署名行
    ("你说：sorry", False),               # 中文头+拉丁但太短 → 不剥
    ("合：La la la la la la la la", False),   # 『合』是对唱标记不是名单
]

# (原文, 期望剥出来的歌词) —— 对唱标注要「剥掉歌手名、留下词」
DUET_CASES = [
    ("（周杰伦：这个时候）", "这个时候"),
    ("(Jay: Let's go)", "Let's go"),
    ("小派：You always have to do something", "You always have to do something"),
    ("Jay：这世界有些事有些人凭感觉", "这世界有些事有些人凭感觉"),
    ("合：La la la la la la la la", "La la la la la la la la"),
    ("窗台的花 绽放开", "窗台的花 绽放开"),        # 原样返回
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()

    print("=" * 72)
    print("A. 制作名单判据（纯函数，离线）")
    for t, exp in CASES:
        got = F._is_credit_line(t)
        ck("%-40s → %s" % (t[:40], "名单" if exp else "歌词"), got == exp,
           "got=%s want=%s" % (got, exp))

    print("=" * 72)
    print("B. 对唱标注剥离（纯函数，离线）")
    for t, exp in DUET_CASES:
        got = F._clean_lyric_line(t)
        ck("%-40s → %s" % (t[:40], got[:24]), got == exp,
           "got=%r want=%r" % (got, exp))

    print("=" * 72)
    print("C. 顺序陷阱：剥标注必须先过名单（否则名单被剥成歌词）")
    # 「吉他：KenChan陈恩健」若先剥对唱标注会成「KenChan陈恩健」贴进歌词页
    for t in ("吉他：KenChan陈恩健", "录音棚：顾潇予音乐工作室"):
        ck("先判名单：%s" % t, F._is_credit_line(t), "应为名单")

    if a.offline:
        print("=" * 72)
        print("（--offline：跳过在线抽样）")
    else:
        print("=" * 72)
        print("D. 在线抽样：真实专辑里不能再有冒号残留")
        try:
            import noproxy  # noqa: F401
            import json
            js = json.load(open("outputs/周杰伦-专辑全集/albums.json", encoding="utf-8"))
            total, susp = 0, []
            for al in js["albums"][:20]:
                for nm, lines in F.album_lyrics(al["name"], "周杰伦", al.get("id"),
                                                max_songs=2):
                    for ln in lines:
                        total += 1
                        if "：" in ln or ":" in ln:
                            susp.append((al["name"], nm, ln))
            ck("周杰伦 20 张歌词里无冒号残留（共 %d 行）" % total, not susp,
               str(susp[:3]))
            ck("抽样量够（>500 行）", total > 500, str(total))
            got = F.album_lyrics("你是迟来的欢喜", "颜人中", 368505591, max_songs=1)
            if got:
                ls = got[0][1]
                ck("OST 首行不是名单（%s）" % got[0][0],
                   not F._is_credit_line(ls[0]), repr(ls[0][:40]))
                ck("OST 歌词行数合理（30~60）", 30 <= len(ls) <= 60, str(len(ls)))
                # 原版《蓄谋已久的爱》有 13 行名单，修好后必然少一截
                ck("OST 已剔掉名单块（<46 行）", len(ls) < 46, str(len(ls)))
        except Exception as e:  # noqa: BLE001
            print("  [SKIP] 在线抽样（网络不可用：%s）" % e)

    print("=" * 72)
    print("== 结果: %d 通过 / %d 失败 ==" % (PASS, FAIL))
    if FAILS:
        print("失败项： " + "、".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
