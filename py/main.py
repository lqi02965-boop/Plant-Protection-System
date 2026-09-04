# -*- coding: utf-8 -*-
"""农田虫害智能监测系统 - PC 上位机
PySide6(Qt for Python): 主线程只跑 UI, 视频收流/TCP收数各放子线程,
子线程通过 Signal/Slot 跨线程把帧和数据发回主线程刷新界面。
运行: python main.py
"""
import sys
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel,
                               QVBoxLayout, QHBoxLayout, QGridLayout,
                               QPushButton, QSpinBox, QGroupBox, QTableWidget,
                               QTableWidgetItem, QMessageBox)
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Qt, QTimer
import pyqtgraph as pg

from video_thread import VideoThread
from data_server import TcpServerThread
from database import MonitorDB

# 按现场环境修改
K230_STREAM_URL = "http://192.168.1.50:8080"   # K230 MJPG 推流地址

MAX_CURVE_POINTS = 200


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("农田虫害智能监测系统 - 上位机")
        self.resize(1280, 800)

        self.db = MonitorDB()
        self._build_ui()

        # 视频线程
        self.video = VideoThread(K230_STREAM_URL)
        self.video.frame_received.connect(self.on_frame)     # 跨线程信号 -> 槽
        self.video.error_occurred.connect(lambda m: self.statusBar().showMessage(m, 5000))
        self.video.start()

        # TCP 数据线程
        self.server = TcpServerThread()
        self.server.data_received.connect(self.on_data)
        self.server.client_connected.connect(
            lambda a: self.statusBar().showMessage("设备上线: " + a))
        self.server.start()

        self._curve_t = []
        self._curve_p = []

    # ---------------- UI ----------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # 左: 视频 + 曲线
        left = QVBoxLayout()
        self.video_label = QLabel("等待 K230 视频流...")
        self.video_label.setMinimumSize(640, 480)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background:#000; color:#888;")
        left.addWidget(self.video_label, 4)

        self.plot = pg.PlotWidget(title="虫数 / 温度 趋势")
        self.plot.addLegend()
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.curve_pest = self.plot.plot(pen=pg.mkPen("#e74c3c", width=2), name="虫数")
        self.curve_temp = self.plot.plot(pen=pg.mkPen("#3498db", width=2), name="温度℃")
        left.addWidget(self.plot, 2)
        root.addLayout(left, 3)

        # 右: 状态 + 控制 + 历史
        right = QVBoxLayout()
        env_box = QGroupBox("环境数据")
        grid = QGridLayout(env_box)
        self.temp_label = self._big_label("--")
        self.humi_label = self._big_label("--")
        self.pest_label = self._big_label("0")
        self.spray_label = self._big_label("待机")
        grid.addWidget(QLabel("温度"), 0, 0); grid.addWidget(self.temp_label, 1, 0)
        grid.addWidget(QLabel("湿度"), 0, 1); grid.addWidget(self.humi_label, 1, 1)
        grid.addWidget(QLabel("虫数"), 0, 2); grid.addWidget(self.pest_label, 1, 2)
        grid.addWidget(QLabel("喷雾状态"), 0, 3); grid.addWidget(self.spray_label, 1, 3)
        right.addWidget(env_box)

        ctrl_box = QGroupBox("控制")
        cl = QGridLayout(ctrl_box)
        self.th_spin = QSpinBox(); self.th_spin.setRange(1, 999); self.th_spin.setValue(5)
        cl.addWidget(QLabel("喷雾虫数阈值"), 0, 0); cl.addWidget(self.th_spin, 0, 1)
        self.spray_btn = QPushButton("手动喷雾")
        self.spray_btn.clicked.connect(self.on_manual_spray)
        cl.addWidget(self.spray_btn, 1, 0)
        self.export_btn = QPushButton("导出 CSV")
        self.export_btn.clicked.connect(self.on_export)
        cl.addWidget(self.export_btn, 1, 1)
        right.addWidget(ctrl_box)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["时间", "温度", "湿度", "虫数", "喷雾", "诱虫灯"])
        self.table.horizontalHeader().setStretchLastSection(True)
        right.addWidget(self.table)
        root.addLayout(right, 2)

        # 历史表定时刷新
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_table)
        self._timer.start(3000)
        self.refresh_table()

    @staticmethod
    def _big_label(text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size:28px; font-weight:bold;")
        return lbl

    # ---------------- 槽函数 ----------------
    def on_frame(self, img: QImage):
        """视频线程信号 -> 更新画面(QLabel.setPixmap 自动缩放)"""
        self.video_label.setPixmap(QPixmap.fromImage(img).scaled(
            self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def on_data(self, d: dict):
        """TCP线程信号 -> 刷新实时数值 + 曲线 + 入库"""
        self.temp_label.setText("%.1f ℃" % d["temp"])
        self.humi_label.setText("%.1f %%" % d["humi"])
        self.pest_label.setText(str(d["pests"]))
        self.spray_label.setText("喷雾中!" if d["spray"] else "待机")
        self.spray_label.setStyleSheet(
            "color:#c0392b; font-weight:bold;" if d["spray"] else "")

        self._curve_t.append(d["temp"])
        self._curve_p.append(d["pests"])
        if len(self._curve_t) > MAX_CURVE_POINTS:
            self._curve_t.pop(0); self._curve_p.pop(0)
        self.curve_temp.setData(self._curve_t)
        self.curve_pest.setData(self._curve_p)

        self.db.insert(d["temp"], d["humi"], d["pests"], d["spray"], d["lamp"])

    def on_manual_spray(self):
        # TODO: 下发手动喷雾指令(需 STM32 端增加下行帧, 如 SPRAY#)
        QMessageBox.information(self, "提示", "手动喷雾: 硬件版请在设备端按 WK_UP 键;\n"
                                             "下行控制帧需在 STM32/ESP8266 端扩展。")

    def on_export(self):
        path = self.db.export_csv()
        QMessageBox.information(self, "导出完成", "已导出: " + path)

    def refresh_table(self):
        rows = self.db.query_recent(100)
        self.table.setRowCount(len(rows))
        for i, (t, te, hu, p, s, l) in enumerate(rows):
            vals = [t, "%.1f" % te, "%.1f" % hu, str(p),
                    "是" if s else "否", "开" if l else "关"]
            for j, v in enumerate(vals):
                self.table.setItem(i, j, QTableWidgetItem(v))

    def closeEvent(self, e):
        self.video.stop()
        self.server.stop()
        e.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
