"""Chunk Y14 — one cache for both keyword signals.

`_KeywordSignalClient` exists so the fetch, quota and "404 is not an error"
rules cannot drift between the two per-keyword Moz signals. The cache was left
out of it: `MozKeywordClient` and `MozIntentClient` each carried their own
`_init_cache_table` / `_cache_lookup` / `_cache_store`, so the three rules that
must hold for both — a row past its TTL is ignored, a cached failure is never
served, a measured absence is served — were written twice.

Every rule here is asserted against *both* clients through the same test, which
is the point: a rule asserted against one class was how a divergence could pass.

Spec: docs/review_2026-11-04/PLAN_Y14_one_cache_for_both_signals.md
"""

import ast
import io
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import db_connect
import moz_keywords


_UTC = timezone.utc

#: Each signal: its client, a cached-ok payload, and the field a reader of
#: that signal's block looks at.
SIGNALS = (
    ("keyword metrics", moz_keywords.MozKeywordClient,
     {"volume": 140, "difficulty": 31, "organic_ctr": 62, "priority": 48},
     "volume"),
    ("search intent", moz_keywords.MozIntentClient,
     {"primary_intents": ["informational"], "scores": {"informational": 0.8}},
     "primary_intents"),
)


class _CacheCase(unittest.TestCase):

    def setUp(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, directory,
                        ignore_errors=True)
        self.db_path = os.path.join(directory, "t.db")

    def client(self, cls, **kwargs):
        return cls(db_path=self.db_path, **kwargs)

    def seed(self, client, keyword, status, payload=None, age_days=0):
        """Put one row in that client's cache table, *age_days* old."""
        payload = payload or {}
        names = [name for name, _type in client.CACHE_PAYLOAD_COLUMNS]
        mapped = client._payload_for_cache(payload) if payload else {}
        values = tuple(mapped.get(name) for name in names)
        fetched_at = (datetime.now(_UTC)
                      - timedelta(days=age_days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {client.CACHE_TABLE_NAME} "
                f"(keyword, engine, locale, device, status, "
                f"{', '.join(names)}, fetched_at) "
                f"VALUES ({','.join('?' * (6 + len(names)))})",
                [keyword, client._engine, client._locale, client._device,
                 status, *values, fetched_at])
            conn.commit()


class TestTheThreeRulesHoldForEverySignal(_CacheCase):

    def test_a_fresh_ok_row_is_served_from_cache(self):
        for label, cls, payload, field in SIGNALS:
            with self.subTest(label):
                client = self.client(cls)
                self.seed(client, "kw", moz_keywords.STATUS_OK, payload)
                cached, to_fetch = client._cache_lookup(["kw"])
                self.assertEqual(to_fetch, [], label)
                self.assertTrue(cached["kw"]["data_available"])
                self.assertEqual(cached["kw"][field], payload[field])

    def test_a_row_past_its_ttl_is_ignored(self):
        """Rule 1. It was one `continue` written twice."""
        for label, cls, payload, _field in SIGNALS:
            with self.subTest(label):
                client = self.client(cls, cache_ttl_days=30)
                self.seed(client, "kw", moz_keywords.STATUS_OK, payload,
                          age_days=31)
                cached, to_fetch = client._cache_lookup(["kw"])
                self.assertEqual(cached, {}, label)
                self.assertEqual(to_fetch, ["kw"])

    def test_a_row_with_no_timestamp_is_not_treated_as_fresh(self):
        """Still rule 1. A row carrying no `fetched_at` cannot be shown to be
        inside the TTL, so it is re-fetched rather than served indefinitely —
        comparing a NULL against the cutoff would have served it."""
        for label, cls, payload, _field in SIGNALS:
            with self.subTest(label):
                client = self.client(cls)
                self.seed(client, "kw", moz_keywords.STATUS_OK, payload)
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        f"UPDATE {client.CACHE_TABLE_NAME} "
                        f"SET fetched_at = NULL")
                    conn.commit()
                cached, to_fetch = client._cache_lookup(["kw"])
                self.assertEqual(cached, {}, label)
                self.assertEqual(to_fetch, ["kw"])

    def test_a_cached_failure_is_never_served(self):
        """Rule 2. A keyword whose last fetch errored is re-fetched, not
        reported as absent for a month."""
        for label, cls, _payload, _field in SIGNALS:
            with self.subTest(label):
                client = self.client(cls)
                self.seed(client, "kw", moz_keywords.STATUS_ERROR)
                cached, to_fetch = client._cache_lookup(["kw"])
                self.assertEqual(cached, {}, label)
                self.assertEqual(to_fetch, ["kw"])

    def test_a_measured_absence_is_served_from_cache(self):
        """Rule 3. Moz holding no record is a fact, not a failed fetch, so it
        is not bought again every run — and the reason names this signal."""
        for label, cls, _payload, _field in SIGNALS:
            with self.subTest(label):
                client = self.client(cls)
                self.seed(client, "kw", moz_keywords.STATUS_NO_RECORD)
                cached, to_fetch = client._cache_lookup(["kw"])
                self.assertEqual(to_fetch, [], label)
                self.assertFalse(cached["kw"]["data_available"])
                self.assertEqual(cached["kw"]["status"],
                                 moz_keywords.STATUS_NO_RECORD)
                self.assertIn(client.SIGNAL_NAME, cached["kw"]["reason"])

    def test_an_unknown_keyword_is_fetched(self):
        for label, cls, _payload, _field in SIGNALS:
            with self.subTest(label):
                client = self.client(cls)
                self.assertEqual(client._cache_lookup(["kw"]), ({}, ["kw"]))


