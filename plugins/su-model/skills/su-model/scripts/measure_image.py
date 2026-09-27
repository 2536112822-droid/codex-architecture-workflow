#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析一张参考图：尺寸/宽高比、主色、区域配色网格、边缘能量带。
用途：把一张图精确复刻成 SketchUp 模型前的“量化”步骤——拿到比例、配色、结构线位置。
用法：python measure_image.py <图片> [--dominant 6] [--grid 8] [--edges 1] [--json]
"""
import sys, json, argparse
from PIL import Image
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--dominant", type=int, default=6)
    ap.add_argument("--grid", type=int, default=8)
    ap.add_argument("--edges", type=int, default=1)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    img = Image.open(a.path).convert("RGB")
    w, h = img.size
    arr = np.asarray(img, dtype=np.float32)

    # 主色（中位切分量化）
    small = img.resize((64, 64))
    q = small.quantize(colors=max(2, a.dominant), method=Image.MEDIANCUT)
    pal = q.getpalette()
    counts = sorted(q.getcolors(), reverse=True)
    dom = []
    for cnt, idx in counts[:max(2, a.dominant)]:
        rgb = pal[idx * 3: idx * 3 + 3]
        dom.append({"count": cnt, "rgb": [int(v) for v in rgb]})

    # 区域配色网格（用于布局/配色映射）
    gs = max(2, a.grid)
    grid = []
    for gy in range(gs):
        row = []
        for gx in range(gs):
            y0, y1 = int(gy * h / gs), int((gy + 1) * h / gs)
            x0, x1 = int(gx * w / gs), int((gx + 1) * w / gs)
            cell = arr[y0:y1, x0:x1]
            row.append([int(v) for v in cell.reshape(-1, 3).mean(0)])
        grid.append(row)

    out = {"size": [w, h], "aspect": round(w / h, 4), "dominant": dom, "grid": grid}

    # 边缘能量带（找墙线/结构）
    if a.edges:
        gray = arr.mean(2)
        gy, gx = np.gradient(gray)
        eg = np.abs(gx) + np.abs(gy)
        nb = 16
        col = [float(eg[:, int(c * w / nb):int((c + 1) * w / nb)].mean()) for c in range(nb)]
        row = [float(eg[int(r * h / nb):int((r + 1) * h / nb), :].mean()) for r in range(nb)]
        out["edge_col"] = col
        out["edge_row"] = row

    print(json.dumps(out, ensure_ascii=False, indent=2 if not a.json else None))
    if not a.json:
        print("尺寸: %d x %d  宽高比: %.4f" % (w, h, w / h), file=sys.stderr)


if __name__ == "__main__":
    main()
