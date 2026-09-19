# -*- coding: utf-8 -*-
"""e2e 脚本共用的小工具。

目前只有一样：**版本号比较**。

🔴 为什么非要单独一个函数：`"1.11.0" >= "1.8.0"` 在 Python 里是 **False**
   —— 字符串是逐字符比的，"1" < "8"。于是版本号每跳到一个两位数段
   （1.9 → 1.10 → 1.11），各个 e2e 里的「版本 >= x」都会假报失败，
   看起来像真回归，实际是断言写错了。
   这个坑已经踩过三次（e2e_album / e2e_vinyl / e2e_keychain），
   所以抽出来共用 —— 别再抄第四份。
"""


def ver_tuple(s):
    """版本号字符串 → 整数元组。非数字段按 0 算（`1.9.0rc1` 这类尾巴不炸）。"""
    out = []
    for x in str(s or "0").split("."):
        try:
            out.append(int(x))
        except ValueError:
            out.append(0)
    return tuple(out)


def ver_ok(version, want):
    """`version >= want`？两边都先转成整数元组再比，绕开字符串逐字符比较。"""
    return ver_tuple(version) >= tuple(want)
