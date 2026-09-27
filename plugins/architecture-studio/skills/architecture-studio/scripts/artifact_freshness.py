"""Read-only, declared-artifact byte/metadata comparison; never a CAD QA gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import sys

FORMAT = "artifact-freshness/1"
SCOPE = ("Saved disk bytes and declared artifact metadata only. No claim about active "
         "documents, unsaved changes, geometry, visual QA, or permission to reuse/skip checks.")
STATUSES = {"draft", "verified", "superseded", "failed", "presentation_only"}
STAGES = {"site", "model", "drawing", "render", "presentation", "report"}
CONTEXT_FIELDS = ("units", "coordinate_reference", "brief", "levels", "elements", "views", "evidence")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_mode)


def _local_path(raw, root):
    """Local regular-file paths only; reject network/device/URL paths before I/O."""
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError("invalid_path")
    if raw.startswith(("\\\\", "//")):
        raise ValueError("network_or_device_path")
    windows = PureWindowsPath(raw)
    if windows.drive:
        if not re.fullmatch(r"[A-Za-z]:", windows.drive) or not windows.is_absolute():
            raise ValueError("invalid_drive_path")
        if os.name != "nt":
            raise ValueError("foreign_absolute_path")
    elif re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw):
        raise ValueError("url_or_scheme_path")
    # ADS and Windows device aliases are not saved files.
    for part in windows.parts[1:] if windows.drive else windows.parts:
        if ":" in part or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part):
            raise ValueError("device_or_stream_path")
    path = Path(raw)
    path = path if path.is_absolute() else root / path
    resolved = path.resolve(strict=False)
    if str(resolved).startswith(("\\\\", "//")):
        raise ValueError("network_or_device_path")
    return resolved


def _read_file(path, keep_bytes=False):
    """Check path/open-file identity before and after reading (not a filesystem lock)."""
    first = path.stat()
    if not stat.S_ISREG(first.st_mode):
        raise ValueError("not_regular_file")
    digest = hashlib.sha256()
    chunks = []
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if _signature(first) != _signature(opened):
            raise ValueError("file_changed_during_read")
        size = 0
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
            if keep_bytes:
                chunks.append(chunk)
        after = os.fstat(handle.fileno())
    final = path.stat()
    # Some Windows runtimes expose different ctime semantics through stat/fstat;
    # compare ctime only within the same API, while comparing file identity across both.
    if (not (_signature(first) == _signature(after) == _signature(final))
            or first.st_ctime_ns != final.st_ctime_ns
            or opened.st_ctime_ns != after.st_ctime_ns or size != first.st_size):
        raise ValueError("file_changed_during_read")
    result = {"sha256": digest.hexdigest(), "size": size}
    return (result, b"".join(chunks)) if keep_bytes else result


def _file_record(raw, root):
    try:
        return _read_file(_local_path(raw, root)), []
    except FileNotFoundError:
        return None, ["file_missing"]
    except (OSError, ValueError, RuntimeError) as error:
        reason = str(error) if isinstance(error, ValueError) else "file_unreadable"
        return None, [reason]


def _graph_errors(rows):
    """Validate edges, including cycles; preserve usable edges for impact propagation."""
    for ident, row in rows.items():
        for source in row["sources"] or []:
            if source not in rows:
                row["errors"].append("dangling_source:" + source)
    # A reachability check avoids recursion limits and marks exactly cyclic nodes.
    for ident, row in rows.items():
        pending = list(row["sources"] or [])
        seen = set()
        while pending:
            source = pending.pop()
            if source == ident:
                row["errors"].append("dependency_cycle")
                break
            if source not in seen and source in rows:
                seen.add(source)
                pending.extend(rows[source]["sources"] or [])


def capture(contract, project_root):
    """Capture facts/errors without writes. Missing dependency declarations stay unknown."""
    rows, errors = {}, []
    project_id, context_hash = None, None
    try:
        contract = json.loads(_canonical(contract))  # freeze caller data; reject NaN/Infinity
        if not isinstance(contract, dict):
            raise ValueError("contract_not_object")
        context_hash = _digest({key: contract.get(key) for key in CONTEXT_FIELDS})
        if any(key not in contract for key in CONTEXT_FIELDS):
            errors.append("project_context_incomplete")
        project_id = contract.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            errors.append("invalid_project_id")
        artifacts = contract.get("artifacts")
        if not isinstance(artifacts, list):
            raise ValueError("artifacts_not_array")
        root = _local_path(str(project_root), Path.cwd())
        if not root.is_dir():
            raise ValueError("project_root_not_directory")
    except (TypeError, ValueError, OSError, RuntimeError) as error:
        errors.append("invalid_contract_or_root:" + str(error))
        artifacts = []
    for item in artifacts:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            errors.append("invalid_artifact_id")
            continue
        ident = item["id"]
        if ident in rows:
            errors.append("duplicate_artifact_id:" + ident)
            continue
        local_errors = []
        deps = item.get("source_artifact_ids")
        if deps is None:
            local_errors.append("dependencies_unknown")
        elif (not isinstance(deps, list) or any(not isinstance(x, str) or not x for x in deps)
              or len(deps) != len(set(deps))):
            local_errors.append("invalid_dependencies")
            deps = None
        else:
            deps = sorted(deps)
        revision = item.get("source_revision")
        if type(revision) is not int or revision < 0:
            local_errors.append("invalid_source_revision")
        if not isinstance(item.get("status"), str) or item["status"] not in STATUSES:
            local_errors.append("invalid_status")
        if not isinstance(item.get("stage"), str) or item["stage"] not in STAGES:
            local_errors.append("invalid_stage")
        file_info, file_errors = _file_record(item.get("path"), root)
        if deps is not None:
            item["source_artifact_ids"] = deps
        rows[ident] = {"metadata": item, "sources": deps, "file": file_info,
                       "errors": sorted(local_errors + file_errors)}
    _graph_errors(rows)
    snapshot = {"format": FORMAT, "scope": SCOPE, "project_id": project_id,
                "project_context_sha256": context_hash, "artifacts": rows, "errors": sorted(errors)}
    snapshot["snapshot_sha256"] = _digest(snapshot)
    return snapshot


def _snapshot_error(snapshot):
    try:
        if not isinstance(snapshot, dict) or snapshot.get("format") != FORMAT:
            return "unsupported_snapshot"
        payload = {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
        if snapshot.get("snapshot_sha256") != _digest(payload):
            return "snapshot_integrity_mismatch"
        if not isinstance(snapshot.get("errors"), list) or not isinstance(snapshot.get("artifacts"), dict):
            return "invalid_snapshot_structure"
        if not re.fullmatch(r"[0-9a-f]{64}", str(snapshot.get("project_context_sha256", ""))):
            return "snapshot_context_unknown"
        for ident, row in snapshot["artifacts"].items():
            if not isinstance(ident, str) or not isinstance(row, dict):
                return "invalid_snapshot_structure"
            if not isinstance(row.get("metadata"), dict) or row["metadata"].get("id") != ident:
                return "invalid_snapshot_structure"
            if not isinstance(row.get("errors"), list) or "sources" not in row or "file" not in row:
                return "invalid_snapshot_structure"
            sources = row["sources"]
            if sources is not None and (not isinstance(sources, list) or any(not isinstance(x, str) for x in sources)):
                return "invalid_snapshot_structure"
            file_info = row["file"]
            if file_info is not None and (not isinstance(file_info, dict)
                    or not re.fullmatch(r"[0-9a-f]{64}", str(file_info.get("sha256", "")))
                    or type(file_info.get("size")) is not int or file_info["size"] < 0):
                return "invalid_snapshot_structure"
        return None
    except (TypeError, ValueError, KeyError):
        return "invalid_snapshot_structure"


def compare(contract, snapshot, project_root):
    """Compare one saved baseline; old and new edges both propagate uncertainty/change."""
    current = capture(contract, project_root)
    error = _snapshot_error(snapshot)
    before = {} if error else snapshot["artifacts"]
    after = current["artifacts"]
    global_errors = list(current["errors"])
    if error:
        global_errors.append(error)
    else:
        global_errors.extend("baseline:" + str(value) for value in snapshot["errors"])
        if snapshot.get("project_id") != current["project_id"]:
            global_errors.append("project_identity_changed")
        if snapshot["project_context_sha256"] != current["project_context_sha256"]:
            global_errors.append("project_context_changed")
    report_rows = {}
    edges = {}
    for ident in sorted(before.keys() | after.keys()):
        old, new = before.get(ident), after.get(ident)
        reasons = []
        unresolved = bool(global_errors)
        if old is None:
            reasons.append("artifact_added")
        if new is None:
            reasons.append("artifact_removed")
        for label, row in (("baseline", old), ("current", new)):
            if row:
                reasons.extend(label + ":" + str(value) for value in row["errors"])
                unresolved = unresolved or bool(row["errors"]) or row["file"] is None or row["sources"] is None
                for source in row["sources"] or []:
                    edges.setdefault(source, set()).add(ident)
        if old and new:
            for field, reason in (("path", "path_changed"), ("source_revision", "source_revision_changed"),
                                  ("status", "status_changed"), ("source_artifact_ids", "dependencies_changed")):
                if old["metadata"].get(field) != new["metadata"].get(field):
                    reasons.append(reason)
            if old["metadata"] != new["metadata"]:
                reasons.append("metadata_changed")
            if old["file"] != new["file"]:
                reasons.append("file_bytes_changed_or_unavailable")
        report_rows[ident] = {"state": "unverifiable" if unresolved else "affected" if reasons else "unchanged_since_snapshot",
                              "declared_status": new["metadata"].get("status") if new else None,
                              "reasons": sorted(set(reasons)), "affected_by": []}
    # Seed each cause independently so cycles terminate and every affected source is named.
    seeds = [ident for ident, row in report_rows.items() if row["state"] != "unchanged_since_snapshot"]
    for seed in seeds:
        pending, visited = list(edges.get(seed, ())), {seed}
        while pending:
            ident = pending.pop()
            if ident in visited:
                continue
            visited.add(ident)
            row = report_rows[ident]
            row["affected_by"].append(seed)
            if row["state"] == "unchanged_since_snapshot":
                row["state"] = "affected"
            pending.extend(edges.get(ident, ()))
    for row in report_rows.values():
        row["affected_by"].sort()
        if row["affected_by"]:
            row["reasons"].append("upstream_affected")
    attention = bool(global_errors) or any(row["state"] != "unchanged_since_snapshot" for row in report_rows.values())
    return {"format": FORMAT, "scope": SCOPE, "comparison": "attention_required" if attention else "unchanged_since_snapshot",
            "errors": sorted(set(global_errors)), "artifacts": report_rows}


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key:" + key)
        result[key] = value
    return result


def _load(path):
    _, payload = _read_file(path, keep_bytes=True)
    def nonfinite(value):
        raise ValueError("nonfinite_json:" + value)
    return json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_json_object, parse_constant=nonfinite)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("snapshot", "check"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--contract", required=True)
        sub.add_argument("--root", required=True)
        sub.add_argument("--out" if command == "snapshot" else "--snapshot", required=True)
    args = parser.parse_args(argv)
    try:
        root = _local_path(args.root, Path.cwd())
        contract_path = _local_path(args.contract, Path.cwd())
        contract = _load(contract_path)
        if args.command == "check":
            snapshot = _load(_local_path(args.snapshot, Path.cwd()))
            result = compare(contract, snapshot, root)
            exit_code = 0 if result["comparison"] == "unchanged_since_snapshot" else 2
        else:
            result = capture(contract, root)
            output = _local_path(args.out, Path.cwd())
            inputs = {contract_path}
            for row in result["artifacts"].values():
                try:
                    inputs.add(_local_path(row["metadata"].get("path"), root))
                except (ValueError, OSError, RuntimeError):
                    pass
            if output in inputs:
                raise ValueError("snapshot_output_is_input")
            # x forbids replacing existing files, including symlinks/hardlinks.
            with output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            exit_code = 2 if result["errors"] or any(row["errors"] for row in result["artifacts"].values()) else 0
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False))
        return exit_code
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        print(json.dumps({"comparison": "attention_required", "scope": SCOPE,
                          "errors": [str(error)]}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
