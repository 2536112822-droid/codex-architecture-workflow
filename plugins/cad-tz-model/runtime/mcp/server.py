#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cad-mcp protocol-2 stdio server for AutoCAD 2025 + TArch T30."""

from __future__ import annotations

import json
import sys
import traceback

import cad_core


def _schema(properties=None, required=None, additional=False):
    result = {"type": "object", "properties": properties or {}, "additionalProperties": additional}
    if required:
        result["required"] = required
    return result


UNIT = {"type": "string", "enum": ["mm", "cm", "m", "inch", "feet"]}

TOOLS = [
    {
        "name": "cad_discover",
        "description": "列出所有可达 AutoCAD/TzServer 实例及其进程、端口、活动图纸。只读；多开时先调用。",
        "inputSchema": _schema(),
    },
    {
        "name": "cad_use_instance",
        "description": "选择后续工具唯一允许操作的 AutoCAD 实例，避免多开时写错图纸。",
        "inputSchema": _schema(
            {
                "process_id": {"type": "integer"},
                "instance_id": {"type": "string"},
                "port": {"type": "integer", "minimum": 1, "maximum": 65535},
            }
        ),
    },
    {
        "name": "cad_ping",
        "description": "读取所选 AutoCAD 的协议、进程、document_id、revision 与基本状态。任何写入前调用。",
        "inputSchema": _schema(),
    },
    {
        "name": "cad_launch",
        "description": "未运行时启动 AutoCAD/T30 并等待协议桥就绪；若已多开则拒绝猜测。",
        "inputSchema": _schema({"timeout": {"type": "integer", "minimum": 5, "maximum": 180, "default": 90}}),
    },
    {
        "name": "cad_quickstart",
        "description": "连接或启动 AutoCAD，并在没有活动图纸时新建一张。返回精确目标状态。",
        "inputSchema": _schema({"timeout": {"type": "integer", "minimum": 5, "maximum": 180, "default": 90}}),
    },
    {
        "name": "cad_state",
        "description": "结构化检查活动图纸：单位、图层、文字样式、实体计数、命令状态和天正模块。只读。",
        "inputSchema": _schema(),
    },
    {
        "name": "cad_selftest",
        "description": "执行无副作用协议自检：对线、圆、尺寸标注做批量 dry-run，不写入当前图纸。",
        "inputSchema": _schema(),
    },
    {
        "name": "cad_new",
        "description": "新建图纸并返回新的 document_id/revision。",
        "inputSchema": _schema({"template": {"type": "string"}}),
    },
    {
        "name": "cad_open",
        "description": "打开指定 DWG；返回 document_id，后续写入必须使用新的修订状态。",
        "inputSchema": _schema(
            {"path": {"type": "string"}, "read_only": {"type": "boolean", "default": False}},
            ["path"],
        ),
    },
    {
        "name": "cad_set_units",
        "description": "受文档/修订保护地设置图纸插入单位与显示精度。",
        "inputSchema": _schema(
            {"unit": UNIT, "precision": {"type": "integer", "minimum": 0, "maximum": 8, "default": 3}},
            ["unit"],
        ),
    },
    {
        "name": "cad_layer",
        "description": "创建或更新图层，可设置颜色、线型及当前图层；操作带 document_id/revision 防写错。",
        "inputSchema": _schema(
            {
                "name": {"type": "string"},
                "color": {"type": "integer", "minimum": 1, "maximum": 255},
                "linetype": {"type": "string"},
                "set_active": {"type": "boolean", "default": False},
            },
            ["name"],
        ),
    },
    {
        "name": "cad_textstyle",
        "description": "创建/更新中文文字样式并可设为当前样式。固定高度用 0 表示可变。",
        "inputSchema": _schema(
            {
                "name": {"type": "string", "default": "hz"},
                "font": {"type": "string", "default": "simsun.ttc"},
                "bigfont": {"type": "string", "default": "gbcbig.shx"},
                "height": {"type": "number", "minimum": 0, "default": 0},
                "set_active": {"type": "boolean", "default": True},
            }
        ),
    },
    {
        "name": "cad_apply_plan",
        "description":
            "推荐写入入口：先在原始 document/revision 上无副作用 dry-run，再受保护地设置单位/图层/文字样式，"
            "最后以单事务批量绘制，几何失败整体回滚；提交必须带 idempotency_key，安全重试会识别重放或冲突，"
            "完成后自动数值 QA。",
        "inputSchema": _schema(
            {
                "plan": {
                    "type": "object",
                    "properties": {
                        "unit": UNIT,
                        "precision": {"type": "integer", "minimum": 0, "maximum": 8},
                        "expected_document_id": {"type": "string"},
                        "expected_revision": {"type": "integer", "minimum": 0},
                        "idempotency_key": {"type": "string", "minLength": 1},
                        "dry_run": {"type": "boolean", "default": False},
                        "layers": {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "object"}]}},
                        "text_style": {"type": "object"},
                        "operations": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 2000,
                            "items": {
                                "type": "object",
                                "description": "type=line/rect/circle/arc/polyline/text/mtext/dim；坐标字段见 cad_draw。",
                            },
                        },
                        "required_layers": {"type": "array", "items": {"type": "string"}},
                        "tolerance": {"type": "number", "exclusiveMinimum": 0, "default": 0.01},
                        "require_closed_polylines": {"type": "boolean", "default": False},
                    },
                    "required": ["unit", "expected_document_id", "expected_revision", "operations"],
                    "additionalProperties": True,
                }
            },
            ["plan"],
        ),
    },
    {
        "name": "cad_draw",
        "description":
            "单实体兼容入口；推荐成批工作改用 cad_apply_plan。operation.type 支持 line/rect/circle/arc/" 
            "polyline/text/mtext/dim，几何坐标用 p 或 pts，另可给 layer/style/dimstyle。",
        "inputSchema": _schema({"operation": {"type": "object"}}, ["operation"]),
    },
    {
        "name": "cad_edit",
        "description": "按句柄执行 move/copy/rotate/scale/mirror/offset/erase；写入前自动锁定 document_id/revision。",
        "inputSchema": _schema(
            {
                "action": {"type": "string", "enum": ["move", "copy", "rotate", "scale", "mirror", "offset", "erase"]},
                "handles": {"type": "array", "items": {"type": "string"}},
                "handle": {"type": "string"},
                "dx": {"type": "number"}, "dy": {"type": "number"},
                "bx": {"type": "number"}, "by": {"type": "number"},
                "angle": {"type": "number"}, "factor": {"type": "number"},
                "x1": {"type": "number"}, "y1": {"type": "number"},
                "x2": {"type": "number"}, "y2": {"type": "number"},
                "distance": {"type": "number"},
                "side_x": {"type": "number"}, "side_y": {"type": "number"},
                "count": {"type": "integer", "minimum": 1},
            },
            ["action"],
            additional=True,
        ),
    },
    {
        "name": "cad_query",
        "description": "结构化读取实体句柄、类型、图层、包围盒、几何点、长度、文字或标注值。只读。",
        "inputSchema": _schema(
            {
                "handles": {"type": "array", "items": {"type": "string"}},
                "object_filter": {"type": "string"},
                "layer": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 200},
            }
        ),
    },
    {
        "name": "cad_count",
        "description": "按类型关键词/图层统计实体。只读。",
        "inputSchema": _schema({"object_filter": {"type": "string"}, "layer": {"type": "string"}}),
    },
    {
        "name": "cad_select",
        "description": "按几何包围盒做 window/crossing 选择，返回真实句柄。只读，不改变 AutoCAD 选择集。",
        "inputSchema": _schema(
            {
                "x1": {"type": "number"}, "y1": {"type": "number"},
                "x2": {"type": "number"}, "y2": {"type": "number"},
                "crossing": {"type": "boolean", "default": False},
            },
            ["x1", "y1", "x2", "y2"],
        ),
    },
    {
        "name": "cad_validate",
        "description": "数值 QA：缺失图层、零长/重复线、退化/未闭合多段线、非零 Z、无效圆。只读。",
        "inputSchema": _schema(
            {
                "tolerance": {"type": "number", "exclusiveMinimum": 0, "default": 0.01},
                "required_layers": {"type": "array", "items": {"type": "string"}},
                "require_closed_polylines": {"type": "boolean", "default": False},
            }
        ),
    },
    {
        "name": "cad_zoom",
        "description": "缩放到全图或一个句柄的范围；返回计算后的数值 bounds。",
        "inputSchema": _schema({"handle": {"type": "string"}, "margin": {"type": "number", "minimum": 1, "default": 1.1}}),
    },
    {
        "name": "cad_screenshot",
        "description": "只截取所选 TzServer 进程对应的 AutoCAD 窗口，避免多开时截错；返回 PNG 与 document_id/revision。",
        "inputSchema": _schema({"path": {"type": "string"}}),
    },
    {
        "name": "cad_save_as",
        "description": "严格按 fmt 输出 DWG 或真正的 DXF；扩展名不匹配会报错，默认不覆盖现有文件。",
        "inputSchema": _schema(
            {
                "path": {"type": "string"},
                "fmt": {"type": "string", "enum": ["dwg", "dwg2018", "dwg2013", "dwg2010", "dwg2007", "dwg2004", "dwg2000", "dxf", "dxf2018", "dxf2013", "dxf2010", "dxf2007", "dxf2004", "dxf2000", "dxfr12"], "default": "dwg"},
                "overwrite": {"type": "boolean", "default": False},
            },
            ["path"],
        ),
    },
    {
        "name": "cad_save",
        "description": "保存已有路径的当前图纸；未命名图纸会要求 cad_save_as。",
        "inputSchema": _schema(),
    },
    {
        "name": "cad_command",
        "description": "专家级异步命令入口；仅入队并返回 job_id，不把 SendStringToExecute 误报为完成。优先使用 typed 工具。",
        "inputSchema": _schema({"cmd": {"type": "string", "minLength": 1}}, ["cmd"]),
    },
    {
        "name": "cad_job",
        "description": "查询 cad_command/tz_cmd 返回的 job_id 是否 completed/failed/cancelled。只读。",
        "inputSchema": _schema({"job_id": {"type": "string"}}, ["job_id"]),
    },
    {
        "name": "tz_status",
        "description": "从所选 AutoCAD 进程的已加载模块检测天正 TArch。只读。",
        "inputSchema": _schema(),
    },
    {
        "name": "tz_cmd",
        "description": "异步调用天正命令并返回 job_id；弹窗型命令需要用户交互，必须随后用 cad_job 检查终态。",
        "inputSchema": _schema({"cmd": {"type": "string", "minLength": 1}}, ["cmd"]),
    },
    {
        "name": "tz_cmds",
        "description": "查询用户本地天正命令表。公开版默认空表；可用 CAD_TZ_COMMANDS_FILE 指向用户自备 JSON，空结果不表示天正未安装。只读。",
        "inputSchema": _schema({"keyword": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200}}),
    },
]


