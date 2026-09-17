# -*- coding: utf-8 -*-
# =============================================================================
#  K230 视觉检测端主程序  ——  农田虫害智能监测系统
# -----------------------------------------------------------------------------
#  这块板子在系统里的角色：**眼睛 + 计数器**
#
#  数据流（从上到下就是程序的执行顺序）：
#
#     摄像头 ──┬─> CHN2(RGBP888) ─> AI2D(缩放+灰边) ─> KPU推理 ─> yolov8解码(自己写)
#              │                                                    │
#              │                                              检测框列表
#              │                                                    │
#              └─> CHN1(RGB888) ─> 画框 ─> JPEG ─┬─> HTTP推流(浏览器/小程序看)
#                                                │
#                                         虫数 = 框的个数
#                                                │
#                                                └─> UART2 "$虫数#" ─> STM32
#                                                        （STM32 再上报华为云 → 小程序）
#
#  模型：best.kmodel（本项目自己训练的 YOLOv8s 单类害虫检测模型）
#        - 训练：ultralytics yolov8s，imgsz=640，epochs=50，单类 pest
#        - 转换：best.pt → best.onnx(opset 12) → best.kmodel（nncase 2.11 + nncase-kpu）
#        - 输入：uint8 NCHW [1, 3, 640, 640]
#        - 输出：[1, 5, 8400]（4 个框坐标 + 1 个类别分，8400 个候选框）
#        - 后处理：YOLOv8 是无锚框(anchor-free)，必须自己解码 → PestDetApp.postprocess()
#
#  参考厂商例程（API 用法，在 CanMV IDE 安装目录里）：
#    share/qtcreator/examples/04-AI-Demo/object_detect_yolov8n.py     ← yolov8 后处理写法
#    share/qtcreator/examples/17-Sensor/camera_snapshot_and_save.py    ← 多通道取图
# =============================================================================


# -----------------------------------------------------------------------------
# 一、导入的库都是干什么的
# -----------------------------------------------------------------------------
import os
import gc
import sys
import time
import socket          # 用来起 HTTP 服务（给浏览器推流）
import network         # 用来连 WiFi

from media.sensor import *     # Sensor / CAM_CHN_ID_x：摄像头（多通道）
from media.display import *    # Display：屏幕显示（3.1寸 MIPI 屏 / HDMI）
from media.media import *      # MediaManager：媒体缓冲区管理（必须 init/deinit）
from machine import UART       # 串口，用来跟 STM32 通信
import image                   # image.Image：用来创建 OSD 图层画检测框

import nncase_runtime as nn    # K230 的 AI 运行时：KPU(神经网络加速器) + AI2D(图像预处理)
import ulab.numpy as np        # MicroPython 上的 numpy（K230 上用它处理张量）
# 注：本项目用自己训练的 YOLOv8 模型，后处理是自己写的(见 PestDetApp.postprocess)，
#     所以不需要固件里的 aicube 模块（那个是给厂商 YOLOv5 式模型用的）

from libs.AIBase import AIBase # 厂商封装：负责“取图→预处理→送入KPU→拿输出”的骨架
from libs.AI2D import Ai2d     # 厂商封装：AI2D 硬件预处理的配置接口
# 注意：libs 在板子 SD 卡的 /sdcard/libs/ 目录下（亚博镜像自带，不用我们自己传）


# -----------------------------------------------------------------------------
# 二、可配置参数（★ = 现场必须改 / 可能要调）
# -----------------------------------------------------------------------------

# ★ 模型文件路径：程序按顺序找，用第一个存在的
KMODEL_CANDIDATES = [
    "/sdcard/kmodel/best.kmodel",                           # 卡上 kmodel 目录(和厂商模型放一起)
    "/sdcard/best.kmodel",                                  # SD 卡根目录
    "/data/best.kmodel",                                    # 板子 /data 分区
]

# 类别标签：你自己的模型是单类（pest_dataset/data.yaml 里 names: {0: pest}）
LABELS = ["pest"]

MODEL_INPUT = [640, 640]   # 模型输入分辨率：必须和训练 imgsz=640 / 转换 kmodel 时一致

# ★ 置信度阈值：模型认为“这里是虫子”的最低把握。调低=更敏感(召回高但误检多)
CONF_THRESH = 0.45
# NMS 阈值：两个框重叠超过这个比例就认为在框同一只虫，只留一个
NMS_THRESH = 0.45
# 一帧最多保留多少个框（防止误检太多把虫数算爆）
MAX_BOXES = 50

# 送给 AI 的图像分辨率（CHN2 通道，RGBP888 格式，宽度需要 16 字节对齐）
AI_CHN_W, AI_CHN_H = 640, 480
# 推流/画框用的图像分辨率（CHN1 通道，RGB565 格式）
STREAM_CHN_W, STREAM_CHN_H = 640, 480

