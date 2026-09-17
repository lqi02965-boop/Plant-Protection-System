# -*- coding: utf-8 -*-
# =============================================================================
#  在电脑上跑 kmodel（用板子导出的真实输入），并判断输入数据是否像真实图像
# =============================================================================
import os
import sys
import numpy as np

SP = r"D:\python\python\field\v81\Lib\site-packages"
D = r"D:\ai_project_tree\230\_dump"
KMODEL = r"D:\ai_project_tree\yolo\runs\detect\crop_pest_final\weights\best.kmodel"
MODEL_IN = os.path.join(D, "model_in.bin")     # 板子导出的"模型真正输入"(uint8 NCHW 640x640x3)
AI_RAW = os.path.join(D, "ai_raw.bin")

# ---- 把插件目录塞进 PATH 和 DLL 搜索路径（Simulator 要加载 k230 运行模块）----
kpu_dir = os.path.join(SP, "nncase", "modules", "kpu")
for p in (SP, os.path.join(SP, "nncase"), kpu_dir):
    if os.path.isdir(p):
        os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(p)
        except Exception:
            pass
os.environ["NNCASE_PLUGIN_PATH"] = kpu_dir


def likeness(plane2d, name):
    """判断一块 2D 像素数据像不像真实图像：相邻像素差越小越像图"""
    p = plane2d.astype(np.int16)
    dh = np.abs(np.diff(p, axis=1)).mean()      # 水平相邻差
    dv = np.abs(np.diff(p, axis=0)).mean()      # 垂直相邻差
    print("   %-14s: 水平相邻差=%6.2f  垂直相邻差=%6.2f  均值=%6.1f  (真实图像<10, 随机噪声约85)"
          % (name, dh, dv, p.mean()))


def decode(out, conf=0.45):
    d = np.asarray(out).reshape(out.shape[1], out.shape[2]).T
    sc = d[:, 4]
    return int((sc > conf).sum()), float(sc.max()), np.round(np.sort(sc)[-5:], 3)


def main():
    # ---------- 1) 先看板子导出的数据像不像真实图像 ----------
    print("=== 1. 板子导出数据的'像不像图'检验 ===")
    raw = np.fromfile(AI_RAW, dtype=np.uint8)
    n = 640 * 480
    for c in range(3):
        likeness(raw[c * n:(c + 1) * n].reshape(480, 640), "ai_raw ch%d" % c)
    mi = np.fromfile(MODEL_IN, dtype=np.uint8)
    mplane = mi.reshape(3, 640, 640)
    for c in range(3):
        likeness(mplane[c], "model_in ch%d" % c)

    # ---------- 2) 用 Simulator 跑 kmodel ----------
    print("\n=== 2. 在 PC 上模拟运行 kmodel ===")
    try:
        import nncase
        sim = nncase.Simulator()
        with open(KMODEL, 'rb') as f:
            sim.load_model(f.read())
        print("   load_model 成功")

        # 先摸清 API 到底是属性还是方法
        n_in = sim.inputs_size
        n_out = sim.outputs_size
        if callable(n_in):
            n_in = n_in()
        if callable(n_out):
            n_out = n_out()
        print("   输入个数=%s 输出个数=%s" % (n_in, n_out))

        def get_shape(which, i):
            fn = sim.get_input_shape if which == 'in' else sim.get_output_shape
            try:
                return fn(i)
            except TypeError:
                try:
                    return fn[i] if hasattr(fn, '__getitem__') else fn
                except Exception:
                    return fn

        try:
            print("   输入 shape:", [get_shape('in', i) for i in range(int(n_in))])
            print("   输出 shape:", [get_shape('out', i) for i in range(int(n_out))])
        except Exception as e:
            print("   读 shape 失败(不影响跑):", e)

        inp = mi.reshape(1, 3, 640, 640).astype(np.uint8)
        sim.set_input_tensor(0, nncase.RuntimeTensor.from_numpy(inp))
        sim.run()
        out = sim.get_output_tensor(0).to_numpy()
        print("   输出 dtype/shape:", out.dtype, out.shape,
              " min=%.4f max=%.4f" % (out.min(), out.max()))
        n, mx, top = decode(out)
        print("   >>> kmodel 在板子真实输入上: 过阈值框数=%d 最高分=%.3f 前5高分=%s" % (n, mx, top))
    except Exception as e:
        import traceback
        print("   Simulator 失败:")
        traceback.print_exc()


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
    main()
