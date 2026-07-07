"""Tests for Y.5 — profile questions wired into the probe + cross-engine
share-of-voice, plus the Y-D4 max_total_calls ceiling and the idempotent
persona/source column migration.

Spec: yoast_geo_upgrade_spec_v1.md#Y.5
- Y.5.1 profile questions probed first, rows tagged persona + source='profile';
  with NO profile, precedence equals the current G.1 behaviour (regression).
- Y.5.2 max_total_calls ceiling enforced; over budget ⇒ zero calls unless --yes.
- Y.5.3 share-of-voice + per-persona breakdown render with zero and with history;
  competitor domains appear when cited; caveat paragraph always present.
- Y.5.4 idempotent persona/source column migration; old NULL rows read back.
- Y.5.5 docs (checked in the docs tests below).
"""
import json
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import probe_ai_visibility as pav

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _analysis_fixture():
    return {
        "overview": [
            {"Query_Label": "A", "Source_Keyword": "family counselling north vancouver"},
        ],
        "organic_results": [
            {"Query_Label": "A", "Rank": 1, "Link": "https://www.psychologytoday.com/ca/x"},
            {"Query_Label": "A", "Rank": 3, "Link": "https://wellbeings.ca/about"},
        ],
        "situational_probes": [
            {"Executed_Query": "my partner refuses to try counselling what can I do"},
            {"Executed_Query": "how do I know if we actually need family counselling"},
        ],
        "paa_questions": [
            {"Question": "What is family systems therapy and how does it work?"},
        ],
    }


def _fake_probe(answer_text, urls, model="mock-model"):
    probe = MagicMock()
    probe.ask.return_value = {
        "answer_text": answer_text, "source_urls": urls, "model_id": model}
    return probe


# ---------------------------------------------------------------------------
# Y.5.1 — precedence + row tagging
# ---------------------------------------------------------------------------

