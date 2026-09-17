# -*- coding: utf-8 -*-
# =============================================================================
#  K230 文件接收器（电脑把文件"推"到板子上，不用拔卡、不用读卡器）
# -----------------------------------------------------------------------------
#  为什么用这个方向？
#      "板子去电脑拉"要经过 Windows 防火墙（默认挡入站，且你这个网络配置下
#      Python 的放行规则不生效）；而"电脑推给板子"时，板子这边没有任何防火墙，
#      电脑是主动发起连接的一方，所以一定通。
#
#  【怎么用】
#      1) 填好下面的 WLAN_SSID / WLAN_PASS（2.4G，和电脑同一个 WiFi）
#      2) CanMV IDE 打开本文件 → 点绿色三角运行（IDE 会把脚本发给板子执行）
#      3) 看串口终端打印的这行：
#             >>> 板子 IP = 192.168.x.x  端口 8080 已就绪，等电脑推文件...
#         把这个 IP 告诉我（或自己用电脑执行下面的命令推）：
#             curl.exe -T "D:\ai_project_tree\yolo\runs\detect\crop_pest_final\weights\best.kmodel" http://192.168.x.x:8080/upload
#      4) 传完脚本会打印 "接收完成 ✅"，然后就可以去跑 main.py 了
#
#  这个脚本做的事：
#      在 8080 端口起一个极简 HTTP 服务：
#        GET  /          → 回一行字，用来测试电脑能不能连上板子
#        PUT  /upload    → 把请求体（文件内容）流式写入 /sdcard/kmodel/best.kmodel
# =============================================================================

import os
import gc
import time
import socket
import network

# ============================ ★ 要改的地方 ============================
WLAN_SSID = "your_wifi_ssid"     # ★ 板子连的 WiFi（2.4G，和电脑同一个）
WLAN_PASS = "your_wifi_pass"
# =====================================================================

PORT = 8080                                   # 板子监听端口
SAVE_AS = "/sdcard/kmodel/best.kmodel"        # 收到的文件存到这里（会覆盖同名文件）
CHUNK = 4096                                  # 每次读写 4KB，避免大内存占用


def connect_wifi():
    """连 WiFi，返回板子 IP"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("正在连接 WiFi:", WLAN_SSID)
        wlan.connect(WLAN_SSID, WLAN_PASS)
        for _ in range(150):                  # 最多等 15 秒
            if wlan.isconnected():
                break
            time.sleep_ms(100)
    if not wlan.isconnected():
        raise Exception("WiFi 连不上：检查 SSID/密码，确认是 2.4G 频段")
    ip = wlan.ifconfig()[0]
    print("WiFi 已连接, 板子 IP =", ip)
    return ip


def make_dirs(path):
    """逐级建目录（MicroPython 没有 makedirs）"""
    parts = [p for p in path.split("/") if p]
    cur = ""
    for p in parts:
        cur = cur + "/" + p
        try:
            os.mkdir(cur)
            print("   新建目录:", cur)
        except OSError:
            pass                              # 已存在


def read_headers(conn):
    """读到 HTTP 请求头结束（\r\n\r\n），返回请求头字符串"""
    buf = b""
    while b"\r\n\r\n" not in buf and len(buf) < 8192:
        d = conn.recv(512)
        if not d:
            break
        buf += d
    head, _, rest = buf.partition(b"\r\n\r\n")
    return head.decode(errors="replace"), rest


def handle_one(conn):
    """处理一个连接"""
    head, body_start = read_headers(conn)
    first_line = head.split("\r\n")[0] if head else ""
    print("收到请求:", first_line)

    # --- 简单探活：GET / ---
    if first_line.startswith("GET"):
        msg = b"K230 ready. Use: PUT /upload\r\n"
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: "
                     + str(len(msg)).encode() + b"\r\nConnection: close\r\n\r\n" + msg)
        return

    # --- 接收文件：PUT/POST /upload ---
    if not (first_line.startswith("PUT") or first_line.startswith("POST")):
        conn.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
        return

    # 从请求头里取总长度
    total = 0
    for line in head.split("\r\n"):
        if line.lower().startswith("content-length:"):
            total = int(line.split(":", 1)[1].strip())

    print("开始接收，大小: %.2f MB" % (total / 1048576.0))
    written = 0
    f = open(SAVE_AS, "wb")
    try:
        # 请求头后面可能已经跟了一部分 body
        if body_start:
            f.write(body_start)
            written += len(body_start)
        last = 0
        while True:
            if total and written >= total:
                break
            d = conn.recv(CHUNK)
            if not d:
                break
            f.write(d)
            written += len(d)
            if written - last >= 512 * 1024:          # 每 512KB 报一次
                last = written
                if total:
                    print("   %.1f%%  (%d/%d KB)" % (written * 100.0 / total,
                                                     written // 1024, total // 1024))
    finally:
        f.close()

    # 校验大小
    try:
        size = os.stat(SAVE_AS)[6]
    except Exception:
        size = written

    if total and size == total:
        print("接收完成 ✅  %d 字节  ->  %s" % (size, SAVE_AS))
        print("现在可以去运行 main.py 了")
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
    else:
        print("接收不完整 ❌ 收到 %d / 期望 %d 字节" % (size, total))
        conn.sendall(b"HTTP/1.1 500 Error\r\nContent-Length: 5\r\n\r\nFAIL\n")


def main():
    print("=" * 62)
    print("  K230 文件接收器：等电脑把 best.kmodel 推过来")
    print("=" * 62)
    ip = connect_wifi()
    make_dirs("/sdcard/kmodel")

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(2)
    print("")
    print(">>> 板子 IP = %s  端口 %d 已就绪，等电脑推文件..." % (ip, PORT))
    print(">>> (把这个 IP 填到电脑端的推送命令里)")
    print("")

    while True:
        try:
            conn, addr = srv.accept()
            print("电脑连上了:", addr)
            try:
                handle_one(conn)
            except Exception as e:
                print("处理出错:", e)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
            gc.collect()
        except KeyboardInterrupt:
            print("用户停止")
            break
        except Exception as e:
            print("accept 出错:", e)
            time.sleep_ms(200)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("用户停止")
    except BaseException as e:
        import sys
        print("!!! 异常:", type(e).__name__, ":", e)