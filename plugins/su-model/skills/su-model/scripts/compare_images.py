#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把“参考图”和“SU 截图”并排或混合叠加，并输出平均像素差，用于评估复刻精度。
用法：python compare_images.py <参考图> <SU截图> [--mode side|blend] [--out 输出png]
"""
import sys, argparse
from PIL import Image
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref")
    ap.add_argument("shot")
    ap.add_argument("--mode", default="side", choices=["side", "blend"])
    ap.add_argument("--out", default="su_compare.png")
    a = ap.parse_args()

    ref = Image.open(a.ref).convert("RGB")
    shot = Image.open(a.shot).convert("RGB")
    W = 900
    H = int(W * ref.height / ref.width)
    ref = ref.resize((W, H))
    shot = shot.resize((W, H))
    refA = np.asarray(ref, dtype=np.float32)
    shotA = np.asarray(shot, dtype=np.float32)
    diff = float(np.abs(refA - shotA).mean())

    if a.mode == "blend":
        out = Image.blend(ref, shot, 0.5)
    else:
        out = Image.new("RGB", (W * 2 + 10, H), "black")
        out.paste(ref, (0, 0))
        out.paste(shot, (W + 10, 0))
    out.save(a.out)
    print("平均像素差: %.2f / 255" % diff)
    print("已保存对比图: %s" % a.out)


if __name__ == "__main__":
    main()