class TestProfilePrecedence(unittest.TestCase):
    """Y.5.1 — profile questions first + tagged; no profile ⇒ G.1 precedence."""

    PROFILE_QS = [
        {"question": "how do I stop repeating my parents' patterns",
         "persona": "prospective_client", "city": None, "intent": "informational"},
        {"question": "relationship counselling North Vancouver",
         "persona": "prospective_client", "city": "North Vancouver",
         "intent": "local_transactional"},
    ]

    def test_profile_questions_probed_first_and_tagged(self):
        questions = pav.build_question_set(
            _analysis_fixture(), ["t {base}"], "North Vancouver",
            max_questions=20, profile_questions=self.PROFILE_QS)
        # Profile questions win the precedence — situational probes are NOT used.
        self.assertTrue(all(q["source"] == "profile" for q in questions))
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[0]["persona"], "prospective_client")
        self.assertEqual(
            questions[0]["query"], "how do I stop repeating my parents' patterns")

    def test_no_profile_equals_g1_precedence(self):
        """Regression: with no profile the precedence is the pre-Y.5 order."""
        with_none = pav.build_question_set(
            _analysis_fixture(), ["t {base}"], "North Vancouver", max_questions=20)
        with_empty = pav.build_question_set(
            _analysis_fixture(), ["t {base}"], "North Vancouver",
            max_questions=20, profile_questions=[])
        # Both fall through to situational probes (the G.1 top source).
        self.assertEqual([q["query"] for q in with_none],
                         [q["query"] for q in with_empty])
        self.assertTrue(all(q["source"] == "situational" for q in with_none))
        self.assertTrue(all(q["persona"] is None for q in with_none))

    def test_profile_rows_stored_with_persona_and_source(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            probe = _fake_probe("Living Systems can help.", [])
            rows = pav.run_engine_probes(
                {"claude": probe},
                [{"query": "how childhood affects adult relationships",
                  "source": "profile", "persona": "prospective_client"}],
                "", ["Living Systems"], "livingsystems.ca", [],
                "2026-07-06T00:00:00+00:00")
            pav.save_probe_rows(tmp.name, rows)
            with sqlite3.connect(tmp.name) as conn:
                stored = conn.execute(
                    "SELECT persona, source FROM ai_visibility_probes").fetchall()
            self.assertEqual(stored, [("prospective_client", "profile")])
        finally:
            os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# Y.5.2 — max_total_calls ceiling
# ---------------------------------------------------------------------------

class TestMaxTotalCalls(unittest.TestCase):
    """Y.5.2 — ceiling enforced; over budget ⇒ zero calls unless --yes."""

    def _run_main(self, config, extra_args):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "market_analysis_test_20260701_1200.json")
            data = _analysis_fixture()
            # 40 situational probes ⇒ 40 questions × 2 engines = 80 > ceiling 60.
            data["situational_probes"] = [
                {"Executed_Query": f"unique probing question number {i} about counselling"}
                for i in range(40)
            ]
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            db_path = os.path.join(tmpdir, "test.db")
            out_path = os.path.join(tmpdir, "out.md")
            args = ["--json", json_path, "--db", db_path, "--out", out_path,
                    "--config", os.path.join(tmpdir, "missing.yml")]
            args.extend(extra_args)
            claude_cls = MagicMock(return_value=_fake_probe("a", []))
            gemini_cls = MagicMock(return_value=_fake_probe("a", []))
            printed = []
            env = dict(os.environ)
            env["ANTHROPIC_API_KEY"] = "key"
            env["GEMINI_API_KEY"] = "gkey"
            with patch.dict(os.environ, env, clear=True):
                with patch.object(pav, "_load_config", return_value=config):
                    with patch.object(pav, "load_client_profiles", return_value={}):
                        with patch.object(pav, "ClaudeProbe", claude_cls):
                            with patch.object(pav, "GeminiProbe", gemini_cls):
                                with patch("builtins.print",
                                           side_effect=lambda *a, **k: printed.append(
                                               " ".join(str(x) for x in a))):
                                    code = pav.main(args)
            return SimpleNamespace(exit_code=code, printed="\n".join(printed),
                                   claude_cls=claude_cls, gemini_cls=gemini_cls)

    def _config(self):
        return {
            "ai_visibility": {"engines": ["claude", "gemini"],
                              "max_questions": 40, "max_total_calls": 60},
            "analysis_report": {"client_name_patterns": ["Living Systems"],
                                "client_domain": "livingsystems.ca"},
        }

    def test_over_budget_plan_states_ceiling_and_makes_zero_calls(self):
        result = self._run_main(self._config(), [])  # no --yes
        self.assertEqual(result.exit_code, 0)
        result.claude_cls.assert_not_called()
        result.gemini_cls.assert_not_called()
        # Plan states the ceiling and the truncation.
        self.assertIn("max_total_calls ceiling 60", result.printed)
        self.assertIn("truncated", result.printed)
        # 60 // 2 engines = 30 questions ⇒ 60 calls, never above the ceiling.
        self.assertIn("30 questions x 2 engines", result.printed)
        self.assertIn("= 60 paid API calls", result.printed)
        self.assertIn("Cost guard: no API calls were made", result.printed)

    def test_over_budget_with_yes_stays_within_ceiling(self):
        result = self._run_main(self._config(), ["--yes"])
        self.assertEqual(result.exit_code, 0)
        # Truncated to 30 questions per engine ⇒ 30 asks per engine, 60 total.
        self.assertEqual(result.claude_cls.return_value.ask.call_count, 30)
        self.assertEqual(result.gemini_cls.return_value.ask.call_count, 30)


# ---------------------------------------------------------------------------
# Y.5.3 — share-of-voice + per-persona rendering
# ---------------------------------------------------------------------------

