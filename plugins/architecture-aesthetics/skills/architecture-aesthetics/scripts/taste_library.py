#!/usr/bin/env python3
"""Local, inspectable architecture reference and preference library (stdlib only).

This program stores supplied analysis. It never inspects images, downloads URLs,
trains model weights, or converts candidate rules into confirmed preferences.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import urlsplit
import uuid

DOMAINS = ("architecture", "presentation", "model", "render", "cad")
STATES = ("active", "rejected", "retired", "candidate")
SCHEMA_VERSION = "2"
METADATA_FIELDS = ("title", "note", "source_url", "source_note", "original_path")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def nonempty(value, name, maximum=20000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be a nonempty string (max {maximum} characters)")
    return value.strip()


def strings(value, name, allow_empty=True):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(f"{name} must be {'a' if allow_empty else 'a nonempty'} string array")
    return [nonempty(item, name) for item in value]


def exact_keys(value, names, label):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError(f"{label} must contain exactly: {', '.join(names)}")


def read_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")
    with Path(path).expanduser().open("r", encoding="utf-8-sig") as stream:
        return json.load(stream, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)


def validate_analysis(data):
    exact_keys(data, ("observations", "takeaways", "avoid", "limitations"), "analysis")
    if not isinstance(data["observations"], list) or not data["observations"]:
        raise ValueError("observations must be a nonempty array")
    observations = []
    for observation in data["observations"]:
        exact_keys(observation, ("dimension", "text", "evidence", "certainty"), "observation")
        if observation["certainty"] not in ("fact", "inference", "unknown"):
            raise ValueError("certainty must be fact, inference, or unknown")
        observations.append({key: nonempty(value, key) for key, value in observation.items()})
    return {"observations": observations,
            **{key: strings(data[key], key) for key in ("takeaways", "avoid", "limitations")}}


def validate_rule(data):
    names = ("scope", "domain", "dimension", "statement", "rationale", "applies_when", "exclude_when", "case_ids")
    exact_keys(data, names, "rule")
    result = {key: nonempty(data[key], key) for key in ("scope", "domain", "dimension", "statement", "rationale")}
    nonempty(result["scope"], "scope", 200)
    if result["domain"] not in DOMAINS:
        raise ValueError("Invalid rule domain")
    result.update({key: strings(data[key], key, allow_empty=key != "case_ids")
                   for key in ("applies_when", "exclude_when", "case_ids")})
    if len(set(result["case_ids"])) != len(result["case_ids"]):
        raise ValueError("case_ids must not contain duplicates")
    return result


def validate_proposal(data):
    """Validate structure only; actual review and consent are agent responsibilities."""
    exact_keys(data, ("schema_version", "session_id", "case", "aspects"), "learning proposal")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Learning proposal schema_version must be 1")
    session_id = nonempty(data["session_id"], "session_id", 200)
    case = data["case"]
    allowed = {"title", "domain", "file", "file_sha256", "url", "source_note"}
    if not isinstance(case, dict) or not {"title", "domain"} <= set(case) or set(case) - allowed:
        raise ValueError("case requires title/domain and only file/file_sha256/url/source_note provenance fields")
    case = {key: nonempty(value, key, 2000) for key, value in case.items()}
    if case["domain"] not in DOMAINS:
        raise ValueError("Invalid case domain")
    if not any(case.get(key) for key in ("file", "url", "source_note")):
        raise ValueError("case requires a source locator: file, url, or source_note")
    if bool(case.get("file")) != bool(case.get("file_sha256")):
        raise ValueError("file and file_sha256 must be supplied together")
    if case.get("file"):
        if not Path(case["file"]).is_absolute():
            raise ValueError("file must be an absolute path")
        if not re.fullmatch(r"[a-f0-9]{64}", case["file_sha256"]):
            raise ValueError("file_sha256 must be a lowercase SHA-256 hex digest")
    if case.get("url"):
        validate_url(case["url"])
    if not isinstance(data["aspects"], list) or not data["aspects"]:
        raise ValueError("aspects must be a nonempty array")
    aspects = []
    for aspect in data["aspects"]:
        exact_keys(aspect, ("id", "label", "analysis", "rules"), "aspect")
        aspect_id = nonempty(aspect["id"], "aspect id", 100)
        if not isinstance(aspect["rules"], list):
            raise ValueError("aspect rules must be an array")
        rules = []
        for rule in aspect["rules"]:
            exact_keys(rule, ("domain", "dimension", "statement", "rationale", "applies_when", "exclude_when"), "aspect rule")
            valid = validate_rule({**rule, "scope": "global", "case_ids": ["CASE-validation-only"]})
            rules.append({key: value for key, value in valid.items() if key not in ("scope", "case_ids")})
        aspects.append({"id": aspect_id, "label": nonempty(aspect["label"], "aspect label", 200),
                        "analysis": validate_analysis(aspect["analysis"]), "rules": rules})
    if len({aspect["id"] for aspect in aspects}) != len(aspects):
        raise ValueError("aspect ids must be unique")
    return {"schema_version": 1, "session_id": session_id, "case": case, "aspects": aspects}


def validate_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL must use http/https, have a host, and contain no credentials")
    if any(character.isspace() for character in url):
        raise ValueError("URL must not contain whitespace")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("Invalid URL port") from error


def verify_proposal_source(proposal):
    case = proposal["case"]
    if case.get("file"):
        source = Path(case["file"]).expanduser().resolve(strict=True)
        if not source.is_file() or file_hash(source) != case["file_sha256"]:
            raise ValueError("Source bytes differ from the reviewed file_sha256; review again")


def preview_learning(data):
    proposal = validate_proposal(data)
    verify_proposal_source(proposal)
    return {"session_id": proposal["session_id"], "proposal_sha256": digest(proposal),
            "saved": False, "proposal": proposal,
            "consent_required": "Ask after showing the analysis: whether to save, selected aspects, scope, reference/candidate/preference, and whether to archive the original. No reply is not consent."}


def validate_consent(proposal, data):
    names = ("session_id", "proposal_sha256", "decision", "selected_aspects", "scope", "save_as", "archive_source", "user_quote")
    exact_keys(data, names, "consent")
    if data["session_id"] != proposal["session_id"] or data["proposal_sha256"] != digest(proposal):
        raise ValueError("Consent does not match this reviewed proposal")
    if data["decision"] not in ("save", "decline"):
        raise ValueError("decision must be save or decline")
    nonempty(data["user_quote"], "actual post-analysis user_quote")
    selected = strings(data["selected_aspects"], "selected_aspects", allow_empty=data["decision"] == "decline")
    if len(set(selected)) != len(selected) or set(selected) - {aspect["id"] for aspect in proposal["aspects"]}:
        raise ValueError("selected_aspects must contain unique known aspect ids")
    if data["save_as"] not in ("reference", "candidate", "preference"):
        raise ValueError("save_as must be reference, candidate, or preference")
    nonempty(data["scope"], "scope", 200)
    if type(data["archive_source"]) is not bool:
        raise ValueError("archive_source must be a boolean")
    if data["decision"] == "decline" and (selected or data["archive_source"]):
        raise ValueError("decline must have no selected aspects and archive_source=false")
    if data["archive_source"] and not proposal["case"].get("file"):
        raise ValueError("Archiving requires a supplied local source file")
    chosen = [aspect for aspect in proposal["aspects"] if aspect["id"] in selected]
    if data["decision"] == "save" and data["save_as"] != "reference" and any(not aspect["rules"] for aspect in chosen):
        raise ValueError("Each selected candidate/preference aspect must include a reviewed rule")
    return {**data, "selected_aspects": selected, "scope": data["scope"].strip()}


def keywords(query):
    """Explainable English terms + Chinese phrases/bigrams; no embeddings."""
    result = []
    for token in re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", query.casefold()):
        result.append(token)
        if re.fullmatch(r"[\u3400-\u9fff]+", token) and len(token) > 2:
            result.extend(token[index:index + 2] for index in range(len(token) - 1))
    return list(dict.fromkeys(result))


def rank(fields, tokens):
    matches = {}
    for name, value in fields.items():
        text = (value if isinstance(value, str) else canonical(value)).casefold()
        found = [term for term in tokens if term in text]
        if found:
            matches[name] = found
    found = {term for values in matches.values() for term in values}
    score = sum(min(3, len(term)) for term in found)
    return {"keyword_score": score, "matched_fields": matches}


COMMIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_commits (
    session_id TEXT PRIMARY KEY, proposal_sha256 TEXT NOT NULL,
    consent_sha256 TEXT NOT NULL, consent TEXT NOT NULL,
    result TEXT NOT NULL, created_at TEXT NOT NULL, commit_sha256 TEXT NOT NULL);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assets (
    sha256 TEXT PRIMARY KEY, relative_path TEXT NOT NULL UNIQUE,
    byte_size INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY, project TEXT NOT NULL, domain TEXT NOT NULL,
    title TEXT NOT NULL, note TEXT NOT NULL, source_url TEXT NOT NULL,
    source_note TEXT NOT NULL, original_path TEXT NOT NULL,
    asset_sha256 TEXT REFERENCES assets(sha256), source_key TEXT NOT NULL,
    created_at TEXT NOT NULL, UNIQUE(project, domain, source_key));
CREATE TABLE IF NOT EXISTS analyses (
    case_id TEXT NOT NULL REFERENCES cases(id), version INTEGER NOT NULL,
    payload TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(case_id, version));
CREATE TABLE IF NOT EXISTS ingest_events (
    case_id TEXT NOT NULL REFERENCES cases(id), version INTEGER NOT NULL,
    payload TEXT NOT NULL, event_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(case_id, version));
CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY, scope TEXT NOT NULL, domain TEXT NOT NULL,
    payload TEXT NOT NULL, rule_content_sha256 TEXT NOT NULL,
    state TEXT NOT NULL, revision INTEGER NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rule_cases (
    rule_id TEXT NOT NULL REFERENCES rules(id), case_id TEXT NOT NULL REFERENCES cases(id),
    PRIMARY KEY(rule_id, case_id));
CREATE TABLE IF NOT EXISTS feedback (
    rule_id TEXT NOT NULL REFERENCES rules(id), revision INTEGER NOT NULL,
    state TEXT NOT NULL, quote TEXT NOT NULL, created_at TEXT NOT NULL,
    feedback_sha256 TEXT NOT NULL,
    PRIMARY KEY(rule_id, revision));
CREATE INDEX IF NOT EXISTS cases_scope ON cases(project, domain);
CREATE INDEX IF NOT EXISTS rules_scope ON rules(scope, domain, state);
""" + COMMIT_SCHEMA