def _tool(name):
    return next((tool for tool in TOOLS if tool["name"] == name), None)


def call_tool(name, args):
    args = args or {}
    if name == "cad_discover":
        return {"instances": cad_core.discover_instances()}
    if name == "cad_use_instance":
        return cad_core.select_instance(
            process_id=args.get("process_id"), instance_id=args.get("instance_id"), port=args.get("port")
        )
    if name in {"cad_ping", "cad_state"}:
        return cad_core.state()
    if name == "cad_launch":
        return cad_core.launch(args.get("timeout", 90))
    if name == "cad_quickstart":
        return cad_core.quickstart(args.get("timeout", 90))
    if name == "cad_selftest":
        return cad_core.selftest()
    if name == "cad_new":
        return cad_core.new_document(args.get("template"))
    if name == "cad_open":
        return cad_core.open_document(args["path"], args.get("read_only", False))
    if name == "cad_set_units":
        return cad_core.set_units(args["unit"], args.get("precision", 3))
    if name == "cad_layer":
        return cad_core.set_layer(args["name"], args.get("color"), args.get("linetype"), args.get("set_active", False))
    if name == "cad_textstyle":
        return cad_core.set_text_style(
            args.get("name", "hz"), args.get("font", "simsun.ttc"), args.get("bigfont", "gbcbig.shx"),
            args.get("height", 0), args.get("set_active", True)
        )
    if name == "cad_apply_plan":
        return cad_core.apply_plan(args["plan"])
    if name == "cad_draw":
        return cad_core.draw(args["operation"])
    if name == "cad_edit":
        payload = dict(args)
        action = payload.pop("action")
        return cad_core.edit(action, **payload)
    if name == "cad_query":
        return cad_core.query_entities(
            args.get("handles"), args.get("object_filter"), args.get("layer"), args.get("limit", 200)
        )
    if name == "cad_count":
        return cad_core.count_entities(args.get("object_filter"), args.get("layer"))
    if name == "cad_select":
        return cad_core.select_window(args["x1"], args["y1"], args["x2"], args["y2"], args.get("crossing", False))
    if name == "cad_validate":
        return cad_core.validate_drawing(
            args.get("tolerance", 0.01), args.get("required_layers"), args.get("require_closed_polylines", False)
        )
    if name == "cad_zoom":
        return cad_core.zoom(args.get("handle"), args.get("margin", 1.1))
    if name == "cad_screenshot":
        return cad_core.screenshot(args.get("path"))
    if name == "cad_save_as":
        return cad_core.save_as(args["path"], args.get("fmt", "dwg"), args.get("overwrite", False))
    if name == "cad_save":
        return cad_core.save_current()
    if name == "cad_command":
        return cad_core.send_command(args["cmd"])
    if name == "cad_job":
        return cad_core.command_job(args["job_id"])
    if name == "tz_status":
        return cad_core.tz_status()
    if name == "tz_cmd":
        return cad_core.tz_command(args["cmd"])
    if name == "tz_cmds":
        return cad_core.tz_commands(args.get("keyword"), args.get("limit", 200))
    raise cad_core.CadError("未知工具: " + str(name), "unknown_tool")