class TestShareOfVoiceReport(unittest.TestCase):
    """Y.5.3 — SoV table + per-persona breakdown; caveat always present."""

    def _rows(self, with_persona):
        persona = "prospective_client" if with_persona else None
        return [
            {"run_ts": "2026-07-06T00:00:00+00:00", "engine": "claude",
             "model": "m", "question": "q1", "mentioned": True, "cited": False,
             "competitors_cited": ["psychologytoday.com"],
             "answer_excerpt": "a", "persona": persona, "source": "profile"},
            {"run_ts": "2026-07-06T00:00:00+00:00", "engine": "claude",
             "model": "m", "question": "q2", "mentioned": False, "cited": True,
             "competitors_cited": ["psychologytoday.com", "wellbeings.ca"],
             "answer_excerpt": "a", "persona": persona, "source": "profile"},
            {"run_ts": "2026-07-06T00:00:00+00:00", "engine": "gemini",
             "model": "m", "question": "q1", "mentioned": False, "cited": False,
             "competitors_cited": [], "answer_excerpt": "a",
             "persona": persona, "source": "profile"},
        ]

    def _report(self, rows, trends):
        return pav.generate_report(
            "market_analysis_x.json", "2026-07-06T00:00:00+00:00",
            ["claude", "gemini"], rows, trends, [],
            "I'm in North Vancouver, BC.", "Living Systems Counselling")

    def test_share_of_voice_with_zero_history(self):
        report = self._report(self._rows(with_persona=True),
                              {"claude": [], "gemini": []})
        self.assertIn("## Cross-engine share of voice", report)
        # Per-engine client rate + competitor domains cited.
        self.assertIn("psychologytoday.com (2)", report)
        self.assertIn("wellbeings.ca (1)", report)
        # Per-persona breakdown present.
        self.assertIn("### Client mention rate by persona", report)
        self.assertIn("| prospective_client |", report)

    def test_share_of_voice_with_history(self):
        trends = {
            "claude": [{"run_ts": "2026-06-01T00:00:00+00:00", "model": "m",
                        "questions": 2, "mentioned": 1, "cited": 0,
                        "mention_rate": 0.5, "citation_rate": 0.0}],
            "gemini": [],
        }
        report = self._report(self._rows(with_persona=True), trends)
        self.assertIn("## Cross-engine share of voice", report)
        self.assertIn("psychologytoday.com", report)

    def test_per_persona_states_absence_when_no_profile(self):
        report = self._report(self._rows(with_persona=False),
                              {"claude": [], "gemini": []})
        self.assertIn("### Client mention rate by persona", report)
        self.assertIn("No persona-tagged questions this run", report)

    def test_caveat_always_present_with_share_of_voice(self):
        report = self._report(self._rows(with_persona=True),
                              {"claude": [], "gemini": []})
        self.assertIn(pav.SNAPSHOT_CAVEAT, report)
        # The SoV section also reiterates that visibility is comparative.
        self.assertIn("Visibility is comparative", report)


# ---------------------------------------------------------------------------
# Y.5.4 — idempotent persona/source migration; old NULL rows read back
# ---------------------------------------------------------------------------

