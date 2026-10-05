from ultralytics import YOLO

if __name__ == '__main__':
    # 1. 加载刚训练好的最佳模型权重
    model = YOLO('runs/detect/crop_pest_final/weights/best.pt')

    # 2. 导出为 ONNX 格式 (适用于 nncase 转换)
    # opset=11 或 12 是 KPU 转换的最佳推荐版本，simplify 自动简化图结构
    model.export(
        format='onnx',
        imgsz=640,
        opset=12,
        simplify=True
    )
    print("ONNX 导出完成！生成文件位于 runs/detect/crop_pest_final/weights/best.onnx")
    