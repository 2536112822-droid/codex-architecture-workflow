#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Typed client for the in-AutoCAD TzServer protocol 2 bridge.

The bridge owns all AutoCAD API access on AutoCAD's main context.  This client
discovers live instances, refuses ambiguous targets, attaches document/revision
guards to every write, and exposes a plan -> dry-run -> atomic batch -> QA flow.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


BASE_PORT = 45679
PORT_SEARCH_COUNT = 21
PROTOCOL_VERSION = "2"
_selected_port: int | None = None


class CadError(RuntimeError):
    def __init__(self, message: str, code: str = "cad_error", data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.data = data or {}


def _json_request(port: int, api: str, payload=None, timeout: float = 60) -> dict:
    url = f"http://127.0.0.1:{int(port)}/{api.lstrip('/')}"
    try:
        if payload is None:
            request = urllib.request.Request(url, method="GET")
        else:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            request = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Content-Length": str(len(body)),
                },
            )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise CadError(f"AutoCAD bridge HTTP {exc.code}: {url}", "http_error") from exc
    except Exception as exc:
        raise CadError(f"无法连接 AutoCAD 内部桥 {url}: {exc}", "bridge_unreachable") from exc

    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CadError(f"AutoCAD bridge 返回无效 JSON: {text[:500]}", "invalid_json") from exc
    if not isinstance(result, dict):
        raise CadError("AutoCAD bridge 返回值不是 JSON 对象", "invalid_response")
    if result.get("error"):
        raise CadError(str(result["error"]), str(result.get("code") or "cad_error"), result)
    return result


