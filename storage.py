"""
storage.py
~~~~~~~~~~
Manages the SQLite database for SERP history and enriched features.

Tables
------
runs                   One row per audit run (run_id, date, params hash).
keywords               Keyword inventory.
serp_results           Raw SERP rankings per keyword per run.
url_features           Enriched URL data including Moz DA/PA.
domain_features        Entity type per domain.
autocomplete_suggestions  Search autocomplete data.
keyword_feasibility    Per-keyword DA gap assessment and pivot suggestions.

All schema changes use ``CREATE TABLE IF NOT EXISTS`` or
``ALTER TABLE … ADD COLUMN`` wrapped in ``try/except OperationalError``
so the database migrates automatically on first use with no manual steps.
"""
import sqlite3
import json
import logging
from datetime import datetime

# For MINIMA_FIELDS only — the names of the fields a feasibility
# assessment carries, so this writer cannot fall behind the producer.
import feasibility


class SerpStorage:
    def __init__(self, db_path="serp_data.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # 1. Runs
        c.execute('''CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            run_date TEXT,
            params_hash TEXT,
            completed_at TEXT   -- NULL until the run wrote all its outputs
        )''')

        # 2. Keywords
        c.execute('''CREATE TABLE IF NOT EXISTS keywords (
            keyword_id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword_text TEXT UNIQUE,
            locale TEXT
        )''')

        # 3. SERP Results
        c.execute('''CREATE TABLE IF NOT EXISTS serp_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            keyword_text TEXT,
            result_type TEXT, -- organic, paid, local, etc.
            rank INTEGER,       -- absolute SERP position, not per-page
            title TEXT,
            url TEXT,
            domain TEXT,
            snippet TEXT,
            features_json TEXT,
            query_label TEXT,   -- "A" primary | "A.1"/"A.2" alt | "P" pivot
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        )''')

        # 4. URL Features (Enriched)
        c.execute('''CREATE TABLE IF NOT EXISTS url_features (
            url TEXT PRIMARY KEY,
            fetched_at TEXT,
            status_code INTEGER,
            content_type TEXT,
            schema_types TEXT,
            word_count_est INTEGER,
            evidence_json TEXT
        )''')

        # 5. Domain Features (Classified)
        c.execute('''CREATE TABLE IF NOT EXISTS domain_features (
            domain TEXT PRIMARY KEY,
            entity_type TEXT,
            domain_age_years INTEGER
        )''')

        # 6. Autocomplete Suggestions
        c.execute('''CREATE TABLE IF NOT EXISTS autocomplete_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            source_keyword TEXT,
            suggestion TEXT,
            rank INTEGER,
            relevance INTEGER,
            type TEXT,
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        )''')

        # 7. Keyword Feasibility  (DA gap analysis + hyper-local pivot suggestions)
        c.execute('''CREATE TABLE IF NOT EXISTS keyword_feasibility (
            keyword_text        TEXT,
            run_id              TEXT,
            query_label         TEXT,       -- "A" primary | "P" pivot
            avg_serp_da         REAL,
            client_da           INTEGER,
            gap                 REAL,
            feasibility_score   REAL,
            feasibility_status  TEXT,
            client_in_local_pack INTEGER,   -- 0/1; NULL for primary keywords
            pivot_variants      TEXT,       -- JSON array of neighbourhood variants
            -- Coverage travels with the mean: avg_serp_da over 2 of 10 domains
            -- and over 10 of 10 are different facts that read identically
            -- without these (review chunk D2, finding F9). NULL = a row
            -- written before D2a, which is "unknown", not 0 of 0.
            da_count            INTEGER,    -- domains with a DA figure
            da_missing          INTEGER,    -- window positions with none
            da_provider         TEXT,       -- "dataforseo" | "moz" | "none"
            client_da_source    TEXT,       -- how client_da was obtained
            -- The minima the mean cannot show (review chunk D6, D-M-09).
            -- min_non_directory_da NULL means no competitor's entity type was
            -- resolved, which is not "no directory ranks here";
            -- entities_known says how many were resolved, so a figure taken
            -- over 1 of 10 is never read as taken over 10.
            min_competitor_da    REAL,
            max_competitor_da    REAL,
            min_non_directory_da REAL,
            non_directory_count  INTEGER,
            entities_known       INTEGER,
            computed_at         TEXT,
            PRIMARY KEY (keyword_text, run_id),
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        )''')

        # --- Migration: feasibility minima columns (review chunk D6) ---
        for col, col_type in [("min_competitor_da", "REAL"),
                              ("max_competitor_da", "REAL"),
                              ("min_non_directory_da", "REAL"),
                              ("non_directory_count", "INTEGER"),
                              ("entities_known", "INTEGER")]:
            try:
                c.execute(
                    f"ALTER TABLE keyword_feasibility ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass  # Column already exists — safe to ignore

        # --- Migrations: add Moz DA/PA columns to url_features if absent ---
        for col, col_type in [("competitor_da", "INTEGER"), ("page_authority", "INTEGER")]:
            try:
                c.execute(f"ALTER TABLE url_features ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass  # Column already exists — safe to ignore

        # --- Migrations: run-completion and query-label columns (D-C-22) ---
        # `runs.completed_at` is NULL until the run writes all its outputs, so
        # an aborted run cannot become the baseline a later run's deltas are
        # measured against. `serp_results.query_label` separates the primary
        # query ("A") from AI-alternative queries ("A.1"/"A.2") and pivot
        # fetches ("P"), which were all stored under the root keyword and so
        # produced cross-product merges in metrics.py.
        # Rows written before this migration keep NULL in both columns, which
        # means "unknown", not "A" and not "completed" — metrics.py counts and
        # reports what it skipped rather than guessing.
        for table, col, col_type in [
            ("runs", "completed_at", "TEXT"),
            ("serp_results", "query_label", "TEXT"),
            # D2a coverage/provenance. Rows written before this keep NULL,
            # which means "not recorded", never "0 of 0" (finding F9).
            ("keyword_feasibility", "da_count", "INTEGER"),
            ("keyword_feasibility", "da_missing", "INTEGER"),
            ("keyword_feasibility", "da_provider", "TEXT"),
            ("keyword_feasibility", "client_da_source", "TEXT"),
        ]:
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass  # Column already exists — safe to ignore

        conn.commit()
        conn.close()

    def save_run(self, run_id, params_hash):
        """Record (or update) a run. ``completed_at`` stays NULL until
        ``mark_run_completed`` — this is called before the first fetch, so a
        run that aborts on keyword 1 must not look like usable history
        (finding D-C-22).
        """
        run_date = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            # UPSERT rather than INSERT OR REPLACE: REPLACE deletes the row and
            # re-inserts it, which would wipe a completed_at already set.
            conn.execute(
                """INSERT INTO runs (run_id, run_date, params_hash)
                   VALUES (?, ?, ?)
                   ON CONFLICT(run_id) DO UPDATE SET
                       run_date = excluded.run_date,
                       params_hash = excluded.params_hash""",
                (run_id, run_date, params_hash))

    def mark_run_completed(self, run_id, completed_at=None):
        """Stamp ``runs.completed_at``: this run wrote all of its outputs.

        Called once, at the end of a successful run. Only runs with a
        completion stamp are eligible as the baseline for rank deltas
        (finding D-C-22).
        """
        stamp = completed_at or datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE runs SET completed_at = ? WHERE run_id = ?",
                         (stamp, run_id))

    def save_serp_result(self, run_id, keyword, result_type, rank, title, url,
                         domain, snippet, features=None, query_label=None):
        """Store one SERP row. *rank* is the absolute SERP position (D-C-01).

        *query_label* says which query produced the row — "A" for the primary
        keyword, "A.1"/"A.2" for AI-alternative phrasings, "P" for a pivot
        fetch. All of them are stored under the root keyword, so rank history
        has to filter on the label (finding D-C-22).
        """
        features_json = json.dumps(features) if features else "{}"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''INSERT INTO serp_results 
                            (run_id, keyword_text, result_type, rank, title, url, domain, snippet, features_json, query_label)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                         (run_id, keyword, result_type, rank, title, url, domain, snippet, features_json, query_label))

    def save_url_features(self, url, status_code, content_type, schema_types, word_count, evidence):
        fetched_at = datetime.now().isoformat()
        schema_json = json.dumps(schema_types)
        evidence_json = json.dumps(evidence)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''INSERT OR REPLACE INTO url_features 
                            (url, fetched_at, status_code, content_type, schema_types, word_count_est, evidence_json)
                            VALUES (?, ?, ?, ?, ?, ?, ?)''',
                         (url, fetched_at, status_code, content_type, schema_json, word_count, evidence_json))

    def save_domain_features(self, domain, entity_type):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''INSERT OR REPLACE INTO domain_features (domain, entity_type) VALUES (?, ?)''',
                         (domain, entity_type))

    def save_autocomplete_suggestion(self, run_id, source_keyword, suggestion, rank, relevance=None, type_=None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''INSERT INTO autocomplete_suggestions
                            (run_id, source_keyword, suggestion, rank, relevance, type)
                            VALUES (?, ?, ?, ?, ?, ?)''',
                         (run_id, source_keyword, suggestion, rank, relevance, type_))

    # ------------------------------------------------------------------
    # Moz DA/PA
    # ------------------------------------------------------------------

    def save_url_moz_metrics(self, url: str, da: int, pa: int | None) -> None:
        """Update the Moz Domain Authority and Page Authority for a URL.

        If the URL does not yet exist in ``url_features`` a minimal row is
        inserted so the FK relationship remains valid and the DA is queryable
        even for URLs that weren't fully enriched.

        ``pa`` is ``None`` when the URL is a site root recovered from Google's
        redirect wrapper rather than the page that ranked: Page Authority is a
        property of the page, so the front page's figure must not be stored
        under the ranked page's row. Domain Authority is a property of the
        domain and is stored either way.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO url_features (url) VALUES (?)", (url,)
            )
            conn.execute(
                "UPDATE url_features SET competitor_da = ?, page_authority = ? WHERE url = ?",
                (da, pa, url),
            )

    # ------------------------------------------------------------------
    # Keyword Feasibility
    # ------------------------------------------------------------------

    def save_keyword_feasibility(
        self,
        keyword_text: str,
        run_id: str,
        query_label: str,
        avg_serp_da: float | None,
        client_da: int | None,
        gap: float | None,
        feasibility_status: str,
        feasibility_score: float | None,
        client_in_local_pack: int | None,
        pivot_variants: list,
        da_count: int | None = None,
        da_missing: int | None = None,
        da_provider: str | None = None,
        client_da_source: str | None = None,
        minima: dict | None = None,
    ) -> None:
        """Upsert a feasibility assessment row.

        Parameters
        ----------
        keyword_text:
            The keyword or pivot keyword assessed.
        run_id:
            Current run identifier.
        query_label:
            ``"A"`` for a primary keyword, ``"P"`` for a pivot variant.
        avg_serp_da:
            Mean Domain Authority of the top-10 competitors (``None`` if
            no Moz data was available).
        client_da:
            Domain Authority of the non-profit client, or ``None`` when no
            provider returned one and no config fallback applied. A fabricated
            0 here would read as a measurement (review chunk D2).
        gap:
            ``avg_serp_da - client_da`` (``None`` if no Moz data).
        feasibility_status:
            ``"High Feasibility"``, ``"Moderate Feasibility"``,
            ``"Low Feasibility"``, or ``"Not Measured"`` when too little of
            the window had a DA record for a verdict
            (``feasibility.NOT_MEASURED``).
        feasibility_score:
            Normalised score 0.0–1.0 (``None`` if no Moz data).
        client_in_local_pack:
            ``1`` if the client domain appears in the local 3-pack for this
            keyword, ``0`` if not, ``None`` for primary keywords (not checked).
        pivot_variants:
            List of neighbourhood-variant keyword strings.
        da_count / da_missing:
            How many of the window's positions carried a DA figure and how
            many did not. ``None`` means the caller did not record it, which
            is not the same as 0 of 0 — every reader of these two must keep
            absent and zero apart (finding F9).
        da_provider:
            Which provider was asked (``"dataforseo"``, ``"moz"``,
            ``"none"``). The two providers' 0–100 scales are different
            vendors' models, so a gap is only like-for-like within one.
        client_da_source:
            How ``client_da`` was obtained — a measurement, the config
            fallback, or not measured. Reported beside the figure so a
            config value is never read as a measurement.
        minima:
            The ``feasibility.MINIMA_FIELDS`` keys from the assessment — the
            weakest competitor, the weakest non-directory competitor, and how
            many competitors had a resolved entity type. Passed as one mapping
            so a new field does not have to be added at three call sites;
            absent keys store NULL, which is "not recorded", never 0.
        """
        pivot_json = json.dumps(pivot_variants)
        computed_at = datetime.now().isoformat()
        mins = minima or {}
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO keyword_feasibility
                   (keyword_text, run_id, query_label, avg_serp_da, client_da,
                    gap, feasibility_score, feasibility_status,
                    client_in_local_pack, pivot_variants, da_count,
                    da_missing, da_provider, client_da_source,
                    min_competitor_da, max_competitor_da,
                    min_non_directory_da, non_directory_count,
                    entities_known, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?)""",
                (keyword_text, run_id, query_label, avg_serp_da, client_da,
                 gap, feasibility_score, feasibility_status,
                 client_in_local_pack, pivot_json, da_count, da_missing,
                 da_provider, client_da_source,
                 mins.get("min_competitor_da"), mins.get("max_competitor_da"),
                 mins.get("min_non_directory_da"),
                 mins.get("non_directory_count"), mins.get("entities_known"),
                 computed_at),
            )

    def save_feasibility_from_row(
        self,
        row: dict,
        run_id: str,
        query_label: str,
        client_in_local_pack: int | None = None,
        pivot_variants: list | None = None,
    ) -> None:
        """Persist one feasibility row as :func:`compute_feasibility` produced it.

        The caller already holds the whole assessment as a dict — the mean,
        the gap, the verdict, the coverage and the provenance. Re-listing
        those fields at each call site is how the coverage came to be written
        to the JSON and the report but not to the database: two new fields,
        two call sites, and nothing that fails when one is forgotten
        (finding F9). Everything this table records travels in *row*; only
        the three things that are not part of the assessment are arguments.

        Unknown keys are ignored, so a row from an older run (no
        ``da_count``) stores NULL rather than raising — NULL being "not
        recorded", never 0.
        """
        self.save_keyword_feasibility(
            keyword_text=row.get("Keyword") or row.get("keyword_text") or "",
            run_id=run_id,
            query_label=query_label,
            avg_serp_da=row.get("avg_serp_da"),
            client_da=row.get("client_da"),
            gap=row.get("gap"),
            feasibility_status=row.get("feasibility_status", ""),
            feasibility_score=row.get("feasibility_score"),
            client_in_local_pack=client_in_local_pack,
            pivot_variants=pivot_variants or [],
            da_count=row.get("da_count"),
            da_missing=row.get("da_missing"),
            da_provider=row.get("da_provider"),
            client_da_source=row.get("client_da_source"),
            minima={k: row.get(k) for k in feasibility.MINIMA_FIELDS
                    if k in row},
        )

    def get_keyword_feasibility(self, run_id: str) -> list[dict]:
        """Return all feasibility rows for *run_id*, ordered by gap descending.

        Primary keywords (``query_label = "A"``) come first; pivot keywords
        (``"P"``) immediately follow their parent sorted by gap.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM keyword_feasibility
                   WHERE run_id = ?
                   ORDER BY query_label ASC, gap DESC""",
                (run_id,),
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["pivot_variants"] = json.loads(d["pivot_variants"] or "[]")
            except (ValueError, TypeError):
                d["pivot_variants"] = []
            result.append(d)
        return result
