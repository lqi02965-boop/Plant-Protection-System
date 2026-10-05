# -*- coding: utf-8 -*-
# 把板子导出的原始数据还原成图片，用来判断"通道排列"对不对
import os
import numpy as np
from PIL import Image

D = r"D:\ai_project_tree\230\_dump"
AI_W, AI_H = 640, 480
MW, MH = 640, 640


def load(name):
    p = os.path.join(D, name)
    if not os.path.exists(p):
        print("缺文件:", name)
        return None
    a = np.fromfile(p, dtype=np.uint8)
    print("%-14s %d 字节" % (name, a.size))
    return a


def save(arr, name):
    Image.fromarray(arr).save(os.path.join(D, name))
    print("  写出", name, arr.shape)


raw = load("ai_raw.bin")
if raw is not None and raw.size == AI_W * AI_H * 3:
    print("按不同解释还原 AI 原始数据:")
    # 平面RGB888 => 实际是 CHW: (3,H,W)
    chw = raw.reshape(3, AI_H, AI_W).transpose(1, 2, 0)
    save(chw, "A_ai_raw_按CHW.png")
    # 另一种可能: HWC
    hwc = raw.reshape(AI_H, AI_W, 3)
    save(hwc, "B_ai_raw_按HWC.png")
    # 通道顺序对比（BGR）
    save(chw[:, :, ::-1], "C_ai_raw_按CHW_BGR.png")
    print("   各通道均值(按CHW): R=%.1f G=%.1f B=%.1f"
          % (chw[:, :, 0].mean(), chw[:, :, 1].mean(), chw[:, :, 2].mean()))

mi = load("model_in.bin")
if mi is not None and mi.size == MW * MH * 3:
    print("按不同解释还原 模型输入(AI2D输出):")
    chw = mi.reshape(3, MH, MW).transpose(1, 2, 0)
    save(chw, "D_model_in_按CHW.png")
    hwc = mi.reshape(MH, MW, 3)
    save(hwc, "E_model_in_按HWC.png")
    print("   各通道均值(按CHW): R=%.1f G=%.1f B=%.1f"
          % (chw[:, :, 0].mean(), chw[:, :, 1].mean(), chw[:, :, 2].mean()))
    # 看看上下有没有灰边(letterbox 应该是 80 像素灰边)
    top = chw[0:80].mean()
    mid = chw[280:360].mean()
    print("   顶部80行均值=%.1f  中间均值=%.1f  (letterbox 灰边应约 114, 中间是画面)"
          % (top, mid))

print("\nstream.jpg 大小:", os.path.getsize(os.path.join(D, "stream.jpg")) if os.path.exists(os.path.join(D, "stream.jpg")) else "缺失")
