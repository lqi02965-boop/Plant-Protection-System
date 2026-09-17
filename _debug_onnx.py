# -*- coding: utf-8 -*-
# =============================================================================
#  只验证 ONNX 模型本身（不涉及 kmodel / 板子）
#  目的：确认"模型+我们的预处理(letterbox 640)"在标准测试图上能正常检出虫子
#  用法: python _debug_onnx.py
# =============================================================================
import os
import glob
import sys

import numpy as np
from PIL import Image

YOLO_DIR = r"D:\ai_project_tree\yolo"
ONNX = os.path.join(YOLO_DIR, r"runs\detect\crop_pest_final\weights\best.onnx")
IMG_DIR = os.path.join(YOLO_DIR, r"pest_dataset\test\images")
LBL_DIR = os.path.join(YOLO_DIR, r"pest_dataset\test\labels")
MODEL_W = MODEL_H = 640
PAD = 114
CONF = 0.45
IOU = 0.45


def letterbox(path):
    img = Image.open(path).convert('RGB')
    w, h = img.size
    r = min(MODEL_W / float(w), MODEL_H / float(h))
    nw, nh = int(round(w * r)), int(round(h * r))
    img = img.resize((nw, nh), Image.BILINEAR)
    canvas = Image.new('RGB', (MODEL_W, MODEL_H), (PAD, PAD, PAD))
    canvas.paste(img, ((MODEL_W - nw) // 2, (MODEL_H - nh) // 2))
    return canvas, np.asarray(canvas, dtype=np.uint8)


def nms(boxes, scores, thr=IOU):
    """boxes: list of [x1,y1,x2,y2]"""
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    keep = []
    while order:
        i = order.pop(0)
        keep.append(i)
        rest = []
        for j in order:
            ax1, ay1, ax2, ay2 = boxes[i]
            bx1, by1, bx2, by2 = boxes[j]
            ix1, iy1 = max(ax1, bx1), max(ay1, by1)
            ix2, iy2 = min(ax2, bx2), min(ay2, by2)
            iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
            inter = iw * ih
            ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
            if (inter / ua if ua > 0 else 0) < thr:
                rest.append(j)
        order = rest
    return keep


def main():
    import onnxruntime as ort
    sess = ort.InferenceSession(ONNX, providers=['CPUExecutionProvider'])
    in_name = sess.get_inputs()[0].name
    print("ONNX:", os.path.basename(ONNX))
    print("输入:", in_name, sess.get_inputs()[0].shape, " 输出:", sess.get_outputs()[0].shape)
    print()

    imgs = sorted(glob.glob(os.path.join(IMG_DIR, '*.jpg')) +
                  glob.glob(os.path.join(IMG_DIR, '*.png')))[:5]
    print("用 %d 张测试图验证（阈值 conf=%.2f）:\n" % (len(imgs), CONF))

    total_boxes = 0
    for p in imgs:
        canvas, hwc = letterbox(p)
        x = hwc.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        out = sess.run(None, {in_name: x})[0]              # (1,5,8400)
        d = out[0].T                                       # (8400,5)
        bx, sc = d[:, 0:4], d[:, 4]

        cand_b, cand_s = [], []
        for i in range(len(sc)):
            if sc[i] >= CONF:
                cx, cy, w, h = bx[i]
                cand_b.append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])
                cand_s.append(float(sc[i]))
        keep = nms(cand_b, cand_s)

        # 真实标注数量（做参考）
        gt = 0
        lf = os.path.join(LBL_DIR, os.path.splitext(os.path.basename(p))[0] + ".txt")
        if os.path.exists(lf):
            gt = sum(1 for line in open(lf) if line.strip())

        total_boxes += len(keep)
        print("  %-46s 检出=%2d (标注=%2d)  最高分=%.3f  候选(过阈)=%d"
              % (os.path.basename(p)[:46], len(keep), gt, max(cand_s) if cand_s else 0, len(cand_b)))

    print("\n合计检出 %d 个框" % total_boxes)
    print("→ 如果检出数量和标注接近，说明模型和 letterbox 预处理都是对的，")
    print("  问题就在板子端(取图/喂数据/后处理)；如果这里也是几十个乱框，那是模型本身的问题。")


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
    main()
