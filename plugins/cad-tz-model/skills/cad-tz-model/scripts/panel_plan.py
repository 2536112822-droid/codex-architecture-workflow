#!/usr/bin/env python3
"""Generate an offline, non-executable cad_apply_plan JSON template.

All lengths use unit (mm/cm/m). origin is the plate's lower-left corner;
offset_x/y measure from that corner to the first hole centre. Rows increase
in +Y and columns in +X. Clearance means material between circle edges and
the plate boundary or neighbouring circle edges, not centre spacing.

The output is 2D drawing geometry, NOT solid cutting or a manufacturing /
construction certification. No CAD connection, state lookup or apply exists.
Document/revision/idempotency guards must be supplied by the existing trusted
workflow after review; this generator never invents them.

operation.id is a result mapping, not an upsert key; parameter_sha256 is NOT a
CAD idempotency key. Submitting changed geometry again adds new entities. Query
the old handles and use guarded cad_edit or an explicitly authorised replacement
plan; this generator never deletes or updates an existing drawing.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import math
from pathlib import Path
import sys


VERSION = "1.0.0"
COMPONENT_ID = "panel-2d"
MAX_OPERATIONS = 2000
BRIDGE_MIN_TOLERANCE = Decimal("1e-9")
FIELDS = frozenset({
    "unit", "origin", "width", "height", "rows", "columns", "diameter",
    "pitch_x", "pitch_y", "offset_x", "offset_y",
    "min_edge_clearance", "min_hole_clearance",
})
LENGTH_FIELDS = tuple(sorted(FIELDS - {"unit", "origin", "rows", "columns"}))
LAYERS = (
    {"name": "C-PANEL-OUTLINE", "color": 7},
    {"name": "C-PANEL-HOLES", "color": 3},
)


class ParameterError(ValueError):
    """The requested template cannot be represented safely."""


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _reject_constant(value: str):
    raise ParameterError(f"Non-finite JSON number is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ParameterError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def read_parameters(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      parse_float=Decimal, parse_constant=_reject_constant,
                      object_pairs_hook=_unique_object)


def _number(value: object, name: str, *, positive: bool = True) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ParameterError(f"{name} must be a number, not a boolean or string")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ParameterError(f"{name} must be a finite number") from exc
    if not number.is_finite() or (positive and number <= 0):
        raise ParameterError(f"{name} must be {'positive and ' if positive else ''}finite")
    # Reject unsafe precision / range rather than quietly collapsing geometry.
    _json_number(number, name)
    return number


def _json_number(value: Decimal, name: str = "derived geometry") -> int | float:
    number = float(value)
    if not math.isfinite(number) or Decimal(str(number)) != value:
        raise ParameterError(f"{name} cannot round-trip safely as a CAD JSON number")
    if value == 0:
        return 0
    return int(value) if value == value.to_integral_value() else number


def _integer(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ParameterError(f"{name} must be a positive integer")
    return value


def _point(*coordinates: Decimal) -> list[int | float]:
    return [_json_number(value) for value in coordinates]


def generate(parameters: dict) -> dict:
    """Return an existing-schema plan template plus JSON provenance; no I/O."""
    if not isinstance(parameters, dict):
        raise ParameterError("Parameters must be a JSON object")
    unknown = set(parameters) - FIELDS
    missing = FIELDS - set(parameters)
    if unknown or missing:
        raise ParameterError(f"Unknown fields: {sorted(unknown)}; missing fields: {sorted(missing)}")
    unit = parameters["unit"]
    if not isinstance(unit, str) or unit not in {"mm", "cm", "m"}:
        raise ParameterError("unit must be exactly mm, cm or m")
    rows = _integer(parameters["rows"], "rows")
    columns = _integer(parameters["columns"], "columns")
    if rows * columns + 1 > MAX_OPERATIONS:
        raise ParameterError("Hole count plus boundary exceeds 2000 operations")
    origin = parameters["origin"]
    if not isinstance(origin, list) or len(origin) != 2:
        raise ParameterError("origin must be exactly [x, y]")
    x0, y0 = [_number(value, f"origin[{index}]", positive=False)
              for index, value in enumerate(origin)]
    lengths = {name: _number(parameters[name], name) for name in LENGTH_FIELDS}
    # Input and output are round-trip checked. High precision avoids cancellation
    # during sums; any derived unrepresentable coordinate is rejected below.
    with localcontext() as context:
        context.prec = 1000
        width, height, diameter = (lengths[key] for key in ("width", "height", "diameter"))
        pitch_x, pitch_y = lengths["pitch_x"], lengths["pitch_y"]
        offset_x, offset_y = lengths["offset_x"], lengths["offset_y"]
        radius = diameter / 2
        if radius <= BRIDGE_MIN_TOLERANCE:
            raise ParameterError("Hole radius is at or below the existing CAD bridge's 1e-9 unit QA floor")
        last_x = offset_x + (columns - 1) * pitch_x
        last_y = offset_y + (rows - 1) * pitch_y
        edges = {"left": offset_x - radius, "bottom": offset_y - radius,
                 "right": width - last_x - radius, "top": height - last_y - radius}
        for side, actual in edges.items():
            if actual < lengths["min_edge_clearance"]:
                raise ParameterError(f"{side} edge clearance {actual} is below min_edge_clearance")
        gaps = {"x": pitch_x - diameter if columns > 1 else None,
                "y": pitch_y - diameter if rows > 1 else None}
        for axis, actual in gaps.items():
            if actual is not None and actual < lengths["min_hole_clearance"]:
                raise ParameterError(f"{axis} hole clearance {actual} is below min_hole_clearance")

        canonical_parameters = {"unit": unit, "origin": _point(x0, y0),
                                "rows": rows, "columns": columns}
        canonical_parameters.update({name: _json_number(value, name)
                                     for name, value in lengths.items()})
        operations = [{"id": f"{COMPONENT_ID}/outline", "type": "rect",
                       "p": _point(x0, y0, width, height), "layer": LAYERS[0]["name"]}]
        for row in range(rows):
            for column in range(columns):
                operations.append({
                    "id": f"{COMPONENT_ID}/hole/r{row + 1:04d}/c{column + 1:04d}",
                    "type": "circle",
                    "p": _point(x0 + offset_x + column * pitch_x,
                                y0 + offset_y + row * pitch_y, radius),
                    "layer": LAYERS[1]["name"],
                })
        # Check the far edges independently of the rect width/height fields.
        bounds = _point(x0, y0, x0 + width, y0 + height)
        if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            raise ParameterError("Plate bounds collapse in numeric representation")
        millimetres_per_unit = {"mm": Decimal(1), "cm": Decimal(10), "m": Decimal(1000)}[unit]
        # Preserve a 0.01 mm QA ceiling, reduce it for deliberately tiny features.
        tolerance = max(BRIDGE_MIN_TOLERANCE,
                        min(Decimal("0.01") / millimetres_per_unit,
                            radius / 100, lengths["min_edge_clearance"] / 100,
                            lengths["min_hole_clearance"] / 100))
        evidence = {"unit": unit, "hole_count": rows * columns,
                    "operation_count": len(operations), "bounds_xyxy": bounds,
                    "width": _json_number(width), "height": _json_number(height),
                    "edge_clearances": {side: _json_number(value) for side, value in edges.items()},
                    "hole_clearances": {axis: None if value is None else _json_number(value)
                                        for axis, value in gaps.items()},
                    "minimum_actual_edge_clearance": _json_number(min(edges.values())),
                    "minimum_actual_hole_clearance": (
                        _json_number(min(value for value in gaps.values() if value is not None))
                        if any(value is not None for value in gaps.values()) else None)}

        plan = {"unit": unit, "precision": 8,
                "layers": [dict(layer) for layer in LAYERS],
                "required_layers": [layer["name"] for layer in LAYERS],
                "operations": operations, "tolerance": _json_number(tolerance),
                "require_closed_polylines": True}
        fingerprint_payload = {"generator": "panel_plan", "version": VERSION,
                               "component_id": COMPONENT_ID,
                               "parameters": canonical_parameters, "plan": plan}
        fingerprint = hashlib.sha256(canonical_json(fingerprint_payload).encode("utf-8")).hexdigest()
        parameter_hash = hashlib.sha256(canonical_json(canonical_parameters).encode("utf-8")).hexdigest()
        return {
            "kind": "cad_plan_template", "component_id": COMPONENT_ID,
            "plan": plan, "parameters": canonical_parameters,
            "parameter_sha256": parameter_hash, "checks": evidence,
            "provenance": {
                "status": "template_requires_live_guards",
                "generator": "panel_plan", "generator_version": VERSION,
                "template_sha256": fingerprint,
                "hash_scope": "canonical JSON of {generator,version,component_id,parameters,plan}",
            },
            "limitations": ["2D geometry only; circles do not cut a solid",
                            "Not a construction or manufacturing certification",
                            "No document/revision/idempotency guards are generated",
                            "operation.id maps results; it does not upsert existing entities",
                            "parameter_sha256 is provenance, not a CAD idempotency key",
                            "Resubmission adds entities: query old handles, then use guarded cad_edit or an authorised replacement plan",
                            "This generator never connects to CAD, applies, deletes or updates entities"],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params", required=True, help="Strict parameter JSON file")
    parser.add_argument("--out", help="Create a NEW JSON file; never overwrite")
    args = parser.parse_args(argv)
    try:
        rendered = canonical_json(generate(read_parameters(args.params))) + "\n"
        if args.out:
            with Path(args.out).open("x", encoding="utf-8", newline="\n") as destination:
                destination.write(rendered)
        else:
            sys.stdout.write(rendered)
        return 0
    except (ParameterError, OSError, json.JSONDecodeError) as exc:
        print(f"panel_plan: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
