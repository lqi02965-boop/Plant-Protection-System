from ultralytics import YOLO

if __name__ == '__main__':
    # 1. 加载预训练模型权重
    model = YOLO('yolov8s.pt')

    # 2. 启动 GPU 训练
    results = model.train(
        data='pest_dataset/data.yaml',  # 数据集配置文件路径
        epochs=50,                      # 训练轮数
        imgsz=640,                      # 图像输入分辨率
        batch=16,                       # RTX 4060 8GB 显存推荐批次大小
        device=0,                       # 使用 GPU 0 训练
        workers=4,                      # 加载数据的多线程数
        name='crop_pest_final',         # 训练结果保存目录名
        exist_ok=True,                  # 覆盖同名文件夹，避免生成过多 `-1`, `-2` 副本
    )