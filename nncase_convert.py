# -*- coding: utf-8 -*-
# =============================================================================
#  PC 端模型转换脚本：ONNX -> K230 .kmodel（适配 nncase 2.11 + nncase-kpu 插件）
# -----------------------------------------------------------------------------
#  这个脚本和 yolo/convert_kmodel.py 是同一份逻辑，放在这里方便和 K230 端代码对照。
#  实际转换时用的是 D:\ai_project_tree\yolo\convert_kmodel.py（已经跑通，生成 best.kmodel）。
#
#  用法：
#      python nncase_convert.py best.onnx best.kmodel [校准图目录]
#
#  依赖（关键，装错就报 KeyNotFoundException: 'k230'）：
#      pip install nncase==2.11.0
#      pip install <GitHub Release 下载的> nncase_kpu-2.11.0-py2.py3-none-win_amd64.whl
#      nncase-kpu 不在 PyPI，必须从 https://github.com/kendryte/nncase/releases 下
#
#  踩过的坑（原脚本 4 处错误，这里都已修正）：
#      1. nncase.PTQOptions()        → 2.x 里类名是 PTQTensorOptions
#      2. ptq_options.dataset = 目录 → 2.x 要用 set_tensor_data([...]) 传图片数组
#      3. 必须配 input_type/input_range/preprocess，否则 kmodel 输入是 float32，
#         板子端喂 uint8 会报错
#      4. mean/std 要用 ultralytics 的归一化(即只除以 255)，不能填 ImageNet 那组
# =============================================================================

import os
import sys
import glob

# Windows 控制台是 GBK，遇到编不进去的字符会崩，这里让它替换而不是抛异常
try:
    sys.stdout.reconfigure(errors='replace')
except Exception:
    pass

import numpy as np
from PIL import Image
import nncase

MODEL_H = 640           # 模型输入高，必须和训练 imgsz 一致
MODEL_W = 640           # 模型输入宽
CALIB_NUM = 50          # 用多少张校准图
LETTERBOX_VALUE = 114   # 灰边填充值，和训练时一致


def load_calibration_data(calib_dir):
    """读校准图 -> letterbox 到模型输入尺寸 -> uint8 NCHW 数组"""
    files = []
    for pat in ('*.jpg', '*.jpeg', '*.png', '*.bmp', '*.JPG', '*.PNG'):
        files += glob.glob(os.path.join(calib_dir, pat))
    files = sorted(set(files))[:CALIB_NUM]
    if not files:
        raise SystemExit("[FAIL] 校准图目录里没图片: %s" % os.path.abspath(calib_dir))

    print("校准图数量: %d 张（来自 %s）" % (len(files), calib_dir))
    data = []
    for f in files:
        img = Image.open(f).convert('RGB')
        w, h = img.size
        ratio = min(MODEL_W / float(w), MODEL_H / float(h))
        nw, nh = int(round(w * ratio)), int(round(h * ratio))
        img = img.resize((nw, nh), Image.BILINEAR)
        canvas = Image.new('RGB', (MODEL_W, MODEL_H), (LETTERBOX_VALUE,) * 3)
        canvas.paste(img, ((MODEL_W - nw) // 2, (MODEL_H - nh) // 2))
        arr = np.asarray(canvas, dtype=np.uint8).transpose(2, 0, 1)[None]   # (1,3,640,640)
        data.append([arr])
    return data


def main():
    onnx_path = sys.argv[1] if len(sys.argv) > 1 else "best.onnx"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "best.kmodel"
    calib_dir = sys.argv[3] if len(sys.argv) > 3 else "pest_dataset/test/images"

    # 先确认 K230 目标插件在不在（最常见的卡点）
    try:
        nncase.check_target('k230')
        print("[OK] K230 目标插件已就绪")
    except Exception as e:
        print("[FAIL] K230 目标不可用: %s" % e)
        print("       请先安装 nncase-kpu 插件（GitHub Release 里的 whl）")
        sys.exit(1)

    if not os.path.exists(onnx_path):
        raise SystemExit("[FAIL] 找不到 ONNX: %s" % os.path.abspath(onnx_path))
    print("ONNX: %s (%.1f MB)" % (onnx_path, os.path.getsize(onnx_path) / 1048576.0))

    # 编译选项
    co = nncase.CompileOptions()
    co.target = 'k230'
    co.input_type = 'uint8'                 # 板子端喂 uint8
    co.input_shape = [1, 3, MODEL_H, MODEL_W]
    co.input_layout = 'NCHW'
    co.output_layout = 'NCHW'
    co.preprocess = True                    # 归一化融进模型（片内做，不占 CPU）
    co.input_range = [0, 255]               # uint8 原始范围
    co.mean = [0.0, 0.0, 0.0]               # ultralytics 只除以 255，不减均值
    co.std = [255.0, 255.0, 255.0]   # ★ 关键: 除 255 才有 0~1, 否则模型分数饱和乱报
    co.swapRB = False

    compiler = nncase.Compiler(co)
    with open(onnx_path, 'rb') as f:
        compiler.import_onnx(f.read(), nncase.ImportOptions())

    # PTQ 量化：K230 只跑 uint8 定点，必须提供校准集
    calib = load_calibration_data(calib_dir)
    ptq = nncase.PTQTensorOptions()
    ptq.samples_count = len(calib)
    ptq.set_tensor_data(calib)
    ptq.calibrate_method = 'NoClip'
    compiler.use_ptq(ptq)

    print("开始编译（几分钟到十几分钟，请等）...")
    compiler.compile()
    kmodel = compiler.gencode_tobytes()
    with open(out_path, 'wb') as f:
        f.write(kmodel)

    print("转换成功: %s (%.2f MB)" % (os.path.abspath(out_path), len(kmodel) / 1048576.0))


if __name__ == '__main__':
    main()
