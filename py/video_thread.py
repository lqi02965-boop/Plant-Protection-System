# -*- coding: utf-8 -*-
"""K230 MJPG 视频流接收线程
OpenCV VideoCapture 会自动解析 HTTP multipart/x-mixed-replace 流,
逐帧解码 JPEG; 网络收包+解码是耗时操作, 必须放 QThread 防 UI 卡死。
解码结果通过 QImage 信号跨线程发给主线程更新 QLabel。
"""
import cv2
from PySide6.QtCore import QThread, Signal, QMutex, QWaitCondition


class VideoThread(QThread):
    frame_received = Signal(object)      # 携带 QImage
    error_occurred = Signal(str)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url
        self._running = True

    def run(self):
        cap = cv2.VideoCapture(self.url)   # http://<k230_ip>:8080
        if not cap.isOpened():
            self.error_occurred.emit("无法连接 K230 视频流: %s" % self.url)
            return

        while self._running:
            ok, frame = cap.read()         # 阻塞式收包+JPEG解码
            if not ok:
                self.error_occurred.emit("视频流中断, 3s 后重连")
                self.msleep(3000)
                cap.release()
                cap = cv2.VideoCapture(self.url)
                continue

            h, w, ch = frame.shape
            from PySide6.QtGui import QImage
            img = QImage(frame.data, w, h, ch * w, QImage.Format_BGR888)
            self.frame_received.emit(img.copy())   # copy 脱离原缓冲区

        cap.release()

    def stop(self):
        self._running = False
        self.wait(3000)
