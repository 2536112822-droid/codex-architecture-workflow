import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import artifact_freshness as af


class ArtifactFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.contract = {"project_id": "test", "revision": 1, "title": "test",
                         "units": "mm", "coordinate_reference": {"kind": "local"},
                         "brief": {"known": [], "inferred": [], "unknown": []},
                         "levels": [], "elements": [], "views": [], "evidence": [],
                         "qa": [], "history": [], "artifacts": []}
        for ident, deps in (("A", []), ("B", ["A"]), ("C", ["B"]), ("D", [])):
            (self.root / (ident + ".dat")).write_bytes(ident.encode())
            self.contract["artifacts"].append({"id": ident, "path": ident + ".dat", "stage": "model",
                                                "source_artifact_ids": deps, "source_revision": 1,
                                                "status": "verified"})
        self.snapshot = af.capture(self.contract, self.root)

    def check(self, contract=None, snapshot=None, root=None):
        return af.compare(self.contract if contract is None else contract,
                          self.snapshot if snapshot is None else snapshot,
                          self.root if root is None else root)

    def state(self, ident, report=None):
        return (self.check() if report is None else report)["artifacts"][ident]["state"]

    def test_unchanged_is_only_a_baseline_observation(self):
        self.assertEqual(self.check()["comparison"], "unchanged_since_snapshot")
        self.assertEqual(self.check()["artifacts"]["A"]["declared_status"], "verified")
        self.assertIn("No claim about active", self.check()["scope"])

    def test_same_name_same_size_content_change_propagates_chain_not_independent_d(self):
        (self.root / "A.dat").write_bytes(b"Z")
        report = self.check()
        self.assertEqual(self.state("A", report), "affected")
        self.assertEqual(report["artifacts"]["C"]["affected_by"], ["A"])
        self.assertEqual(self.state("D", report), "unchanged_since_snapshot")

    def test_global_revision_title_history_qa_do_not_invalidate(self):
        self.contract.update(revision=99, title="renamed", history=[{"revision": 99}], qa=[{"gate": "x"}])
        self.assertEqual(self.check()["comparison"], "unchanged_since_snapshot")

    def test_context_changes_fail_closed_for_all(self):
        for key, value in (("units", "m"), ("elements", [{"id": "wall", "height": 99}]),
                           ("evidence", [{"id": "weather", "path": "new.csv"}])):
            contract = copy.deepcopy(self.contract)
            contract[key] = value
            report = self.check(contract=contract)
            self.assertIn("project_context_changed", report["errors"])
            self.assertTrue(all(row["state"] == "unverifiable" for row in report["artifacts"].values()))

    def test_missing_context_is_not_a_clean_comparison(self):
        self.contract.pop("units")
        snapshot = af.capture(self.contract, self.root)
        self.assertIn("project_context_incomplete", snapshot["errors"])
        self.assertEqual(self.check(snapshot=snapshot)["comparison"], "attention_required")

    def test_source_revision_change(self):
        self.contract["artifacts"][0]["source_revision"] = 2
        report = self.check()
        self.assertIn("source_revision_changed", report["artifacts"]["A"]["reasons"])
        self.assertEqual(self.state("C", report), "affected")
        self.assertEqual(self.state("D", report), "unchanged_since_snapshot")

    def test_add_dependency_uses_new_edges(self):
        self.contract["artifacts"][3]["source_artifact_ids"] = ["C"]
        (self.root / "A.dat").write_bytes(b"new")
        report = self.check()
        self.assertIn("dependencies_changed", report["artifacts"]["D"]["reasons"])
        self.assertIn("A", report["artifacts"]["D"]["affected_by"])

    def test_removed_dependency_uses_old_edges(self):
        self.contract["artifacts"][1]["source_artifact_ids"] = []
        (self.root / "A.dat").write_bytes(b"new")
        report = self.check()
        self.assertIn("A", report["artifacts"]["B"]["affected_by"])
        self.assertIn("A", report["artifacts"]["C"]["affected_by"])

    def test_added_and_removed_artifacts(self):
        self.contract["artifacts"].pop(0)
        self.contract["artifacts"].append({"id": "E", "path": "D.dat", "source_revision": 1,
                                           "stage": "report", "status": "draft", "source_artifact_ids": []})
        report = self.check()
        self.assertIn("artifact_removed", report["artifacts"]["A"]["reasons"])
        self.assertIn("artifact_added", report["artifacts"]["E"]["reasons"])
        self.assertEqual(self.state("B", report), "unverifiable")
        self.assertEqual(self.state("C", report), "affected")

    def test_unknown_old_contract_is_not_reusable(self):
        self.contract["artifacts"][0].pop("source_artifact_ids")
        snapshot = af.capture(self.contract, self.root)
        report = self.check(snapshot=snapshot)
        self.assertEqual(self.state("A", report), "unverifiable")
        self.assertIn("baseline:dependencies_unknown", report["artifacts"]["A"]["reasons"])
        self.assertEqual(self.state("C", report), "affected")
        self.assertEqual(self.state("D", report), "unchanged_since_snapshot")

    def test_root_relocation_preserves_relative_identity(self):
        moved = Path(self.temp.name) / "moved"
        shutil.copytree(self.root, moved)
        self.assertEqual(self.check(root=moved)["comparison"], "unchanged_since_snapshot")

    def test_path_change_with_equal_bytes_is_reported(self):
        shutil.copyfile(self.root / "A.dat", self.root / "renamed.dat")
        self.contract["artifacts"][0]["path"] = "renamed.dat"
        report = self.check()
        self.assertIn("path_changed", report["artifacts"]["A"]["reasons"])
        self.assertEqual(self.state("C", report), "affected")

    def test_external_absolute_file_is_read_only(self):
        external = Path(self.temp.name) / "outside.dat"
        external.write_bytes(b"outside")
        self.contract["artifacts"][0]["path"] = str(external)
        snapshot = af.capture(self.contract, self.root)
        self.assertEqual(self.check(snapshot=snapshot)["comparison"], "unchanged_since_snapshot")
        self.assertEqual(external.read_bytes(), b"outside")

    def test_cycle_and_self_cycle_never_pass(self):
        for deps in (["C"], ["A"]):
            self.contract["artifacts"][0]["source_artifact_ids"] = deps
            snapshot = af.capture(self.contract, self.root)
            self.assertIn("dependency_cycle", snapshot["artifacts"]["A"]["errors"])
            self.assertEqual(self.check(snapshot=snapshot)["comparison"], "attention_required")

    def test_missing_file_never_passes_even_if_missing_at_baseline(self):
        (self.root / "A.dat").unlink()
        snapshot = af.capture(self.contract, self.root)
        self.assertEqual(self.state("A", self.check(snapshot=snapshot)), "unverifiable")
        self.assertIn("file_missing", snapshot["artifacts"]["A"]["errors"])

    def test_bad_paths_are_not_read(self):
        for value in (str(self.root), "https://example.com/x", "file:///tmp/x", "\\\\server\\share\\x", "NUL"):
            self.contract["artifacts"][0]["path"] = value
            snapshot = af.capture(self.contract, self.root)
            self.assertIsNone(snapshot["artifacts"]["A"]["file"])
            self.assertEqual(self.state("A", self.check(snapshot=snapshot)), "unverifiable")

    def test_duplicate_id_blocks_all(self):
        self.contract["artifacts"].append(copy.deepcopy(self.contract["artifacts"][0]))
        report = self.check()
        self.assertIn("duplicate_artifact_id:A", report["errors"])
        self.assertEqual(self.state("D", report), "unverifiable")

    def test_nonfinite_or_malformed_metadata_fails_closed(self):
        for field, value in (("parameter", float("nan")), ("parameter", float("inf")),
                             ("source_revision", True), ("status", []), ("source_artifact_ids", [3])):
            contract = copy.deepcopy(self.contract)
            contract["artifacts"][0][field] = value
            self.assertEqual(self.check(contract=contract)["comparison"], "attention_required")

    def test_file_change_during_read_is_detected(self):
        original = af.os.fstat
        count = 0
        def changed(fd):
            nonlocal count
            count += 1
            if count == 2:
                with (self.root / "A.dat").open("ab") as handle:
                    handle.write(b"changed-during-read")
            return original(fd)
        with patch.object(af.os, "fstat", side_effect=changed):
            result = af.capture(self.contract, self.root)
        self.assertIn("file_changed_during_read", result["artifacts"]["A"]["errors"])

    def test_snapshot_integrity_corruption_cannot_pass(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["artifacts"]["A"]["file"]["sha256"] = "0" * 64
        self.assertIn("snapshot_integrity_mismatch", self.check(snapshot=snapshot)["errors"])

    def test_preexisting_failed_status_is_preserved_not_promoted(self):
        self.contract["artifacts"][0]["status"] = "failed"
        snapshot = af.capture(self.contract, self.root)
        row = self.check(snapshot=snapshot)["artifacts"]["A"]
        self.assertEqual(row["state"], "unchanged_since_snapshot")
        self.assertEqual(row["declared_status"], "failed")

    def invoke(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = af.main(args)
        return code, json.loads(output.getvalue())

    def contract_file(self):
        path = self.root / "architecture-project.json"
        path.write_text(json.dumps(self.contract), encoding="utf-8")
        return path

    def test_cli_snapshot_exclusive_and_check_writes_nothing(self):
        contract_path = self.contract_file()
        snapshot_path = self.root / "baseline.json"
        common = ("--contract", str(contract_path), "--root", str(self.root))
        self.assertEqual(self.invoke("snapshot", *common, "--out", str(snapshot_path))[0], 0)
        baseline_bytes = snapshot_path.read_bytes()
        self.assertEqual(self.invoke("snapshot", *common, "--out", str(snapshot_path))[0], 2)
        self.assertEqual(snapshot_path.read_bytes(), baseline_bytes)
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.iterdir()}
        self.assertEqual(self.invoke("check", *common, "--snapshot", str(snapshot_path))[0], 0)
        after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.iterdir()}
        self.assertEqual(before, after)

    def test_cli_refuses_output_equal_to_even_missing_input(self):
        (self.root / "A.dat").unlink()
        contract_path = self.contract_file()
        code, result = self.invoke("snapshot", "--contract", str(contract_path), "--root", str(self.root),
                                   "--out", str(self.root / "A.dat"))
        self.assertEqual(code, 2)
        self.assertIn("snapshot_output_is_input", result["errors"])
        self.assertFalse((self.root / "A.dat").exists())

    def test_cli_rejects_duplicate_json_keys_and_nonfinite_json(self):
        contract_path = self.root / "bad.json"
        for payload in ('{"project_id":"x","project_id":"y"}', '{"x":NaN}', '{"x":1e999}'):
            contract_path.write_text(payload, encoding="utf-8")
            code, _ = self.invoke("snapshot", "--contract", str(contract_path), "--root", str(self.root),
                                  "--out", str(self.root / "not-created.json"))
            self.assertEqual(code, 2)
            # Failed captures may be saved as evidence, but can never be clean baselines.
            candidate = self.root / "not-created.json"
            if candidate.exists():
                self.assertTrue(json.loads(candidate.read_text(encoding="utf-8"))["errors"])
                candidate.unlink()


if __name__ == "__main__":
    unittest.main()
