"""Verify the editable Python runtime without connecting to a Rhino document."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import queue
import subprocess
import threading
import time


def verify(server: Path) -> dict:
    import jsonschema
    from rhinomcp.validation import _get_contracts_dir, validate_command

    contracts = _get_contracts_dir().resolve()
    expected_contracts = (Path(__file__).parent / "rhinomcp" / "contracts").resolve()
    if contracts != expected_contracts:
        raise AssertionError("Validation resolved contracts outside this source package")
    source_root = expected_contracts.parent
    manifest = json.loads((source_root / "UPSTREAM_MANIFEST.json").read_text(encoding="utf-8-sig"))
    for entry in manifest["unchanged_files"]:
        digest = hashlib.sha256((source_root / entry["path"]).read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise AssertionError(f"Upstream file changed: {entry['path']}")
    schemas = sorted(contracts.rglob("*.json"))
    for schema_path in schemas:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
    if not validate_command(
        "modify_object",
        {"id": "12345678-1234-1234-1234-123456789012", "new_color": [0, 255, 0]},
    ):
        raise AssertionError("Valid cross-file schema reference was rejected")
    try:
        validate_command("modify_object", {"id": "not-a-guid"})
    except jsonschema.ValidationError:
        pass
    else:
        raise AssertionError("Invalid GUID was not rejected by schema validation")

    # TCP port 0 cannot be a live Rhino listening endpoint. Upstream attempts a
    # startup connection, logs the failure, and continues serving MCP metadata.
    environment = dict(os.environ)
    environment.update({
        "RHINO_MCP_HOST": "127.0.0.1",
        "RHINO_MCP_PORT": "0",
        "RHINO_MCP_ALLOW_REMOTE": "0",
        "RHINO_MCP_VALIDATE": "strict",
        "RHINO_MCP_ENABLE_RUN_COMMAND": "0",
        "RHINO_MCP_ENABLE_RHINOSCRIPT": "0",
        "RHINO_MCP_ENABLE_CSHARP": "0",
        "RHINO_MCP_DEBUG": "0",
        "RHINO_MCP_TIMEOUT": "1",
    })
    responses = queue.Queue()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as diagnostics:
        process = subprocess.Popen(
            [str(server)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=diagnostics, text=True, encoding="utf-8", env=environment,
        )
        def read_responses():
            for line in process.stdout:
                try:
                    responses.put(json.loads(line))
                except json.JSONDecodeError:
                    responses.put({"invalid_stdout": line})
            responses.put({"eof": True})

        threading.Thread(target=read_responses, daemon=True).start()

        def send(message):
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        def request(request_id, method, params):
            send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            deadline = time.monotonic() + 15
            while True:
                response = responses.get(timeout=max(0.01, deadline - time.monotonic()))
                if "invalid_stdout" in response or "eof" in response:
                    raise AssertionError(f"Invalid MCP stream: {response}")
                if response.get("id") == request_id:
                    if "error" in response:
                        raise AssertionError(f"MCP request failed: {response['error']}")
                    return response["result"]

        try:
            request(1, "initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "architecture-runtime-check", "version": "1"},
            })
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            names = {tool["name"] for tool in request(2, "tools/list", {})["tools"]}
            required = {"describe_capabilities", "get_document_summary", "create_object"}
            if not required.issubset(names):
                raise AssertionError(f"Required tools missing: {required - names}")
            documentation = request(3, "tools/call", {
                "name": "list_rhinoscript_modules", "arguments": {},
            })
            response_text = " ".join(block.get("text", "") for block in documentation["content"])
            if "not bundled" not in response_text:
                raise AssertionError("Excluded documentation did not report its limitation")
        except Exception as error:
            diagnostics.flush()
            diagnostics.seek(0)
            tail = diagnostics.read()[-4000:]
            raise RuntimeError(f"MCP smoke check failed: {error}\nServer diagnostics:\n{tail}") from error
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
    return {
        "status": "passed",
        "tools_registered": len(names),
        "upstream_hashes_verified": len(manifest["unchanged_files"]),
        "json_schemas_checked": len(schemas),
        "schema_references_enforced": True,
        "documentation_exclusion_reported": True,
        "live_rhino_tested": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server", type=Path,
        default=Path(sys.executable).with_name("rhinomcp.exe" if os.name == "nt" else "rhinomcp"),
    )
    args = parser.parse_args()
    if not args.server.is_file():
        parser.error("Install this runtime in the active virtual environment first")
    print(json.dumps(verify(args.server), indent=2))


if __name__ == "__main__":
    main()
