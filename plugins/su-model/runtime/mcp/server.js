#!/usr/bin/env node
"use strict";

// su-mcp: zero-dependency MCP bridge for the SketchUp-side Ruby service.
// stdout is reserved for JSON-RPC; diagnostics go to stderr.

const http = require("http");
const readline = require("readline");
const os = require("os");
const path = require("path");

const SU_BASE = "http://127.0.0.1:45678";
const SU_TIMEOUT = 120000;
const MAX_RESPONSE_BYTES = 8 * 1024 * 1024;

function requestJson(apiPath, payload, timeoutMs = 30000, contentType = "application/json; charset=utf-8") {
  return new Promise((resolve, reject) => {
    const body = payload == null
      ? null
      : Buffer.from(typeof payload === "string" ? payload : JSON.stringify(payload), "utf8");
    const req = http.request(
      SU_BASE + apiPath,
      {
        method: body == null ? "GET" : "POST",
        headers: body == null ? {} : {
          "Content-Type": contentType,
          "Content-Length": body.length,
        },
        timeout: timeoutMs,
      },
      (res) => {
        const chunks = [];
        let bytes = 0;
        res.on("data", (chunk) => {
          const data = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
          bytes += data.length;
          if (bytes > MAX_RESPONSE_BYTES) {
            req.destroy(new Error("SketchUp response exceeded 8 MiB"));
            return;
          }
          chunks.push(data);
        });
        res.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          if (!res.statusCode || res.statusCode < 200 || res.statusCode >= 300) {
            reject(new Error(`SketchUp HTTP ${res.statusCode}: ${text.slice(0, 500)}`));
            return;
          }
          let parsed;
          try {
            parsed = JSON.parse(text);
          } catch (error) {
            reject(new Error("SketchUp returned invalid JSON: " + text.slice(0, 500)));
            return;
          }
          if (parsed.status === "error") {
            reject(new Error(parsed.error || "SketchUp returned an unknown error"));
            return;
          }
          resolve(Object.prototype.hasOwnProperty.call(parsed, "result") ? parsed.result : parsed);
        });
      }
    );
    req.on("timeout", () => req.destroy(new Error("SketchUp service timed out")));
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

function suCall(method, args = {}, timeoutMs = SU_TIMEOUT) {
  return requestJson("/call", { method, args }, timeoutMs);
}

function suEval(code) {
  return requestJson("/eval", code, SU_TIMEOUT, "text/plain; charset=utf-8");
}

function clampInteger(value, fallback, min, max) {
  const number = Number.parseInt(value, 10);
  return Math.min(max, Math.max(min, Number.isFinite(number) ? number : fallback));
}

function defaultDesktopFile(prefix, extension = ".png") {
  return path.join(os.homedir(), "Desktop", `${prefix}_${Date.now()}${extension}`);
}

const SU_HINT =
  "SketchUp 建模服务未连接。请打开 SketchUp 2025 并新建/打开模型，然后在“扩展程序 → SU AI 建模”点击一键启动。";

function errText(error) {
  const message = error && error.message ? error.message : String(error);
  if (/ECONNREFUSED|ENOTFOUND|ECONNRESET|timeout|timed out|超时/i.test(message)) return SU_HINT;
  return message;
}

const TOOLS = [
  {
    name: "su_ping",
    description: "检查 SketchUp 侧服务是否已连接。任何写入前先调用。",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "su_capabilities",
    description: "读取服务版本、单位约束、结构化操作类型和限制。规划建模前调用。",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "su_info",
    description: "读取当前模型、SketchUp 版本、显示单位、内部英寸单位、修订号与模型令牌。",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "su_inspect_model",
    description: "结构化检查模型包围盒、实体、Tag、材质、稳定 persistent_id 与建筑语义字段。只读。",
    inputSchema: {
      type: "object",
      properties: {
        unit: { type: "string", enum: ["mm", "cm", "m", "in", "ft", "model"], default: "model" },
      },
      additionalProperties: false,
    },
  },
  {
    name: "su_validate_model",
    description: "对当前模型执行结构化 QA：重复 spec_id、未命名容器、零包围盒和顶层松散几何。只读。",
    inputSchema: {
      type: "object",
      properties: {
        unit: { type: "string", enum: ["mm", "cm", "m", "in", "ft", "model"], default: "model" },
      },
      additionalProperties: false,
    },
  },
  {
    name: "su_apply_plan",
    description:
      "原子执行参数化建模计划；失败整体回滚，并用 expected_revision 防止写错模型、idempotency_key 防止重复执行。" +
      "plan.unit 必填且必须是 mm/cm/m/in/ft；裸数不会被误当成模型显示单位。优先用此工具，不要用 raw eval。",
    inputSchema: {
      type: "object",
      properties: {
        plan: {
          type: "object",
          properties: {
            label: { type: "string" },
            unit: { type: "string", enum: ["mm", "cm", "m", "in", "ft"] },
            expected_revision: { type: "integer", minimum: 0 },
            idempotency_key: { type: "string", minLength: 1 },
            operations: {
              type: "array",
              minItems: 1,
              maxItems: 500,
              items: {
                type: "object",
                description:
                  "type 可为 set_units/material/box/cylinder/cone/ngon/curve/move/rotate/assign_material/mark/erase；" +
                  "几何操作应带 id、name、尺寸和可选 semantic{spec_id,kind,level,certainty,source}。",
              },
            },
          },
          required: ["unit", "expected_revision", "idempotency_key", "operations"],
          additionalProperties: true,
        },
      },
      required: ["plan"],
      additionalProperties: false,
    },
  },
  {
    name: "su_bounds",
    description: "精确读取整个模型或名称/spec_id/persistent_id 指向实体的包围盒。缺省以模型显示单位输出。",
    inputSchema: {
      type: "object",
      properties: {
        reference: { type: "string", description: "名称、spec_id 或 persistent_id；省略表示整个模型" },
        unit: { type: "string", enum: ["mm", "cm", "m", "in", "ft", "model"], default: "model" },
      },
      additionalProperties: false,
    },
  },
  {
    name: "su_capture_views",
    description:
      "批量拍摄 iso/front/back/left/right/top 或自定义相机视图；clean=true 临时隐藏边线，完成后恢复原相机和可见性。",
    inputSchema: {
      type: "object",
      properties: {
        views: {
          type: "array",
          maxItems: 12,
          items: { anyOf: [{ type: "string" }, { type: "object" }] },
        },
        directory: { type: "string" },
        width: { type: "integer", minimum: 64, maximum: 4000, default: 1600 },
        height: { type: "integer", minimum: 64, maximum: 4000, default: 900 },
        clean: { type: "boolean", default: true },
      },
      additionalProperties: false,
    },
  },
  {
    name: "su_screenshot",
    description: "保存当前视图 PNG；不改变相机、边线或模型几何。",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string" },
        width: { type: "integer", minimum: 64, maximum: 4000, default: 1600 },
        height: { type: "integer", minimum: 64, maximum: 4000, default: 900 },
      },
      additionalProperties: false,
    },
  },
  {
    name: "su_render",
    description: "输出无边线材质截图，截图后自动恢复边线、相机、阴影和样式；适合交给原生 ImageGen 做表现图。",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string" },
        width: { type: "integer", minimum: 64, maximum: 4000, default: 1600 },
        height: { type: "integer", minimum: 64, maximum: 4000, default: 900 },
      },
      additionalProperties: false,
    },
  },
  {
    name: "su_save",
    description: "保存 .skp；省略 path 时生成时间戳副本，不覆盖用户原文件。",
    inputSchema: {
      type: "object",
      properties: { path: { type: "string" } },
      additionalProperties: false,
    },
  },
  {
    name: "su_selftest",
    description: "在 SketchUp 内执行单位、几何、PBR、纹理、截图恢复测试；测试几何最终回滚。",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "su_eval",
    description:
      "专家级兜底：直接执行 SketchUp Ruby。高风险，可能部分执行；必须自行用 Su.transaction 包裹。" +
      "SketchUp 裸数字长度永远是英寸，不能把它当模型显示单位；优先使用 su_apply_plan。",
    inputSchema: {
      type: "object",
      properties: { code: { type: "string", minLength: 1 } },
      required: ["code"],
      additionalProperties: false,
    },
  },
];

