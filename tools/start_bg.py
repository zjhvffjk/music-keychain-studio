# -*- coding: utf-8 -*-
"""以「脱离父子关系」的方式启动工作台服务。

背景：用 shell 的后台方式起服务时，进程绑在当前会话上，会话一结束就被回收。
用户感受到的就是「刚才还能用，过一会儿点了没反应」。

这里用 Windows 的 DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP 让服务
彻底独立，stdin/stdout/stderr 全部重定向到文件，父进程退出不影响它。

用法：
    python tools/start_bg.py            # 有实例则复用，不会重复起
    python tools/start_bg.py --force    # 结束旧实例后重启
"""
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
BOOT_LOG = os.path.join(ROOT, "workbench", "server_boot.log")
PORT = int(os.environ.get("MINUET_PORT") or 8765)

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
# 不要加 CREATE_NO_WINDOW：它要求进程自带控制台，与 DETACHED_PROCESS
# （不要控制台）语义冲突，两者同用时子进程会**静默启动失败**（stdout
# 一个字节都没有，日志里也看不到任何启动记录），极难排查。


def _detach_kwargs():
    """按平台给出「脱离父进程」的启动参数。"""
    if os.name == "nt":
        return dict(creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                    close_fds=True)
    # POSIX（Linux/macOS）：开新会话即可，父进程退出不影响它
    return dict(start_new_session=True, close_fds=True)


def ping(port, timeout=1.5):
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/ping", timeout=timeout) as r:
            import json
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def main():
    force = "--force" in sys.argv

    cur = ping(PORT)
    old_pid = (cur or {}).get("pid")
    if cur and not force:
        print(f"已有实例在运行：pid={old_pid} 版本={cur.get('version')}")
        print("（要强制重启加 --force）")
        return
    if cur and force:
        print(f"结束旧实例 pid={old_pid} …")

    args = [PY, os.path.join(ROOT, "workbench", "server.py"),
            "--no-browser", "--force"]
    with open(BOOT_LOG, "ab") as lf:
        lf.write(("\n--- %s  detached start ---\n"
                  % time.strftime("%Y-%m-%d %H:%M:%S")).encode("utf-8"))
        subprocess.Popen(
            args, cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=lf, stderr=subprocess.STDOUT,
            **_detach_kwargs())

    # 判定「起来了」必须看 pid 变了 —— 只看 ping 通会把旧实例误判成新实例
    # （旧实例在被杀掉之前照样能响应，于是脚本谎报成功）。
    for _ in range(60):
        time.sleep(0.25)
        info = ping(PORT)
        if info and info.get("pid") != old_pid:
            print(f"已启动（脱离式）：pid={info.get('pid')} "
                  f"版本={info.get('version')} 端口={info.get('port')}")
            print(f"地址 http://127.0.0.1:{PORT}/")
            print("该进程不随当前会话结束而退出。")
            return
    print("启动失败（pid 没变或没起来），请看 workbench/server_boot.log")


if __name__ == "__main__":
    main()