# ---------------- 屏幕显示（3.1 寸 MIPI 小屏）----------------
# 我的程序默认也可以不接屏（画面走 HTTP 推流）。你接的是 3.1 寸 MIPI 屏，
# 所以这里开着：CHN0 出 YUV420 直接绑到显示视频层，检测框画在 OSD 透明层上叠加。
SHOW_SCREEN = True         # 不想用屏就改成 False
SCREEN_MODE = "lcd"        # "lcd" = ST7701(3.1寸MIPI屏)   "hdmi" = LT9611(HDMI显示器)
SCREEN_W, SCREEN_H = 800, 480   # 3.1寸屏的分辨率（如果你的屏是 480x800 竖屏，改成 480,800）

# HTTP 推流服务：监听所有网卡，端口 8080
STREAM_HOST = "0.0.0.0"
STREAM_PORT = 8080         # 浏览器访问 http://<K230的IP>:8080
JPEG_QUALITY = 75          # 推流画质（数字越大越清晰、越慢）

# 串口：K230 的 UART2，物理引脚 IO11(TX) / IO12(RX)
UART_ID = 2
UART_BAUD = 115200
UART_TX_PIN = 11           # K230 IO11 -> STM32 PA3 (USART2_RX)
UART_RX_PIN = 12           # K230 IO12 -> STM32 PA2 (USART2_TX)
REPORT_PERIOD_MS = 1000    # 虫数上报周期：每秒给 STM32 发一次 $虫数#

# ★ 现场 WiFi（必须是 2.4G，无线模块不支持 5G；密码里不能有英文双引号）
WLAN_SSID = "xxq"       # 2.4G WiFi 名
WLAN_PASS = "liqi5334"       # WiFi 密码


