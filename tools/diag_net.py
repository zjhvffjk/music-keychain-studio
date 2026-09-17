# -*- coding: utf-8 -*-
"""诊断：工作台为什么突然 404 / 连不上。

只读，不改任何系统设置。检查三件事：
1. 系统代理是否开启、绕过列表里有没有 127.0.0.1
2. 是否有 TUN / 虚拟网卡在接管流量（TUN 模式会无视绕过列表）
3. 工作台服务本身是否活着、返回什么
"""
import json
import os
import socket
import subprocess
import sys
import urllib.request

try:
    import winreg
except ImportError:
    winreg = None

PORT = int(os.environ.get("MINUET_PORT") or 8765)
BAR = "-" * 62


def read_proxy_reg():
    """读 IE/系统代理设置。这是浏览器真正读的那份配置。"""
    out = {}
    if not winreg:
        return out
    key = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            for name in ("ProxyEnable", "ProxyServer", "ProxyOverride",
                         "AutoConfigURL"):
                try:
                    v, _ = winreg.QueryValueEx(k, name)
                    out[name] = v
                except FileNotFoundError:
                    out[name] = None
    except OSError as e:
        out["_error"] = str(e)
    return out


def check_bypass(override):
    """绕过列表里有没有把本地地址排除掉。"""
    if not override:
        return False, "绕过列表为空"
    s = str(override).lower()
    hits = []
    if "<local>" in s:
        hits.append("<local>")
    for pat in ("127.0.0.1", "127.*", "localhost", "0.0.0.0"):
        if pat in s:
            hits.append(pat)
    return bool(hits), ", ".join(hits) if hits else "未包含任何本地地址"


def list_adapters():
    """找出疑似 TUN / 虚拟网卡。TUN 模式会绕过一切代理绕过设置。"""
    ps = (
        "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | "
        "ForEach-Object { $_.Name + '|' + $_.InterfaceDescription }"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, timeout=25)
        txt = r.stdout.decode("utf-8", "replace")
    except Exception as e:
        return [], str(e)
    bad = []
    for line in txt.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        name, desc = line.split("|", 1)
        blob = (name + " " + desc).lower()
        if any(k in blob for k in ("tun", "tap", "wintun", "mihomo",
                                   "clash", "wireguard", "singbox",
                                   "sing-box", "virtual")):
            bad.append(f"{name}  ({desc})")
    return bad, None


def probe_server(port):
    """服务活着吗？返回体是什么？"""
    url = f"http://127.0.0.1:{port}/api/ping"
    try:
        with urllib.request.urlopen(url, timeout=4) as r:
            return r.status, r.read(200).decode("utf-8", "replace")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def port_listening(port):
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main():
    print(BAR)
    print("  工作台网络诊断")
    print(BAR)

    print("\n[1] 本机服务状态")
    print(f"    127.0.0.1:{PORT} 可连接: {port_listening(PORT)}")
    st, body = probe_server(PORT)
    print(f"    /api/ping  -> HTTP {st}")
    print(f"    响应体      -> {body[:160]}")

    print("\n[2] 系统代理（浏览器实际读取的配置）")
    reg = read_proxy_reg()
    if reg.get("_error"):
        print(f"    读取失败: {reg['_error']}")
    enabled = reg.get("ProxyEnable")
    server = reg.get("ProxyServer")
    override = reg.get("ProxyOverride")
    auto = reg.get("AutoConfigURL")
    print(f"    ProxyEnable   : {enabled}  ({'开启' if enabled else '关闭'})")
    print(f"    ProxyServer   : {server}")
    print(f"    ProxyOverride : {override}")
    print(f"    AutoConfigURL : {auto}")
    ok, why = check_bypass(override)
    if enabled and server and not ok:
        print(f"    >>> 风险: 系统代理已开启，但没有绕过本地地址（{why}）")
        print("        浏览器访问 127.0.0.1 会被送到代理节点，")
        print("        代理不认识这个地址，就会回一个空的 404。")
    elif enabled and server:
        print(f"    >>> 绕过列表已含本地地址（{why}），系统代理层面应无问题")
    else:
        print("    >>> 系统代理未开启")

    print("\n[3] TUN / 虚拟网卡（会无视上面的绕过列表）")
    bad, err = list_adapters()
    if err:
        print(f"    检测失败: {err}")
    elif bad:
        for b in bad:
            print(f"    >>> 发现: {b}")
        print("        TUN 模式在网络层劫持全部流量，代理绕过列表对它无效。")
    else:
        print("    未发现活动中的 TUN / 虚拟网卡")

    print("\n[4] 代理类进程")
    for exe in ("clash-verge-service.exe", "verge-mihomo.exe",
                "v2rayN.exe", "xray.exe", "sing-box.exe"):
        try:
            r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe}"],
                               capture_output=True, timeout=15)
            t = r.stdout.decode("utf-8", "replace")
            if exe.lower() in t.lower():
                print(f"    运行中: {exe}")
        except Exception:
            pass

    print("\n" + BAR)
    print("  结论")
    print(BAR)
    if st == 200 and enabled and server and not ok:
        print("  服务没问题，是系统代理把浏览器到 127.0.0.1 的请求劫持了。")
        print("  修复：把 127.0.0.1 加进代理绕过，或关掉其中一个代理工具。")
        print("  一键修复： python tools\\fix_net.py")
    elif st == 200:
        print("  服务正常。若浏览器仍异常，多为页面缓存，Ctrl+F5 强刷。")
    else:
        print("  服务没响应，先重启工作台： 启动工作台.bat --force")
    print(BAR)


if __name__ == "__main__":
    main()
