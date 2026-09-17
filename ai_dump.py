# -*- coding: utf-8 -*-
# =============================================================================
#  K230 AI 输入数据导出 + 文件服务（排查"虫数乱跳"的问题）
# -----------------------------------------------------------------------------
#  这个脚本做两件事：
#    1) 把 AI 通道的原始数据、推流通道的 JPEG 存到 /sdcard
#       （AI 通道的数据就是喂给模型的东西，存下来我在电脑上还原成图片看）
#    2) 起一个文件服务(8080)，电脑可以直接下载这些文件
#
#  【怎么用】
#      1) 填好下面的 WiFi
#      2) CanMV IDE 打开本脚本 → 点运行
#      3) 把它打印的 IP 告诉我，我从电脑把文件拉下来分析
#
#  产出文件（都在 /sdcard 下）：
#      ai_raw.bin     AI 通道原始像素(平面RGB888, 640x480x3 = 921600 字节)
#      ai_meta.txt    数据统计(每通道均值/最值)，附在文件服务里一起看
#      stream.jpg     推流通道(RGB565)编码出的 JPEG，用来对照"相机看到什么"
#      model_in.bin   (尽力而为) AI2D 预处理后的数据 = 模型真正吃进去的输入
# =============================================================================

import os
import gc
import time
import socket
import network

from media.sensor import *
from media.display import *
from media.media import *

# ============================ ★ 填 WiFi ============================
WLAN_SSID = "your_wifi_ssid"
WLAN_PASS = "your_wifi_pass"
# ===================================================================

# ==== 可选：把相机画面显示到屏幕上（LCD 黑屏就是这个开关没开）====
# 我的 main.py 默认不初始化显示（画面走 HTTP 推流），所以 LCD 一直黑是正常的。
# 想直接看到画面，把 SHOW_SCREEN 改成 True，并选对屏幕类型：
#     "lcd"  = 3.1 寸 MIPI 屏（驱动 ST7701）
#     "hdmi" = HDMI 显示器（驱动 LT9611）
SHOW_SCREEN = False
SCREEN_MODE = "lcd"

AI_W, AI_H = 640, 480          # AI 通道尺寸(和你 main.py 保持一致)
ST_W, ST_H = 640, 480          # 推流通道尺寸
PORT = 8080


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("正在连接 WiFi:", WLAN_SSID)
        wlan.connect(WLAN_SSID, WLAN_PASS)
        for _ in range(150):
            if wlan.isconnected():
                break
            time.sleep_ms(100)
    if not wlan.isconnected():
        raise Exception("WiFi 连不上：检查 SSID/密码是否填对（2.4G）")
    ip = wlan.ifconfig()[0]
    print("WiFi OK, 板子 IP =", ip)
    return ip