class TestWhatIsStoredIsWhatComesBack(_CacheCase):

    def test_a_stored_block_round_trips(self):
        for label, cls, payload, field in SIGNALS:
            with self.subTest(label):
                client = self.client(cls)
                block = dict(payload, status=moz_keywords.STATUS_OK,
                             data_available=True)
                client._cache_store({"kw": block})
                cached, to_fetch = client._cache_lookup(["kw"])
                self.assertEqual(to_fetch, [], label)
                self.assertEqual(cached["kw"][field], payload[field])

    def test_a_failure_is_not_written_to_the_cache(self):
        for label, cls, _payload, _field in SIGNALS:
            with self.subTest(label):
                client = self.client(cls)
                client._cache_store(
                    {"kw": moz_keywords.absent(moz_keywords.STATUS_ERROR,
                                               "Moz returned 500")})
                self.assertEqual(self._rows(client), 0, label)

    def test_a_measured_absence_is_written_to_the_cache(self):
        for label, cls, _payload, _field in SIGNALS:
            with self.subTest(label):
                client = self.client(cls)
                client._cache_store(
                    {"kw": moz_keywords.absent(moz_keywords.STATUS_NO_RECORD,
                                               "nothing held")})
                self.assertEqual(self._rows(client), 1, label)

    def test_the_write_is_committed(self):
        """`db_connect.connection` commits on a clean exit; the two old
        `_cache_store` copies each called `conn.commit()` as well, and the
        shared one does not — so this is what proves the row is durable."""
        for label, cls, payload, _field in SIGNALS:
            with self.subTest(label):
                client = self.client(cls)
                client._cache_store({"kw": dict(
                    payload, status=moz_keywords.STATUS_OK)})
                with sqlite3.connect(self.db_path) as conn:
                    count = conn.execute(
                        f"SELECT COUNT(*) FROM {client.CACHE_TABLE_NAME}"
                    ).fetchone()[0]
                self.assertEqual(count, 1, label)

    def _rows(self, client):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                f"SELECT COUNT(*) FROM {client.CACHE_TABLE_NAME}"
            ).fetchone()[0]


