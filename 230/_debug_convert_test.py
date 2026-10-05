# -*- coding: utf-8 -*-
# =============================================================================
#  本地迭代转换参数：重转 kmodel 并用模拟器验证，和 ONNX 对比
#  裁判标准：拿板子导出的真实输入 model_in.bin，
#            分别喂给 ONNX(除255) 和 kmodel，比较"过阈值框数"和"最高分"
# =============================================================================
import os
import sys
import glob

import numpy as np
from PIL import Image

SP = r"D:\python\python\field\v81\Lib\site-packages"
YOLO = r"D:\ai_project_tree\yolo"
ONNX = os.path.join(YOLO, r"runs\detect\crop_pest_final\weights\best.onnx")
CALIB_DIR = os.path.join(YOLO, r"pest_dataset\test\images")
OUT_DIR = r"D:\ai_project_tree\230\_kmodels"
MODEL_IN = r"D:\ai_project_tree\230\_dump\model_in.bin"

# 插件/DLL 路径（Simulator 要用）
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

MODEL_W = MODEL_H = 640
PAD = 114
CALIB_NUM = 20
CONF = 0.45


def letterbox_uint8(path):
    img = Image.open(path).convert('RGB')
    w, h = img.size
    r = min(MODEL_W / float(w), MODEL_H / float(h))
    nw, nh = int(round(w * r)), int(round(h * r))
    img = img.resize((nw, nh), Image.BILINEAR)
    canvas = Image.new('RGB', (MODEL_W, MODEL_H), (PAD, PAD, PAD))
    canvas.paste(img, ((MODEL_W - nw) // 2, (MODEL_H - nh) // 2))
    return np.asarray(canvas, dtype=np.uint8).transpose(2, 0, 1)[None]


def decode(out, conf=CONF):
    d = np.asarray(out).reshape(out.shape[1], out.shape[2]).T
    sc = d[:, 4]
    return int((sc > conf).sum()), float(sc.max())


def convert(std, mean, input_range, out_path):
    co = nncase.CompileOptions()
    co.target = 'k230'
    co.input_type = 'uint8'
    co.input_shape = [1, 3, MODEL_H, MODEL_W]
    co.input_layout = 'NCHW'
    co.output_layout = 'NCHW'
    co.preprocess = True
    co.input_range = input_range
    co.mean = mean
    co.std = std
    co.swapRB = False

    compiler = nncase.Compiler(co)
    with open(ONNX, 'rb') as f:
        compiler.import_onnx(f.read(), nncase.ImportOptions())

    files = sorted(glob.glob(os.path.join(CALIB_DIR, '*.jpg')) +
                   glob.glob(os.path.join(CALIB_DIR, '*.png')))[:CALIB_NUM]
    data = [[letterbox_uint8(p)] for p in files]
    ptq = nncase.PTQTensorOptions()
    ptq.samples_count = len(data)
    ptq.set_tensor_data(data)
    ptq.calibrate_method = 'NoClip'
    compiler.use_ptq(ptq)
    compiler.compile()
    with open(out_path, 'wb') as f:
        f.write(compiler.gencode_tobytes())
    return out_path


def run_kmodel(path, inp):
    sim = nncase.Simulator()
    with open(path, 'rb') as f:
        sim.load_model(f.read())
    sim.set_input_tensor(0, nncase.RuntimeTensor.from_numpy(inp))
    sim.run()
    return sim.get_output_tensor(0).to_numpy()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # 板子的真实输入（模子真正吃到的那张图）
    inp = np.fromfile(MODEL_IN, dtype=np.uint8).reshape(1, 3, MODEL_H, MODEL_W)
    print("板子真实输入:", inp.shape, inp.dtype)

    # ONNX 基准（同一张图，除以 255）
    import onnxruntime as ort
    sess = ort.InferenceSession(ONNX, providers=['CPUExecutionProvider'])
    ref = sess.run(None, {'images': inp.astype(np.float32) / 255.0})[0]
    n_ref, mx_ref = decode(ref)
    print("ONNX 基准         : 框数=%3d 最高分=%.3f" % (n_ref, mx_ref))
    print()

    # 待测试的转换配置
    configs = [
        ("当前(错) std=1",      [1.0, 1.0, 1.0],         [0.0, 0.0, 0.0], [0, 255]),
        ("修正 std=255",        [255.0, 255.0, 255.0],   [0.0, 0.0, 0.0], [0, 255]),
        ("mean=0.5 std=0.5",    [0.5, 0.5, 0.5],         [0.5, 0.5, 0.5], [0, 1]),
    ]

    for name, std, mean, rng in configs:
        tag = name.replace(' ', '_').replace('(', '').replace(')', '').replace('=', '')
        out_path = os.path.join(OUT_DIR, "best_%s.kmodel" % tag)
        print("---- %s   std=%s mean=%s range=%s ----" % (name, std, mean, rng))
        try:
            convert(std, mean, rng, out_path)
            out = run_kmodel(out_path, inp)
            n, mx = decode(out)
            # 和 ONNX 的分数向量相关性（越接近 1 越像）
            a = ref.reshape(ref.shape[1], ref.shape[2])[4]
            b = out.reshape(out.shape[1], out.shape[2])[4]
            corr = float(np.corrcoef(a, b)[0, 1])
            print("   kmodel: 框数=%3d 最高分=%.3f  与ONNX分数相关性=%.3f  (文件 %.2f MB)"
                  % (n, mx, corr, os.path.getsize(out_path) / 1048576.0))
            verdict = "✅ 正常" if (abs(n - n_ref) <= 5 and corr > 0.8) else "❌ 仍然不对"
            print("   判定:", verdict)
        except Exception as e:
            import traceback
            print("   转换/模拟失败:")
            traceback.print_exc()
        print()


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
    main()