async function callTool(name, args) {
  if (name === "su_ping") {
    const ping = await requestJson("/ping", null, 8000);
    return { connected: true, endpoint: SU_BASE, service: ping };
  }
  if (name === "su_capabilities") return suCall("capabilities");
  if (name === "su_info") return suCall("info");
  if (name === "su_inspect_model") return suCall("inspect_model", { unit: args.unit || "model" });
  if (name === "su_validate_model") return suCall("validate_model", { unit: args.unit || "model" });
  if (name === "su_apply_plan") return suCall("apply_plan", { plan: args.plan }, SU_TIMEOUT);
  if (name === "su_bounds") {
    return suCall("bounds", { reference: args.reference || "", unit: args.unit || "model" });
  }
  if (name === "su_capture_views") {
    return suCall("capture_views", {
      views: args.views,
      directory: args.directory,
      width: clampInteger(args.width, 1600, 64, 4000),
      height: clampInteger(args.height, 900, 64, 4000),
      clean: args.clean !== false,
    }, SU_TIMEOUT);
  }
  if (name === "su_screenshot") {
    return suCall("screenshot", {
      path: args.path || defaultDesktopFile("su_view"),
      width: clampInteger(args.width, 1600, 64, 4000),
      height: clampInteger(args.height, 900, 64, 4000),
    });
  }
  if (name === "su_render") {
    return suCall("render_ready", {
      path: args.path || defaultDesktopFile("su_render"),
      width: clampInteger(args.width, 1600, 64, 4000),
      height: clampInteger(args.height, 900, 64, 4000),
    });
  }
  if (name === "su_save") return suCall("save", { path: args.path || null });
  if (name === "su_selftest") return suCall("selftest", {}, SU_TIMEOUT);
  if (name === "su_eval") {
    if (!args.code || typeof args.code !== "string") throw new Error("缺少 code 参数");
    return suEval(args.code);
  }
  throw new Error("未知工具: " + name);
}