class TestTheColumnOrderIsNotASecondContract(_CacheCase):
    """The cold review's finding 3. The hooks used to exchange a positional
    tuple, so the order of `CACHE_PAYLOAD_COLUMNS` was a second, unwritten
    contract — reordering it would have handed every keyword its neighbour's
    figure, with no value out of range to notice. They exchange a mapping
    keyed by column name instead, so the order cannot carry meaning."""

    def test_reordering_the_columns_changes_nothing_a_reader_sees(self):
        for label, cls, payload, _field in SIGNALS:
            with self.subTest(label):
                spec = cls.CACHE_PAYLOAD_COLUMNS
                reversed_spec = tuple(reversed(spec))

                class Reordered(cls):
                    CACHE_TABLE_NAME = cls.CACHE_TABLE_NAME
                    CACHE_PAYLOAD_COLUMNS = reversed_spec

                straight = self.client(cls)
                straight._cache_store({"kw": dict(
                    payload, status=moz_keywords.STATUS_OK)})
                expected, _ = straight._cache_lookup(["kw"])

                other = os.path.join(
                    os.path.dirname(self.db_path), "reordered.db")
                flipped = Reordered(db_path=other)
                flipped._cache_store({"kw": dict(
                    payload, status=moz_keywords.STATUS_OK)})
                got, to_fetch = flipped._cache_lookup(["kw"])

                self.assertEqual(to_fetch, [], label)
                self.assertEqual(got, expected, label)

    def test_each_hook_names_the_columns_the_table_declares(self):
        """A column the store never fills is always NULL; a key the store
        emits that the table has no column for is dropped on the floor."""
        for label, cls, payload, _field in SIGNALS:
            with self.subTest(label):
                client = self.client(cls)
                emitted = client._payload_for_cache(
                    dict(payload, status=moz_keywords.STATUS_OK))
                self.assertEqual(set(emitted), set(client._payload_names()),
                                 label)


class TestAnExistingTableGainsADeclaredColumn(_CacheCase):
    """The cold review's finding 2. `CREATE TABLE IF NOT EXISTS` does not
    alter a table that already exists, and adding a payload column is now a
    one-line edit. Without a migration, every existing installation fails on
    the first write and `brief_rendering` reports the signal as unavailable
    for every keyword, every run."""

    def test_a_column_added_to_the_spec_is_added_to_the_live_table(self):
        for label, cls, payload, _field in SIGNALS:
            with self.subTest(label):
                client = self.client(cls)
                client._cache_store({"kw": dict(
                    payload, status=moz_keywords.STATUS_OK)})

                class Widened(cls):
                    CACHE_TABLE_NAME = cls.CACHE_TABLE_NAME
                    CACHE_PAYLOAD_COLUMNS = (cls.CACHE_PAYLOAD_COLUMNS
                                             + (("cpc", "INTEGER"),))

                widened = Widened(db_path=self.db_path)
                with sqlite3.connect(self.db_path) as conn:
                    columns = {row[1] for row in conn.execute(
                        f"PRAGMA table_info({cls.CACHE_TABLE_NAME})")}
                self.assertIn("cpc", columns, label)

                # The rows that were already there survive the migration, and
                # the new column reads as NULL — which every consumer already
                # treats as "not held".
                widened._cache_store({"kw2": dict(
                    payload, status=moz_keywords.STATUS_OK)})
                cached, _ = widened._cache_lookup(["kw", "kw2"])
                self.assertEqual(set(cached), {"kw", "kw2"}, label)

    def test_a_column_the_spec_dropped_is_left_alone(self):
        """Every query here names its columns, so an orphan column is inert;
        dropping it would mean rewriting the table and risking the rows."""
        for label, cls, payload, _field in SIGNALS:
            with self.subTest(label):
                client = self.client(cls)
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(f"ALTER TABLE {cls.CACHE_TABLE_NAME} "
                                 f"ADD COLUMN legacy TEXT")
                    conn.commit()
                again = self.client(cls)
                again._cache_store({"kw": dict(
                    payload, status=moz_keywords.STATUS_OK)})
                cached, to_fetch = again._cache_lookup(["kw"])
                self.assertEqual(to_fetch, [], label)
                self.assertIn("kw", cached)


