# -*- coding: utf-8 -*-
# =============================================================================
#  ONNX -> K230 kmodel 转换脚本（适配 nncase 2.11 + K230 KPU 插件）
# -----------------------------------------------------------------------------
#  用法：
#      cd D:\ai_project_tree\yolo
#      D:\python\python\field\v81\Scripts\python.exe convert_kmodel.py
#
#  前提（这条最重要）：
#      pip install nncase==2.11.0
#      pip install <从 GitHub Release 下的> nncase_kpu-2.11.0-py2.py3-none-win_amd64.whl
#      ↑ nncase-kpu 不在 PyPI，必须手动装，否则会报：
#        KeyNotFoundException: The given key 'k230' was not present in the dictionary
#
#  原脚本 4 个错误（已在本文件修正）：
#      1. nncase.PTQOptions()        → 2.x 里叫 PTQTensorOptions（PTQOptions 不存在）
#      2. ptq_options.dataset = 目录 → 2.x 要用 set_tensor_data([...]) 传真正的图片数组
#      3. 没配 input_type/preprocess → kmodel 会变成 float32 输入，板子上喂 uint8 就出错
#      4. compile_options.mean/std   → 要和 ultralytics 训练时的归一化一致（见下面的注释）
# =============================================================================

import os
import sys
import glob

# Windows 控制台默认是 GBK 编码，遇到编不进去的字符会直接崩。
# 这一句让无法编码的字符变成 '?' 而不是抛 UnicodeEncodeError。
try:
    sys.stdout.reconfigure(errors='replace')
except Exception:
    pass

import numpy as np
from PIL import Image
import nncase

# ---------------------------- 配置区 ----------------------------
ONNX_PATH = r'runs/detect/crop_pest_final/weights/best.onnx'
KMODEL_OUT = r'runs/detect/crop_pest_final/weights/best.kmodel'
CALIB_DIR = r'pest_dataset/test/images'      # 量化校准图目录（用真实场景图）
CALIB_NUM = 50                               # 用多少张校准图（20~100 张足够，越多越慢）
DUMP_DIR = r'runs/detect/crop_pest_final/nncase_dump'

MODEL_H = 640                                # 模型输入高（必须和训练 imgsz 一致）
MODEL_W = 640                                # 模型输入宽
LETTERBOX_VALUE = 114                        # 灰边填充值，和 ultralytics 训练时一致

# ultralytics 训练时的归一化是「像素/255」，没有 ImageNet 均值方差。
# nncase 的处理顺序是：先用 input_range 把 uint8 归一到 0~1，再 (x-mean)/std。
# 所以 mean=0, std=255 才是对的（nncase 算的是 (x-mean)/std）
INPUT_RANGE = [0, 255]
MEAN = [0.0, 0.0, 0.0]
STD = [255.0, 255.0, 255.0]   # ★ 关键: (x-mean)/std, 要把 0~255 除成 0~1


