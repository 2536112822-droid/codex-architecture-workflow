"""Standard-library checks for numerical correctness and read-only CLI behavior."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import color_audit


SCRIPT = Path(__file__).with_name("color_audit.py")


def pair(foreground="#000", background="#fff", **extra):
    return {"id": "pair", "foreground": foreground, "background": background, **extra}


def ramp(colors=None, kind="sequential", **extra):
    return {"id": "ramp", "colors": colors if colors is not None else ["#000", "#fff"], "kind": kind, **extra}


class NumericalTests(unittest.TestCase):
    def test_known_reference_ratios_and_symmetry(self):
        references = [("#000", "#fff", 21.0), ("#777", "#777", 1.0),
                      ("#AAA", "#fff", 2.3231230535045992),
                      ("#777", "#fff", 4.478089453577214)]
        for foreground, background, expected in references:
            with self.subTest(foreground=foreground, background=background):
                actual = color_audit.contrast_ratio(foreground, background)
                self.assertAlmostEqual(actual, expected, places=12)
                self.assertEqual(actual, color_audit.contrast_ratio(background, foreground))

    def test_luminance_endpoints_and_transfer_function_branches(self):
        self.assertEqual(color_audit.relative_luminance("#000"), 0.0)
        self.assertEqual(color_audit.relative_luminance("#fff"), 1.0)
        self.assertAlmostEqual(color_audit.relative_luminance("#0A0A0A"), (10 / 255) / 12.92, places=15)
        self.assertAlmostEqual(color_audit.relative_luminance("#0B0B0B"), ((11 / 255 + 0.055) / 1.055) ** 2.4, places=15)

    def test_short_hex_normalizes_without_changing_ratio(self):
        self.assertEqual(color_audit.parse_color("#aBc"), "#AABBCC")
        self.assertEqual(color_audit.contrast_ratio("#aBc", "#FFF"), color_audit.contrast_ratio("#AABBCC", "#FFFFFF"))

    def test_unrounded_boundary_must_not_pass(self):
        result = color_audit.audit({"pairs": [pair("#777", minimum=4.5)]})
        self.assertEqual(round(result["pairs"][0]["contrast_ratio"], 1), 4.5)
        self.assertEqual(result["pairs"][0]["status"], "fail")
        self.assertEqual(result["status"], "failed")

    def test_exact_minimum_and_valid_endpoints(self):
        exact = color_audit.contrast_ratio("#AAA", "#fff")
        result = color_audit.audit({"pairs": [pair("#AAA", minimum=exact), pair(minimum=21), pair("#777", "#777", minimum=1)]})
        self.assertTrue(all(item["status"] == "pass" for item in result["pairs"]))

    def test_no_minimum_never_reports_pass(self):
        result = color_audit.audit({"pairs": [pair()]})
        self.assertEqual(result["pairs"][0]["status"], "not_applicable")
        self.assertIsNone(result["pairs"][0]["minimum"])
        self.assertEqual(result["status"], "no_explicit_failure")
        self.assertIn("minimum_not_set", [item["code"] for item in result["diagnostics"]])


class RampTests(unittest.TestCase):
    def test_increasing_and_decreasing_reversals_use_zero_based_current_index(self):
        for direction, colors, expected in [
            ("increasing", ["#000", "#fff", "#777", "#000"], [2, 3]),
            ("decreasing", ["#fff", "#000", "#777", "#fff"], [2, 3]),
        ]:
            with self.subTest(direction=direction):
                result = color_audit.audit({"ramps": [ramp(colors, direction=direction)]})
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["ramps"][0]["index_base"], 0)
                self.assertEqual(result["ramps"][0]["monotonicity"]["reversal_indices"], expected)

    def test_valid_monotonic_sequences_pass_only_the_order_check(self):
        for direction, colors in [("increasing", ["#000", "#777", "#fff"]),
                                  ("decreasing", ["#fff", "#777", "#000"])]:
            with self.subTest(direction=direction):
                result = color_audit.audit({"ramps": [ramp(colors, direction=direction)]})
                self.assertEqual(result["ramps"][0]["monotonicity"]["status"], "pass")

    def test_categorical_and_diverging_do_not_have_monotonic_failures(self):
        for kind in ("categorical", "diverging"):
            for options in ({}, {"direction": "increasing"}):
                with self.subTest(kind=kind, options=options):
                    result = color_audit.audit({"ramps": [ramp(["#000", "#fff", "#000"], kind, **options)]})
                    self.assertEqual(result["status"], "no_explicit_failure")
                    self.assertEqual(result["ramps"][0]["monotonicity"]["status"], "not_applicable")
                    self.assertEqual(result["ramps"][0]["monotonicity"]["reversal_indices"], [])

    def test_sequential_without_explicit_direction_is_not_evaluated(self):
        result = color_audit.audit({"ramps": [ramp(["#000", "#fff", "#000"])]})
        self.assertEqual(result["ramps"][0]["monotonicity"]["status"], "not_applicable")
        self.assertIn("direction_not_set", [item["code"] for item in result["diagnostics"]])

    def test_repeated_colors_warn_but_equal_luminance_is_not_a_reversal(self):
        result = color_audit.audit({"ramps": [ramp(["#aaa", "#AAAAAA", "#fff"], direction="increasing")]})
        self.assertEqual(result["ramps"][0]["duplicates"], [{"color": "#AAAAAA", "indices": [0, 1]}])
        self.assertEqual(result["ramps"][0]["monotonicity"]["status"], "pass")
        self.assertIn("duplicate_colors", [item["code"] for item in result["diagnostics"]])

    def test_report_has_explicit_scope_limitations(self):
        limitations = " ".join(color_audit.audit({"ramps": [ramp()]})["limitations"])
        for phrase in ("perceptual uniformity", "color-vision", "aesthetics", "print/projector", "overall accessibility"):
            self.assertIn(phrase, limitations)


class InputValidationTests(unittest.TestCase):
    def test_unsupported_or_incomplete_colors_are_not_measured(self):
        invalid = ["red", "transparent", "#12", "#1234", "#12345", "#12345678", "123456",
                   "#ggg", " #fff", "#fff\n", "rgb(0,0,0)", "", None, 123, [0, 0, 0]]
        for color in invalid:
            with self.subTest(color=color):
                with self.assertRaises(color_audit.InputError):
                    color_audit.audit({"pairs": [pair(foreground=color)]})
                with self.assertRaises(color_audit.InputError):
                    color_audit.audit({"ramps": [ramp(["#fff", color])]})

    def test_invalid_minimum_is_rejected(self):
        for value in (0, -1, 0.99, 21.01, float("nan"), float("inf"), -float("inf"), "4.5", True, None, 10 ** 1000):
            with self.subTest(value=str(value)[:50]):
                with self.assertRaises(color_audit.InputError):
                    color_audit.audit({"pairs": [pair(minimum=value)]})

    def test_unknown_fields_at_each_schema_level_are_rejected(self):
        for payload in ({"pairs": [pair()], "paris": []}, {"pairs": [pair(mininum=4.5)]},
                        {"ramps": [ramp(direciton="increasing")]}):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(color_audit.InputError, "Unknown field"):
                    color_audit.audit(payload)

    def test_missing_fields_and_invalid_collections_are_rejected(self):
        invalid = [None, [], {}, {"pairs": [], "ramps": []}, {"pairs": None}, {"ramps": {}},
                   {"pairs": [None]}, {"pairs": [{"id": "x", "foreground": "#fff"}]},
                   {"ramps": [{"id": "x", "colors": ["#000", "#fff"]}]}]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(color_audit.InputError):
                    color_audit.audit(payload)

    def test_ids_must_be_nonempty_strings(self):
        for identifier in (1, True, None, "", "  ", "\ud800", "\udfff"):
            for payload in ({"pairs": [pair(id=identifier)]}, {"ramps": [ramp(id=identifier)]}):
                with self.subTest(payload=payload):
                    with self.assertRaises(color_audit.InputError):
                        color_audit.audit(payload)

    def test_ramp_shape_kind_and_direction_are_validated(self):
        invalid = [ramp([]), ramp(["#000"]), ramp("#000,#fff"), ramp(kind="Sequential"),
                   ramp(kind=[]), ramp(direction="ascending"), ramp(direction=None)]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(color_audit.InputError):
                    color_audit.audit({"ramps": [value]})

    def test_input_python_payload_remains_unchanged(self):
        payload = {"pairs": [pair("#abc", minimum=2)],
                   "ramps": [ramp(["#000", "#fff", "#000"], direction="increasing")]}
        before = copy.deepcopy(payload)
        color_audit.audit(payload)
        self.assertEqual(payload, before)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        process = subprocess.run([sys.executable, "-B", str(SCRIPT), *args],
                                 capture_output=True, encoding="utf-8", check=False)
        self.assertEqual(process.stderr, "", process.stderr)
        report = json.loads(process.stdout)
        return process.returncode, report

    def test_cli_exit_codes_for_unset_pass_and_fail(self):
        for extra, expected_code, expected_status in [([], 0, "not_applicable"),
                                                      (["--minimum", "4.0"], 0, "pass"),
                                                      (["--minimum", "4.5"], 1, "fail")]:
            with self.subTest(extra=extra):
                code, report = self.run_cli("--foreground", "#777", "--background", "#fff", *extra)
                self.assertEqual(code, expected_code)
                self.assertEqual(report["pairs"][0]["status"], expected_status)

    def test_cli_usage_and_threshold_errors_are_json(self):
        invalid = [[], ["--foreground", "#fff"], ["--minimum", "4.5"],
                   ["--foreground", "#fff", "--background", "#000", "--minimun", "4.5"],
                   ["--foreground"], ["--input", "missing.json", "--foreground", "#000"],
                   ["--foreground", "#fff", "--background", "#000", "--minim", "4.5"]]
        for minimum in ("NaN", "Infinity", "-1", "0", "22", "abc"):
            invalid.append(["--foreground", "#fff", "--background", "#000", "--minimum", minimum])
        for args in invalid:
            with self.subTest(args=args):
                code, report = self.run_cli(*args)
                self.assertEqual(code, 2)
                self.assertEqual(report["status"], "invalid_input")
                self.assertNotIn("pairs", report)

    def test_unicode_path_ids_and_input_bytes_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="颜色审计-") as directory:
            path = Path(directory) / "色值 输入.json"
            contents = json.dumps({"pairs": [pair(id="中文 🎨", minimum=4.5)],
                                   "ramps": [ramp(["#000", "#fff", "#777"], id="顺序色阶", direction="increasing")]},
                                  ensure_ascii=False, indent=3).encode("utf-8")
            path.write_bytes(contents)
            before = path.stat()
            code, report = self.run_cli("--input", str(path))
            self.assertEqual(code, 1)
            self.assertEqual(report["pairs"][0]["id"], "中文 🎨")
            self.assertEqual(report["ramps"][0]["id"], "顺序色阶")
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), hashlib.sha256(contents).digest())
            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), [path.name])

    def test_invalid_json_does_not_yield_partial_measurements(self):
        contents = ["{bad", '{"pairs":[{"id":"x","foreground":"#000","background":"#fff","minimum":NaN}]}',
                    '{"pairs":[],"pairs":[]}',
                    '{"pairs":[{"id":"x","foreground":"#000","background":"#fff","minimum":1e999}]}',
                    json.dumps({"pairs": [pair(), pair("#12345")]})]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            for contents_text in contents:
                with self.subTest(contents=contents_text):
                    path.write_text(contents_text, encoding="utf-8")
                    code, report = self.run_cli("--input", str(path))
                    self.assertEqual(code, 2)
                    self.assertEqual(report["status"], "invalid_input")
                    self.assertNotIn("pairs", report)
                    self.assertEqual(path.read_text(encoding="utf-8"), contents_text)

    def test_missing_file_and_invalid_encoding_are_reported_as_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            code, report = self.run_cli("--input", str(path))
            self.assertEqual(code, 2)
            path.write_bytes(b"\xff\xfe\x00")
            code, report = self.run_cli("--input", str(path))
            self.assertEqual(code, 2)
            self.assertEqual(report["diagnostics"][0]["path"], "cli.input")

    def test_unpaired_surrogate_ids_and_error_messages_remain_json(self):
        payloads = [{"pairs": [pair(id="\ud800")]},
                    {"ramps": [ramp(id="\udfff")]},
                    {"pairs": [pair()], "\ud800": True}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-unicode.json"
            for payload in payloads:
                with self.subTest(payload=repr(payload)):
                    contents = json.dumps(payload, ensure_ascii=True)
                    path.write_text(contents, encoding="utf-8")
                    code, report = self.run_cli("--input", str(path))
                    self.assertEqual(code, 2)
                    self.assertEqual(report["status"], "invalid_input")
                    self.assertNotIn("pairs", report)
                    self.assertEqual(path.read_text(encoding="utf-8"), contents)


if __name__ == "__main__":
    unittest.main()