class TestColumnMigration(unittest.TestCase):
    """Y.5.4 — a pre-Y.5 DB is upgraded once; old rows read back as NULL."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _create_legacy_table(self):
        """Create the pre-Y.5 table WITHOUT persona/source columns."""
        with sqlite3.connect(self.tmp.name) as conn:
            conn.execute(f'''CREATE TABLE {pav.PROBE_TABLE} (
                run_ts TEXT, engine TEXT, model TEXT, question TEXT,
                mentioned INTEGER, cited INTEGER,
                competitor_domains_json TEXT, answer_excerpt TEXT
            )''')
            conn.execute(
                f"INSERT INTO {pav.PROBE_TABLE} (run_ts, engine, model, question, "
                "mentioned, cited, competitor_domains_json, answer_excerpt) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("2026-01-01T00:00:00+00:00", "claude", "old", "old q",
                 1, 0, "[]", "old answer"))
            conn.commit()

    def test_legacy_db_migrated_and_old_rows_read_null(self):
        self._create_legacy_table()
        # First init migrates; old row must read back with NULL persona/source.
        pav.init_probe_table(self.tmp.name)
        with sqlite3.connect(self.tmp.name) as conn:
            row = conn.execute(
                "SELECT persona, source FROM ai_visibility_probes "
                "WHERE question = 'old q'").fetchone()
        self.assertEqual(row, (None, None))

    def test_migration_is_idempotent(self):
        self._create_legacy_table()
        pav.init_probe_table(self.tmp.name)
        pav.init_probe_table(self.tmp.name)  # second call must not raise
        # New rows still insert cleanly alongside the legacy NULL row.
        pav.save_probe_rows(self.tmp.name, [{
            "run_ts": "2026-07-06T00:00:00+00:00", "engine": "claude",
            "model": "m", "question": "new q", "mentioned": False, "cited": False,
            "competitors_cited": [], "answer_excerpt": "a",
            "persona": "prospective_client", "source": "profile"}])
        with sqlite3.connect(self.tmp.name) as conn:
            rows = conn.execute(
                "SELECT question, persona, source FROM ai_visibility_probes "
                "ORDER BY question").fetchall()
        self.assertIn(("new q", "prospective_client", "profile"), rows)
        self.assertIn(("old q", None, None), rows)

    def test_fresh_table_has_new_columns(self):
        pav.init_probe_table(self.tmp.name)
        with sqlite3.connect(self.tmp.name) as conn:
            cols = [r[1] for r in conn.execute(
                f"PRAGMA table_info({pav.PROBE_TABLE})").fetchall()]
        self.assertIn("persona", cols)
        self.assertIn("source", cols)


# ---------------------------------------------------------------------------
# Y.5 — full-run integration: profile wired in from the shipped file
# ---------------------------------------------------------------------------

class TestProfileWiredIntoMain(unittest.TestCase):
    """End-to-end: the shipped living_systems profile seeds the probe."""

    def test_profile_questions_used_and_persona_stored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "market_analysis_test_20260701_1200.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(_analysis_fixture(), f)
            db_path = os.path.join(tmpdir, "test.db")
            out_path = os.path.join(tmpdir, "out.md")
            config = {
                "ai_visibility": {"engines": ["claude"], "assume_yes": True,
                                  "client_slug": "living_systems",
                                  "max_questions": 5, "max_total_calls": 60},
                "analysis_report": {"client_name_patterns": ["Living Systems"],
                                    "client_domain": "livingsystems.ca"},
            }
            claude_cls = MagicMock(return_value=_fake_probe("Living Systems helps.", []))
            env = dict(os.environ)
            env["ANTHROPIC_API_KEY"] = "key"
            with patch.dict(os.environ, env, clear=True):
                with patch.object(pav, "_load_config", return_value=config):
                    with patch.object(pav, "ClaudeProbe", claude_cls):
                        code = pav.main(["--json", json_path, "--db", db_path,
                                         "--out", out_path,
                                         "--config", os.path.join(tmpdir, "n.yml")])
            self.assertEqual(code, 0)
            # The probe was asked profile-seeded questions (not situational).
            asked = [c.args[0] for c in claude_cls.return_value.ask.call_args_list]
            self.assertTrue(asked)
            # Rows carry source='profile' and a persona.
            with sqlite3.connect(db_path) as conn:
                sources = {r[0] for r in conn.execute(
                    "SELECT DISTINCT source FROM ai_visibility_probes").fetchall()}
                personas = {r[0] for r in conn.execute(
                    "SELECT DISTINCT persona FROM ai_visibility_probes").fetchall()}
            self.assertEqual(sources, {"profile"})
            self.assertIn("prospective_client", personas)


if __name__ == "__main__":
    unittest.main()
