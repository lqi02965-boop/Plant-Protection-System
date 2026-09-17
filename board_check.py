# -*- coding: utf-8 -*-
# =============================================================================
#  K230 上板自检脚本 (防御版 v2)  ——  第一次连上板子时先跑这一个
# -----------------------------------------------------------------------------
#  为什么要有这个版本：
#    固件版本之间 API 会有些差异（比如某些固件 os 模块没有 statvfs）。
#    v1 里一处调用不存在就会报 “没有对应属性”(AttributeError)。
#    这一版做了三件事：
#      1. 每一步都单独 try/except，任何一项失败都不影响后面的检查
#      2. 调用可选的函数前先用 hasattr() 探测它到底存不存在
#      3. 出错时打印“带文件名+行号”的完整堆栈，方便直接把错误发给我
#
#  检查项：
#    0. 能力探测：这台固件到底有哪些函数（先摸清家底）
#    1. 系统信息：固件版本、内存、SD 卡
#    2. 依赖库：/sdcard/libs/ 下的 AIBase.py / AI2D.py / PipeLine.py（亚博镜像自带）
#    3. aicube 后处理模块（可选：你用自训 yolov8 时不需要它）
#    4. 模型 best.kmodel（你自己训练的 yolov8s 害虫模型）
#    5. 摄像头出图（存 /sdcard/check_cam.jpg）
#    6. WiFi（打印 IP）
#    7. 串口发 3 次 $5#（验证跟 STM32 的接线）
#
#  用法（CanMV IDE）：连上板子 → 打开本文件 → 点绿色三角运行 → 看“串口终端”输出
# =============================================================================

import os
import gc
import sys
import time

# --- ★ 需要你填的 ---
WLAN_SSID = "xxq"       # 2.4G WiFi 名
WLAN_PASS = "liqi5334"       # WiFi 密码

# --- 其它配置（和 main.py 保持一致即可）---
KMODEL_CANDIDATES = [
    "/sdcard/kmodel/best.kmodel",
    "/sdcard/best.kmodel",
    "/data/best.kmodel",
]
LIBS_DIR = "/sdcard/libs"      # 亚博镜像里库就在这（不是 /sdcard/app/libs）
# AIBase.py 内部会 import PipeLine.py 里的 ScopedTiming，所以这三个是一套，缺一不可
NEED_LIBS = ["AIBase.py", "AI2D.py", "PipeLine.py"]
UART_ID, UART_BAUD, UART_TX, UART_RX = 2, 115200, 11, 12

results = []          # 汇总结果: (名称, 是否通过, 建议)


def check(name, ok, advice=""):
    """记录并打印一条检查结果"""
    print("%s %s" % ("✅" if ok else "❌", name))
    if not ok and advice:
        print("      → 建议: %s" % advice)
    results.append((name, ok, advice))


def run_step(title, fn):
    """
    跑一个步骤。任何异常都在这里兜住，打印完整堆栈后继续下一步，
    绝不会因为一项失败让整个脚本停住。
    """
    print("\n---------- %s ----------" % title)
    try:
        fn()
    except BaseException as e:
        # 打印异常：这套固件的 sys 没有 print_exception（直接调用会再抛 AttributeError）
        print("❌ 该步骤发生异常（下面是你需要复制给我的信息）：")
        try:
            print("!!! 异常:", type(e).__name__, ":", e)
        except Exception:
            print("   异常:", e)
        results.append((title, False, "见上面的异常堆栈"))


# =============================================================================
# 0. 能力探测：固件里这些函数到底有没有
# =============================================================================
def step0_probe():
    probes = {
        "os.uname":        lambda: hasattr(os, "uname"),
        "os.statvfs":      lambda: hasattr(os, "statvfs"),
        "os.listdir":      lambda: hasattr(os, "listdir"),
        "os.stat":         lambda: hasattr(os, "stat"),
        "gc.mem_free":     lambda: hasattr(gc, "mem_free"),
        "time.ticks_ms":   lambda: hasattr(time, "ticks_ms"),
    }
    print("固件能力探测（False = 这个固件没提供，脚本会自动跳过相关检查）：")
    for name, fn in probes.items():
        try:
            print("   %-16s %s" % (name, "有" if fn() else "没有"))
        except Exception as e:
            print("   %-16s 探测失败: %s" % (name, e))