def _discovery_records() -> list[dict]:
    records: list[dict] = []
    for path in Path(tempfile.gettempdir()).glob("tzserver-*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(record, dict):
                record["discovery_path"] = str(path.resolve())
                records.append(record)
        except (OSError, json.JSONDecodeError):
            continue
    return records


def discover_instances(timeout: float = 1.5) -> list[dict]:
    """Return reachable protocol-2 instances, never stale discovery files."""
    candidate_ports: list[int] = []
    explicit_port = os.environ.get("CAD_MCP_PORT")
    if explicit_port:
        try:
            candidate_ports.append(int(explicit_port))
        except ValueError as exc:
            raise CadError("CAD_MCP_PORT 必须是整数", "invalid_configuration") from exc
    candidate_ports.extend(
        int(record["port"])
        for record in _discovery_records()
        if record.get("status") == "listening" and str(record.get("port", "")).isdigit()
    )
    # Dynamic ports are advertised through discovery files.  Probe the legacy
    # base port as a fallback, but do not stall on every unused port in range.
    candidate_ports.append(BASE_PORT)

    instances: list[dict] = []
    seen: set[tuple] = set()
    for port in dict.fromkeys(candidate_ports):
        try:
            state = _json_request(port, "state", timeout=timeout)
        except CadError:
            continue
        if str(state.get("protocol_version")) != PROTOCOL_VERSION:
            continue
        key = (state.get("process_id"), state.get("instance_id"))
        if key in seen:
            continue
        seen.add(key)
        state["endpoint"] = f"http://127.0.0.1:{port}"
        state["port"] = int(port)
        instances.append(state)

    target_pid = os.environ.get("CAD_MCP_PROCESS_ID")
    target_instance = os.environ.get("CAD_MCP_INSTANCE_ID")
    if target_pid:
        instances = [item for item in instances if str(item.get("process_id")) == target_pid]
    if target_instance:
        instances = [item for item in instances if str(item.get("instance_id")) == target_instance]
    return sorted(instances, key=lambda item: (int(item.get("process_id") or 0), int(item["port"])))


def select_instance(*, process_id=None, instance_id=None, port=None) -> dict:
    """Select one live bridge for subsequent calls."""
    global _selected_port
    instances = discover_instances()
    if port is not None:
        instances = [item for item in instances if int(item["port"]) == int(port)]
    if process_id is not None:
        instances = [item for item in instances if str(item.get("process_id")) == str(process_id)]
    if instance_id is not None:
        instances = [item for item in instances if str(item.get("instance_id")) == str(instance_id)]
    if not instances:
        raise CadError("未找到符合条件的 AutoCAD 实例", "instance_not_found")
    if len(instances) > 1:
        raise CadError(
            "匹配到多个 AutoCAD 实例，请用 process_id、instance_id 或 port 精确选择",
            "ambiguous_instance",
            {"instances": instances},
        )
    _selected_port = int(instances[0]["port"])
    return instances[0]


def _port() -> int:
    global _selected_port
    if _selected_port is not None:
        try:
            _json_request(_selected_port, "ping", timeout=1.5)
            return _selected_port
        except CadError:
            _selected_port = None
    instances = discover_instances()
    if not instances:
        raise CadError(
            "未连接到 AutoCAD。请启动 AutoCAD 2025/T30，并确认 TzServer 插件已加载。",
            "no_instance",
        )
    if len(instances) > 1:
        summary = [
            {
                "process_id": item.get("process_id"),
                "instance_id": item.get("instance_id"),
                "port": item.get("port"),
                "document_name": item.get("document_name"),
            }
            for item in instances
        ]
        raise CadError(
            "检测到多个 AutoCAD 实例；为避免写错图纸，必须先 cad_use_instance。",
            "ambiguous_instance",
            {"instances": summary},
        )
    _selected_port = int(instances[0]["port"])
    return _selected_port


def _read(api: str, payload=None, timeout: float = 60) -> dict:
    return _json_request(_port(), api, payload, timeout)


def state() -> dict:
    return _read("state", timeout=8)


def ping() -> dict:
    return state()


def _guard(payload: dict | None = None, expected: dict | None = None) -> tuple[dict, dict]:
    snapshot = dict(expected or state())
    if not snapshot.get("has_document"):
        raise CadError("当前 AutoCAD 实例没有活动图纸", "no_document")
    guarded = dict(payload or {})
    guarded.setdefault("expected_document_id", snapshot.get("document_id"))
    guarded.setdefault("expected_revision", snapshot.get("revision"))
    return guarded, snapshot


def _write(api: str, payload: dict | None = None, expected: dict | None = None,
           timeout: float = 120) -> dict:
    guarded, _ = _guard(payload, expected)
    return _read(api, guarded, timeout)


def new_document(template: str | None = None) -> dict:
    return _read("new", {"template": template} if template else {}, timeout=120)


def open_document(path: str, read_only: bool = False) -> dict:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise CadError(f"DWG 不存在: {resolved}", "path_not_found")
    return _read("open", {"path": str(resolved), "read_only": bool(read_only)}, timeout=120)


def set_units(unit: str = "mm", precision: int = 3, expected: dict | None = None) -> dict:
    return _write("units", {"unit": str(unit), "precision": int(precision)}, expected)


def set_layer(name: str, color=None, linetype=None, set_active: bool = False,
              expected: dict | None = None) -> dict:
    payload = {"name": str(name), "set_active": bool(set_active)}
    if color is not None:
        payload["color"] = int(color)
    if linetype:
        payload["linetype"] = str(linetype)
    return _write("layer", payload, expected)


def set_text_style(name="hz", font="simsun.ttc", bigfont="gbcbig.shx", height=0.0,
                   set_active=True, expected: dict | None = None) -> dict:
    return _write(
        "textstyle",
        {
            "name": str(name),
            "font": str(font),
            "bigfont": str(bigfont or ""),
            "height": float(height),
            "set_active": bool(set_active),
        },
        expected,
    )


def draw(operation: dict, expected: dict | None = None) -> dict:
    return _write("draw", dict(operation), expected)


def edit(action: str, *, expected: dict | None = None, **kwargs) -> dict:
    payload = {"action": str(action), **kwargs}
    if "side_x" in payload or "side_y" in payload:
        payload["side_point"] = [float(payload.pop("side_x", 0)), float(payload.pop("side_y", 0))]
    return _write("edit", payload, expected)


def query_entities(handles=None, object_filter=None, layer=None, limit=200) -> dict:
    payload = {"limit": max(1, min(5000, int(limit)))}
    if handles:
        payload["handles"] = [str(handle) for handle in handles]
    if object_filter:
        payload["object_filter"] = str(object_filter)
    if layer:
        payload["layer"] = str(layer)
    return _read("entities", payload)


def count_entities(object_filter=None, layer=None) -> dict:
    result = query_entities(object_filter=object_filter, layer=layer, limit=5000)
    return {
        "count": result.get("count", 0),
        "counts": result.get("counts", {}),
        "document_id": result.get("document_id"),
        "revision": result.get("revision"),
    }


def select_window(x1, y1, x2, y2, crossing=False) -> dict:
    return _read(
        "select",
        {"x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2),
         "crossing": bool(crossing)},
    )


def validate_drawing(tolerance=0.01, required_layers=None,
                     require_closed_polylines=False) -> dict:
    return _read(
        "validate",
        {
            "tolerance": float(tolerance),
            "required_layers": list(required_layers or []),
            "require_closed_polylines": bool(require_closed_polylines),
        },
    )


def zoom(handle=None, margin=1.10) -> dict:
    payload = {"margin": max(1.0, float(margin))}
    if handle:
        payload["handle"] = str(handle)
    return _read("zoom", payload)


def save_as(path: str, fmt="dwg", overwrite=False, expected: dict | None = None) -> dict:
    resolved = Path(path).resolve()
    if not resolved.parent.is_dir():
        raise CadError(f"输出目录不存在: {resolved.parent}", "directory_not_found")
    return _write(
        "saveas",
        {"path": str(resolved), "fmt": str(fmt), "overwrite": bool(overwrite)},
        expected,
        timeout=180,
    )


def save_current(expected: dict | None = None) -> dict:
    return _write("save", {}, expected, timeout=180)


def send_command(command: str, expected: dict | None = None) -> dict:
    if not str(command).strip():
        raise CadError("命令不能为空", "empty_command")
    return _write("command", {"cmd": str(command)}, expected)


def command_job(job_id: str) -> dict:
    return _read("job", {"job_id": str(job_id)})


def apply_plan(plan: dict) -> dict:
    """Preflight, configure, atomically draw, and numerically verify a CAD plan.

    The first bridge call is always side-effect free.  It also acts as a replay
    probe: a response lost after a successful commit can be retried with the
    original document revision and idempotency key without duplicating geometry.
    """
    if not isinstance(plan, dict):
        raise CadError("plan 必须是对象", "invalid_plan")
    unit = str(plan.get("unit") or "").lower()
    if unit not in {"mm", "cm", "m", "inch", "inches", "feet", "foot"}:
        raise CadError("plan.unit 必填，支持 mm/cm/m/inch/feet", "invalid_unit")
    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        raise CadError("plan.operations 必须是非空数组", "invalid_plan")
    if len(operations) > 2000:
        raise CadError("plan.operations 超过 2000", "invalid_plan")

    plan_dry_run = bool(plan.get("dry_run"))
    key = str(plan.get("idempotency_key") or "").strip()
    if not key and not plan_dry_run:
        raise CadError("提交计划必须提供 idempotency_key", "missing_idempotency_key")
    if plan.get("expected_document_id") is None:
        raise CadError("plan.expected_document_id 必填", "missing_expected_document_id")
    if plan.get("expected_revision") is None:
        raise CadError("plan.expected_revision 必填", "missing_expected_revision")
    expected_document = str(plan["expected_document_id"])
    try:
        expected_revision = int(plan["expected_revision"])
    except (TypeError, ValueError) as exc:
        raise CadError("plan.expected_revision 必须是整数", "invalid_expected_revision") from exc
    if expected_revision < 0:
        raise CadError("plan.expected_revision 不能小于 0", "invalid_expected_revision")

    fingerprint_source = {
        "unit": unit,
        "precision": int(plan.get("precision", 3)),
        "layers": plan.get("layers") or [],
        "text_style": plan.get("text_style"),
        "operations": operations,
        "required_layers": plan.get("required_layers") or [],
        "tolerance": float(plan.get("tolerance", 0.01)),
        "require_closed_polylines": bool(plan.get("require_closed_polylines", False)),
    }
    fingerprint_json = json.dumps(
        fingerprint_source, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    fingerprint = hashlib.sha256(fingerprint_json.encode("utf-8")).hexdigest()

    initial = state()
    if expected_document != str(initial.get("document_id")):
        raise CadError("计划的 expected_document_id 与活动图纸不一致", "document_mismatch")
    revision_is_stale = expected_revision != int(initial.get("revision"))
    if revision_is_stale and plan_dry_run:
        raise CadError("计划的 expected_revision 与活动图纸不一致", "revision_mismatch")

    preflight_payload = {
        "operations": operations,
        "atomic": True,
        "dry_run": True,
        "expected_document_id": expected_document,
        "expected_revision": expected_revision,
    }
    if not plan_dry_run:
        preflight_payload.update(
            {"idempotency_key": key, "idempotency_fingerprint": fingerprint}
        )
    dry_run = _read("batch", preflight_payload, timeout=120)

    required_layers = plan.get("required_layers") or [
        layer["name"] if isinstance(layer, dict) else str(layer)
        for layer in (plan.get("layers") or [])
    ]
    if dry_run.get("status") == "idempotent_replay":
        qa = validate_drawing(
            plan.get("tolerance", 0.01), required_layers,
            plan.get("require_closed_polylines", False),
        )
        return {
            "status": "idempotent_replay" if qa.get("ok") else "idempotent_replay_with_qa_errors",
            "initial_state": initial,
            "setup": [],
            "dry_run": dry_run,
            "commit": dry_run,
            "validation": qa,
            "final_state": state(),
        }
    if revision_is_stale:
        # A conforming bridge rejects this before returning.  Keep the local
        # guard as defense-in-depth for older or mocked bridge implementations.
        raise CadError("计划的 expected_revision 与活动图纸不一致", "revision_mismatch")
    if plan_dry_run:
        return {"status": "dry_run", "initial_state": initial, "dry_run": dry_run}

    setup_results: list[dict] = []
    current = initial
    desired_units = {
        "mm": "Millimeters", "cm": "Centimeters", "m": "Meters",
        "inch": "Inches", "inches": "Inches", "feet": "Feet", "foot": "Feet",
    }[unit]
    if str(current.get("units")) != desired_units:
        setup_results.append(set_units(unit, int(plan.get("precision", 3)), current))
        current = state()
    for layer_def in plan.get("layers") or []:
        if isinstance(layer_def, str):
            layer_def = {"name": layer_def}
        setup_results.append(
            set_layer(
                layer_def["name"], layer_def.get("color"), layer_def.get("linetype"),
                layer_def.get("set_active", False), current,
            )
        )
        current = state()
    if plan.get("text_style"):
        style = plan["text_style"]
        setup_results.append(
            set_text_style(
                style.get("name", "hz"), style.get("font", "simsun.ttc"),
                style.get("bigfont", "gbcbig.shx"), style.get("height", 0.0),
                style.get("set_active", True), current,
            )
        )
        current = state()

    commit_payload = {
        "operations": operations,
        "atomic": True,
        "dry_run": False,
        "idempotency_key": key,
        "idempotency_fingerprint": fingerprint,
        "expected_document_id": current.get("document_id"),
        "expected_revision": current.get("revision"),
    }
    commit = _read("batch", commit_payload, timeout=180)
    qa = validate_drawing(
        plan.get("tolerance", 0.01), required_layers,
        plan.get("require_closed_polylines", False),
    )
    return {
        "status": "committed" if qa.get("ok") else "committed_with_qa_errors",
        "initial_state": initial,
        "setup": setup_results,
        "dry_run": dry_run,
        "commit": commit,
        "validation": qa,
        "final_state": state(),
    }


def screenshot(path: str | None = None) -> dict:
    """Capture the window belonging to the selected bridge process, not any AutoCAD."""
    import win32gui
    import win32process
    from PIL import ImageGrab

    snapshot = state()
    zoom()
    time.sleep(0.5)
    process_id = int(snapshot["process_id"])
    windows: list[tuple[int, int]] = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid != process_id:
            return
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        area = max(0, right - left) * max(0, bottom - top)
        if area > 10000:
            windows.append((area, hwnd))

    win32gui.EnumWindows(callback, None)
    if not windows:
        raise CadError(f"找不到 AutoCAD 进程 {process_id} 的可见窗口", "window_not_found")
    hwnd = max(windows)[1]
    try:
        win32gui.ShowWindow(hwnd, 9)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.5)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    output = Path(path).resolve() if path else Path(tempfile.gettempdir()) / f"cad_view_{int(time.time())}.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab((max(0, left), max(0, top), right, bottom)).save(output)
    return {
        "path": str(output),
        "process_id": process_id,
        "document_id": snapshot.get("document_id"),
        "revision": snapshot.get("revision"),
    }


def launch(timeout=90) -> dict:
    try:
        instances = discover_instances()
        if len(instances) == 1:
            return select_instance(port=instances[0]["port"])
        if len(instances) > 1:
            raise CadError("已有多个 AutoCAD 实例，请先选择目标", "ambiguous_instance",
                           {"instances": instances})
    except CadError as exc:
        if exc.code == "ambiguous_instance":
            raise

    candidates = [
        os.environ.get("CAD_TARCH_LAUNCHER"),
        os.environ.get("CAD_AUTOCAD_EXE"),
        str(Path(os.environ.get("ProgramW6432", os.environ.get("ProgramFiles", "C:/Program Files")))
            / "Autodesk" / "AutoCAD 2025" / "acad.exe"),
    ]
    executable = next((Path(item) for item in candidates if item and Path(item).is_file()), None)
    if not executable:
        raise CadError("未找到 AutoCAD/T30 启动器；设置 CAD_TARCH_LAUNCHER 或 CAD_AUTOCAD_EXE", "launcher_not_found")
    subprocess.Popen([str(executable)], cwd=str(executable.parent))
    deadline = time.monotonic() + max(5, int(timeout))
    last_instances: list[dict] = []
    while time.monotonic() < deadline:
        last_instances = discover_instances(timeout=1.0)
        if len(last_instances) == 1:
            return select_instance(port=last_instances[0]["port"])
        if len(last_instances) > 1:
            raise CadError("启动后发现多个 AutoCAD 实例，请选择目标", "ambiguous_instance",
                           {"instances": last_instances})
        time.sleep(1.5)
    raise CadError("已启动 AutoCAD，但等待 TzServer 超时", "launch_timeout")


def quickstart(timeout=90) -> dict:
    try:
        snapshot = state()
    except CadError:
        snapshot = launch(timeout)
    if not snapshot.get("has_document"):
        new_document()
    return state()


def selftest() -> dict:
    snapshot = state()
    if not snapshot.get("has_document"):
        return {"ok": False, "status": "needs_document", "state": snapshot}
    operations = [
        {"id": "line", "type": "line", "p": [0, 0, 1000, 0]},
        {"id": "circle", "type": "circle", "p": [500, 500, 250]},
        {"id": "dim", "type": "dim", "p": [0, 0, 1000, 0, 500, -200]},
    ]
    dry_run = _read(
        "batch",
        {
            "operations": operations,
            "dry_run": True,
            "atomic": True,
            "expected_document_id": snapshot["document_id"],
            "expected_revision": snapshot["revision"],
        },
    )
    return {"ok": True, "side_effect_free": True, "state": snapshot, "dry_run": dry_run}


def tz_status() -> dict:
    snapshot = state()
    return {
        "detected": bool((snapshot.get("tarch") or {}).get("detected")),
        "modules": (snapshot.get("tarch") or {}).get("modules", []),
        "process_id": snapshot.get("process_id"),
        "document_id": snapshot.get("document_id"),
    }


def tz_command(command: str, expected: dict | None = None) -> dict:
    return send_command(command, expected)


def tz_commands(keyword=None, limit=200) -> list[dict]:
    # Vendor command catalogs are not redistributed. Users may point to their
    # own JSON array of {"cmd": ..., "label": ...} records for local lookup.
    local_catalog = os.environ.get("CAD_TZ_COMMANDS_FILE")
    path = Path(local_catalog).expanduser() if local_catalog else Path(__file__).with_name("tz_cmds.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        data = data.get("commands", data.get("items", []))
    if not isinstance(data, list):
        return []
    if keyword:
        needle = str(keyword).lower()
        data = [item for item in data if needle in json.dumps(item, ensure_ascii=False).lower()]
    return data[: max(1, min(1000, int(limit)))]


# Backward-compatible aliases for scripts outside the MCP surface.
info = state
connect = lambda create=False: quickstart() if create else state()
add_layer = set_layer
list_layers = lambda active_only=False: state().get("layers", [])
draw_line = lambda x1, y1, x2, y2, layer=None: draw({"type": "line", "p": [x1, y1, x2, y2], "layer": layer})
draw_rect = lambda x, y, w, h, closed=True, layer=None: draw({"type": "rect", "p": [x, y, w, h], "layer": layer})
draw_circle = lambda cx, cy, r, layer=None: draw({"type": "circle", "p": [cx, cy, r], "layer": layer})
draw_arc = lambda cx, cy, r, start_deg, end_deg, layer=None: draw({"type": "arc", "p": [cx, cy, r, start_deg, end_deg], "layer": layer})
save_current_drawing = save_current