def load_calibration_data():
    """读取校准图，做 letterbox（等比缩放+灰边）到模型输入尺寸，返回 uint8 NCHW 数组列表"""
    patterns = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.JPG', '*.PNG']
    files = []
    for p in patterns:
        files += glob.glob(os.path.join(CALIB_DIR, p))
    files = sorted(set(files))[:CALIB_NUM]

    if not files:
        raise SystemExit("[FAIL] 校准图目录里没有图片: %s" % os.path.abspath(CALIB_DIR))

    print("校准图数量: %d 张（来自 %s）" % (len(files), CALIB_DIR))

    data = []
    for f in files:
        img = Image.open(f).convert('RGB')
        w, h = img.size
        # 等比缩放到 640x640 内，再居中贴到 114 灰底上（和板子端 AI2D 的做法一致）
        ratio = min(MODEL_W / float(w), MODEL_H / float(h))
        new_w, new_h = int(round(w * ratio)), int(round(h * ratio))
        img = img.resize((new_w, new_h), Image.BILINEAR)
        canvas = Image.new('RGB', (MODEL_W, MODEL_H), (LETTERBOX_VALUE,) * 3)
        canvas.paste(img, ((MODEL_W - new_w) // 2, (MODEL_H - new_h) // 2))

        # HWC -> CHW，加 batch 维，保持 uint8（模型输入就是 uint8）
        arr = np.asarray(canvas, dtype=np.uint8).transpose(2, 0, 1)[None]
        data.append([arr])          # 每个样本是「一个输入数组」的列表（2.x 要求这种嵌套）
    return data


def main():
    # ---------- 0. 先检查 K230 目标插件在不在（这是最容易卡住的地方） ----------
    try:
        nncase.check_target('k230')
        print("[OK] K230 目标插件已就绪")
    except Exception as e:
        print("[FAIL] K230 目标不可用: %s" % e)
        print("   请先安装 nncase-kpu 插件（GitHub Release 里的 whl），再重跑本脚本")
        sys.exit(1)

    if not os.path.exists(ONNX_PATH):
        raise SystemExit("[FAIL] 找不到 ONNX: %s" % os.path.abspath(ONNX_PATH))

    onnx_size = os.path.getsize(ONNX_PATH) / 1048576.0
    print("ONNX 模型: %s (%.1f MB)" % (ONNX_PATH, onnx_size))

    # ---------- 1. 编译选项 ----------
    compile_options = nncase.CompileOptions()
    compile_options.target = 'k230'                       # 目标芯片
    compile_options.dump_dir = DUMP_DIR

    # 板子端会用 AI2D 做 letterbox，然后把 uint8 数据喂给模型，
    # 所以这里声明「输入是 uint8 的 NCHW」，并开启片内预处理（归一化）
    compile_options.input_type = 'uint8'
    compile_options.input_shape = [1, 3, MODEL_H, MODEL_W]
    compile_options.input_layout = 'NCHW'
    compile_options.output_layout = 'NCHW'
    compile_options.preprocess = True
    compile_options.input_range = INPUT_RANGE
    compile_options.mean = MEAN
    compile_options.std = STD
    compile_options.swapRB = False                        # 输入已是 RGB，不用交换红蓝

    compiler = nncase.Compiler(compile_options)           # 2.x 必须传 compile_options

    # ---------- 2. 导入 ONNX ----------
    print("导入 ONNX 中...")
    with open(ONNX_PATH, 'rb') as f:
        model_content = f.read()
    compiler.import_onnx(model_content, nncase.ImportOptions())

    # ---------- 3. PTQ 量化（K230 只跑 uint8 定点，必须给校准集） ----------
    calib_data = load_calibration_data()
    ptq_options = nncase.PTQTensorOptions()               # ← 2.x 的正确类名
    ptq_options.samples_count = len(calib_data)           # 必须等于样本数
    ptq_options.set_tensor_data(calib_data)               # ← 2.x 的正确传数据方式
    ptq_options.calibrate_method = 'NoClip'               # 小目标检测常用 NoClip；也可用 Kld
    compiler.use_ptq(ptq_options)

    # ---------- 4. 编译导出 ----------
    print("开始编译（yolov8s@640 + PTQ，通常要几分钟到十几分钟，请耐心等）...")
    compiler.compile()

    kmodel_bytes = compiler.gencode_tobytes()             # 2.11 里这个方法存在
    os.makedirs(os.path.dirname(KMODEL_OUT), exist_ok=True)
    with open(KMODEL_OUT, 'wb') as f:
        f.write(kmodel_bytes)

    print("\n" + "=" * 60)
    print("转换成功！")
    print("   kmodel: %s" % os.path.abspath(KMODEL_OUT))
    print("   大小: %.2f MB" % (len(kmodel_bytes) / 1048576.0))
    print("   下一步：把 kmodel 拷到 K230 的 SD 卡，并在 main.py 里改 KMODEL_CANDIDATES")
    print("=" * 60)


if __name__ == '__main__':
    main()
