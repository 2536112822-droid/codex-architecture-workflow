import json
import subprocess
import unittest
from pathlib import Path


RUNTIME = Path(__file__).resolve().parents[1]
RUBY = RUNTIME / "sketchup" / "su_server.rb"
NODE = RUNTIME / "mcp" / "server.js"


class SketchUpRuntimeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ruby = RUBY.read_text(encoding="utf-8")
        cls.node = NODE.read_text(encoding="utf-8")

    def test_unit_precision_uses_supported_sketchup_option(self):
        self.assertIn('o["LengthPrecision"]', self.ruby)
        self.assertNotIn('o["Precision"]', self.ruby)
        self.assertIn('"internal_length_unit" => "inch"', self.ruby)

    def test_structured_plan_has_revision_idempotency_and_transaction(self):
        self.assertIn('plan["expected_revision"]', self.ruby)
        self.assertIn('plan["idempotency_key"]', self.ruby)
        self.assertIn('request:#{request_key}:fingerprint', self.ruby)
        self.assertIn("def canonical_plan_value", self.ruby)
        self.assertIn("value.keys.sort_by(&:to_s)", self.ruby)
        self.assertLess(
            self.ruby.index('applied_revision = model.get_attribute'),
            self.ruby.index('if expected.to_i != current_revision'),
        )
        self.assertIn('transaction(plan["label"]', self.ruby)
        self.assertIn('"/call"', self.ruby)

    def test_json_error_sanitizer_accepts_frozen_ruby_strings(self):
        self.assertIn('s.to_s.dup.force_encoding("UTF-8").scrub', self.ruby)

    def test_render_capture_restores_visual_and_edge_state(self):
        self.assertIn("def with_temporarily_hidden_edges", self.ruby)
        self.assertIn("m.abort_operation", self.ruby)
        self.assertIn("def with_visual_state", self.ruby)
        self.assertIn("restore_visual_state(state)", self.ruby)
        self.assertIn("def camera_states_equivalent?", self.ruby)
        self.assertIn("camera_states_equivalent?(state[\"camera\"], after[\"camera\"])", self.ruby)

    def test_architectural_bounds_translate_sketchup_axis_names(self):
        self.assertIn('"width" => convert.call(bb.width)', self.ruby)
        self.assertIn('"depth" => convert.call(bb.height)', self.ruby)
        self.assertIn('"height" => convert.call(bb.depth)', self.ruby)

    def test_mcp_exposes_the_small_typed_surface(self):
        requests = "\n".join(
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "contract-test", "version": "1"},
                        },
                    }
                ),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
                "",
            ]
        )
        result = subprocess.run(
            ["node", str(NODE)], input=requests, text=True, encoding="utf-8",
            errors="strict", capture_output=True,
            timeout=15, check=True,
        )
        responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        tools_response = next(item for item in responses if item.get("id") == 2)
        names = {tool["name"] for tool in tools_response["result"]["tools"]}
        expected = {
            "su_ping", "su_capabilities", "su_info", "su_inspect_model",
            "su_validate_model", "su_apply_plan", "su_bounds", "su_capture_views",
            "su_screenshot", "su_render", "su_save", "su_selftest", "su_eval",
        }
        self.assertEqual(names, expected)
        self.assertNotIn("su_reset", names)


if __name__ == "__main__":
    unittest.main()
