# -*- coding: utf-8 -*-
# =============================================================================
#  PC 端排查脚本：对比 ONNX 和 kmodel 在同一张图上的输出
# -----------------------------------------------------------------------------
#  目的：判断"虫数乱跳(50个框)"的问题出在
#        (A) 模型/转换本身 —— 那 kmodel 的输出就会和 ONNX 差很远
#        (B) 板子上取图/喂数据的环节 —— 那 kmodel 在 PC 上模拟是正常的
#
#  用法: python _debug_compare.py
# =============================================================================
import os
import glob
import sys

# kmodel 模拟器需要 k230 的运行模块(Nncase.Modules.K230.dll)，
# 它由 nncase-kpu 装在 nncase/modules/kpu/ 下，必须通过环境变量告诉 nncase，
# 否则报 "The specified module could not be found."
os.environ.setdefault(
    "NNCASE_PLUGIN_PATH",
    r"D:\python\python\field\v81\Lib\site-packages\nncase\modules\kpu")
# 兜底：如果上面这个目录不存在，就从当前解释器的 site-packages 推
try:
    import importlib.util
    spec = importlib.util.find_spec("nncase")
    if spec and spec.origin:
        cand = os.path.join(os.path.dirname(spec.origin), "modules", "kpu")
        if os.path.isdir(cand):
            os.environ["NNCASE_PLUGIN_PATH"] = cand
            print("插件目录:", cand)
except Exception:
    pass

import numpy as np
from PIL import Image

YOLO_DIR = r"D:\ai_project_tree\yolo"
ONNX = os.path.join(YOLO_DIR, r"runs\detect\crop_pest_final\weights\best.onnx")
KMODEL = os.path.join(YOLO_DIR, r"runs\detect\crop_pest_final\weights\best.kmodel")
IMG_DIR = os.path.join(YOLO_DIR, r"pest_dataset\test\images")

MODEL_W = MODEL_H = 640
PAD = 114          # letterbox 灰边，和转换校准图/板子端一致
CONF = 0.45        # 板子端 main.py 里的阈值


def letterbox(path):
    """等比缩放 + 灰边到 640x640，返回 HWC uint8"""
    img = Image.open(path).convert('RGB')
    w, h = img.size
    r = min(MODEL_W / float(w), MODEL_H / float(h))
    nw, nh = int(round(w * r)), int(round(h * r))
    img = img.resize((nw, nh), Image.BILINEAR)
    canvas = Image.new('RGB', (MODEL_W, MODEL_H), (PAD, PAD, PAD))
    canvas.paste(img, ((MODEL_W - nw) // 2, (MODEL_H - nh) // 2))
    return np.asarray(canvas, dtype=np.uint8)


def decode(out, conf=CONF):
    """yolov8 输出 (1,5,8400) -> (超过阈值的框数, 最高分, 前5个分数)"""
    d = np.asarray(out).reshape(out.shape[1], out.shape[2]).T     # (8400,5)
    scores = d[:, 4]
    return int((scores > conf).sum()), float(scores.max()), np.round(scores[:5], 3)


def main():
    imgs = sorted(glob.glob(os.path.join(IMG_DIR, '*.jpg')) +
                  glob.glob(os.path.join(IMG_DIR, '*.png')))[:2]
    if not imgs:
        print("找不到测试图:", IMG_DIR)
        return

    # ---------- 1) ONNX 基准（float32，0~1 归一化）----------
    import onnxruntime as ort
    sess = ort.InferenceSession(ONNX, providers=['CPUExecutionProvider'])
    in_name = sess.get_inputs()[0].name
    print("ONNX 输入:", in_name, sess.get_inputs()[0].shape)

    # ---------- 2) kmodel 模拟器（uint8 输入，片内做归一化）----------
    import nncase
    sim = nncase.Simulator()
    with open(KMODEL, 'rb') as f:
        sim.load_model(f.read())          # 注意：要传字节内容，不是路径
    print("kmodel 输入 shape:", [sim.get_input_shape(i) for i in range(sim.inputs_size())])
    print("kmodel 输出 shape:", [sim.get_output_shape(i) for i in range(sim.outputs_size())])
    print()

    for p in imgs:
        hwc = letterbox(p)
        chw = hwc.transpose(2, 0, 1)                     # (3,640,640)

        # ONNX: float32 / 255
        x = chw[None].astype(np.float32) / 255.0
        out_onnx = sess.run(None, {in_name: x})[0]

        # kmodel: uint8（转换时配了 input_type=uint8 + 归一化融合）
        sim.set_input_tensor(0, nncase.RuntimeTensor.from_numpy(chw[None].astype(np.uint8)))
        sim.run()
        out_km = sim.get_output_tensor(0).to_numpy()

        n1, mx1, s1 = decode(out_onnx)
        n2, mx2, s2 = decode(out_km)

        print("图片:", os.path.basename(p))
        print("   ONNX   : 框数=%3d  最高分=%.3f  前5分数=%s" % (n1, mx1, s1))
        print("   kmodel : 框数=%3d  最高分=%.3f  前5分数=%s" % (n2, mx2, s2))
        print("   输出统计: kmodel min=%.3f max=%.3f  (ONNX min=%.3f max=%.3f)"
              % (out_km.min(), out_km.max(), out_onnx.min(), out_onnx.max()))
        print()


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
    main()
