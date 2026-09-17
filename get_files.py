# -*- coding: utf-8 -*-
# =============================================================================
#  K230 一键取文件脚本（不用拔 SD 卡、不用读卡器）
# -----------------------------------------------------------------------------
#  原理：
#      1) 你电脑上起一个简单的 HTTP 服务（一条命令，见下面"电脑上做什么"）
#      2) 板子跑这个脚本，通过 WiFi 把你电脑上准备好的文件拉下来，
#         自动放到正确的目录里
#
#  【电脑上做什么】
#      要传的文件已经整理好，就在这个文件夹里（结构和 SD 卡一致）：
#          D:\ai_project_tree\230\sdcard_upload\
#              └── kmodel\best.kmodel
#      在那个文件夹里执行：
#          python -m http.server 8001   （我这边已经起好了）
#      （PC_IP 我已经帮你填成这台电脑 WLAN 的地址了）
#
#  【板子上做什么】
#      1) 填好下面的 WiFi
#      2) CanMV IDE 打开本文件，点运行（IDE 会自动把脚本发给板子执行）
#      3) 等它打印"全部完成"，就可以去跑 main.py 了
#
#  这个脚本做的事：
#      /sdcard/kmodel/best.kmodel     ← 从电脑拉（11.9MB，走 WiFi 大概几十秒）
#
#  注意：如果连不上电脑，多半是 Windows 防火墙挡了 8000 端口。
#        这时改用 board_recv.py（方向反过来：板子起服务、电脑推文件），一定通。
# =============================================================================

import os
import gc
import time
import socket
import network

# ============================ ★ 要改的地方 ============================
PC_IP = "192.168.186.197"      # 你电脑 WLAN 的 IPv4（已自动填好）
PC_PORT = 8001                 # 和电脑上 python -m http.server 8001 的端口一致

WLAN_SSID = "your_wifi_ssid"   # ★ 板子要连的 WiFi（2.4G，和电脑同一个网）
WLAN_PASS = "your_wifi_pass"
# =====================================================================

# 要拉的文件：(电脑上的路径, 板子上的保存路径)
# 注：AI 库(AIBase/AI2D/PipeLine)亚博镜像里已经自带在 /sdcard/libs/ 了，不用传
FILES = [
    ("kmodel/best.kmodel", "/sdcard/kmodel/best.kmodel"),
]

CHUNK = 4096                   # 每次读 4KB 写盘，避免一次占用大内存


def make_dirs(path):
    """像 mkdir -p 一样逐级建目录（MicroPython 没有 makedirs）"""
    parts = [p for p in path.split("/") if p]      # ['sdcard','app','libs']
    cur = ""
    for p in parts:
        cur = cur + "/" + p
        try:
            os.mkdir(cur)
            print("   新建目录:", cur)
        except OSError:
            pass                                    # 已存在，忽略


def connect_wifi():
    """连 WiFi，返回 IP"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("正在连接 WiFi:", WLAN_SSID)
        wlan.connect(WLAN_SSID, WLAN_PASS)
        for _ in range(150):                        # 最多等 15 秒
            if wlan.isconnected():
                break
            time.sleep_ms(100)
    if not wlan.isconnected():
        raise Exception("WiFi 连不上：检查 SSID/密码，确认是 2.4G")
    ip = wlan.ifconfig()[0]
    print("WiFi 已连接, 板子 IP =", ip)
    return ip


def http_get(remote_path, local_path):
    """
    用最原始的 socket 发一个 HTTP GET，把响应体流式写入文件。
    不用 urequests，是因为固件不一定带这个库，socket 一定有。
    返回写入的字节数。
    """
    s = socket.socket()
    s.settimeout(20)
    try:
        s.connect((PC_IP, PC_PORT))
    except OSError as e:
        raise Exception("连不上电脑 %s:%d —— 检查 PC_IP 对不对、电脑上 http.server 起了没、"
                        "电脑防火墙是否拦了 8000 端口 (%s)" % (PC_IP, PC_PORT, e))

    # 发请求（HTTP/1.0 + Connection: close，服务器发完就断开，方便我们读到 EOF）
    req = ("GET /%s HTTP/1.0\r\nHost: %s\r\nConnection: close\r\n\r\n"
           % (remote_path, PC_IP))
    s.send(req.encode())

    # --- 先读 HTTP 响应头（读到空行为止）---
    head = b""
    while b"\r\n\r\n" not in head:
        d = s.recv(512)
        if not d:
            raise Exception("连接被中断（还没读到响应头）")
        head += d
    header, rest = head.split(b"\r\n\r\n", 1)

    status = header.split(b"\r\n")[0].decode()
    if "200" not in status:
        raise Exception("服务器返回: %s （文件是不是没放在 sdcard_upload 里？）" % status)

    # 解析总长度，便于打印进度
    total = 0
    for line in header.split(b"\r\n"):
        l = line.lower()
        if l.startswith(b"content-length:"):
            total = int(line.split(b":")[1])

    # --- 收响应体，边收边写盘 ---
    written = len(rest)
    f = open(local_path, "wb")
    try:
        f.write(rest)
        last_report = 0
        while True:
            if total and written >= total:
                break
            d = s.recv(CHUNK)
            if not d:
                break
            f.write(d)
            written += len(d)
            if written - last_report >= 512 * 1024:      # 每 512KB 报一次进度
                last_report = written
                if total:
                    print("      %.1f%%  (%d/%d KB)" % (written * 100.0 / total,
                                                        written // 1024, total // 1024))
                else:
                    print("      已收 %d KB" % (written // 1024))
    finally:
        f.close()
        s.close()
    return written


def main():
    print("=" * 62)
    print("  K230 一键取文件：从电脑 %s:%d 拉取文件到 SD 卡" % (PC_IP, PC_PORT))
    print("=" * 62)

    connect_wifi()

    # 目标目录先建好
    make_dirs("/sdcard/kmodel")

    ok = 0
    for remote, local in FILES:
        print("\n>>> %s  ->  %s" % (remote, local))
        try:
            t0 = time.ticks_ms()
            n = http_get(remote, local)
            ms = time.ticks_diff(time.ticks_ms(), t0)
            # 复查一下文件真的在、大小对得上
            size = os.stat(local)[6]
            print("   完成: %d 字节 (%.1f 秒)" % (n, ms / 1000.0))
            if size != n:
                print("   [警告] 磁盘上的大小(%d)和收到的不一致，可能是 SD 卡空间不够" % size)
                continue
            ok += 1
        except Exception as e:
            print("   [失败]", e)
        gc.collect()

    print("\n" + "=" * 62)
    if ok == len(FILES):
        print("全部完成（%d/%d）！现在可以去运行 main.py 了" % (ok, len(FILES)))
    else:
        print("成功 %d/%d，失败的按上面的提示处理后重跑本脚本即可" % (ok, len(FILES)))
    print("=" * 62)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("用户停止")
    except BaseException as e:
        import sys
        print("!!! 异常:", type(e).__name__, ":", e)