class TestACachedRowThisSignalCannotReadIsCounted(_CacheCase):
    """The cold review's finding 4. A row the subclass returns None for is
    re-fetched, which costs billed Moz rows every run, so the count is
    stated rather than discarded."""

    def test_the_unusable_rows_are_logged_with_their_share(self):
        cls = moz_keywords.MozKeywordClient

        class Unreadable(cls):
            CACHE_TABLE_NAME = cls.CACHE_TABLE_NAME
            CACHE_PAYLOAD_COLUMNS = cls.CACHE_PAYLOAD_COLUMNS

            def _block_from_cache(self, payload):
                return None

        seeded = self.client(cls)
        seeded._cache_store({"kw": {"status": moz_keywords.STATUS_OK,
                                    "volume": 10}})
        client = Unreadable(db_path=self.db_path)
        with self.assertLogs(moz_keywords.logger, level="WARNING") as logs:
            cached, to_fetch = client._cache_lookup(["kw"])
        self.assertEqual(cached, {})
        self.assertEqual(to_fetch, ["kw"])
        self.assertTrue(any("1 of 1" in line and "unusable" in line
                            for line in logs.output), logs.output)

    def test_a_clean_lookup_says_nothing_about_unusable_rows(self):
        client = self.client(moz_keywords.MozKeywordClient)
        client._cache_store({"kw": {"status": moz_keywords.STATUS_OK,
                                    "volume": 10}})
        with self.assertNoLogs(moz_keywords.logger, level="WARNING"):
            client._cache_lookup(["kw"])


class TestAnIncompleteSignalSaysWhatItIsMissing(unittest.TestCase):
    """The cold review's finding 5. An empty spec used to surface as `near
    "(": syntax error`, or — for an empty column tuple — as a real table that
    failed on the first lookup. Neither names the class or the attribute, and
    the message a user sees comes through `brief_rendering`'s handler."""

    def test_a_signal_with_no_table_name_names_the_attribute(self):
        class NoTable(moz_keywords.MozKeywordClient):
            CACHE_TABLE_NAME = ""

        with self.assertRaises(NotImplementedError) as caught:
            NoTable(db_path=":memory:")
        self.assertIn("NoTable", str(caught.exception))
        self.assertIn("CACHE_TABLE_NAME", str(caught.exception))

    def test_a_signal_with_no_payload_columns_names_the_attribute(self):
        class NoColumns(moz_keywords.MozKeywordClient):
            CACHE_PAYLOAD_COLUMNS = ()

        with self.assertRaises(NotImplementedError) as caught:
            NoColumns(db_path=":memory:")
        self.assertIn("NoColumns", str(caught.exception))
        self.assertIn("CACHE_PAYLOAD_COLUMNS", str(caught.exception))


class TestAnUnreadableBlobIsNotSilentlyAnEmptyOpinion(unittest.TestCase):
    """Also finding 3. `_decode_json` emptied a blob that parsed but held the
    wrong shape, which reads as "Moz has no opinion" rather than as a bug."""

    def test_a_blob_of_the_wrong_shape_is_logged(self):
        with self.assertLogs(moz_keywords.logger, level="WARNING") as logs:
            self.assertEqual(moz_keywords._decode_json('{"a": 1}', list), [])
        self.assertTrue(any("expected list" in line for line in logs.output),
                        logs.output)

    def test_a_blob_of_the_right_shape_is_not_logged(self):
        with self.assertNoLogs(moz_keywords.logger, level="WARNING"):
            self.assertEqual(moz_keywords._decode_json('["a"]', list), ["a"])


class TestTheCacheKeyIsTheQueryContext(_CacheCase):
    """All three of engine, locale and device change Moz's answer, so a row
    cached under one context must not be served under another."""

    def test_another_locale_does_not_read_this_locales_row(self):
        for label, cls, payload, _field in SIGNALS:
            with self.subTest(label):
                here = self.client(cls, locale="en-CA")
                there = self.client(cls, locale="en-US")
                here._cache_store({"kw": dict(payload,
                                              status=moz_keywords.STATUS_OK)})
                self.assertEqual(there._cache_lookup(["kw"]), ({}, ["kw"]),
                                 label)

    def test_the_table_is_created_with_this_signals_columns(self):
        for label, cls, _payload, _field in SIGNALS:
            with self.subTest(label):
                client = self.client(cls)
                with sqlite3.connect(self.db_path) as conn:
                    columns = {row[1] for row in conn.execute(
                        f"PRAGMA table_info({client.CACHE_TABLE_NAME})")}
                expected = {"keyword", "engine", "locale", "device", "status",
                            "fetched_at"}
                expected |= {name for name, _t
                             in client.CACHE_PAYLOAD_COLUMNS}
                self.assertEqual(columns, expected, label)


