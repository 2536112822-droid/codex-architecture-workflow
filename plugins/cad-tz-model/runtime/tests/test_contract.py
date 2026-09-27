import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


RUNTIME = Path(__file__).resolve().parents[1]
MCP = RUNTIME / "mcp"
sys.path.insert(0, str(MCP))

import cad_core

SPEC = importlib.util.spec_from_file_location("cad_mcp_server_contract", MCP / "server.py")
server = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(server)


class CadRuntimeContractTests(unittest.TestCase):
    def test_tool_surface_is_typed_and_has_no_lisp(self):
        names = {tool["name"] for tool in server.TOOLS}
        for required in {
            "cad_discover", "cad_use_instance", "cad_state", "cad_apply_plan",
            "cad_query", "cad_validate", "cad_screenshot", "cad_save_as",
            "cad_command", "cad_job", "tz_status", "tz_cmd",
        }:
            self.assertIn(required, names)
        self.assertNotIn("cad_lisp", names)

    def test_every_write_gets_document_and_revision_guards(self):
        snapshot = {"has_document": True, "document_id": "doc-1", "revision": 7}
        with mock.patch.object(cad_core, "state", return_value=snapshot):
            guarded, returned = cad_core._guard({"name": "A-WALL"})
        self.assertEqual(returned, snapshot)
        self.assertEqual(guarded["expected_document_id"], "doc-1")
        self.assertEqual(guarded["expected_revision"], 7)

    def test_commit_requires_idempotency_key(self):
        with self.assertRaises(cad_core.CadError) as caught:
            cad_core.apply_plan({"unit": "mm", "operations": [{"type": "line", "p": [0, 0, 1, 1]}]})
        self.assertEqual(caught.exception.code, "missing_idempotency_key")

    def test_apply_plan_dry_runs_then_commits_atomically_and_validates(self):
        snapshot = {
            "status": "ok", "has_document": True, "document_id": "doc-1",
            "revision": 7, "units": "Millimeters",
        }
        calls = []

        def fake_read(api, payload=None, timeout=60):
            calls.append((api, payload))
            if api == "batch":
                return {"ok": True, "dry_run": bool(payload.get("dry_run"))}
            if api == "validate":
                return {"ok": True, "issues": []}
            raise AssertionError(f"unexpected endpoint: {api}")

        plan = {
            "unit": "mm",
            "expected_document_id": "doc-1",
            "expected_revision": 7,
            "idempotency_key": "contract-plan-v1",
            "operations": [{"id": "l1", "type": "line", "p": [0, 0, 100, 0]}],
        }
        with mock.patch.object(cad_core, "state", return_value=snapshot), \
                mock.patch.object(cad_core, "_read", side_effect=fake_read):
            result = cad_core.apply_plan(plan)

        batches = [payload for api, payload in calls if api == "batch"]
        self.assertEqual(len(batches), 2)
        self.assertTrue(batches[0]["dry_run"])
        self.assertFalse(batches[1]["dry_run"])
        self.assertTrue(batches[1]["atomic"])
        self.assertEqual(batches[1]["idempotency_key"], "contract-plan-v1")
        self.assertEqual(batches[0]["idempotency_key"], "contract-plan-v1")
        self.assertEqual(
            batches[0]["idempotency_fingerprint"], batches[1]["idempotency_fingerprint"]
        )
        self.assertEqual(batches[1]["expected_document_id"], "doc-1")
        self.assertEqual(result["status"], "committed")

    def test_dry_run_never_applies_setup_changes(self):
        snapshot = {
            "status": "ok", "has_document": True, "document_id": "doc-1",
            "revision": 7, "units": "Meters",
        }
        plan = {
            "unit": "mm", "dry_run": True,
            "expected_document_id": "doc-1", "expected_revision": 7,
            "layers": [{"name": "A-WALL", "color": 1}],
            "text_style": {"name": "hz"},
            "operations": [{"type": "line", "p": [0, 0, 100, 0]}],
        }
        with mock.patch.object(cad_core, "state", return_value=snapshot), \
                mock.patch.object(cad_core, "_read", return_value={"ok": True, "status": "dry_run"}), \
                mock.patch.object(cad_core, "set_units") as units, \
                mock.patch.object(cad_core, "set_layer") as layer, \
                mock.patch.object(cad_core, "set_text_style") as text_style:
            result = cad_core.apply_plan(plan)
        self.assertEqual(result["status"], "dry_run")
        units.assert_not_called()
        layer.assert_not_called()
        text_style.assert_not_called()

    def test_stale_revision_can_replay_without_setup_writes(self):
        snapshot = {
            "status": "ok", "has_document": True, "document_id": "doc-1",
            "revision": 9, "units": "Meters",
        }
        plan = {
            "unit": "mm", "expected_document_id": "doc-1", "expected_revision": 7,
            "idempotency_key": "lost-response-v1",
            "layers": [{"name": "A-WALL"}],
            "operations": [{"type": "line", "p": [0, 0, 100, 0]}],
        }

        def fake_read(api, payload=None, timeout=60):
            if api == "batch":
                self.assertTrue(payload["dry_run"])
                self.assertEqual(payload["expected_revision"], 7)
                return {"ok": True, "status": "idempotent_replay", "skipped": True}
            if api == "validate":
                return {"ok": True, "issues": []}
            raise AssertionError(f"unexpected endpoint: {api}")

        with mock.patch.object(cad_core, "state", return_value=snapshot), \
                mock.patch.object(cad_core, "_read", side_effect=fake_read), \
                mock.patch.object(cad_core, "set_units") as units, \
                mock.patch.object(cad_core, "set_layer") as layer:
            result = cad_core.apply_plan(plan)
        self.assertEqual(result["status"], "idempotent_replay")
        self.assertEqual(result["setup"], [])
        units.assert_not_called()
        layer.assert_not_called()

    def test_offset_side_coordinates_become_a_typed_point(self):
        with mock.patch.object(cad_core, "_write", return_value={"ok": True}) as write:
            cad_core.edit("offset", handle="A1", distance=200, side_x=10, side_y=20)
        payload = write.call_args.args[1]
        self.assertEqual(payload["side_point"], [10.0, 20.0])
        self.assertNotIn("side_x", payload)
        self.assertNotIn("side_y", payload)


if __name__ == "__main__":
    unittest.main()
