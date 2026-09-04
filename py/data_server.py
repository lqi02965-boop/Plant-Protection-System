# -*- coding: utf-8 -*-
"""TCP 数据接收线程: 监听端口, 接收 STM32 -> ESP8266 -> WiFi 的数据帧
帧格式: DATA,温度x10,湿度x10,虫数,喷雾中,诱虫灯#   例: DATA,256,600,12,1,0#
'#' 定界, 逗号分隔; 收到后解析成字典通过信号发主线程
"""
import socket
from PySide6.QtCore import QThread, Signal


class TcpServerThread(QThread):
    data_received = Signal(dict)
    client_connected = Signal(str)

    LISTEN_PORT = 9000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True

    def run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.LISTEN_PORT))
        srv.listen(4)
        srv.settimeout(1.0)
        print("TCP 服务监听中, 端口 %d ..." % self.LISTEN_PORT)

        buf = b""
        while self._running:
            try:
                conn, addr = srv.accept()
                self.client_connected.emit("%s:%d" % addr)
                conn.settimeout(1.0)
                try:
                    while self._running:
                        chunk = conn.recv(256)
                        if not chunk:
                            break
                        buf += chunk
                        # 按 '#' 拆帧, 半帧留到下一次
                        while b"#" in buf:
                            frame, buf = buf.split(b"#", 1)
                            self._parse(frame.decode(errors="ignore").strip())
                except socket.timeout:
                    pass          # 没数据, 回到外层检查 _running
                finally:
                    conn.close()
            except socket.timeout:
                continue

        srv.close()

    def _parse(self, frame):
        # DATA,256,600,12,1,0 -> temp=25.6 humi=60.0 pests=12 spray=1 lamp=0
        parts = frame.split(",")
        if len(parts) != 6 or parts[0] != "DATA":
            return
        try:
            data = {
                "temp":  int(parts[1]) / 10.0,
                "humi":  int(parts[2]) / 10.0,
                "pests": int(parts[3]),
                "spray": int(parts[4]),
                "lamp":  int(parts[5]),
            }
            self.data_received.emit(data)
        except ValueError:
            pass

    def stop(self):
        self._running = False
        self.wait(3000)
