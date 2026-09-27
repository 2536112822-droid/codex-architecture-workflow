#!/usr/bin/env python3
"""Read-only numerical diagnostics for explicitly opaque sRGB hex colors.

No third-party packages, image interpretation, color correction, or file writes.
Exit codes: 0 = no explicit check failed, 1 = an explicit check failed,
2 = invalid input. A successful process is not an accessibility certification.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


HEX_COLOR = re.compile(r"\A#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\Z")
LIMITATIONS = [
    "Only explicitly opaque sRGB #RGB and #RRGGBB values are supported; "
    "no alpha compositing, image sampling, or color-profile inference is performed.",
    "Contrast results apply only to the supplied foreground/background pair "
    "and supplied numeric minimum; they do not establish overall accessibility.",
    "Relative-luminance monotonicity does not establish perceptual uniformity, "
    "color-vision distinguishability, overall aesthetics, or print/projector performance.",
    "No colors or artwork are modified. The input file is read only.",
]


class InputError(ValueError):
    """A user input error with a machine-readable location."""

    def __init__(self, message: str, location: str = "$") -> None:
        super().__init__(message)
        self.location = location


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # Keep usage errors in the same JSON channel as schema errors.
        raise InputError(message, "cli")


def _object(value: Any, allowed: set[str], required: set[str], location: str) -> dict:
    if not isinstance(value, dict):
        raise InputError("Expected an object.", location)
    unknown = set(value) - allowed
    if unknown:
        raise InputError("Unknown field(s): " + ", ".join(sorted(map(str, unknown))), location)
    missing = required - set(value)
    if missing:
        raise InputError("Missing field(s): " + ", ".join(sorted(missing)), location)
    return value


def _identifier(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError("Expected a nonempty string id.", location)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise InputError("Id must contain valid Unicode scalar values.", location) from error
    return value


def parse_color(value: Any, location: str = "color") -> str:
    """Validate before deriving any number; return canonical six-digit hex."""
    if not isinstance(value, str) or not HEX_COLOR.fullmatch(value):
        raise InputError("Expected an opaque sRGB color as #RGB or #RRGGBB.", location)
    digits = value[1:]
    if len(digits) == 3:
        digits = "".join(channel * 2 for channel in digits)
    return "#" + digits.upper()


def _minimum(value: Any, location: str) -> float:
    # bool is an int subclass, but must not become a numeric threshold.
    if type(value) not in (int, float):
        raise InputError("Minimum must be a finite number from 1 through 21.", location)
    if isinstance(value, float) and not math.isfinite(value):
        raise InputError("Minimum must be a finite number from 1 through 21.", location)
    if not 1 <= value <= 21:
        raise InputError("Minimum must be a finite number from 1 through 21.", location)
    return float(value)


def relative_luminance(color: str) -> float:
    """WCAG sRGB relative luminance, using the 0.04045 transfer threshold."""
    normalized = parse_color(color)
    channels = [int(normalized[index:index + 2], 16) / 255.0 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045
              else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    luminances = (relative_luminance(foreground), relative_luminance(background))
    return (max(luminances) + 0.05) / (min(luminances) + 0.05)


def _diagnostic(code: str, message: str, location: str, severity: str = "info") -> dict:
    return {"severity": severity, "code": code, "path": location, "message": message}


def audit(payload: Any) -> dict:
    """Validate and calculate a complete report without mutating the payload.

    Reversal indices are zero-based indices of colors that violate the selected
    direction relative to their immediate predecessor. Equal luminance is
    allowed (non-strict monotonicity); duplicate colors receive a separate note.
    """
    root = _object(payload, {"pairs", "ramps"}, set(), "$")
    collections = {}
    for name in ("pairs", "ramps"):
        value = root.get(name, [])
        if not isinstance(value, list):
            raise InputError("Expected an array.", f"$.{name}")
        collections[name] = value
    if not collections["pairs"] and not collections["ramps"]:
        raise InputError("Provide at least one pair or one ramp.")

    pairs = []
    ramps = []
    diagnostics = []
    failed = False
    for index, raw in enumerate(collections["pairs"]):
        path = f"$.pairs[{index}]"
        item = _object(raw, {"id", "foreground", "background", "minimum"},
                       {"id", "foreground", "background"}, path)
        identifier = _identifier(item["id"], path + ".id")
        foreground = parse_color(item["foreground"], path + ".foreground")
        background = parse_color(item["background"], path + ".background")
        foreground_luminance = relative_luminance(foreground)
        background_luminance = relative_luminance(background)
        ratio = contrast_ratio(foreground, background)
        minimum = _minimum(item["minimum"], path + ".minimum") if "minimum" in item else None
        # Compare the full computed value. Display rounding must never turn a
        # ratio below the requested minimum into a passing result.
        status = "not_applicable" if minimum is None else ("pass" if ratio >= minimum else "fail")
        if minimum is None:
            diagnostics.append(_diagnostic("minimum_not_set", "No contrast minimum was supplied; no pass/fail judgment was made.", path))
        if status == "fail":
            failed = True
            diagnostics.append(_diagnostic("contrast_below_minimum", "The unrounded contrast ratio is below the supplied minimum.", path, "error"))
        pairs.append({"id": identifier, "foreground": foreground, "background": background,
                      "foreground_luminance": foreground_luminance,
                      "background_luminance": background_luminance,
                      "contrast_ratio": ratio, "minimum": minimum, "status": status})

    for index, raw in enumerate(collections["ramps"]):
        path = f"$.ramps[{index}]"
        item = _object(raw, {"id", "colors", "kind", "direction"}, {"id", "colors", "kind"}, path)
        identifier = _identifier(item["id"], path + ".id")
        kind = item["kind"]
        if not isinstance(kind, str) or kind not in ("sequential", "categorical", "diverging"):
            raise InputError("Kind must be sequential, categorical, or diverging.", path + ".kind")
        direction = item.get("direction")
        if "direction" in item and (not isinstance(direction, str) or direction not in ("increasing", "decreasing")):
            raise InputError("Direction must be increasing or decreasing.", path + ".direction")
        if not isinstance(item["colors"], list) or len(item["colors"]) < 2:
            raise InputError("A ramp must contain an array of at least two colors.", path + ".colors")
        colors = [parse_color(color, f"{path}.colors[{i}]") for i, color in enumerate(item["colors"])]
        luminances = [relative_luminance(color) for color in colors]
        occurrences = {}
        for i, color in enumerate(colors):
            occurrences.setdefault(color, []).append(i)
        duplicates = [{"color": color, "indices": indices} for color, indices in occurrences.items() if len(indices) > 1]
        if duplicates:
            diagnostics.append(_diagnostic("duplicate_colors", "The ramp contains repeated colors after hex normalization; see duplicate indices.", path, "warning"))

        reversals = []
        monotonicity_status = "not_applicable"
        if kind == "sequential" and direction is not None:
            reversals = [i for i in range(1, len(luminances))
                         if (luminances[i] < luminances[i - 1] if direction == "increasing"
                             else luminances[i] > luminances[i - 1])]
            monotonicity_status = "fail" if reversals else "pass"
            if reversals:
                failed = True
                diagnostics.append(_diagnostic("luminance_direction_reversal", "Relative luminance reverses the explicitly selected sequential direction.", path, "error"))
        elif kind == "sequential":
            diagnostics.append(_diagnostic("direction_not_set", "No sequential direction was supplied; monotonicity was not evaluated.", path))
        else:
            diagnostics.append(_diagnostic("monotonicity_not_applicable", "Categorical and diverging ramps are not subjected to a monotonicity pass/fail check.", path))
            if direction is not None:
                diagnostics.append(_diagnostic("direction_not_used", "Direction is only used for sequential ramps.", path + ".direction", "warning"))
        ramps.append({"id": identifier, "kind": kind, "colors": colors,
                      "relative_luminances": luminances, "index_base": 0,
                      "duplicates": duplicates,
                      "monotonicity": {"status": monotonicity_status, "direction": direction,
                                       "reversal_indices": reversals,
                                       "definition": "Non-strict relative-luminance order; each reversal index is compared with its predecessor."}})

    return {"schema_version": 1, "status": "failed" if failed else "no_explicit_failure",
            "color_space": "opaque sRGB", "pairs": pairs, "ramps": ramps,
            "diagnostics": diagnostics, "limitations": list(LIMITATIONS)}


def _reject_json_constant(value: str) -> None:
    raise InputError(f"Non-finite JSON number is not allowed: {value}")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _parse_arguments(argv: list[str] | None) -> Any:
    parser = JsonArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--input", metavar="JSON_PATH", help="Read a UTF-8 JSON file without modifying it.")
    parser.add_argument("--foreground", metavar="HEX", help="Opaque sRGB #RGB or #RRGGBB.")
    parser.add_argument("--background", metavar="HEX", help="Opaque sRGB #RGB or #RRGGBB.")
    parser.add_argument("--minimum", metavar="NUMBER", help="Optional explicit numeric contrast minimum, from 1 through 21.")
    args = parser.parse_args(argv)
    if args.input is not None:
        if any(value is not None for value in (args.foreground, args.background, args.minimum)):
            raise InputError("Use either --input or --foreground/--background [--minimum], not both.", "cli")
        try:
            contents = Path(args.input).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError, ValueError) as error:
            raise InputError(f"Unable to read UTF-8 input file: {error}", "cli.input") from error
        try:
            return json.loads(contents, parse_constant=_reject_json_constant,
                              object_pairs_hook=_unique_json_object)
        except (ValueError, RecursionError) as error:
            if isinstance(error, InputError):
                raise
            raise InputError(f"Invalid JSON: {error}", "cli.input") from error
    if args.foreground is None or args.background is None:
        raise InputError("Provide --input, or both --foreground and --background.", "cli")
    pair = {"id": "cli", "foreground": args.foreground, "background": args.background}
    if args.minimum is not None:
        try:
            pair["minimum"] = _minimum(float(args.minimum), "cli.minimum")
        except ValueError as error:
            if isinstance(error, InputError):
                raise
            raise InputError("Minimum must be a finite number from 1 through 21.", "cli.minimum") from error
    return {"pairs": [pair]}


def main(argv: list[str] | None = None) -> int:
    try:
        report = audit(_parse_arguments(argv))
        exit_code = 1 if report["status"] == "failed" else 0
    except InputError as error:
        report = {"schema_version": 1, "status": "invalid_input",
                  "diagnostics": [_diagnostic("invalid_input", str(error), error.location, "error")],
                  "limitations": list(LIMITATIONS)}
        exit_code = 2
    # UTF-8 and JSON escapes also keep malformed Unicode in error messages
    # machine-readable. Valid Unicode ids round-trip through json.loads.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, allow_nan=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
