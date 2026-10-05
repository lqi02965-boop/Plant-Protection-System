from ultralytics import YOLO
import glob
import os

if __name__ == '__main__':
    # 1. 加载刚训练好的最佳模型权重
    model_path = r'runs/detect/crop_pest_final/weights/best.pt'
    
    if not os.path.exists(model_path):
        print(f"错误：未找到模型文件 {model_path}，请检查训练是否正常完成。")
        exit()
        
    model = YOLO(model_path)

    # 2. 获取测试集目录下的第一张图片（或者你可以把路径替换为你想测试的具体图片路径）
    test_images = glob.glob('pest_dataset/test/images/*.*')
    
    if test_images:
        target_img = test_images[0]
        print(f"正在分析图片: {target_img}")
        
        # 进行推理（conf=0.25 为置信度阈值）
        results = model(target_img, conf=0.25)

        for result in results:
            # 统计检测到的边界框总数
            pest_count = len(result.boxes)
            
            print("\n" + "=" * 40)
            print(f" 识别完成！图像中检测到的虫子总数: {pest_count} 只")
            print("=" * 40 + "\n")
            
            # 显示结果图并保存到本地
            result.show()
            result.save(filename='pest_result.jpg')
            print("标注结果图片已保存为 pest_result.jpg")
    else:
        print("未在 pest_dataset/test/images/ 目录下找到测试图片，请检查图片路径！")