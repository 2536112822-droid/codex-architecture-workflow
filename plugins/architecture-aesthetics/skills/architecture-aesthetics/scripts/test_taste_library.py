#!/usr/bin/env python3
"""Isolated behavior tests. Never reads or writes the user's actual library."""
import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from taste_library import Library, digest, file_hash, read_json, preview_learning


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="architecture-taste-tests-")
        self.root = Path(self.temp.name)
        self.library = Library(self.root / "审美 库", initialize=True)

    def tearDown(self):
        self.library.close()
        self.temp.cleanup()

    def case(self, project="global", domain="render", source="合成测试参考 混凝土", **kwargs):
        return self.library.import_case(project=project, domain=domain, source_note=source, **kwargs)["case"]

    def rule(self, case, scope=None, statement="混凝土要保留自然纹理", **kwargs):
        data = {"scope": scope or case["project"], "domain": "render", "dimension": "material",
                "statement": statement, "rationale": "合成测试规则，用于验证存储逻辑",
                "applies_when": ["材料展示"], "exclude_when": ["标准技术图纸"], "case_ids": [case["id"]]}
        data.update(kwargs)
        return self.library.create_rule(data)

    def analysis(self, text="合成测试文字，不代表实际图片观察"):
        return {"observations": [{"dimension": "material", "text": text,
                                  "evidence": "隔离测试夹具", "certainty": "unknown"}],
                "takeaways": ["测试待审"], "avoid": [], "limitations": ["未进行图片观察"]}

    def proposal(self, session="isolated-session-1", file=None):
        def aspect(identifier, text):
            return {"id": identifier, "label": text,
                    "analysis": self.analysis(text),
                    "rules": [{"domain": "render", "dimension": identifier, "statement": text,
                               "rationale": text, "applies_when": [text], "exclude_when": [text]}]}
        case = {"title": "合成测试参考", "domain": "render", "source_note": "隔离夹具 source-001"}
        if file:
            case.update(file=str(file), file_sha256=file_hash(file))
        return {"schema_version": 1, "session_id": session, "case": case,
                "aspects": [aspect("material", "保存的材料测试纹理"),
                            aspect("lighting", "UNSELECTED_LIGHTING_SENTINEL_9123")]}

    def consent(self, proposal, **kwargs):
        result = {"session_id": proposal["session_id"], "proposal_sha256": preview_learning(proposal)["proposal_sha256"],
                  "decision": "save", "selected_aspects": ["material"], "scope": "global",
                  "save_as": "preference", "archive_source": False,
                  "user_quote": "只保存材料为长期偏好，其他方面和原图不保存。"}
        result.update(kwargs)
        return result

    def test_project_isolation_and_cross_project_rule_rejection(self):
        shared, a, b = self.case(), self.case("项目 A"), self.case("项目 B")
        shared_rule, a_rule, b_rule = self.rule(shared), self.rule(a), self.rule(b)
        for rule in (shared_rule, a_rule, b_rule):
            self.library.feedback(rule["id"], "active", "确认采用这条测试偏好")
        result = self.library.search("混凝土", "项目 A", "render")
        self.assertEqual({c["id"] for c in result["cases"]}, {shared["id"], a["id"]})
        self.assertEqual({r["id"] for r in result["active_rules"]}, {shared_rule["id"], a_rule["id"]})
        self.assertEqual({c["id"] for c in self.library.search()["cases"]}, {shared["id"]})
        before = self.library.status()
        with self.assertRaises(ValueError):
            self.rule(b, scope="项目 A")
        with self.assertRaises(ValueError):
            self.rule(a, scope="global")
        self.assertEqual(before, self.library.status())

    def test_candidates_are_separate_and_retirement_removes_application(self):
        rule = self.rule(self.case())
        result = self.library.search("混凝土")
        self.assertEqual(len(result["candidate_rules"]), 1)
        self.assertEqual(result["active_rules"], [])
        with self.assertRaises(ValueError):
            self.library.feedback(rule["id"], "active", "   ")
        self.assertEqual(self.library.show_rule(rule["id"])["revision"], 1)
        quote = "  我喜欢这种材料表达，作为渲染偏好。  "
        active = self.library.feedback(rule["id"], "active", quote)
        self.assertEqual(active["feedback"][-1]["quote"], quote)
        self.assertEqual(len(self.library.search("混凝土")["active_rules"]), 1)
        self.assertEqual(self.library.search("混凝土")["candidate_rules"], [])
        self.library.feedback(rule["id"], "retired", "这个偏好已经不适用了")
        result = self.library.search("混凝土")
        self.assertEqual(result["active_rules"] + result["candidate_rules"], [])
        self.assertEqual(len(self.library.show_rule(rule["id"])["feedback"]), 2)
        self.assertTrue(self.library.doctor()["ok"])

    def test_source_deduplication_is_scoped_but_asset_bytes_are_shared(self):
        source = self.root / "原图 有空格.txt"
        source.write_bytes("保留原件：合成测试内容".encode("utf-8"))
        original = source.read_bytes()
        first = self.library.import_case(file=source, project="项目 A", domain="render")
        duplicate = self.library.import_case(file=source, project="项目 A", domain="render", note="不会静默覆盖元数据")
        other = self.library.import_case(file=source, project="项目 B", domain="render")
        another_domain = self.library.import_case(file=source, project="项目 A", domain="model")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(first["case"]["id"], duplicate["case"]["id"])
        self.assertNotEqual(first["case"]["id"], other["case"]["id"])
        self.assertNotEqual(first["case"]["id"], another_domain["case"]["id"])
        self.assertEqual(first["case"]["asset_path"], other["case"]["asset_path"])
        archived = Path(first["case"]["asset_path"])
        self.assertEqual(archived.read_bytes(), original)
        self.assertEqual(file_hash(source), first["case"]["asset_sha256"])
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.library.status()["assets"], 1)
        self.assertTrue(self.library.doctor()["ok"])
        archived.write_bytes(b"deliberate corruption in temporary test library")
        self.assertFalse(self.library.doctor()["ok"])

    def test_invalid_records_and_missing_references_do_not_pollute(self):
        case = self.case()
        before = self.library.status()
        bad = self.analysis()
        bad["observations"][0]["certainty"] = "certain"
        with self.assertRaises(ValueError):
            self.library.analyze(case["id"], bad)
        with self.assertRaises(ValueError):
            self.library.analyze("CASE-missing", self.analysis())
        with self.assertRaises(ValueError):
            self.rule(case, case_ids=[case["id"], "CASE-missing"])
        with self.assertRaises(ValueError):
            self.rule(case, domain="invalid")
        with self.assertRaises(ValueError):
            self.library.import_case(url="javascript:alert(1)")
        with self.assertRaises(ValueError):
            self.library.import_case(url="https://user:password@example.org")
        with self.assertRaises((ValueError, OSError)):
            self.library.import_case(file=self.root / "missing.png")
        with self.assertRaises(ValueError):
            self.library.import_case()
        self.assertEqual(before, self.library.status())
        self.assertEqual(list((self.library.home / "assets").iterdir()), [])
        bad_file = self.root / "坏数据.json"
        for content in ('{"x": 1, "x": 2}', '{"x": NaN}', '{bad json}'):
            bad_file.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                read_json(bad_file)

    def test_snapshot_is_frozen_complete_and_refuses_overwrite(self):
        # The supporting architecture case is outside the render-domain case
        # search, but must remain accessible as evidence for the render rule.
        case = self.case("项目 A", domain="architecture", source="测试观察来源")
        self.library.analyze(case["id"], self.analysis())
        rule = self.rule(case, statement="渲染使用克制暖光")
        self.library.feedback(rule["id"], "active", "对，这个暖光方向我喜欢")
        output = self.root / "冻结 快照.json"
        self.library.snapshot(project="项目 A", domain="render", query="暖光", out=output)
        original = output.read_bytes()
        frozen = read_json(output)
        self.assertEqual(frozen["selection"]["cases"], [])
        self.assertEqual(frozen["supporting_cases"][0]["analysis_version"], 1)
        hash_copy = copy.deepcopy(frozen)
        claimed = hash_copy.pop("snapshot_sha256")
        self.assertEqual(claimed, digest(hash_copy))
        self.library.analyze(case["id"], self.analysis("第二版测试观察"))
        self.library.feedback(rule["id"], "retired", "后续调整")
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(frozen["selection"]["active_rules"][0]["state"], "active")
        with self.assertRaises(ValueError):
            self.library.snapshot(project="项目 A", out=output)
        self.assertEqual(output.read_bytes(), original)

    def test_url_and_conversation_sources_do_not_invent_archived_images(self):
        url = self.library.import_case(url="https://example.org/design?id=1", domain="presentation")
        conversation = self.case(source="Codex 当前任务，第 2 张图片；未取得本地原文件")
        self.assertFalse(url["case"]["asset_archived"])
        self.assertFalse(conversation["asset_archived"])
        self.assertIsNone(conversation["asset_path"])
        self.assertEqual(self.library.status()["assets"], 0)
        self.assertEqual(self.library.doctor()["cases_without_archived_asset"], 2)
        export = self.root / "完整 导出.json"
        self.library.export(export)
        data = read_json(export)
        self.assertEqual(len(data["cases"]), 2)
        self.assertEqual(data["assets"], [])

    def test_duplicate_import_preserves_new_metadata_as_traceable_events(self):
        source = self.root / "重复 导入.txt"
        source.write_text("同一参考的测试字节", encoding="utf-8")
        first = self.library.import_case(file=source, project="项目 A", domain="render",
                                         title="首次标题", note="首次备注")
        second = self.library.import_case(file=source, project="项目 A", domain="render",
                                          title="新标题", note="新的晚霞偏好",
                                          url="https://example.org/reference")
        case = second["case"]
        self.assertTrue(second["duplicate"])
        self.assertTrue(second["ingest_event_added"])
        self.assertEqual(first["case"]["id"], case["id"])
        self.assertEqual(case["title"], "首次标题")
        self.assertEqual(case["note"], "首次备注")
        self.assertEqual(case["latest_metadata"]["title"], "新标题")
        self.assertEqual(case["latest_metadata"]["note"], "新的晚霞偏好")
        self.assertEqual(len(case["ingest_events"]), 2)
        for event in case["ingest_events"]:
            content = {key: event[key] for key in ("case_id", "version", "payload", "created_at")}
            self.assertEqual(event["event_sha256"], digest(content))
        unchanged = self.library.import_case(file=source, project="项目 A", domain="render",
                                             title="新标题", note="新的晚霞偏好",
                                             url="https://example.org/reference")
        self.assertFalse(unchanged["ingest_event_added"])
        omitted = self.library.import_case(file=source, project="项目 A", domain="render")
        self.assertFalse(omitted["ingest_event_added"])
        self.assertEqual(self.library.status()["cases"], 1)
        self.assertEqual(self.library.status()["ingest_events"], 2)
        matched = self.library.search("晚霞", "项目 A", "render")["cases"]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["ingest_events"], case["ingest_events"])
        snapshot = self.root / "重复来源 快照.json"
        self.library.snapshot(project="项目 A", domain="render", query="晚霞", out=snapshot)
        self.assertEqual(read_json(snapshot)["selection"]["cases"][0]["ingest_events"], case["ingest_events"])
        exported = self.root / "重复来源 导出.json"
        self.library.export(exported)
        self.assertEqual(read_json(exported)["cases"][0]["ingest_events"], case["ingest_events"])
        self.assertTrue(self.library.doctor()["ok"])

    def test_stored_hashes_detect_rule_feedback_and_ingest_content_changes(self):
        case = self.case()
        rule = self.rule(case)
        original_quote = "  原始用户反馈，保留首尾空格。  "
        active = self.library.feedback(rule["id"], "active", original_quote)
        self.assertEqual(active["feedback"][-1]["quote"], original_quote)
        self.assertEqual(active["rule_content_sha256"], digest(active["payload"]))
        self.assertTrue(self.library.doctor()["ok"])
        original_payload = self.library.db.execute("SELECT payload FROM rules WHERE id=?", (rule["id"],)).fetchone()[0]
        changed = json.loads(original_payload)
        changed["statement"] += " 被意外改写"
        with self.library.db:
            self.library.db.execute("UPDATE rules SET payload=? WHERE id=?", (json.dumps(changed, ensure_ascii=False), rule["id"]))
        self.assertTrue(any("Rule content hash mismatch" in item for item in self.library.doctor()["errors"]))
        with self.library.db:
            self.library.db.execute("UPDATE rules SET payload=? WHERE id=?", (original_payload, rule["id"]))
            self.library.db.execute("UPDATE feedback SET quote=? WHERE rule_id=?", ("被意外改写的反馈", rule["id"]))
        self.assertTrue(any("Feedback hash mismatch" in item for item in self.library.doctor()["errors"]))
        with self.library.db:
            self.library.db.execute("UPDATE feedback SET quote=? WHERE rule_id=?", (original_quote, rule["id"]))
        original_ingest = self.library.db.execute("SELECT payload FROM ingest_events WHERE case_id=?", (case["id"],)).fetchone()[0]
        changed_ingest = json.loads(original_ingest)
        changed_ingest["note"] = "被意外改写的案例备注"
        with self.library.db:
            self.library.db.execute("UPDATE ingest_events SET payload=? WHERE case_id=?", (json.dumps(changed_ingest, ensure_ascii=False), case["id"]))
        self.assertTrue(any("Ingest event hash/version mismatch" in item for item in self.library.doctor()["errors"]))
        with self.library.db:
            self.library.db.execute("UPDATE ingest_events SET payload=? WHERE case_id=?", (original_ingest, case["id"]))
        self.assertTrue(self.library.doctor()["ok"])
        snapshot = self.root / "摘要快照.json"
        self.library.snapshot(project="global", domain="render", out=snapshot)
        frozen = read_json(snapshot)
        frozen_rule = frozen["selection"]["active_rules"][0]
        self.assertEqual(frozen_rule["rule_content_sha256"], active["rule_content_sha256"])
        self.assertEqual(frozen_rule["feedback"][-1]["feedback_sha256"], active["feedback"][-1]["feedback_sha256"])
        self.assertEqual(frozen_rule["feedback"][-1]["quote"], original_quote)

    def test_cli_env_unicode_output_and_invalid_limit(self):
        script = Path(__file__).with_name("taste_library.py")
        isolated = self.root / "命令行 空间"
        env = dict(os.environ, ARCH_TASTE_HOME=str(isolated))
        def run(*args):
            return subprocess.run([sys.executable, str(script), *args], env=env,
                                  capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run("init").returncode, 0)
        created = run("import", "--source-note", "测试资料", "--title", "中文 标题")
        self.assertEqual(created.returncode, 2)
        self.assertIn("commit-learning", json.loads(created.stderr)["error"])
        invalid = run("search", "--limit", "21")
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("error", json.loads(invalid.stderr))
        override = run("--home", str(self.library.home), "status")
        self.assertEqual(json.loads(override.stdout)["home"], str(self.library.home))

    def test_preview_decline_and_absent_consent_never_open_or_create_library(self):
        script = Path(__file__).with_name("taste_library.py")
        isolated = self.root / "不得创建的长期库"
        proposal = self.proposal()
        draft = self.root / "proposal.json"
        draft.write_text(json.dumps(proposal, ensure_ascii=False), encoding="utf-8")
        consent = self.consent(proposal, decision="decline", selected_aspects=[], user_quote="这次不保存。")
        reply = self.root / "consent.json"
        reply.write_text(json.dumps(consent, ensure_ascii=False), encoding="utf-8")
        def run(*args):
            return subprocess.run([sys.executable, str(script), "--home", str(isolated), *args],
                                  capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run("preview-learning", "--json", str(draft)).returncode, 0)
        self.assertFalse(isolated.exists())
        declined = run("commit-learning", "--json", str(draft), "--consent", str(reply))
        self.assertEqual(declined.returncode, 0, declined.stderr)
        self.assertFalse(json.loads(declined.stdout)["saved"])
        self.assertFalse(isolated.exists())
        self.assertEqual(run("commit-learning", "--json", str(draft)).returncode, 2)
        self.assertFalse(isolated.exists())
        consent.update(decision="save", selected_aspects=["material"], user_quote="  ")
        reply.write_text(json.dumps(consent), encoding="utf-8")
        self.assertEqual(run("commit-learning", "--json", str(draft), "--consent", str(reply)).returncode, 2)
        self.assertFalse(isolated.exists())
        original = file_hash(self.library.database)
        self.library.commit_learning(proposal, self.consent(proposal, decision="decline", selected_aspects=[]))
        self.assertEqual(file_hash(self.library.database), original)

    def test_selected_material_only_persists_without_original_archive(self):
        source = self.root / "案例 原件.txt"
        source.write_text("原件字节包含所有可见方面", encoding="utf-8")
        proposal = self.proposal(file=source)
        consent = self.consent(proposal)
        saved = self.library.commit_learning(proposal, consent)
        self.assertTrue(saved["saved"])
        case = self.library.show_case(saved["case_id"])
        self.assertFalse(case["asset_archived"])
        self.assertIsNone(case["asset_path"])
        self.assertIn(proposal["case"]["file_sha256"], case["source_note"])
        self.assertEqual(self.library.status()["assets"], 0)
        self.assertEqual(list((self.library.home / "assets").iterdir()), [])
        self.assertEqual(len(case["analyses"]), 1)
        self.assertEqual(len(case["latest_analysis"]["payload"]["observations"]), 1)
        self.assertNotIn("UNSELECTED_LIGHTING_SENTINEL_9123", "\n".join(self.library.db.iterdump()))
        self.assertEqual(len(self.library.search("材料")["active_rules"]), 1)
        self.assertEqual(self.library.search("UNSELECTED_LIGHTING_SENTINEL_9123")["cases"], [])
        receipt = self.library.show_learning(proposal["session_id"])
        self.assertEqual(receipt["consent"]["user_quote"], consent["user_quote"])
        self.assertNotIn("proposal", receipt)
        self.assertTrue(self.library.doctor()["ok"])

    def test_reference_candidate_preference_modes_and_project_scope(self):
        for index, mode in enumerate(("reference", "candidate", "preference")):
            proposal = self.proposal(session=f"mode-{index}")
            self.library.commit_learning(proposal, self.consent(proposal, save_as=mode, scope="项目 A"))
        project = self.library.search("材料", "项目 A")
        self.assertEqual(len(project["cases"]), 3)
        self.assertEqual(len(project["active_rules"]), 1)
        self.assertEqual(len(project["candidate_rules"]), 1)
        self.assertEqual(self.library.search("材料", "项目 B")["cases"], [])
        self.assertEqual(self.library.search("材料")["cases"], [])
        self.assertTrue(self.library.doctor()["ok"])

    def test_learning_sessions_keep_independent_selected_aspects_for_same_source(self):
        source = self.root / "共享 原件.txt"
        source.write_bytes(b"independent learning sessions")
        first = self.proposal("material-session", file=source)
        material = self.library.commit_learning(first, self.consent(first, archive_source=True))
        second = self.proposal("lighting-session", file=source)
        light = self.library.commit_learning(second, self.consent(second, selected_aspects=["lighting"], archive_source=False))
        self.assertNotEqual(material["case_id"], light["case_id"])
        self.assertEqual(self.library.status()["assets"], 1)
        self.assertFalse(self.library.show_case(light["case_id"])["asset_archived"])
        self.assertNotIn("UNSELECTED_LIGHTING_SENTINEL_9123", json.dumps(self.library.show_case(material["case_id"])))
        self.assertEqual({row["id"] for row in self.library.search("材料")["cases"]}, {material["case_id"]})
        self.assertTrue(self.library.doctor()["ok"])

    def test_commit_is_idempotent_and_conflicting_retry_is_rejected(self):
        proposal = self.proposal()
        consent = self.consent(proposal)
        first = self.library.commit_learning(proposal, consent)
        before = self.library.status()
        again = self.library.commit_learning(proposal, consent)
        self.assertTrue(again["idempotent_replay"])
        self.assertEqual(again["case_id"], first["case_id"])
        self.assertEqual(before, self.library.status())
        altered = copy.deepcopy(proposal)
        altered["aspects"][0]["analysis"]["takeaways"].append("改变了已审阅内容")
        with self.assertRaises(ValueError):
            self.library.commit_learning(altered, consent)
        with self.assertRaises(ValueError):
            self.library.commit_learning(altered, self.consent(altered))
        with self.assertRaises(ValueError):
            self.library.commit_learning(proposal, self.consent(proposal, scope="项目 B"))
        self.assertEqual(before, self.library.status())

    def test_invalid_selection_or_rule_fails_before_any_write(self):
        proposal = self.proposal()
        before = self.library.status()
        for options in ({"selected_aspects": []}, {"selected_aspects": ["missing"]},
                        {"selected_aspects": ["material", "material"]}, {"archive_source": True},
                        {"user_quote": ""}, {"save_as": "active"}, {"archive_source": 1}):
            with self.assertRaises(ValueError):
                self.library.commit_learning(proposal, self.consent(proposal, **options))
        invalid = copy.deepcopy(proposal)
        invalid["aspects"][0]["rules"][0]["domain"] = "invalid"
        consent = self.consent(proposal)
        with self.assertRaises(ValueError):
            self.library.commit_learning(invalid, consent)
        self.assertEqual(before, self.library.status())

    def test_failure_at_receipt_write_rolls_back_all_rows_and_new_asset(self):
        source = self.root / "回滚 原件.txt"
        source.write_bytes(b"rollback fixture")
        proposal = self.proposal(file=source)
        before = self.library.status()
        self.library.db.execute("CREATE TEMP TRIGGER refuse_receipt BEFORE INSERT ON learning_commits BEGIN SELECT RAISE(ABORT, 'receipt failure fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.library.commit_learning(proposal, self.consent(proposal, archive_source=True))
        self.assertEqual(before, self.library.status())
        self.assertEqual(list((self.library.home / "assets").iterdir()), [])
        self.assertEqual(source.read_bytes(), b"rollback fixture")
        self.assertTrue(self.library.doctor()["ok"])

    def test_changed_original_cannot_reuse_old_review_hash(self):
        source = self.root / "来源变化.txt"
        source.write_bytes(b"reviewed bytes")
        proposal = self.proposal(file=source)
        consent = self.consent(proposal, archive_source=True)
        before = self.library.status()
        source.write_bytes(b"different bytes at the same path")
        with self.assertRaises(ValueError):
            self.library.commit_learning(proposal, consent)
        self.assertEqual(before, self.library.status())
        self.assertEqual(list((self.library.home / "assets").iterdir()), [])

    def test_explicit_schema_one_migration_preserves_rows_assets_and_states(self):
        source = self.root / "旧版 原件.txt"
        source.write_bytes(b"schema-one fixture")
        case = self.library.import_case(file=source, domain="render")["case"]
        self.library.analyze(case["id"], self.analysis())
        rule = self.rule(case)
        self.library.feedback(rule["id"], "active", "旧版已确认偏好")
        expected = self.library.show_rule(rule["id"])
        asset_bytes = Path(case["asset_path"]).read_bytes()
        library_path = self.library.home
        with self.library.db:
            self.library.db.execute("DROP TABLE learning_commits")
            self.library.db.execute("UPDATE metadata SET value='1' WHERE key='schema_version'")
        self.library.close()
        before = file_hash(library_path / "library.sqlite3")
        with self.assertRaises(ValueError):
            Library(library_path)
        with self.assertRaises(ValueError):
            Library(library_path, initialize=True)
        self.assertEqual(file_hash(library_path / "library.sqlite3"), before)
        self.library = Library(library_path, migrate=True)
        self.assertEqual(self.library.status()["schema_version"], "2")
        self.assertEqual(self.library.status()["learning_commits"], 0)
        self.assertEqual(self.library.show_rule(rule["id"]), expected)
        self.assertEqual(Path(case["asset_path"]).read_bytes(), asset_bytes)
        self.assertTrue(self.library.doctor()["ok"])

    def test_missing_archived_asset_duplicate_fails_and_show_does_not_claim_available(self):
        source = self.root / "缺失归档.txt"
        source.write_bytes(b"intact source fixture")
        saved = self.library.import_case(file=source)["case"]
        Path(saved["asset_path"]).unlink()
        before = self.library.status()
        self.assertFalse(self.library.show_case(saved["id"])["asset_archived"])
        self.assertTrue(self.library.show_case(saved["id"])["asset_registered"])
        with self.assertRaisesRegex(ValueError, "missing or corrupt"):
            self.library.import_case(file=source, note="must not append")
        self.assertEqual(before, self.library.status())
        self.assertFalse(self.library.doctor()["ok"])

    def test_no_query_recency_tracks_new_analysis_and_ingest_events(self):
        earlier = self.case(source="older source")
        later = self.case(source="newer source")
        self.assertEqual(self.library.search(limit=1)["cases"][0]["id"], later["id"])
        self.library.analyze(earlier["id"], self.analysis("新分析"))
        self.assertEqual(self.library.search(limit=1)["cases"][0]["id"], earlier["id"])
        self.library.import_case(source_note="newer source", domain="render", note="新的备注")
        self.assertEqual(self.library.search(limit=1)["cases"][0]["id"], later["id"])

    def test_excluded_rule_reasons_follow_case_without_cross_project_leakage(self):
        shared = self.case()
        global_rule = self.rule(shared, statement="全局排除的合成手法")
        project_rule = self.rule(shared, scope="项目 A", statement="A_ONLY_RETIRED_SENTINEL")
        global_quote = "  全局不采用这种测试效果。  "
        self.library.feedback(global_rule["id"], "rejected", global_quote)
        self.library.feedback(project_rule["id"], "retired", "A_ONLY_REASON_SENTINEL")
        for project in ("global", "项目 A", "项目 B"):
            found = self.library.search("混凝土", project)
            history = found["cases"][0]["excluded_rule_history"]
            expected = {global_rule["id"], project_rule["id"]} if project == "项目 A" else {global_rule["id"]}
            self.assertEqual({item["id"] for item in history}, expected)
            self.assertEqual(next(item for item in history if item["id"] == global_rule["id"])["feedback_quote"], global_quote)
            self.assertEqual(found["active_rules"] + found["candidate_rules"], [])
            if project != "项目 A":
                self.assertNotIn("A_ONLY", json.dumps(found))

    def test_cli_saved_session_can_be_read_and_replayed_from_new_process(self):
        script = Path(__file__).with_name("taste_library.py")
        proposal = self.proposal(session="cli-session")
        draft, reply = self.root / "cli-proposal.json", self.root / "cli-consent.json"
        draft.write_text(json.dumps(proposal, ensure_ascii=False), encoding="utf-8")
        reply.write_text(json.dumps(self.consent(proposal, scope="项目 A"), ensure_ascii=False), encoding="utf-8")
        def run(*args):
            result = subprocess.run([sys.executable, str(script), "--home", str(self.library.home), *args],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        saved = run("commit-learning", "--json", str(draft), "--consent", str(reply))
        self.assertTrue(saved["saved"])
        found = run("search", "--project", "项目 A", "--query", "材料")
        self.assertEqual(found["active_rules"][0]["id"], saved["rules"][0]["id"])
        receipt = run("show-learning", "--session-id", "cli-session")
        self.assertEqual(receipt["result"]["case_id"], saved["case_id"])
        self.assertTrue(run("commit-learning", "--json", str(draft), "--consent", str(reply))["idempotent_replay"])
        self.assertTrue(run("doctor")["ok"])

    def test_same_committed_session_replays_even_if_original_was_later_removed(self):
        source = self.root / "已删除 原件.txt"
        source.write_bytes(b"committed original fixture")
        proposal = self.proposal(file=source)
        consent = self.consent(proposal, archive_source=True)
        first = self.library.commit_learning(proposal, consent)
        source.unlink()
        replay = self.library.commit_learning(proposal, consent)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(first["case_id"], replay["case_id"])
        self.assertTrue(self.library.doctor()["ok"])

    def test_cross_domain_snapshot_support_preserves_scoped_exclusion_conditions(self):
        shared = self.case(domain="architecture", source="跨媒介来源")
        adopted = self.rule(shared, statement="active render technique")
        retired = self.rule(shared, scope="项目 A", statement="retired conditional technique",
                            applies_when=["ONLY_CLOSE_VIEW"], exclude_when=["DISTANT_VIEW_EXCLUDED"])
        other = self.rule(shared, scope="项目 B", statement="B_PRIVATE_EXCLUSION")
        self.library.feedback(adopted["id"], "active", "确认渲染用法")
        self.library.feedback(retired["id"], "retired", "仅在近景不采用旧手法")
        self.library.feedback(other["id"], "rejected", "B_PRIVATE_REASON")
        output = self.root / "跨媒介否决快照.json"
        self.library.snapshot(project="项目 A", domain="render", out=output)
        frozen = read_json(output)
        self.assertEqual(frozen["selection"]["cases"], [])
        support = frozen["supporting_cases"][0]
        self.assertEqual(support["id"], shared["id"])
        history = support["excluded_rule_history"]
        self.assertEqual([item["id"] for item in history], [retired["id"]])
        self.assertEqual(history[0]["applies_when"], ["ONLY_CLOSE_VIEW"])
        self.assertEqual(history[0]["exclude_when"], ["DISTANT_VIEW_EXCLUDED"])
        self.assertNotIn("B_PRIVATE", json.dumps(frozen))


if __name__ == "__main__":
    unittest.main(verbosity=1)
