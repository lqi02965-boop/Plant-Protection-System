# K230 视觉检测端

## 目录说明

| 文件 | 说明 |
|------|------|
| `main.py` | CanMV K230 主脚本：推理 + 计数 + MJPG 推流 + UART 上报 |
| `nncase_convert.py` | PC 端模型转换脚本（ONNX → kmodel） |
| `README.md` | 本说明 |

## 模型训练与部署流程（PC 上做，K230 上跑）

```bash
# 1. 训练（PC，ultralytics）
pip install ultralytics
yolo detect train data=pest.yaml model=yolov8s.pt imgsz=320 epochs=100

# 2. 导出 ONNX（imgsz、opset 与转换脚本保持一致）
yolo export model=runs/detect/train/weights/best.pt format=onnx imgsz=320 opset=13

# 3. nncase 转换（本目录 nncase_convert.py）
pip install nncase[nrt]==2.9.1 nncase-kpu==2.9.1
python nncase_convert.py best.onnx pest_det.kmodel

# 4. 把 pest_det.kmodel 拷到 K230 的 SD 卡 /data 目录
```

## 验证方法

1. CanMV IDE 打开 `main.py`，先确认串口/WiFi/模型路径三个配置对得上
2. PC 浏览器访问 `http://<K230_IP>:8080` 应看到带检测框的画面
3. 用 `py/` 端 OpenCV `VideoCapture("http://<K230_IP>:8080")` 拉流
4. K230 TX 接 STM32 RX（共地），STM32 端应收到 `$n#` 虫数帧

## 面试要点

- **为什么检测放 K230 不放 PC**：边缘计算，断网也能检测和触发喷雾，PC 只是"看"的窗口
- **nncase 全流程**：.pt → ONNX → .kmodel，推理跑在 KPU（6TOPS），CPU 只做前后处理
- **推流原理**：`multipart/x-mixed-replace`，每帧独立 JPEG，HTTP 长连接持续 push
- **串口帧 `$n#`**：自定义文本帧，简单可靠，方便 STM32 端用 `$` `#` 定界解析
