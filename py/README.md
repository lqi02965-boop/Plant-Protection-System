# PC 调试端（PySide6，已被小程序替代，仅留作开发调试工具）

> 注意：主方案已改为微信小程序（见 `../mp/`），数据链路也改为华为云 IoTDA。
> 本目录的 TCP 直连链路与新版 STM32（MQTT）**不再兼容**，仅当 PC+K230 调试工具使用；
> 若要对接新版设备，请用 `video_thread.py` 看推流 + 用 `230/main.py` 的 /snapshot 接口。

## 运行

```bash
cd py
pip install -r requirements.txt
python main.py
```

先改 `main.py` 里的 `K230_STREAM_URL` 为你 K230 的实际推流地址。
PC 需与 K230 / ESP8266 在同一局域网，TCP 监听端口 9000（防火墙放行）。

## 文件结构

| 文件 | 说明 |
|------|------|
| `main.py` | 主窗口：画面显示、实时数据、趋势曲线、阈值设置、历史表、CSV 导出 |
| `video_thread.py` | QThread：OpenCV 拉 K230 的 HTTP MJPG 流，解码成 QImage 发信号 |
| `data_server.py` | QThread：TCP Server 收 `DATA,...#` 帧并解析 |
| `database.py` | SQLite 存储 + CSV 导出（utf-8-sig，Excel 直开不乱码） |

## 测试（没有硬件也能跑）

另开一个终端模拟 STM32 发数据：

```python
import socket, time
s = socket.create_connection(("127.0.0.1", 9000))
import random
while True:
    t, h = random.randint(180, 350), random.randint(300, 900)
    p = random.randint(0, 20)
    s.sendall(f"DATA,{t},{h},{p},{1 if p>5 else 0},0#".encode())
    time.sleep(3)
```

视频区显示"等待视频流"属正常；数据区、曲线、历史表、导出都能验证。

## 面试要点

- **为什么视频接收放 QThread**：主线程只跑 UI，网络收包 + JPEG 解码耗时，放主线程界面假死；QThread + Signal/Slot 跨线程传 QImage
- **pyqtgraph vs matplotlib**：pyqtgraph 基于 Qt 原生绘图，实时刷新远快于 matplotlib
- **SQLite**：单文件嵌入式，`check_same_thread=False` + 锁保证 TCP 线程与 UI 线程并发写安全