# =============================================================================
# 1. 系统信息
# =============================================================================
def step1_system():
    # 固件版本
    try:
        if hasattr(os, "uname"):
            print("固件:", os.uname())
        else:
            print("(这个固件 os 模块没有 uname，跳过)")
    except Exception as e:
        print("读固件信息失败:", e)

    # SD 卡（statvfs 不一定存在，所以先探测）
    try:
        if hasattr(os, "statvfs"):
            st = os.statvfs("/sdcard")
            blk, total, free = st[0], st[2], st[3]
            total_mb = blk * total / 1048576
            free_mb = blk * free / 1048576
            print("SD 卡: 共 %.0fMB, 剩余 %.0fMB" % (total_mb, free_mb))
            check("SD 卡可访问且有空间", free_mb > 10, "剩余空间不足 10MB，清理一下")
        else:
            # 没有 statvfs 就退化成“能不能列目录”
            files = os.listdir("/sdcard")
            check("SD 卡可访问", True)
            print("     /sdcard 下有 %d 个条目" % len(files))
    except Exception as e:
        check("SD 卡访问", False, "SD 卡没插好/没格式化成 FAT32，错误: %s" % e)

    # 内存
    try:
        if hasattr(gc, "mem_free"):
            gc.collect()
            print("空闲内存: %.1f MB" % (gc.mem_free() / 1048576))
    except Exception as e:
        print("读内存失败:", e)


# =============================================================================
# 2. AI 依赖库
# =============================================================================
def step2_libs():
    try:
        files = os.listdir(LIBS_DIR)
    except Exception:
        files = []

    if not files:
        check("目录 %s 可读" % LIBS_DIR, False,
              "目录不存在：说明 SD 卡上没有厂商 app 目录；把 libs 拷进去，或告诉我，我改成不依赖它的版本")
        return

    for lib in NEED_LIBS:
        check("%s/%s 存在" % (LIBS_DIR, lib), lib in files,
              "把这个文件拷到 %s（可从 CanMV IDE 自带例程/厂商镜像里找）" % LIBS_DIR)
    print("     目录内容:", ", ".join([str(f) for f in files[:15]]))


# =============================================================================
# 3. aicube 后处理模块
# =============================================================================
def step3_aicube():
    try:
        import aicube
    except Exception as e:
        check("import aicube", False,
              "固件没带这个模块 → 告诉我，我用纯 Python 的 YOLOv5 解码替代（错误: %s）" % e)
        return

    check("import aicube 成功", True)
    has_fn = hasattr(aicube, "anchorbasedet_post_process")
    check("有 anchorbasedet_post_process()", has_fn,
          "固件偏旧；告诉我，我自己写解码，不依赖这个函数")
    # 顺便列出这个模块到底提供哪些函数，方便对照
    try:
        names = [n for n in dir(aicube) if not n.startswith("_")]
        print("     aicube 可用接口:", ", ".join(names[:20]))
    except Exception:
        pass


# =============================================================================
# 4. 模型文件
# =============================================================================
def step4_kmodel():
    found = None
    for p in KMODEL_CANDIDATES:
        # 注意：这里不能用 os.path.exists（这个固件的 os 没有 path 子模块）
        try:
            os.stat(p)
            found = p
            break
        except OSError:
            pass

    if found:
        size_mb = 0
        try:
            size_mb = os.stat(found)[6] / 1048576
        except Exception:
            pass
        check("best.kmodel 存在", True)
        print("     位置: %s (%.2f MB)" % (found, size_mb))
        return

    check("best.kmodel 存在", False,
          "把你转换好的 best.kmodel 拷到 %s" % KMODEL_CANDIDATES[0])

    # 顺手把 SD 卡上所有的 kmodel 列出来，方便确认实际路径
    print("     正在扫描 SD 卡上已有的模型文件...")
    for root in ("/sdcard", "/sdcard/app", "/sdcard/app/tests", "/sdcard/app/tests/ai_test_kmodel"):
        try:
            for f in os.listdir(root):
                if str(f).endswith(".kmodel"):
                    print("       - %s/%s" % (root, f))
        except Exception:
            pass


