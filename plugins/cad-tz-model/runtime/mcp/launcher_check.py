#!/usr/bin/env python3
"""Wait for the injected protocol-2 AutoCAD bridge without modifying a drawing."""

from __future__ import annotations

import json
import os
import time

import cad_core


def main() -> int:
    max_wait = int(os.environ.get("CAD_TZ_CONNECT_WAIT", "60"))
    deadline = time.monotonic() + max_wait
    instances = []
    while time.monotonic() < deadline:
        instances = cad_core.discover_instances()
        if instances:
            break
        time.sleep(2)

    if not instances:
        print("未发现 AutoCAD TzServer protocol-2 实例。")
        print("请确认 AutoCAD 2025 已启动，并已加载 TzServer.bundle。")
        return 1

    print(json.dumps({"status": "connected", "instances": instances}, ensure_ascii=False, indent=2))
    if len(instances) > 1:
        print("检测到多个实例；Codex 写入前必须先 cad_use_instance。")
    else:
        print("CONNECTED  AutoCAD protocol-2 bridge ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