def dump_data():
    """取一帧，把 AI 原始数据和推流 JPEG 存盘"""
    sensor = Sensor(width=1280, height=960)
    sensor.reset()
    sensor.set_framesize(width=ST_W, height=ST_H, chn=CAM_CHN_ID_1)
    sensor.set_pixformat(PIXEL_FORMAT_RGB_565, chn=CAM_CHN_ID_1)
    sensor.set_framesize(width=AI_W, height=AI_H, chn=CAM_CHN_ID_2)
    sensor.set_pixformat(PIXEL_FORMAT_RGB_888_PLANAR, chn=CAM_CHN_ID_2)

    # ---- 可选：把画面绑到屏幕上显示 ----
    # 做法照抄板子自带的 libs/PipeLine.py：CHN0(YUV420) 绑到显示层 VIDEO1
    if SHOW_SCREEN:
        try:
            sensor.set_framesize(width=640, height=480)          # CHN0
            sensor.set_pixformat(PIXEL_FORMAT_YUV_SEMIPLANAR_420)  # CHN0
            bind = sensor.bind_info(x=0, y=0, chn=CAM_CHN_ID_0)
            Display.bind_layer(**bind, layer=Display.LAYER_VIDEO1)
            if SCREEN_MODE == "hdmi":
                Display.init(Display.LT9611, to_ide=True)
            else:
                Display.init(Display.ST7701, to_ide=True)
            print("屏幕显示已开启 (%s)" % SCREEN_MODE)
        except Exception as e:
            print("屏幕初始化失败(不影响数据导出):", e)

    MediaManager.init()
    sensor.run()

    # 丢掉前若干帧，等自动曝光稳定（否则第一帧可能是黑的，会误导排查）
    for _ in range(30):
        sensor.snapshot(chn=CAM_CHN_ID_2)
    print("已丢弃 30 帧，开始取样")

    # ---- 1) AI 通道原始数据 ----
    ai_frame = sensor.snapshot(chn=CAM_CHN_ID_2)
    raw = ai_frame.bytearray()            # 这块内存就是 AI2D 的输入
    print("AI 原始数据长度: %d 字节 (期望 %d)" % (len(raw), AI_W * AI_H * 3))
    with open("/sdcard/ai_raw.bin", "wb") as f:
        f.write(raw)

    # ---- 2) 统计信息（即使文件拉不回来，也先看到数）----
    n = AI_W * AI_H
    info = []
    try:
        for c in range(3):
            ch = raw[c * n:(c + 1) * n]
            s = 0
            mn, mx = 255, 0
            step = 97                       # 抽样统计，省时间
            cnt = 0
            for i in range(0, len(ch), step):
                v = ch[i]
                s += v
                if v < mn: mn = v
                if v > mx: mx = v
                cnt += 1
            info.append("ch%d: mean=%.1f min=%d max=%d" % (c, s / float(cnt), mn, mx))
    except Exception as e:
        info.append("统计失败: %s" % e)
    for line in info:
        print("   ", line)

    # ---- 3) 推流通道 JPEG（看相机真正拍到什么）----
    st_frame = sensor.snapshot(chn=CAM_CHN_ID_1)
    st_frame.save("/sdcard/stream.jpg")
    print("stream.jpg 已保存")

    # ---- 4) 尽力而为：导出 AI2D 预处理后的数据(模型真正的输入) ----
    try:
        import nncase_runtime as nn
        import ulab.numpy as np
        from libs.AI2D import Ai2d

        ai2d = Ai2d(0)
        ai2d.set_ai2d_dtype(nn.ai2d_format.NCHW_FMT, nn.ai2d_format.NCHW_FMT,
                            np.uint8, np.uint8)
        # 和 main.py 完全一样的 letterbox 配置：先补灰边再缩放
        ai2d.pad([0, 0, 0, 0, 80, 80, 0, 0], 0, [114, 114, 114])
        ai2d.resize(nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
        ai2d.build([1, 3, AI_H, AI_W], [1, 3, 640, 640])
        out = ai2d.run(ai_frame.to_numpy_ref())
        try:
            arr = out.to_numpy()
            try:
                data = arr.tobytes()
            except Exception:
                data = bytes(bytearray([int(v) & 0xFF for v in arr[0:200000]]))
                print("   (只导出了前 20 万个字节)")
            with open("/sdcard/model_in.bin", "wb") as f:
                f.write(data)
            print("model_in.bin 已保存: %d 字节" % len(data))
        except Exception as e:
            print("导出 AI2D 输出失败:", e)
    except Exception as e:
        print("AI2D 环节失败(不影响其它文件):", e)

    with open("/sdcard/ai_meta.txt", "w") as f:
        f.write("AI raw len=%d (期望 %d)\n" % (len(raw), AI_W * AI_H * 3))
        f.write("\n".join(info) + "\n")

    sensor.stop()
    MediaManager.deinit()
    gc.collect()
    print("采样完成")


# ============================ 电脑端接收地址 ============================
PC_IP = "192.168.186.197"      # 你电脑 WLAN 的 IPv4（已自动填好）
PC_PORT = 8000                 # 电脑端接收器监听的端口
# =====================================================================

FILES = ["ai_meta.txt", "stream.jpg", "ai_raw.bin", "model_in.bin"]


def push_to_pc():
    """
    把导出的文件主动"推"给电脑。

    为什么用这个方向：板子当客户端、电脑当服务端。
    之前让电脑来拉(板子当服务端)时，一旦有一个连接出问题，单线程的服务端
    就会被永久挂住，后面所有请求都不响应 —— 这个方向没这个毛病。
    另外你电脑的网络类别是 Public，防火墙里 Python 的放行规则正好生效。
    """
    ok = 0
    for name in FILES:
        full = "/sdcard/" + name
        try:
            size = os.stat(full)[6]
        except OSError:
            print("   跳过(文件不存在):", name)
            continue

        sent = False
        for attempt in range(1, 4):                  # 每个文件最多试 3 次
            s = socket.socket()
            try:
                s.connect((PC_IP, PC_PORT))
                head = ("POST /%s HTTP/1.0\r\nHost: %s\r\nContent-Length: %d\r\n"
                        "Connection: close\r\n\r\n" % (name, PC_IP, size))
                s.send(head.encode())
                with open(full, "rb") as fp:
                    while True:
                        d = fp.read(4096)
                        if not d:
                            break
                        s.send(d)
                # 等电脑回一句确认（阻塞读，故意不设超时，免得又踩单位坑）
                try:
                    s.recv(64)
                except Exception:
                    pass
                sent = True
                break
            except Exception as e:
                print("   第%d次失败: %s" % (attempt, e))
                time.sleep_ms(500)
            finally:
                try:
                    s.close()
                except Exception:
                    pass

        if sent:
            ok += 1
            print("   已推送 %-16s %d 字节" % (name, size))
        else:
            print("   推送失败:", name)
        gc.collect()
    return ok


def serve_forever(ip):
    """
    备选方案：板子当服务端，等电脑来拉。
    ★ 已修的两个坑：
      - 不用 conn.settimeout()（这套固件的单位是毫秒，会把请求读断成 EAGAIN）
      - 任何情况下都在 finally 里关闭连接，绝不把服务挂住
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(5)
    print("")
    print(">>> 文件服务已启动: http://%s:%d/" % (ip, PORT))
    print(">>> 可下载: ai_raw.bin / stream.jpg / model_in.bin / ai_meta.txt")
    print("")

    while True:
        try:
            conn, addr = srv.accept()
        except KeyboardInterrupt:
            print("用户停止")
            break
        except Exception as e:
            print("accept 出错:", e)
            time.sleep_ms(200)
            continue

        try:
            req = b""
            while b"\r\n\r\n" not in req and len(req) < 4096:
                d = conn.recv(512)
                if not d:
                    break
                req += d
            line = req.split(b"\r\n")[0].decode(errors="replace")
            parts = line.split(" ")
            name = parts[1].lstrip("/").split("?")[0] if len(parts) > 1 else ""
            print("请求:", name)

            if name == "" or ".." in name:
                body = b"files: ai_raw.bin stream.jpg model_in.bin ai_meta.txt\n"
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                             b"Content-Length: " + str(len(body)).encode() +
                             b"\r\nConnection: close\r\n\r\n" + body)
            else:
                full = "/sdcard/" + name
                try:
                    size = os.stat(full)[6]
                except OSError:
                    print("   文件不存在:", full)
                    conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                else:
                    print("   发送 %d 字节" % size)
                    conn.sendall(b"HTTP/1.1 200 OK\r\n"
                                 b"Content-Type: application/octet-stream\r\n"
                                 b"Content-Length: " + str(size).encode() +
                                 b"\r\nConnection: close\r\n\r\n")
                    with open(full, "rb") as fp:
                        while True:
                            d = fp.read(4096)
                            if not d:
                                break
                            conn.sendall(d)
                    print("   完成")
        except Exception as e:
            print("处理请求出错:", e)
        finally:
            # ★ 关键：无论如何都关掉连接，否则服务会被挂死
            try:
                conn.close()
            except Exception:
                pass
            gc.collect()


if __name__ == "__main__":
    import sys
    try:
        ip = connect_wifi()
        dump_data()
        print("")
        print("开始把文件推给电脑 %s:%d ..." % (PC_IP, PC_PORT))
        n = push_to_pc()
        if n == len(FILES):
            print("全部推送完成 ✅（电脑端应该已经收到了）")
        else:
            print("只推送了 %d/%d 个，改用文件服务模式等电脑来拉" % (n, len(FILES)))
            serve_forever(ip)
    except KeyboardInterrupt:
        print("用户停止")
    except BaseException as e:
        print("!!! 异常:", type(e).__name__, ":", e)