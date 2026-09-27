#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained AutoCad smoke test. Requires pywin32 + Pillow (installed in the
project venv). Connect to a running AutoCAD, draw a few primitives, screenshot,
save a DWG, then report. Used to confirm the COM automation bridge is ready."""

import math
import os
import sys
import time

import pythoncom
import win32com.client


def _vt(seq):
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(float(v) for v in seq))


def _pt(x, y, z=0):
    return _vt((x, y, z))


def main():
    pythoncom.CoInitialize()
    ok = False
    try:
        app = win32com.client.GetActiveObject("AutoCAD.Application.25")
    except Exception:
        app = win32com.client.GetActiveObject("AutoCAD.Application")
    try:
        app.Visible = True
    except Exception:
        pass
    d = app.ActiveDocument
    msp = d.ModelSpace
    try:
        d.SetVariable("INSUNITS", 4)  # mm
    except Exception:
        pass
    # a test layer
    try:
        lay = d.Layers.Item("AI_TEST")
    except Exception:
        lay = d.Layers.Add("AI_TEST")
    lay.color = 1
    d.ActiveLayer = lay
    # draw: rectangle, line, circle, mtext
    rect = msp.AddLightWeightPolyline(_vt([0, 0, 100, 0, 100, 60, 0, 60]))
    rect.Closed = True
    msp.AddLine(_pt(0, 0), _pt(100, 0))
    msp.AddCircle(_pt(50, 30), 12)
    msp.AddText("AI-TEST", _pt(5, 70), 6.0)
    d.SendCommand("_.ZOOM _E\n")
    time.sleep(1)
    out = os.path.join(os.environ.get("TEMP", "."), "cad_selftest.dwg")
    d.SaveAs(out, 64)  # ac2018_dwg
    print("CONNECTED  AutoCAD", app.Version)
    print("图纸:", d.Name, "| 实体数:", msp.Count, "| 图层:", lay.Name)
    print("已保存:", out)
    print(">>> SELFTEST PASS <<<")
    ok = True
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
