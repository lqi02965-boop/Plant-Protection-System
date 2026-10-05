# -*- coding: utf-8 -*-
# =============================================================================
#  最终验证：在有虫子的数据集图片上，比较 ONNX 和新 kmodel 的检出结果
# =============================================================================
import os
import sys
import glob

import numpy as np
from PIL import Image

SP = r"D:\python\python\field\v81\Lib\site-packages"
YOLO = r"D:\ai_project_tree\yolo"
ONNX = os.path.join(YOLO, r"runs\detect\crop_pest_final\weights\best.onnx")
IMG_DIR = os.path.join(YOLO, r"pest_dataset\test\images")
KMODELS = [
    os.path.join(r"D:\ai_project_tree\230\_kmodels", "best_修正_std255.kmodel"),
    os.path.join(r"D:\ai_project_tree\230\_kmodels", "best_当前错_std1.kmodel"),
]

kpu_dir = os.path.join(SP, "nncase", "modules", "kpu")
for p in (SP, os.path.join(SP, "nncase"), kpu_dir):
    if os.path.isdir(p):
        os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(p)
        except Exception:
            pass
os.environ["NNCASE_PLUGIN_PATH"] = kpu_dir

import nncase

W = H = 640
PAD = 114
CONF = 0.45


def letterbox(path):
    img = Image.open(path).convert('RGB')
    w, h = img.size
    r = min(W / float(w), H / float(h))
    nw, nh = int(round(w * r)), int(round(h * r))
    img = img.resize((nw, nh), Image.BILINEAR)
    canvas = Image.new('RGB', (W, H), (PAD, PAD, PAD))
    canvas.paste(img, ((W - nw) // 2, (H - nh) // 2))
    return np.asarray(canvas, dtype=np.uint8).transpose(2, 0, 1)[None]


def stats(out, conf=CONF):
    d = np.asarray(out).reshape(out.shape[1], out.shape[2]).T
    sc = d[:, 4]
    return int((sc > conf).sum()), float(sc.max())


def run_kmodel(path, inp):
    sim = nncase.Simulator()
    with open(path, 'rb') as f:
        sim.load_model(f.read())
    sim.set_input_tensor(0, nncase.RuntimeTensor.from_numpy(inp))
    sim.run()
    return sim.get_output_tensor(0).to_numpy()


def main():
    import onnxruntime as ort
    sess = ort.InferenceSession(ONNX, providers=['CPUExecutionProvider'])

    # 每个 kmodel 只加载一次模拟器（加载很慢，复用）
    sims = []
    for k in KMODELS:
        sim = nncase.Simulator()
        with open(k, 'rb') as f:
            sim.load_model(f.read())
        sims.append(sim)
    print("两个 kmodel 模拟器加载完成")

    imgs = sorted(glob.glob(os.path.join(IMG_DIR, '*.jpg')))[:2]
    for p in imgs:
        x = letterbox(p)
        ref = sess.run(None, {'images': x.astype(np.float32) / 255.0})[0]
        n_ref, mx_ref = stats(ref)
        print("\n图片: %s" % os.path.basename(p))
        print("   ONNX 基准        : 框数=%3d 最高分=%.3f" % (n_ref, mx_ref))
        for k, sim in zip(KMODELS, sims):
            t0 = __import__('time').time()
            sim.set_input_tensor(0, nncase.RuntimeTensor.from_numpy(x))
            sim.run()
            out = sim.get_output_tensor(0).to_numpy()
            n, mx = stats(out)
            tag = "修正版(std=255)" if "std255" in k else "错误版(std=1)  "
            print("   %s : 框数=%3d 最高分=%.3f   (%.1fs)"
                  % (tag, n, mx, __import__('time').time() - t0))

    print("\n说明: 每列是「过阈值框数 / 最高分」。正常的话，修正版的框数应和 ONNX 接近(数据集图里都有虫子)。")


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
    main()