class TestTheCacheLivesInOnePlace(unittest.TestCase):

    def test_neither_subclass_carries_its_own_cache_machinery(self):
        """The whole point: a rule fixed in one signal cannot miss the other.
        `_cache_lookup` / `_cache_store` / `_init_cache_table` are the base
        class's, and a subclass supplies only the two halves that differ."""
        base = moz_keywords._KeywordSignalClient
        for _label, cls, _payload, _field in SIGNALS:
            for name in ("_cache_lookup", "_cache_store",
                         "_init_cache_table"):
                self.assertNotIn(
                    name, vars(cls),
                    f"{cls.__name__} overrides {name} again")
            for name in ("_block_from_cache", "_payload_for_cache"):
                self.assertIn(name, vars(cls),
                              f"{cls.__name__} does not supply {name}")
            self.assertTrue(issubclass(cls, base))

    def test_the_metric_columns_are_the_metric_fields(self):
        """The DDL and `METRIC_FIELDS` are one fact: a metric with no column
        would be written nowhere, and a column no metric fills would always
        be NULL."""
        self.assertEqual(
            {name for name, _type
             in moz_keywords.MozKeywordClient.CACHE_PAYLOAD_COLUMNS},
            set(moz_keywords.METRIC_FIELDS))

    def test_the_base_class_refuses_to_guess_a_signals_halves(self):
        """P29 — the two hooks above are the contract, so the base class must
        not silently return nothing when a new signal forgets one."""
        base = moz_keywords._KeywordSignalClient
        with self.assertRaises(NotImplementedError):
            base._block_from_cache(None, ())
        with self.assertRaises(NotImplementedError):
            base._payload_for_cache(None, {})

    def test_the_chunk_size_is_named_once_in_every_cache(self):
        """SQLite's bound-variable cap is one fact. Five production caches
        batch an `IN (...)` lookup for it; `gsc_client` named and explained the
        number while the other four carried a bare literal. The guard walks
        every production module rather than a list of names, because a list of
        names is how the sixth cache gets missed."""
        self.assertIsInstance(db_connect.CACHE_LOOKUP_CHUNK, int)
        self.assertGreater(db_connect.CACHE_LOOKUP_CHUNK, 0)
        self.assertEqual(db_connect.__name__, "db_connect")

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        chunked, offenders = [], []
        for name in sorted(os.listdir(root)):
            if not name.endswith(".py") or name.startswith("test_"):
                continue
            source = io.open(os.path.join(root, name), encoding="utf-8").read()
            if "range(0, len(" not in source:
                continue
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if getattr(node.func, "id", None) != "range":
                    continue
                if len(node.args) != 3:
                    continue
                step = node.args[2]
                if isinstance(step, ast.Constant):
                    offenders.append(f"{name}: range step {step.value!r}")
                elif (isinstance(step, ast.Attribute)
                        and step.attr == "CACHE_LOOKUP_CHUNK"):
                    chunked.append(name)

        # P29 — the walk asserts it found the thing it is about.
        self.assertGreaterEqual(
            len(chunked), 5,
            f"expected every chunked cache lookup to read the named "
            f"constant; found {sorted(set(chunked))}")
        self.assertEqual(offenders, [],
                         "a chunked lookup carries its own literal step")

    def test_a_keyword_list_longer_than_the_chunk_is_all_looked_up(self):
        """The chunking exists because SQLite caps bound variables; a list
        longer than one chunk must still be answered in full."""
        directory = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, directory,
                        ignore_errors=True)
        db_path = os.path.join(directory, "t.db")
        client = moz_keywords.MozKeywordClient(db_path=db_path)
        keywords = [f"kw{i}" for i in range(db_connect.CACHE_LOOKUP_CHUNK + 7)]
        client._cache_store({kw: {"status": moz_keywords.STATUS_OK,
                                  "volume": 1} for kw in keywords})
        cached, to_fetch = client._cache_lookup(keywords)
        self.assertEqual(to_fetch, [])
        self.assertEqual(len(cached), len(keywords))


if __name__ == "__main__":
    unittest.main()
