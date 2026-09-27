"""Offline geometry and current-runtime compatibility checks; no CAD writes."""

import contextlib
from decimal import Decimal
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import panel_plan as panel


HERE = Path(__file__).resolve().parent
PARAMETERS = HERE.parent / "assets" / "panel-parameters.json"
RUNTIME_PATH = Path(os.environ.get(
    "CAD_PANEL_CORE_PATH", str(HERE.parents[2] / "runtime" / "mcp" / "cad_core.py")))


def sample(**updates):
    parameters = json.loads(PARAMETERS.read_text(encoding="utf-8"))
    parameters.update(updates)
    return parameters


class PanelGeometryTests(unittest.TestCase):
    def test_independent_numeric_coordinates_dimensions_and_counts(self):
        template = panel.generate(sample())
        plan = template["plan"]
        boundary, *remaining = plan["operations"]
        self.assertEqual(boundary["p"], [100, -50, 600, 400])
        holes = [op for op in remaining if op["type"] == "circle"]
        self.assertEqual(len(plan["operations"]), 16)
        self.assertEqual(len(holes), 15)
        expected = {(x, y, 10) for x in (200, 300, 400, 500, 600) for y in (50, 150, 250)}
        self.assertEqual({tuple(hole["p"]) for hole in holes}, expected)
        actual_edges, actual_gaps = [], []
        for index, hole in enumerate(holes):
            x, y, radius = hole["p"]
            actual_edges.extend([x - radius - 100, 700 - x - radius,
                                 y - radius + 50, 350 - y - radius])
            for other in holes[index + 1:]:
                ox, oy, other_radius = other["p"]
                actual_gaps.append(math.hypot(x - ox, y - oy) - radius - other_radius)
        self.assertEqual(min(actual_edges), 90)
        self.assertEqual(min(actual_gaps), 80)
        self.assertEqual(template["checks"]["minimum_actual_edge_clearance"], 90)
        self.assertEqual(template["checks"]["minimum_actual_hole_clearance"], 80)
        self.assertEqual(template["checks"]["width"], 600)
        self.assertEqual(template["checks"]["height"], 400)
        self.assertEqual({op["type"] for op in plan["operations"]}, {"rect", "circle"})

    def test_layer_completeness_and_unique_stable_operation_ids(self):
        plan = panel.generate(sample())["plan"]
        layers = {item["name"] for item in plan["layers"]}
        self.assertEqual(set(plan["required_layers"]), layers)
        self.assertEqual({op["layer"] for op in plan["operations"]}, layers)
        ids = [op["id"] for op in plan["operations"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("panel-2d/hole/r0003/c0005", ids)
        self.assertEqual(ids, [op["id"] for op in panel.generate(sample(diameter=22))["plan"]["operations"]])

    def test_exact_boundary_and_hole_clearance_accepted(self):
        plan = panel.generate(sample(min_edge_clearance=90, min_hole_clearance=80))
        self.assertEqual(plan["checks"]["edge_clearances"]["right"], 90)

    def test_single_hole_has_no_invented_neighbour_clearance(self):
        plan = panel.generate(sample(rows=1, columns=1, pitch_x=1, pitch_y=1))
        self.assertIsNone(plan["checks"]["minimum_actual_hole_clearance"])
        self.assertEqual(len(plan["plan"]["operations"]), 2)

    def test_mm_cm_m_scale_consistency(self):
        reference = panel.generate(sample())["plan"]
        for unit, divisor in (("cm", 10), ("m", 1000)):
            parameters = sample(unit=unit)
            for key in panel.LENGTH_FIELDS:
                parameters[key] = Decimal(str(parameters[key])) / divisor
            parameters["origin"] = [Decimal(str(v)) / divisor for v in parameters["origin"]]
            plan = panel.generate(parameters)["plan"]
            for original, scaled in zip(reference["operations"], plan["operations"]):
                for expected, actual in zip(original["p"], scaled["p"]):
                    self.assertAlmostEqual(expected, actual * divisor, places=9)
            self.assertAlmostEqual(reference["tolerance"], plan["tolerance"] * divisor, places=12)

    def test_deterministic_canonical_provenance_fingerprint(self):
        parameters = sample()
        plan = panel.generate(parameters)
        self.assertEqual(plan, panel.generate(dict(reversed(list(parameters.items())))))
        self.assertEqual(plan, panel.generate(sample(width=600.0, origin=[100.0, -50.0])))
        provenance = plan["provenance"]
        payload = {"generator": provenance["generator"], "version": provenance["generator_version"],
                   "component_id": plan["component_id"], "parameters": plan["parameters"], "plan": plan["plan"]}
        self.assertEqual(plan["parameters"], parameters)
        independently_encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.assertEqual(hashlib.sha256(independently_encoded).hexdigest(), provenance["template_sha256"])
        self.assertEqual(plan["parameter_sha256"], hashlib.sha256(json.dumps(
            plan["parameters"], sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest())
        for change in ({"diameter": 22}, {"origin": [101, -50]}, {"min_edge_clearance": 41}):
            changed = panel.generate(sample(**change))
            self.assertNotEqual(provenance["template_sha256"], changed["provenance"]["template_sha256"])
            self.assertNotEqual(plan["parameter_sha256"], changed["parameter_sha256"])

    def test_invalid_fields_and_shapes(self):
        parameters = sample()
        del parameters["width"]
        cases = [parameters, sample(unexpected=1), sample(unit="inch"), sample(unit=True),
                 sample(origin=[1]), sample(origin="0,0"), sample(origin=[1, 2, 3]), [], None]
        for parameters in cases:
            with self.subTest(parameters=parameters), self.assertRaises(panel.ParameterError):
                panel.generate(parameters)

    def test_bad_numbers_and_nonpositive_values_rejected(self):
        for key in panel.LENGTH_FIELDS:
            for value in (0, -1, True, "20", None, float("nan"), float("inf"), -float("inf")):
                with self.subTest(key=key, value=value), self.assertRaises(panel.ParameterError):
                    panel.generate(sample(**{key: value}))
        for key in ("rows", "columns"):
            for value in (0, -1, True, 2.0, "2", float("nan")):
                with self.subTest(key=key, value=value), self.assertRaises(panel.ParameterError):
                    panel.generate(sample(**{key: value}))
        for value in (True, "1", float("nan"), float("inf")):
            with self.subTest(origin=value), self.assertRaises(panel.ParameterError):
                panel.generate(sample(origin=[value, 0]))

    def test_outside_overlap_and_below_clearances_rejected(self):
        cases = [{"offset_x": 9}, {"offset_y": 9}, {"width": 500}, {"height": 300},
                 {"diameter": 101}, {"pitch_x": 10}, {"pitch_y": 10},
                 {"min_edge_clearance": 90.000000001}, {"min_hole_clearance": 80.000000001}]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(panel.ParameterError):
                panel.generate(sample(**changes))

    def test_operation_cap_includes_boundary(self):
        plan = panel.generate(sample(rows=1, columns=1999, width=200000))
        self.assertEqual(len(plan["plan"]["operations"]), 2000)
        with self.assertRaises(panel.ParameterError):
            panel.generate(sample(rows=1, columns=2000, width=300000))

    def test_unsafe_derived_coordinates_and_ranges_rejected(self):
        for changes in ({"origin": [1e20, 0]}, {"width": 10 ** 400},
                        {"offset_x": Decimal("100.0000000000000000001")}):
            with self.subTest(changes=changes), self.assertRaises(panel.ParameterError):
                panel.generate(sample(**changes))

    def test_bridge_minimum_tolerance_and_circle_radius_limit(self):
        parameters = sample(origin=[0, 0], width=1e-8, height=1e-8, rows=1, columns=1,
                            diameter=4e-9, offset_x=5e-9, offset_y=5e-9,
                            min_edge_clearance=1e-10, min_hole_clearance=1e-10)
        self.assertEqual(panel.generate(parameters)["plan"]["tolerance"], 1e-9)
        parameters["diameter"] = 2e-9
        with self.assertRaises(panel.ParameterError):
            panel.generate(parameters)

    def test_template_has_no_live_guards(self):
        plan = panel.generate(sample())
        for guard in ("expected_document_id", "expected_revision", "idempotency_key", "dry_run"):
            self.assertNotIn(guard, plan["plan"])
        self.assertEqual(plan["provenance"]["status"], "template_requires_live_guards")


class PanelCliTests(unittest.TestCase):
    def test_stdout_is_deterministic_json(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(panel.main(["--params", str(PARAMETERS)]), 0)
        self.assertEqual(output.getvalue(), panel.canonical_json(panel.generate(sample())) + "\n")

    def test_create_only_and_failure_preserve_existing_file(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temporary:
            output = Path(temporary) / "plan.json"
            args = ["--params", str(PARAMETERS), "--out", str(output)]
            self.assertEqual(panel.main(args), 0)
            before = output.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(panel.main(args), 2)
            self.assertEqual(output.read_bytes(), before)

    def test_bad_input_does_not_create_output(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temporary:
            source, output = Path(temporary) / "bad.json", Path(temporary) / "plan.json"
            for text in ('{"width": NaN}', '{"width":1,"width":2}', '{"width":Infinity}'):
                source.write_text(text, encoding="utf-8")
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(panel.main(["--params", str(source), "--out", str(output)]), 2)
                self.assertFalse(output.exists())


class ExistingRuntimeCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not RUNTIME_PATH.is_file():
            raise AssertionError(f"Existing runtime source not found: {RUNTIME_PATH}")
        spec = importlib.util.spec_from_file_location("cad_core_panel_offline", RUNTIME_PATH)
        cls.core = importlib.util.module_from_spec(spec)
        # Import currently has no top-level connection calls; fail closed if that changes.
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("Network forbidden")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("Process launch forbidden")):
            spec.loader.exec_module(cls.core)

    def test_existing_runtime_rejects_template_before_any_state_or_io(self):
        with mock.patch.object(self.core, "state", side_effect=AssertionError("No state lookup allowed")), \
                mock.patch.object(self.core, "_read", side_effect=AssertionError("No I/O allowed")):
            with self.assertRaises(self.core.CadError) as caught:
                self.core.apply_plan(panel.generate(sample())["plan"])
        self.assertEqual(caught.exception.code, "missing_idempotency_key")

    def test_existing_runtime_rejects_missing_document_and_revision(self):
        plan = panel.generate(sample())["plan"]
        plan["dry_run"] = True
        with mock.patch.object(self.core, "state", side_effect=AssertionError("No state lookup allowed")):
            with self.assertRaises(self.core.CadError) as caught:
                self.core.apply_plan(plan)
            self.assertEqual(caught.exception.code, "missing_expected_document_id")
            plan["expected_document_id"] = "OFFLINE-TEST-DOCUMENT"
            with self.assertRaises(self.core.CadError) as caught:
                self.core.apply_plan(plan)
            self.assertEqual(caught.exception.code, "missing_expected_revision")

    def test_existing_runtime_offline_dry_run_shape_and_no_setup(self):
        plan = panel.generate(sample())["plan"]
        plan.update(dry_run=True, expected_document_id="OFFLINE-TEST-DOCUMENT", expected_revision=7)
        state = {"has_document": True, "document_id": "OFFLINE-TEST-DOCUMENT", "revision": 7,
                 "units": "Millimeters"}
        with mock.patch.object(self.core, "state", return_value=state), \
                mock.patch.object(self.core, "_read", return_value={"status": "dry_run", "ok": True}) as read, \
                mock.patch.object(self.core, "set_units", side_effect=AssertionError("No setup")), \
                mock.patch.object(self.core, "set_layer", side_effect=AssertionError("No setup")), \
                mock.patch.object(self.core, "set_text_style", side_effect=AssertionError("No setup")):
            result = self.core.apply_plan(plan)
        self.assertEqual(result["status"], "dry_run")
        read.assert_called_once()
        self.assertEqual(read.call_args.args[0], "batch")
        payload = read.call_args.args[1]
        self.assertTrue(payload["dry_run"])
        self.assertTrue(payload["atomic"])
        self.assertEqual(payload["operations"], plan["operations"])
        self.assertEqual(payload["expected_document_id"], "OFFLINE-TEST-DOCUMENT")
        self.assertEqual(payload["expected_revision"], 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