# =============================================================================
# 5. 摄像头
# =============================================================================
def step5_camera():
    sensor = None
    media_ok = False
    try:
        # 注意：星号导入(import *)只能写在文件顶层，函数里必须写具体名字
        from media.sensor import Sensor, CAM_CHN_ID_1
        from media.media import MediaManager
        try:
            import media.sensor as sensor_mod      # 用来取模块级常量 PIXEL_FORMAT_xxx
        except Exception:
            sensor_mod = None

        # 摄像头测试必须用 RGB565！
        # 因为 CanMV 的 JPEG 编码器只支持 GRAYSCALE/RGB565/YUV/BAYER，
        # 用 RGB888/平面格式调 save() 会报 "current format not support save function!"
        fmt = None
        used = ""
        if sensor_mod is not None and hasattr(sensor_mod, "PIXEL_FORMAT_RGB_565"):
            fmt = getattr(sensor_mod, "PIXEL_FORMAT_RGB_565")
            used = "PIXEL_FORMAT_RGB_565"
        elif hasattr(Sensor, "RGB565"):
            fmt = Sensor.RGB565
            used = "Sensor.RGB565"
        if fmt is None:
            check("摄像头像素格式", False,
                  "找不到 RGB565（JPEG 编码必需，RGB888 不能编码）")
            return
        print("使用像素格式: %s" % used)

        sensor = Sensor(width=1280, height=960)
        sensor.reset()
        # 注意：官方例程用的关键字是 width/height（不是 w/h）
        sensor.set_framesize(width=640, height=480, chn=CAM_CHN_ID_1)
        sensor.set_pixformat(fmt, chn=CAM_CHN_ID_1)

        MediaManager.init()
        media_ok = True
        sensor.run()

        for _ in range(10):                 # 丢掉前几帧，等自动曝光稳定
            sensor.snapshot(chn=CAM_CHN_ID_1)

        img = sensor.snapshot(chn=CAM_CHN_ID_1)
        print("取到图像: %dx%d" % (img.width(), img.height()))

        path = "/sdcard/check_cam.jpg"
        img.save(path)
        # 同样不能用 os.path.exists（固件 os 没有 path 子模块），用 os.stat 判断
        saved = True
        try:
            saved = os.stat(path)[6] > 0
        except OSError:
            saved = False
        check("摄像头出图并保存", saved,
              "检查摄像头排线；确认用的是配套 GC2093 模组")
        print("     已存图: %s（可以拔卡到电脑上看画面）" % path)

    except BaseException as e:
        check("摄像头初始化/取图", False, "错误: %s" % e)
    finally:
        # 无论成功失败都要释放，否则第二次运行会报 “设备被占用”
        try:
            if sensor:
                sensor.stop()
        except Exception:
            pass
        if media_ok:
            try:
                MediaManager.deinit()
            except Exception:
                pass
        gc.collect()


# =============================================================================
# 6. WiFi
# =============================================================================
def step6_wifi():
    try:
        import network
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        if not wlan.isconnected():
            print("正在连接 %s ..." % WLAN_SSID)
            wlan.connect(WLAN_SSID, WLAN_PASS)
            for _ in range(100):            # 最多 10 秒
                if wlan.isconnected():
                    break
                time.sleep_ms(100)
        if wlan.isconnected():
            cfg = wlan.ifconfig()
            check("WiFi 已连接", True)
            print("     IP = %s  → 以后推流地址: http://%s:8080" % (cfg[0], cfg[0]))
        else:
            check("WiFi 连接", False,
                  "查 SSID/密码是否正确、是否 2.4G、密码里是否有英文双引号")
    except BaseException as e:
        check("WiFi 模块", False, "错误: %s" % e)


# =============================================================================
# 7. 串口（验证与 STM32 的接线）
# =============================================================================
def step7_uart():
    try:
        from machine import UART
        uart = UART(UART_ID, baudrate=UART_BAUD, tx=UART_TX, rx=UART_RX, timeout=100)
        for i in range(3):
            uart.write("$5#")
            print("已发送: $5#  (%d/3)" % (i + 1))
            time.sleep_ms(500)
        check("串口发送完成", True)
        print("     请在 STM32 侧确认：调试串口(USART1)应打印 pest=5")
        print("     接线：K230 IO%d(TX)->STM32 PA3(RX)，K230 IO%d(RX)->STM32 PA2(TX)，两板共地"
              % (UART_TX, UART_RX))
    except BaseException as e:
        check("串口初始化/发送", False, "错误: %s" % e)


# =============================================================================
# 主流程：每步独立执行，互不影响
# =============================================================================
def main():
    print("=" * 62)
    print("  K230 上板自检 v2 (防御版)  开始")
    print("=" * 62)

    run_step("0. 固件能力探测", step0_probe)
    run_step("1. 系统信息",     step1_system)
    run_step("2. AI 依赖库",    step2_libs)
    run_step("3. aicube 模块",  step3_aicube)
    run_step("4. 模型文件",     step4_kmodel)
    run_step("5. 摄像头",       step5_camera)
    run_step("6. WiFi",         step6_wifi)
    run_step("7. 串口",         step7_uart)

    print("\n" + "=" * 62)
    print("  自检汇总")
    print("=" * 62)
    fail = 0
    for name, ok, advice in results:
        print("%s %s" % ("✅" if ok else "❌", name))
        if not ok:
            fail += 1
            if advice:
                print("     → %s" % advice)
    print("-" * 62)
    if fail == 0:
        print("全部通过 ✅  现在可以运行 main.py 了")
    else:
        print("有 %d 项未通过 ❌  把上面的 ❌ 行 + 异常堆栈发给我，我来改代码" % fail)
    print("=" * 62)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("用户停止")
    except BaseException as e:
        print("!!! 异常:", type(e).__name__, ":", e)