class Library:
    def __init__(self, home, initialize=False, migrate=False):
        self.home = Path(home).expanduser().resolve()
        self.database = self.home / "library.sqlite3"
        creating = initialize and not self.database.exists()
        if creating:
            self.home.mkdir(parents=True, exist_ok=True)
            (self.home / "assets").mkdir(exist_ok=True)
        if not initialize and not self.database.is_file():
            raise ValueError("Library does not exist; run init first")
        self.db = sqlite3.connect(str(self.database), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self._created_assets = []
        if creating:
            self.db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
            with self.db:
                self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        version = self.db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if version and version[0] == "1" and migrate:
            # Explicit, additive migration; all prior rows/assets remain in place.
            try:
                self.db.executescript("BEGIN IMMEDIATE;\n" + COMMIT_SCHEMA +
                                      "UPDATE metadata SET value='2' WHERE key='schema_version';\nCOMMIT;")
            except Exception:
                self.db.rollback()
                self.db.close()
                raise
            version = self.db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if not version or version[0] != SCHEMA_VERSION:
            self.db.close()
            raise ValueError("Unsupported library schema version; back up schema 1 libraries and run migrate explicitly")

    @contextmanager
    def transaction(self):
        """Nested savepoints prevent inner methods from committing an outer batch."""
        outer = not self.db.in_transaction
        marker = "sp_" + uuid.uuid4().hex
        start_assets = len(self._created_assets)
        self.db.execute("BEGIN IMMEDIATE" if outer else "SAVEPOINT " + marker)
        try:
            yield
            self.db.execute("COMMIT" if outer else "RELEASE SAVEPOINT " + marker)
        except Exception:
            if outer:
                self.db.rollback()
            else:
                self.db.execute("ROLLBACK TO SAVEPOINT " + marker)
                self.db.execute("RELEASE SAVEPOINT " + marker)
            for path in self._created_assets[start_assets:]:
                path.unlink(missing_ok=True)
            del self._created_assets[start_assets:]
            raise
        finally:
            if outer:
                self._created_assets.clear()

    def close(self):
        self.db.close()

    def status(self):
        return {"home": str(self.home), "database": str(self.database), "schema_version": SCHEMA_VERSION,
                **{name: self.db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                   for name in ("cases", "assets", "analyses", "ingest_events", "rules", "feedback", "learning_commits")},
                "rule_states": {row[0]: row[1] for row in self.db.execute("SELECT state, COUNT(*) FROM rules GROUP BY state")}}

    def asset_path(self, relative):
        target = (self.home / relative).resolve()
        if not target.is_relative_to((self.home / "assets").resolve()):
            raise ValueError("Asset path escapes the library assets directory")
        return target

    def import_case(self, *, file=None, url="", source_note="", title="", project="global", domain="architecture", note="",
                    _source_key=None, _archive_source=True, _expected_sha256=None):
        project = nonempty(project, "project", 200)
        if domain not in DOMAINS:
            raise ValueError("Invalid case domain")
        for name, value in (("title", title), ("note", note), ("source_note", source_note), ("url", url)):
            if not isinstance(value, str) or len(value) > 20000:
                raise ValueError(f"Invalid {name}")
        url, source_note = url.strip(), source_note.strip()
        if url:
            validate_url(url)
        source = Path(file).expanduser().resolve(strict=True) if file else None
        if source is not None and not source.is_file():
            raise ValueError("--file must identify a regular file")
        if source is None and not url and not source_note:
            raise ValueError("Supply --file, --url, or --source-note")
        sha = file_hash(source) if source else None
        if _expected_sha256 is not None and sha != _expected_sha256:
            raise ValueError("Source changed after review; no case was saved")
        source_key = _source_key or ("sha256:" + sha if sha else ("url:" + url if url else "note:" + digest(source_note)))
        new_asset = None
        temporary = None
        case_id = "CASE-" + uuid.uuid4().hex[:16]
        try:
            with self.transaction():
                old = self.db.execute("SELECT id FROM cases WHERE project=? AND domain=? AND source_key=?", (project, domain, source_key)).fetchone()
                if old:
                    existing = self.show_case(old[0])
                    if existing["asset_sha256"]:
                        archived = Path(existing["asset_path"])
                        if not archived.is_file() or file_hash(archived) != existing["asset_sha256"]:
                            raise ValueError("Duplicate case has a missing or corrupt archived asset; run doctor and restore from a verified source")
                    supplied = {"title": title.strip(), "note": note, "source_url": url,
                                "source_note": source_note, "original_path": str(source) if source else ""}
                    latest = dict(existing["latest_metadata"])
                    # Unspecified/empty CLI fields do not silently erase earlier
                    # notes. A changed note is another event on the same case.
                    latest.update({key: value for key, value in supplied.items() if value.strip()})
                    added = self._append_ingest_event(old[0], latest)
                    return {"duplicate": True, "ingest_event_added": added, "case": self.show_case(old[0])}
                if source and _archive_source:
                    asset = self.db.execute("SELECT * FROM assets WHERE sha256=?", (sha,)).fetchone()
                    if asset:
                        archived = self.asset_path(asset["relative_path"])
                        if not archived.is_file() or file_hash(archived) != sha:
                            raise ValueError("Existing archived asset is missing or corrupt; run doctor")
                    else:
                        suffix = source.suffix.lower()
                        if not re.fullmatch(r"\.[a-z0-9]{1,12}", suffix):
                            suffix = ".bin"
                        relative = f"assets/{sha}{suffix}"
                        archived = self.asset_path(relative)
                        archived.parent.mkdir(parents=True, exist_ok=True)
                        if archived.exists():
                            if not archived.is_file() or file_hash(archived) != sha:
                                raise ValueError("Unregistered target asset is corrupt; refusing overwrite")
                        else:
                            fd, temporary_name = tempfile.mkstemp(prefix=".import-", dir=archived.parent)
                            temporary = Path(temporary_name)
                            with os.fdopen(fd, "wb") as output, source.open("rb") as input_stream:
                                for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                                    output.write(chunk)
                                output.flush()
                                os.fsync(output.fileno())
                            if file_hash(temporary) != sha:
                                raise ValueError("Source changed during import; no case was saved")
                            os.replace(temporary, archived)
                            temporary = None
                            new_asset = archived
                            self._created_assets.append(archived)
                        self.db.execute("INSERT INTO assets VALUES (?, ?, ?, ?)", (sha, relative, archived.stat().st_size, now()))
                chosen_title = title.strip() or (source.name if source else (url or source_note[:120]))
                self.db.execute("INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (case_id, project, domain, chosen_title, note, url, source_note,
                                 str(source) if source else "", sha if _archive_source else None, source_key, now()))
                self._append_ingest_event(case_id, {"title": chosen_title, "note": note,
                                                   "source_url": url, "source_note": source_note,
                                                   "original_path": str(source) if source else ""})
        except Exception:
            if new_asset is not None:
                new_asset.unlink(missing_ok=True)
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return {"duplicate": False, "ingest_event_added": True, "case": self.show_case(case_id)}

    def _append_ingest_event(self, case_id, payload):
        """Called inside the import transaction; metadata never edits old rows."""
        previous = self.db.execute("SELECT * FROM ingest_events WHERE case_id=? ORDER BY version DESC LIMIT 1", (case_id,)).fetchone()
        if previous and json.loads(previous["payload"]) == payload:
            return False
        version = previous["version"] + 1 if previous else 1
        event = {"case_id": case_id, "version": version, "payload": payload, "created_at": now()}
        self.db.execute("INSERT INTO ingest_events VALUES (?, ?, ?, ?, ?)",
                        (case_id, version, canonical(payload), digest(event), event["created_at"]))
        return True

    def show_case(self, case_id, history=True):
        row = self.db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown case: {case_id}")
        result = dict(row)
        result["asset_archived"] = False
        result["asset_registered"] = bool(row["asset_sha256"])
        result["asset_path"] = None
        if row["asset_sha256"]:
            asset = self.db.execute("SELECT * FROM assets WHERE sha256=?", (row["asset_sha256"],)).fetchone()
            result["asset_path"] = str(self.asset_path(asset["relative_path"]))
            result["asset_bytes"] = asset["byte_size"]
            result["asset_archived"] = Path(result["asset_path"]).is_file()
        version_query = "SELECT * FROM analyses WHERE case_id=? ORDER BY version"
        if not history:
            version_query += " DESC LIMIT 1"
        versions = [{**dict(item), "payload": json.loads(item["payload"])}
                    for item in self.db.execute(version_query, (case_id,))]
        result["analysis_version"] = versions[-1]["version"] if versions else 0
        result["latest_analysis"] = versions[-1] if versions else None
        if history:
            result["analyses"] = versions
        result["ingest_events"] = [{**dict(item), "payload": json.loads(item["payload"])}
                                   for item in self.db.execute("SELECT * FROM ingest_events WHERE case_id=? ORDER BY version", (case_id,))]
        result["ingest_version"] = result["ingest_events"][-1]["version"] if result["ingest_events"] else 0
        result["latest_metadata"] = (result["ingest_events"][-1]["payload"] if result["ingest_events"]
                                     else {key: result[key] for key in METADATA_FIELDS})
        result["updated_at"] = max([row["created_at"]] +
                                   [item["created_at"] for item in versions] +
                                   [item["created_at"] for item in result["ingest_events"]])
        return result

    def analyze(self, case_id, data):
        payload = validate_analysis(data)
        with self.transaction():
            self.show_case(case_id, history=False)
            version = self.db.execute("SELECT COALESCE(MAX(version), 0)+1 FROM analyses WHERE case_id=?", (case_id,)).fetchone()[0]
            self.db.execute("INSERT INTO analyses VALUES (?, ?, ?, ?, ?)", (case_id, version, canonical(payload), digest(payload), now()))
        return self.show_case(case_id)

    def create_rule(self, data):
        payload = validate_rule(data)
        rule_id = "RULE-" + uuid.uuid4().hex[:16]
        timestamp = now()
        with self.transaction():
            for case_id in payload["case_ids"]:
                case = self.show_case(case_id, history=False)
                if case["project"] not in {"global", payload["scope"]}:
                    raise ValueError(f"Case {case_id} belongs to another project; rule creation refused")
            self.db.execute("INSERT INTO rules VALUES (?, ?, ?, ?, ?, 'candidate', 1, ?, ?)",
                            (rule_id, payload["scope"], payload["domain"], canonical(payload), digest(payload), timestamp, timestamp))
            self.db.executemany("INSERT INTO rule_cases VALUES (?, ?)", ((rule_id, case_id) for case_id in payload["case_ids"]))
        return self.show_rule(rule_id)

    def show_rule(self, rule_id):
        row = self.db.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown rule: {rule_id}")
        result = {**dict(row), "payload": json.loads(row["payload"])}
        result["feedback"] = [dict(item) for item in self.db.execute("SELECT * FROM feedback WHERE rule_id=? ORDER BY revision", (rule_id,))]
        result["sha256"] = digest({"payload": result["payload"], "state": result["state"], "revision": result["revision"], "feedback": result["feedback"]})
        return result

    def feedback(self, rule_id, state, quote):
        if state not in STATES:
            raise ValueError("Invalid feedback state")
        # Preserve the exact user quote, including intentional whitespace.
        nonempty(quote, "quote")
        with self.transaction():
            rule = self.show_rule(rule_id)
            revision = rule["revision"] + 1
            timestamp = now()
            event = {"rule_id": rule_id, "revision": revision, "state": state, "quote": quote, "created_at": timestamp}
            self.db.execute("INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?)",
                            (rule_id, revision, state, quote, timestamp, digest(event)))
            self.db.execute("UPDATE rules SET state=?, revision=?, updated_at=? WHERE id=?", (state, revision, timestamp, rule_id))
        return self.show_rule(rule_id)

    def commit_learning(self, data, consent_data):
        proposal = validate_proposal(data)
        consent = validate_consent(proposal, consent_data)
        if consent["decision"] == "decline":
            return {"saved": False, "decision": "decline", "session_id": proposal["session_id"]}
        session_id = proposal["session_id"]
        consent_sha = digest(consent)
        with self.transaction():
            previous = self.db.execute("SELECT * FROM learning_commits WHERE session_id=?", (session_id,)).fetchone()
            if previous:
                if previous["proposal_sha256"] != digest(proposal) or previous["consent_sha256"] != consent_sha:
                    raise ValueError("Learning session already committed with different content or consent; review a new session")
                return {**json.loads(previous["result"]), "idempotent_replay": True}
            verify_proposal_source(proposal)
            source = proposal["case"]
            chosen = [aspect for aspect in proposal["aspects"] if aspect["id"] in consent["selected_aspects"]]
            analysis = {key: [item for aspect in chosen for item in aspect["analysis"][key]]
                        for key in ("observations", "takeaways", "avoid", "limitations")}
            # Validate everything before the first case/asset write. Store no full
            # proposal: the unselected analysis never reaches a persistent table.
            validate_analysis(analysis)
            provenance = source.get("source_note", "")
            if source.get("file_sha256"):
                provenance += ("\n" if provenance else "") + "Source SHA-256: " + source["file_sha256"]
            imported = self.import_case(file=source.get("file"), url=source.get("url", ""),
                                        source_note=provenance, title=source["title"],
                                        project=consent["scope"], domain=source["domain"],
                                        _source_key="learning:" + session_id,
                                        _archive_source=consent["archive_source"],
                                        _expected_sha256=source.get("file_sha256"))
            case_id = imported["case"]["id"]
            case = self.analyze(case_id, analysis)
            saved_rules = []
            if consent["save_as"] != "reference":
                for aspect in chosen:
                    for rule in aspect["rules"]:
                        saved = self.create_rule({**rule, "scope": consent["scope"], "case_ids": [case_id]})
                        if consent["save_as"] == "preference":
                            saved = self.feedback(saved["id"], "active", consent["user_quote"])
                        saved_rules.append({"id": saved["id"], "state": saved["state"], "revision": saved["revision"]})
            result = {"saved": True, "session_id": session_id, "proposal_sha256": digest(proposal),
                      "selected_aspects": consent["selected_aspects"], "scope": consent["scope"],
                      "save_as": consent["save_as"], "archive_source": consent["archive_source"],
                      "case_id": case_id, "analysis_version": case["analysis_version"], "rules": saved_rules}
            record = {"session_id": session_id, "proposal_sha256": digest(proposal), "consent_sha256": consent_sha,
                      "consent": consent, "result": result, "created_at": now()}
            self.db.execute("INSERT INTO learning_commits VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (session_id, record["proposal_sha256"], consent_sha, canonical(consent),
                             canonical(result), record["created_at"], digest(record)))
        return {**result, "idempotent_replay": False}

    def case_excluded_history(self, case_id, project):
        """Only current-project/global negative feedback follows source evidence."""
        excluded = []
        for linked in self.db.execute("SELECT r.id FROM rules r JOIN rule_cases rc ON rc.rule_id=r.id "
                                      "WHERE rc.case_id=? AND r.scope IN (?, ?) "
                                      "AND r.state IN ('rejected', 'retired') ORDER BY r.updated_at DESC, r.id", (case_id, "global", project)):
            rule = self.show_rule(linked[0])
            latest = rule["feedback"][-1] if rule["feedback"] else None
            excluded.append({"id": rule["id"], "scope": rule["scope"], "domain": rule["domain"],
                             **{key: rule["payload"][key] for key in ("dimension", "statement", "applies_when", "exclude_when")},
                             "state": rule["state"], "feedback_quote": latest["quote"] if latest else None,
                             "feedback_at": latest["created_at"] if latest else None})
        return excluded

    def search(self, query="", project="global", domain=None, limit=5):
        project = nonempty(project, "project", 200)
        if not isinstance(query, str) or len(query) > 1000:
            raise ValueError("query must be text, max 1000 characters")
        if domain is not None and domain not in DOMAINS:
            raise ValueError("Invalid search domain")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        tokens = keywords(query)
        if query.strip() and not tokens:
            raise ValueError("query must contain Chinese characters or English letters/numbers")
        args = ["global", project]
        domain_clause = " AND domain=?" if domain else ""
        if domain:
            args.append(domain)
        cases = []
        for row in self.db.execute("SELECT id FROM cases WHERE project IN (?, ?)" + domain_clause, args):
            case = self.show_case(row[0], history=False)
            match = rank({key: case[key] for key in ("title", "note", "source_note", "latest_metadata", "ingest_events", "latest_analysis")}, tokens)
            if not tokens or match["keyword_score"]:
                # Retired rules are not reusable preferences, but their actual
                # rejection history must accompany surviving source evidence.
                # Scope this join separately: a global case can support private
                # project rules that must never leak into another project.
                case["excluded_rule_history"] = self.case_excluded_history(case["id"], project)
                cases.append({**case, "match": match})
        rules = {"active_rules": [], "candidate_rules": []}
        for row in self.db.execute("SELECT id FROM rules WHERE scope IN (?, ?) AND state IN ('active', 'candidate')" + domain_clause, args):
            rule = self.show_rule(row[0])
            match = rank(rule["payload"], tokens)
            if not tokens or match["keyword_score"]:
                rules[rule["state"] + "_rules"].append({**rule, "match": match})
        def ordered(records):
            return sorted(records, key=lambda item: (item["match"]["keyword_score"], item.get("updated_at", item["created_at"]), item["id"]), reverse=True)[:limit]
        return {"query": query, "project": project, "domain": domain, "limit_per_group": limit,
                "method": "Chinese phrases/bigrams and English keywords; scores measure matches, not aesthetic quality or confidence",
                "tokens": tokens, "candidate_policy": "Suggestions only; candidates are never confirmed preferences",
                "cases": ordered(cases), **{key: ordered(value) for key, value in rules.items()}}

    def show_learning(self, session_id):
        row = self.db.execute("SELECT * FROM learning_commits WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            raise ValueError("Unknown saved learning session")
        return {**dict(row), "consent": json.loads(row["consent"]), "result": json.loads(row["result"])}

    def snapshot(self, *, project, domain=None, query="", out, limit=5):
        output = Path(out).expanduser().resolve()
        if output.exists():
            raise ValueError("Snapshot already exists; refusing overwrite")
        # One SQLite read transaction freezes all selected record versions together.
        with self.db:
            self.db.execute("BEGIN")
            selection = self.search(query, project, domain, limit)
            selected_ids = {case["id"] for case in selection["cases"]}
            support_ids = {case_id for rule in selection["active_rules"] + selection["candidate_rules"]
                           for case_id in rule["payload"]["case_ids"]} - selected_ids
            supporting = [{**self.show_case(case_id, history=False),
                           "excluded_rule_history": self.case_excluded_history(case_id, project)}
                          for case_id in sorted(support_ids)]
            payload = {"schema_version": SCHEMA_VERSION, "id": "SNAP-" + uuid.uuid4().hex[:16],
                       "created_at": now(), "library_home": str(self.home), "selection": selection,
                       "supporting_cases": supporting,
                       "asset_policy": "Original bytes remain in library assets; archived paths and SHA-256 hashes are frozen here. Missing image bytes are not invented."}
            payload["snapshot_sha256"] = digest(payload)
        write_new_json(output, payload)
        return {"path": str(output), "snapshot_sha256": payload["snapshot_sha256"],
                "cases": len(selection["cases"]), "supporting_cases": len(supporting),
                "active_rules": len(selection["active_rules"]), "candidate_rules": len(selection["candidate_rules"])}

    def export(self, out):
        with self.db:
            self.db.execute("BEGIN")
            data = {"schema_version": SCHEMA_VERSION, "exported_at": now(), "home": str(self.home),
                    "assets": [dict(row) for row in self.db.execute("SELECT * FROM assets ORDER BY sha256")],
                    "cases": [self.show_case(row[0]) for row in self.db.execute("SELECT id FROM cases ORDER BY id")],
                    "rules": [self.show_rule(row[0]) for row in self.db.execute("SELECT id FROM rules ORDER BY id")],
                    "learning_commits": [self.show_learning(row[0]) for row in self.db.execute("SELECT session_id FROM learning_commits ORDER BY session_id")]}
        output = Path(out).expanduser().resolve()
        write_new_json(output, data)
        return {"path": str(output), "cases": len(data["cases"]), "rules": len(data["rules"])}

    def doctor(self):
        errors = []
        integrity = [row[0] for row in self.db.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            errors.extend(integrity)
        errors.extend("Foreign key violation: " + str(tuple(row)) for row in self.db.execute("PRAGMA foreign_key_check"))
        checked = 0
        for asset in self.db.execute("SELECT * FROM assets"):
            try:
                path = self.asset_path(asset["relative_path"])
                if not path.is_file() or path.stat().st_size != asset["byte_size"] or file_hash(path) != asset["sha256"]:
                    errors.append(f"Missing or corrupt asset: {asset['relative_path']}")
                checked += 1
            except (ValueError, OSError) as error:
                errors.append(str(error))
        for row in self.db.execute("SELECT * FROM analyses"):
            try:
                payload = validate_analysis(json.loads(row["payload"]))
                if digest(payload) != row["sha256"]:
                    errors.append(f"Analysis hash mismatch: {row['case_id']} v{row['version']}")
            except (ValueError, TypeError) as error:
                errors.append(f"Invalid analysis {row['case_id']}: {error}")
        for case in self.db.execute("SELECT * FROM cases"):
            events = list(self.db.execute("SELECT * FROM ingest_events WHERE case_id=? ORDER BY version", (case["id"],)))
            if not events:
                errors.append(f"Case has no ingestion history: {case['id']}")
            for expected_version, row in enumerate(events, 1):
                try:
                    payload = json.loads(row["payload"])
                    exact_keys(payload, METADATA_FIELDS, "ingest metadata")
                    if any(not isinstance(value, str) for value in payload.values()):
                        raise ValueError("Ingest metadata must contain string values")
                    event = {"case_id": row["case_id"], "version": row["version"],
                             "payload": payload, "created_at": row["created_at"]}
                    if row["version"] != expected_version or digest(event) != row["event_sha256"]:
                        errors.append(f"Ingest event hash/version mismatch: {case['id']} v{row['version']}")
                    if expected_version == 1 and payload != {key: case[key] for key in METADATA_FIELDS}:
                        errors.append(f"Original case metadata mismatch: {case['id']}")
                except (ValueError, TypeError) as error:
                    errors.append(f"Invalid ingest event {case['id']}: {error}")
        for row in self.db.execute("SELECT * FROM rules"):
            try:
                payload = json.loads(row["payload"])
                validate_rule(payload)
                if digest(payload) != row["rule_content_sha256"]:
                    errors.append(f"Rule content hash mismatch: {row['id']}")
                if row["state"] not in STATES or row["scope"] != payload["scope"] or row["domain"] != payload["domain"]:
                    errors.append(f"Rule metadata mismatch: {row['id']}")
                feedback = list(self.db.execute("SELECT * FROM feedback WHERE rule_id=? ORDER BY revision", (row["id"],)))
                if row["revision"] != len(feedback) + 1 or (feedback and (feedback[-1]["state"] != row["state"] or feedback[-1]["revision"] != row["revision"])):
                    errors.append(f"Rule revision mismatch: {row['id']}")
                if not feedback and row["state"] != "candidate":
                    errors.append(f"Rule state has no feedback event: {row['id']}")
                for expected_revision, event in enumerate(feedback, 2):
                    if event["revision"] != expected_revision or event["state"] not in STATES or not event["quote"].strip():
                        errors.append(f"Invalid feedback event: {row['id']} revision {event['revision']}")
                    event_content = {key: event[key] for key in ("rule_id", "revision", "state", "quote", "created_at")}
                    if digest(event_content) != event["feedback_sha256"]:
                        errors.append(f"Feedback hash mismatch: {row['id']} revision {event['revision']}")
                linked_ids = {item[0] for item in self.db.execute("SELECT case_id FROM rule_cases WHERE rule_id=?", (row["id"],))}
                if linked_ids != set(payload["case_ids"]):
                    errors.append(f"Rule case-link mismatch: {row['id']}")
                if row["state"] == "active" and (not feedback or not feedback[-1]["quote"].strip()):
                    errors.append(f"Active rule missing user quote: {row['id']}")
                for case_id in payload["case_ids"]:
                    if self.show_case(case_id, history=False)["project"] not in {"global", row["scope"]}:
                        errors.append(f"Rule crosses project boundary: {row['id']}")
            except (ValueError, TypeError) as error:
                errors.append(f"Invalid rule {row['id']}: {error}")
        for row in self.db.execute("SELECT * FROM learning_commits"):
            try:
                receipt = self.show_learning(row["session_id"])
                content = {key: receipt[key] for key in ("session_id", "proposal_sha256", "consent_sha256", "consent", "result", "created_at")}
                if digest(content) != row["commit_sha256"] or digest(receipt["consent"]) != row["consent_sha256"]:
                    errors.append(f"Learning receipt hash mismatch: {row['session_id']}")
                saved = receipt["result"]
                case = self.show_case(saved["case_id"])
                if case["project"] != saved["scope"] or case["source_key"] != "learning:" + row["session_id"]:
                    errors.append(f"Learning receipt case mismatch: {row['session_id']}")
                if saved["analysis_version"] not in {item["version"] for item in case["analyses"]}:
                    errors.append(f"Learning receipt missing analysis: {row['session_id']}")
                for item in saved["rules"]:
                    if saved["case_id"] not in self.show_rule(item["id"])["payload"]["case_ids"]:
                        errors.append(f"Learning receipt rule mismatch: {row['session_id']}")
            except (ValueError, TypeError, KeyError) as error:
                errors.append(f"Invalid learning receipt {row['session_id']}: {error}")
        unarchived = self.db.execute("SELECT COUNT(*) FROM cases WHERE asset_sha256 IS NULL").fetchone()[0]
        return {"ok": not errors, "database_integrity": integrity, "checked_assets": checked,
                "cases_without_archived_asset": unarchived, "errors": errors}


def write_new_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            created = True
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--home", help="Library directory; otherwise ARCH_TASTE_HOME or ~/Documents/ArchitectureTaste")
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("init", "migrate", "status", "doctor"):
        commands.add_parser(name)
    for name in ("preview-learning", "commit-learning"):
        command = commands.add_parser(name)
        command.add_argument("--json", required=True)
        if name == "commit-learning":
            command.add_argument("--consent", required=True)
    command = commands.add_parser("show-learning")
    command.add_argument("--session-id", required=True)
    command = commands.add_parser("import")
    command.add_argument("--file")
    for name in ("url", "source-note", "title", "note"):
        command.add_argument("--" + name, default="")
    command.add_argument("--project", default="global")
    command.add_argument("--domain", choices=DOMAINS, default="architecture")
    command = commands.add_parser("analyze")
    command.add_argument("--id", required=True)
    command.add_argument("--json", required=True)
    command = commands.add_parser("rule")
    command.add_argument("--json", required=True)
    command = commands.add_parser("feedback")
    command.add_argument("--id", required=True)
    command.add_argument("--state", choices=STATES, required=True)
    command.add_argument("--quote", required=True)
    command = commands.add_parser("show")
    command.add_argument("--id", required=True)
    for name in ("search", "snapshot"):
        command = commands.add_parser(name)
        command.add_argument("--query", default="")
        command.add_argument("--project", default="global", required=name == "snapshot")
        command.add_argument("--domain", choices=DOMAINS)
        command.add_argument("--limit", type=int, default=5)
        if name == "snapshot":
            command.add_argument("--out", required=True)
    command = commands.add_parser("export")
    command.add_argument("--out", required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    home = args.home or os.environ.get("ARCH_TASTE_HOME") or str(Path.home() / "Documents" / "ArchitectureTaste")
    library = None
    try:
        if args.command in ("import", "analyze", "rule"):
            raise ValueError("Direct learning writes are disabled. Show preview-learning, ask the user after analysis, then use commit-learning with their actual selected-save reply")
        proposal = consent = None
        if args.command in ("preview-learning", "commit-learning"):
            proposal = validate_proposal(read_json(args.json))
            if args.command == "preview-learning":
                print(json.dumps(preview_learning(proposal), ensure_ascii=False, indent=2))
                return 0
            consent = validate_consent(proposal, read_json(args.consent))
            if consent["decision"] == "decline":
                print(json.dumps({"saved": False, "decision": "decline", "session_id": proposal["session_id"]}, ensure_ascii=False))
                return 0
        library = Library(home, initialize=args.command == "init", migrate=args.command == "migrate")
        if args.command in ("init", "status", "migrate"):
            output = library.status()
        elif args.command == "commit-learning":
            output = library.commit_learning(proposal, consent)
        elif args.command == "show-learning":
            output = library.show_learning(args.session_id)
        elif args.command == "feedback":
            output = library.feedback(args.id, args.state, args.quote)
        elif args.command == "show":
            output = library.show_case(args.id) if args.id.startswith("CASE-") else library.show_rule(args.id)
        elif args.command == "search":
            output = library.search(args.query, args.project, args.domain, args.limit)
        elif args.command == "snapshot":
            output = library.snapshot(project=args.project, domain=args.domain, query=args.query, out=args.out, limit=args.limit)
        elif args.command == "export":
            output = library.export(args.out)
        else:
            output = library.doctor()
        print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
        return 1 if args.command == "doctor" and not output["ok"] else 0
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print(json.dumps({"error": str(error), "command": args.command}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if library:
            library.close()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