let queue = Promise.resolve();

function respond(message) {
  process.stdout.write(JSON.stringify(message) + "\n");
}

function enqueue(handler) {
  queue = queue.then(handler).catch((error) => {
    process.stderr.write("handler error: " + ((error && error.stack) || error) + "\n");
  });
}

function textResult(value) {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function onMessage(message) {
  if (!message || typeof message !== "object" || typeof message.method !== "string") return;
  const { id, method } = message;

  if (method === "initialize") {
    respond({
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "su-mcp", version: "2.0.0" },
      },
    });
    return;
  }
  if (id == null) return;

  enqueue(async () => {
    try {
      if (method === "ping") {
        respond({ jsonrpc: "2.0", id, result: {} });
        return;
      }
      if (method === "tools/list") {
        respond({ jsonrpc: "2.0", id, result: { tools: TOOLS } });
        return;
      }
      if (method === "tools/call") {
        const toolName = message.params && message.params.name;
        const args = (message.params && message.params.arguments) || {};
        if (!TOOLS.some((tool) => tool.name === toolName)) {
          respond({
            jsonrpc: "2.0",
            id,
            result: { content: [{ type: "text", text: "未知工具: " + toolName }], isError: true },
          });
          return;
        }
        try {
          const value = await callTool(toolName, args);
          respond({
            jsonrpc: "2.0",
            id,
            result: { content: [{ type: "text", text: textResult(value) }] },
          });
        } catch (error) {
          respond({
            jsonrpc: "2.0",
            id,
            result: { content: [{ type: "text", text: errText(error) }], isError: true },
          });
        }
        return;
      }
      if (method === "resources/list") {
        respond({ jsonrpc: "2.0", id, result: { resources: [] } });
        return;
      }
      if (method === "prompts/list") {
        respond({ jsonrpc: "2.0", id, result: { prompts: [] } });
        return;
      }
      respond({
        jsonrpc: "2.0",
        id,
        error: { code: -32601, message: "Method not found: " + method },
      });
    } catch (error) {
      respond({
        jsonrpc: "2.0",
        id,
        error: { code: -32603, message: (error && error.message) || String(error) },
      });
    }
  });
}

process.stdin.setEncoding("utf8");
const rl = readline.createInterface({ input: process.stdin, terminal: false });
rl.on("line", (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  try {
    onMessage(JSON.parse(trimmed));
  } catch (error) {
    process.stderr.write("bad json: " + trimmed.slice(0, 200) + "\n");
  }
});
rl.on("close", () => {
  setTimeout(() => process.exit(0), 15000).unref();
  queue.then(() => process.exit(0));
});