# =============================================================================
# 三、检测功能封装（YOLOv8 单类害虫检测）
#    为什么继承 AIBase？因为“取图→AI2D预处理→KPU推理→取输出”这套流程
#    厂商已经封在 AIBase 里了，我们只需要重写两件事：
#      1) config_preprocess()：告诉 AI2D 怎么做预处理（缩放/填充）
#      2) postprocess()      ：把 KPU 输出解码成一个个检测框
#
#    和你之前那个厂商模型的区别（重要）：
#      YOLOv5 式(AnchorBaseDet)：输出 3 个尺度特征图 + 依赖 anchor 先验框
#                                → 可用固件自带 aicube 后处理
#      YOLOv8 式(本项目)：输出单个张量 [1, 4+类别数, 8400]，无 anchor(anchor-free)
#                                → 必须自己解码，就是下面 postprocess 做的事
#        8400 = 80×80 + 40×40 + 20×20（640 输入下 8/16/32 倍下采样三个尺度的格子数）
# =============================================================================
class PestDetApp(AIBase):

    def __init__(self, kmodel_path, labels, model_input_size,
                 confidence_threshold=CONF_THRESH, nms_threshold=NMS_THRESH,
                 max_boxes=MAX_BOXES, rgb888p_size=None, debug_mode=0):
        # 父类 AIBase 负责：加载 kmodel 到 KPU、准备输入输出张量
        super().__init__(kmodel_path, model_input_size, rgb888p_size, debug_mode)

        self.kmodel_path = kmodel_path
        self.labels = labels
        self.model_input_size = model_input_size
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.max_boxes = max_boxes

        # 送进来的图像尺寸（宽向上取 16 的整数倍，因为硬件预处理要求对齐）
        self.rgb888p_size = [ALIGN_UP(rgb888p_size[0], 16), rgb888p_size[1]]
        self.debug_mode = debug_mode

        # letterbox 参数：config_preprocess 里算好，postprocess 反算坐标要用
        self.lb_ratio = 1.0        # 等比缩放比
        self.lb_top = 0            # 上边灰边高度
        self.lb_left = 0           # 左边灰边宽度

        # AI2D 是 K230 的硬件预处理单元：缩放/填充/裁剪都在这里做，不占 CPU
        self.ai2d = Ai2d(debug_mode)
        # 设定数据格式：输入输出都是 NCHW(通道在前)，数据类型都是一字节无符号
        self.ai2d.set_ai2d_dtype(nn.ai2d_format.NCHW_FMT, nn.ai2d_format.NCHW_FMT,
                                 np.uint8, np.uint8)

    # -------------------------------------------------------------------------
    # 计算“灰边”要各填多少像素
    # 为什么要填充？训练时用的是 letterbox：把整张图等比缩放后，四周补灰边凑成正方形。
    # 如果推理时直接拉伸成 640x640（不保持宽高比），虫子会被压扁，模型认不准。
    # -------------------------------------------------------------------------
    def get_padding_param(self):
        ratiow = float(self.model_input_size[0]) / self.rgb888p_size[0]
        ratioh = float(self.model_input_size[1]) / self.rgb888p_size[1]
        ratio = min(ratiow, ratioh)                    # 取小的那个，保证整图都放得下
        new_w = int(ratio * self.rgb888p_size[0])      # 缩放后的实际宽
        new_h = int(ratio * self.rgb888p_size[1])      # 缩放后的实际高
        dw = float(self.model_input_size[0] - new_w) / 2   # 左右各要补的宽度
        dh = float(self.model_input_size[1] - new_h) / 2   # 上下各要补的高度
        # 取整时一上一下，保证补完后正好是 640x640
        top = int(round(dh - 0.1))
        bottom = int(round(dh + 0.1))
        left = int(round(dw - 0.1))
        right = int(round(dw - 0.1))
        return top, bottom, left, right

    # -------------------------------------------------------------------------
    # 告诉 AI2D 怎么做预处理：先补灰边(pad)，再双线性缩放(resize)
    # -------------------------------------------------------------------------
    def config_preprocess(self, input_image_size=None):
        ai2d_input_size = input_image_size if input_image_size else self.rgb888p_size
        top, bottom, left, right = self.get_padding_param()

        # 记下缩放比和灰边：后处理要把框从 640x640 坐标还原回原图坐标
        self.lb_ratio = min(float(self.model_input_size[0]) / self.rgb888p_size[0],
                            float(self.model_input_size[1]) / self.rgb888p_size[1])
        self.lb_top = top
        self.lb_left = left

        # 填充成灰色(114,114,114)——和 YOLO 训练时 letterbox 的填充色一致
        self.ai2d.pad([0, 0, 0, 0, top, bottom, left, right], 0, [114, 114, 114])
        # 缩放算法：tf_bilinear(双线性插值) + half_pixel(像素中心对齐，避免偏移)
        self.ai2d.resize(nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
        # build：声明输入张量形状 [1,3,高,宽] 和输出张量形状，之后才能跑
        self.ai2d.build([1, 3, ai2d_input_size[1], ai2d_input_size[0]],
                        [1, 3, self.model_input_size[1], self.model_input_size[0]])

    # -------------------------------------------------------------------------
    # 交并比：两个框的重叠程度，NMS 用它判断“是不是同一只虫”
    # -------------------------------------------------------------------------
    @staticmethod
    def iou(a, b):
        ix1 = max(a[0], b[0])
        iy1 = max(a[1], b[1])
        ix2 = min(a[2], b[2])
        iy2 = min(a[3], b[3])
        iw = ix2 - ix1
        ih = iy2 - iy1
        if iw <= 0 or ih <= 0:
            return 0.0
        inter = iw * ih
        union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
        return inter / union if union > 0 else 0.0

    # -------------------------------------------------------------------------
    # NMS(非极大值抑制)：一堆框里只留最靠谱的那个，把框同一只虫的重复框删掉
    # 单类检测，所以只做类内抑制；候选框已按分数从高到低排好
    # -------------------------------------------------------------------------
    def nms(self, cand):
        cand = sorted(cand, key=lambda x: x[4], reverse=True)
        keep = []
        while cand:
            best = cand.pop(0)          # 取当前分数最高的
            keep.append(best)
            # 剩下的里面，和 best 重叠太厉害的（同一只虫）丢掉
            cand = [c for c in cand if self.iou(best, c) < self.nms_threshold]
        return keep

    # -------------------------------------------------------------------------
    # 后处理：把 KPU 输出 [1, 4+类别数, 8400] 解码成检测框
    #   坐标含义：(cx, cy, w, h) 中心点+宽高，单位是模型输入(640x640)的像素
    #   类别分已经是 0~1 的概率（ultralytics 导出 ONNX 时已含 sigmoid，无 objectness）
    #
    # 返回格式：[ [类别号, 置信度, x1, y1, x2, y2], ... ]，坐标已还原到原图
    # -------------------------------------------------------------------------
    def postprocess(self, results):
        out = results[0]                       # (1, 4+nc, 8400)，本项目 nc=1 → (1,5,8400)
        n_ch = out.shape[1]                    # 通道数 = 4 + 类别数
        n_anchor = out.shape[2]                # 候选框个数 = 8400

        # 变成 (8400, 5) 的表格：每一行是 [cx, cy, w, h, 类别分]
        data = out.reshape((n_ch, n_anchor)).transpose()
        boxes_ori = data[:, 0:4]               # 前 4 列：框
        scores_ori = data[:, 4:]               # 后面：各类别分数
        confs = np.max(scores_ori, axis=-1)    # 单类，取最大就是该类分数
        inds = np.argmax(scores_ori, axis=-1)  # 类别号（单类时恒为 0）

        # 兼容处理：万一固件输出的分数是 0~255 的量化整数，先归一到 0~1
        # （正常情况 KPU 输出已反量化为 float32，分数天然 ≤ 1，这段不会触发）
        if float(np.max(confs)) > 1.5:
            confs = confs / 255.0

        w_max = self.rgb888p_size[0]
        h_max = self.rgb888p_size[1]
        cand = []
        for i in range(n_anchor):
            if confs[i] < self.confidence_threshold:
                continue                       # 分数不够，跳过（先过滤再做 NMS，省时间）
            cx, cy, w, h = boxes_ori[i, 0], boxes_ori[i, 1], boxes_ori[i, 2], boxes_ori[i, 3]
            # 模型输入坐标(640x640) → 原图坐标：先减掉灰边，再除以缩放比
            x1 = (cx - 0.5 * w - self.lb_left) / self.lb_ratio
            y1 = (cy - 0.5 * h - self.lb_top) / self.lb_ratio
            x2 = (cx + 0.5 * w - self.lb_left) / self.lb_ratio
            y2 = (cy + 0.5 * h - self.lb_top) / self.lb_ratio
            # 裁到画面范围内
            x1 = 0.0 if x1 < 0 else (w_max if x1 > w_max else x1)
            y1 = 0.0 if y1 < 0 else (h_max if y1 > h_max else y1)
            x2 = 0.0 if x2 < 0 else (w_max if x2 > w_max else x2)
            y2 = 0.0 if y2 < 0 else (h_max if y2 > h_max else y2)
            cand.append([x1, y1, x2, y2, confs[i], inds[i]])

        keep = self.nms(cand)
        res = []
        for b in keep[:self.max_boxes]:
            # 转成统一的 [类别, 分数, x1, y1, x2, y2]，方便主循环画框
            res.append([b[5], b[4], b[0], b[1], b[2], b[3]])
        return res


# =============================================================================
# 四、几个小工具函数
# =============================================================================

def file_exists(path):
    """
    判断文件是否存在。

    ★ 绝对不能用 os.path.exists！
      这个固件(K230 CanMV)的 MicroPython 里 os 模块没有 path 子模块，
      调用会报 "'module' object has no attribute 'path'"。
      用 os.stat 自己包一层最稳。
    """
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def find_kmodel():
    """在候选路径里找 kmodel，找到就返回路径，都没有就报错提示怎么放。"""
    for p in KMODEL_CANDIDATES:
        if file_exists(p):
            return p
    raise Exception("找不到 kmodel。请把 best.kmodel 放到: %s" % KMODEL_CANDIDATES[0])


def connect_wifi():
    """
    连 WiFi 并返回本机 IP。
    连不上也不会让程序崩：只是没有推流，检测和串口上报照常工作
    （这就是“边缘计算”：断网本地闭环）。

    ★ 做成"多轮重试 + 每轮重置网卡"：
      软重启(MPY soft reboot)后再跑本脚本时，网卡偶尔会残留上次的状态，
      一次 connect 不成功就再也没有机会了。这里最多试 3 轮，每轮先把网卡
      彻底关掉再打开，并打印 isconnected/status 便于定位。
    """
    wlan = network.WLAN(network.STA_IF)
    ip = None
    for attempt in range(1, 4):
        try:
            if not wlan.active():
                wlan.active(True)
            if wlan.isconnected():
                break
            # 重置网卡，清掉上一轮残留状态
            wlan.active(False)
            time.sleep_ms(500)
            wlan.active(True)
            time.sleep_ms(300)
            wlan.connect(WLAN_SSID, WLAN_PASS)      # 发起连接
            for _ in range(150):                    # 本轮最多等 15 秒
                if wlan.isconnected():
                    break
                time.sleep_ms(100)
            st = ''
            try:
                st = wlan.status()
            except Exception:
                st = '?'
            print("[NET] 第 %d 次连接: isconnected=%s status=%s"
                  % (attempt, wlan.isconnected(), st))
            if wlan.isconnected():
                break
        except Exception as e:
            print("[NET] 第 %d 次连接异常: %s" % (attempt, e))
        time.sleep_ms(500)

    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        print("[NET] WiFi 已连接, IP =", ip)
        return ip
    print("[NET] WiFi 连接失败 -> 只做本地检测和串口上报")
    print("[NET] 排查: 1)手机热点是否开着/是否达客户端上限 2)密码是否改过 3)信号距离")
    return None
    print("[NET] WiFi 连接失败 -> 只做本地检测和串口上报")
    return None


def to_jpeg(img):
    """
    把一帧图像压成 JPEG 字节流（HTTP 推流要用）。

    ★ 这个固件里 image 对象【没有 to_bytes()】，只有 bytearray()：
        img.compress(quality=80) 返回一张 JPEG 压缩图，
        它的 bytearray() 就是 JPEG 原始字节（按引用返回，必须立刻用掉）

    兜底：存盘再读回（慢，而且每帧写 SD 卡，正常不该走到这里）
    """
    try:
        return img.compress(quality=JPEG_QUALITY).bytearray()
    except Exception:
        path = "/sdcard/_snapshot.jpg"
        img.save(path, quality=JPEG_QUALITY)
        with open(path, "rb") as f:
            return f.read()


def pick_pixformat(candidates):
    """
    不同固件对像素格式的支持略有差异（有的叫 Sensor.RGB888，有的用模块级常量
    PIXEL_FORMAT_RGB_888）。这里按优先级挑一个真正存在的，返回 (格式值, 名称)。
    """
    mod = globals()          # 来自 from media.sensor import * 的模块级常量
    for name in candidates:
        if hasattr(Sensor, name):
            return getattr(Sensor, name), name
        if name in mod:
            return mod[name], name
    raise Exception("固件里找不到可用像素格式: %s" % (candidates,))


def print_exc(e):
    """
    打印异常信息（带类型和消息）。

    ★ 这套固件的 sys 模块【没有 print_exception】！直接调它会再抛一个
      AttributeError，把真正的错误盖掉（之前就是这么被坑的）。
      所以这里先打印类型+消息，再尽力尝试各种可用的堆栈打印接口。
    """
    try:
        print("!!! 异常:", type(e).__name__, ":", e)
    except Exception:
        pass
    # 尽力打印调用栈（哪个固件有就用哪个）
    for modname in ("sys", "micropython"):
        try:
            m = __import__(modname)
            fn = getattr(m, "print_exception", None)
            if fn:
                fn(e)
                return
        except Exception:
            pass


def safe_exitpoint(arg=None):
    """
    os.exitpoint() 是“让 IDE 能中断我”的接口，个别固件没有。
    有就调用，没有就忽略，不能让程序因为这一句崩掉。
    """
    if hasattr(os, "exitpoint"):
        try:
            if arg is None:
                os.exitpoint()
            else:
                os.exitpoint(arg)
        except Exception:
            pass


def draw_count(img, text):
    """在画面左上角写虫数；draw_string_advanced 不存在就退回 draw_string"""
    try:
        img.draw_string_advanced(8, 8, 32, text, color=(255, 0, 0))
    except Exception:
        try:
            img.draw_string(8, 8, text, color=(255, 0, 0), scale=2)
        except Exception:
            pass


# =============================================================================
# 五、HTTP 推流服务（MJPG）
#
# 原理小科普：
#   普通 HTTP 请求是“一问一答”，网页拿完就断。要让浏览器一直显示新画面，
#   用的是 multipart/x-mixed-replace —— 一个长连接里不断推“分片”，
#   每个分片是一张完整 JPEG，浏览器收到新分片就替换画面。
#   所以每帧必须写成：
#       --frame\r\n
#       Content-Type: image/jpeg\r\n
#       Content-Length: 长度\r\n
#       \r\n
#       <JPEG 二进制>\r\n
#   少了这段分片头，浏览器就出不来画面（这是最常见的坑）。
#
#   /snapshot 则是“要一帧就走”，给小程序 image 组件定时刷新用。
# =============================================================================
class MjpegServer:

    def __init__(self, host, port):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # 允许端口复用，避免上次没退干净导致 "Address in use"
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind((host, port))
        self.srv.listen(2)
        # 设为非阻塞：主循环还要跑推理，不能被 accept 卡住
        self.srv.setblocking(False)
        self.clients = []         # 正在看推流的连接
        self.snap_conns = []      # 请求了 /snapshot、等着发单帧的连接
        self.boundary = b"frame"  # 分片边界字符串

    def poll_new_clients(self):
        """看看有没有新连接进来（非阻塞，没有就直接返回）"""
        try:
            conn, _ = self.srv.accept()
        except OSError:
            return

        # 把 HTTP 请求头读完（读到空行 \r\n\r\n 为止），判断对方要什么
        req = b""
        try:
            conn.settimeout(1)
            while b"\r\n\r\n" not in req and len(req) < 2048:
                chunk = conn.recv(256)
                if not chunk:
                    break
                req += chunk
        except OSError:
            pass

        if b"/snapshot" in req:
            # 单帧：先记下来，等下一帧编码好再回给他
            self.snap_conns.append(conn)
        else:
            # 推流：先回 HTTP 头，告诉他“后面是连续的多分片图片流”
            try:
                conn.sendall(b"HTTP/1.1 200 OK\r\n"
                             b"Connection: close\r\n"
                             b"Content-Type: multipart/x-mixed-replace; boundary="
                             + self.boundary + b"\r\n\r\n")
                self.clients.append(conn)
            except OSError:
                self._close(conn)

    def push(self, jpeg):
        """把刚编码好的这一帧，推给所有正在看推流的客户端"""
        # 组装分片：边界 + 类型 + 长度 + 空行 + 数据 + 结尾换行
        part = (b"--" + self.boundary + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                + jpeg + b"\r\n")

        alive = []
        for c in self.clients:
            try:
                c.sendall(part)
                alive.append(c)          # 发送成功，保留
            except OSError:
                self._close(c)           # 对方关页面了，踢掉
        self.clients = alive

        # 处理 /snapshot：回一帧完整 HTTP 响应，然后关连接
        for c in self.snap_conns:
            try:
                c.sendall(b"HTTP/1.1 200 OK\r\n"
                          b"Content-Type: image/jpeg\r\n"
                          b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n"
                          b"Connection: close\r\n\r\n" + jpeg)
            except OSError:
                pass
            self._close(c)
        self.snap_conns = []

    @staticmethod
    def _close(c):
        try:
            c.close()
        except OSError:
            pass


# =============================================================================
# 六、主流程
# =============================================================================
def main():
    sensor = None
    det = None
    try:
        # ---------------------------------------------------------------------
        # 1. 启动摄像头
        #    K230 的摄像头可以同时输出多个通道(chn)，每个通道独立设尺寸和格式：
        #      CHN1: RGB888  -> 给人看/推流/画框
        #      CHN2: RGBP888 -> 给 AI 用（P 表示平面格式，AI2D 处理更快）
        #    顺序很重要：先 reset 配置，再 MediaManager.init()，最后 run()
        # ---------------------------------------------------------------------
        # 创建摄像头对象：优先带分辨率参数，老固件不支持就用默认构造
        try:
            sensor = Sensor(width=1280, height=960)
        except TypeError:
            sensor = Sensor()
        sensor.reset()                              # 复位摄像头

        # 像素格式自动挑选（名字各固件版本不完全一样，挑到哪个用哪个）
        # 推流/画框通道：必须是 RGB565！
        #   CanMV 的 JPEG 编码器只支持 GRAYSCALE/RGB565/YUV/BAYER 这几种，
        #   用 RGB888/平面格式去 compress()/save() 会报
        #   "current format not support save function!"
        #   （板子自带 PipeLine.py 用的也是 PIXEL_FORMAT_RGB_565）
        fmt_stream, name_stream = pick_pixformat(("PIXEL_FORMAT_RGB_565", "RGB565"))
        # AI 通道：必须是"平面(planar)RGB888"
        #   因为 AIBase 内部是把这块内存直接当 CHW 张量喂给模型的
        #   （板子自带 PipeLine.py 用的是 PIXEL_FORMAT_RGB_888_PLANAR）
        fmt_ai, name_ai = pick_pixformat(("PIXEL_FORMAT_RGB_888_PLANAR", "RGBP888"))
        print("[CAM] 像素格式: 推流通道=%s, AI通道=%s" % (name_stream, name_ai))

        # 注意：官方例程用的关键字是 width/height（不是 w/h）
        sensor.set_framesize(width=STREAM_CHN_W, height=STREAM_CHN_H, chn=CAM_CHN_ID_1)
        sensor.set_pixformat(fmt_stream, chn=CAM_CHN_ID_1)

        sensor.set_framesize(width=AI_CHN_W, height=AI_CHN_H, chn=CAM_CHN_ID_2)
        sensor.set_pixformat(fmt_ai, chn=CAM_CHN_ID_2)

        # ---------------------------------------------------------------------
        # 1.5 屏幕显示（3.1 寸 MIPI 小屏，驱动 ST7701）
        #     ★ 关键：Display.init 必须指定 osd_num！
        #       不给的话 OSD 图层根本不存在，show_image(layer=...) 会【静默失效】
        #       —— 之前 LCD 只有画面、没有框和文字，就是这个原因。
        #     显示方式照官方例程 camera_single_show_lcd.py：
        #       CHN0 的 YUV420 绑到 VIDEO1（活画面，硬件通路）
        #       检测结果直接画在 RGB565 的 img 上，再整张显示到 OSD1 层
        #     顺序：bind_layer + Display.init 都必须在 MediaManager.init() 之前
        # ---------------------------------------------------------------------
        lcd_on = False
        if SHOW_SCREEN:
            try:
                sensor.set_framesize(width=SCREEN_W, height=SCREEN_H)      # CHN0
                sensor.set_pixformat(PIXEL_FORMAT_YUV_SEMIPLANAR_420)      # CHN0
                bind = sensor.bind_info(x=0, y=0, chn=CAM_CHN_ID_0)
                Display.bind_layer(**bind, layer=Display.LAYER_VIDEO1)

                if SCREEN_MODE == "hdmi":
                    Display.init(Display.LT9611, to_ide=True, osd_num=2)
                else:
                    Display.init(Display.ST7701, to_ide=True, osd_num=2)

                lcd_on = True
                print("[LCD] 屏幕已开启: %dx%d (%s), 检测结果画在 OSD1 层"
                      % (SCREEN_W, SCREEN_H, SCREEN_MODE))
            except Exception as e:
                print("[LCD] 屏幕初始化失败, 只做推流, 不影响检测:", e)
                lcd_on = False

        MediaManager.init()        # 申请媒体缓冲区（必须在 run() 之前！）
        sensor.run()               # 摄像头开始出图
        print("[CAM] 摄像头已启动: 推流通道 %dx%d, AI通道 %dx%d"
              % (STREAM_CHN_W, STREAM_CHN_H, AI_CHN_W, AI_CHN_H))

        # ---------------------------------------------------------------------
        # 2. 加载模型
        # ---------------------------------------------------------------------
        kmodel_path = find_kmodel()
        # 打印字节数：用来确认板上跑的是哪一版模型
        #   （旧的问题版本和修好的版本字节数不一样，一眼就能分辨）
        try:
            print("[AI] 使用模型: %s (%d 字节)" % (kmodel_path, os.stat(kmodel_path)[6]))
        except Exception:
            print("[AI] 使用模型:", kmodel_path)

        det = PestDetApp(kmodel_path, LABELS, MODEL_INPUT,
                         rgb888p_size=[AI_CHN_W, AI_CHN_H], debug_mode=0)
        det.config_preprocess()    # 应用上面的 AI2D 预处理配置
        print("[AI] 模型加载完成, 类别数 =", len(LABELS))

        # ---------------------------------------------------------------------
        # 3. 打开串口（发给 STM32）
        #    协议：$虫数#   例如 $12# 表示检测到 12 只虫
        #    STM32 那边的解析在 32/HARDWARE/k230_uart.c 的 K230_Uart_IRQHandler()
        #    它用 $ 开始、# 结束来切帧，所以这里必须严格按这个格式发。
        # ---------------------------------------------------------------------
        uart = UART(UART_ID, baudrate=UART_BAUD, tx=UART_TX_PIN, rx=UART_RX_PIN, timeout=100)
        print("[UART] UART%d 已打开 %d 8N1, TX=IO%d, RX=IO%d"
              % (UART_ID, UART_BAUD, UART_TX_PIN, UART_RX_PIN))

        # ---------------------------------------------------------------------
        # 4. 连 WiFi + 启动推流服务
        # ---------------------------------------------------------------------
        ip = connect_wifi()
        srv = MjpegServer(STREAM_HOST, STREAM_PORT)
        if ip:
            print("[NET] 实时画面: http://%s:%d" % (ip, STREAM_PORT))
            print("[NET] 单帧快照: http://%s:%d/snapshot" % (ip, STREAM_PORT))

        # ---------------------------------------------------------------------
        # 5. 主循环：检测 -> 计数 -> 画框 -> 推流 -> 上报
        # ---------------------------------------------------------------------
        last_report = time.ticks_ms()     # 上次上报虫数的时间
        t_fps = time.ticks_ms()           # 上次统计帧率的时间
        frames = 0                        # 这 5 秒内处理了多少帧
        cnt = 0                           # 当前虫数
        print("[RUN] 开始检测...")

        while True:
            # 每圈都要调：给 IDE 一个“可以中断我”的机会，否则 Ctrl+C 停不下来
            safe_exitpoint()

            # stage 用来标记当前进行到哪一步：万一抛异常，日志里能直接看到挂在哪个阶段
            stage = "取AI帧"
            try:
                # --- 5.1 取 AI 通道图像并推理 ---------------------------------
                t0 = time.ticks_ms()                              # 开始计时
                ai_frame = sensor.snapshot(chn=CAM_CHN_ID_2)      # 抓一帧给 AI 用(图像对象)
                # ★关键：必须转成 ulab 数组再喂给 AIBase！
                #   因为 AIBase.preprocess() 内部是 nn.from_numpy(input_np)，
                #   直接传图像对象会出错。官方 PipeLine.get_frame() 就是这么做的。
                #   to_numpy_ref() 是"引用"不拷贝，速度快，但下一帧就失效，只能立刻用。
                ai_np = ai_frame.to_numpy_ref()
                stage = "模型推理"
                det_boxes = det.run(ai_np)                        # 预处理+推理+后处理
                infer_ms = time.ticks_diff(time.ticks_ms(), t0)   # 单帧耗时(ms)

                # --- 5.2 算虫数 -----------------------------------------------
                # 单类检测，框的个数就是虫数
                cnt = len(det_boxes) if det_boxes else 0

                # --- 5.3 取推流通道图像并画框 ---------------------------------
                stage = "画框(推流图)"
                img = sensor.snapshot(chn=CAM_CHN_ID_1)

                # 检测框坐标是“AI 图坐标系”(640x480)，推流图也是 640x480，
                # 这里做一次比例换算，将来两个通道尺寸不同也不会画歪。
                sx = float(STREAM_CHN_W) / AI_CHN_W
                sy = float(STREAM_CHN_H) / AI_CHN_H

                if det_boxes:
                    for b in det_boxes:
                        # b = [类别号, 置信度, x1, y1, x2, y2]
                        x1, y1, x2, y2 = b[2], b[3], b[4], b[5]
                        # 注意：draw_rectangle 参数是 (左上角x, 左上角y, 宽, 高)
                        img.draw_rectangle(int(x1 * sx), int(y1 * sy),
                                           int((x2 - x1) * sx), int((y2 - y1) * sy),
                                           color=(0, 255, 0), thickness=2)

                # 左上角写上虫数，截图/推流里一眼能看到
                draw_count(img, "pests: %d" % cnt)

                # --- 5.3b 把画好框的这张图显示到 LCD 上 ---------------------------
                #   照官方例程 camera_single_show_lcd.py 的做法：
                #   直接把 RGB565 的图显示到 OSD1 层（框和文字已经画在这张图上了）。
                #   不用 ARGB 透明叠加层，省得踩 alpha/图层号的坑。
                #   整张图居中显示（640 宽 vs 屏宽 800 → 左右各留一条黑边）。
                #   ★ 单独包 try：屏显万一出问题，只关屏显，检测/推流继续跑
                if lcd_on:
                    try:
                        stage = "LCD显示"
                        Display.show_image(img, x=(SCREEN_W - STREAM_CHN_W) // 2,
                                           layer=Display.LAYER_OSD1)
                    except Exception as e:
                        print("[LCD] 屏显出错, 自动关闭屏显(检测继续跑):",
                              type(e).__name__, e)
                        lcd_on = False

                # --- 5.4 编码 JPEG 并推给所有浏览器 ---------------------------
                stage = "JPEG编码/推流"
                srv.poll_new_clients()          # 先收新连接
                srv.push(to_jpeg(img))          # 再推这一帧

                # --- 5.5 周期性把虫数发给 STM32 -------------------------------
                stage = "串口上报"
                if time.ticks_diff(time.ticks_ms(), last_report) >= REPORT_PERIOD_MS:
                    uart.write("$%d#" % cnt)    # 帧格式 $虫数#
                    last_report = time.ticks_ms()
                    print("[UART] 上报 $%d#   (单帧推理 %dms)" % (cnt, infer_ms))

                # --- 5.6 每 5 秒打印一次帧率（调优用） ------------------------
                frames += 1
                if time.ticks_diff(time.ticks_ms(), t_fps) >= 5000:
                    el = time.ticks_diff(time.ticks_ms(), t_fps)
                    print("[FPS] %.1f fps" % (frames * 1000.0 / el))
                    frames = 0
                    t_fps = time.ticks_ms()

                # 手动回收内存：MicroPython 不会自动及时回收，长时间跑会内存不足
                gc.collect()

            except Exception as e:
                print("!!! 主循环出错，出错阶段 =", stage)
                print_exc(e)
                raise

    finally:
        # ---------------------------------------------------------------------
        # 7. 退出时释放资源（顺序不能乱：先模型和摄像头，再媒体缓冲区）
        # ---------------------------------------------------------------------
        try:
            if det:
                det.deinit()
        except Exception:
            pass
        try:
            if sensor:
                sensor.stop()
        except Exception:
            pass
        # 关掉屏幕（只有在开过屏的时候才需要）
        if SHOW_SCREEN:
            try:
                Display.deinit()
            except Exception:
                pass
        safe_exitpoint(os.EXITPOINT_ENABLE_SLEEP) if hasattr(os, "EXITPOINT_ENABLE_SLEEP") else None
        time.sleep_ms(100)
        try:
            MediaManager.deinit()
        except Exception:
            pass


# =============================================================================
# 七、程序入口
# =============================================================================
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("用户停止")
    except BaseException as e:
        print_exc(e)     # 打印异常（这个固件的 sys 没有 print_exception，见 print_exc 说明）