def _text(value):
    if isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return [{"type": "text", "text": rendered}]


def _error_text(exc):
    data = {"error": str(exc), "code": getattr(exc, "code", "cad_error")}
    if getattr(exc, "data", None):
        data["details"] = exc.data
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def respond(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def on_message(message):
    if not isinstance(message, dict) or not isinstance(message.get("method"), str):
        return
    request_id = message.get("id")
    method = message["method"]
    if method == "initialize":
        respond({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "cad-mcp", "version": "2.0.0"},
            },
        })
        return
    if request_id is None:
        return
    if method == "ping":
        respond({"jsonrpc": "2.0", "id": request_id, "result": {}})
        return
    if method == "tools/list":
        respond({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}})
        return
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if not _tool(name):
            respond({
                "jsonrpc": "2.0", "id": request_id,
                "result": {"content": _text("未知工具: " + str(name)), "isError": True},
            })
            return
        try:
            value = call_tool(name, args)
            respond({
                "jsonrpc": "2.0", "id": request_id,
                "result": {"content": _text(value), "isError": False},
            })
        except Exception as exc:
            sys.stderr.write("tool error: " + traceback.format_exc() + "\n")
            respond({
                "jsonrpc": "2.0", "id": request_id,
                "result": {"content": _text(_error_text(exc)), "isError": True},
            })
        return
    if method == "resources/list":
        respond({"jsonrpc": "2.0", "id": request_id, "result": {"resources": []}})
        return
    if method == "prompts/list":
        respond({"jsonrpc": "2.0", "id": request_id, "result": {"prompts": []}})
        return
    respond({
        "jsonrpc": "2.0", "id": request_id,
        "error": {"code": -32601, "message": "Method not found: " + method},
    })


def main():
    import io
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            on_message(json.loads(line))
        except Exception:
            sys.stderr.write("handler error: " + traceback.format_exc() + "\n")


if __name__ == "__main__":
    main()
