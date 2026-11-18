# Chunk Y5 — an error is not an absence, and a timeout is a judgement

*Review chunk Y5 of the adjacent-issue sweep (`REVIEW_WORKPLAN_2026-11-04.md`).
The issues the earlier chunks' cold reviews logged under "Adjacent issues
found, not fixed".*

Effort tier: **Full** — every item is in a data path, a fetch path or a
status path.

## What is wrong

1. **`storage.py`'s migrations swallow every `OperationalError`, not just
   "column already exists".** Three sites (`keyword_feasibility` minima, the
   `url_features` Moz columns, the run-completion / query-label / provenance
   columns) run `ALTER TABLE ... ADD COLUMN` inside
   `except sqlite3.OperationalError: pass`. SQLite raises the same class for
   "database is locked", "no such table" and a read-only file. So a locked
   database, or a table an earlier `CREATE` failed to make, leaves the column
   missing and the run carries on: the next `INSERT` naming that column fails
   far from the cause, and `da_count`/`da_provider`/`completed_at` read as
   "not recorded" — the wording that means a row written before the
   migration. A real failure is reported to the reader as an absence (P1/P6).
2. **`metrics.get_volatility_metrics` closes its connection by hand on seven
   paths.** Chunk Y3 added five status exits and a `finally`-less `except` that
   closes `conn` defensively; the happy path and the five early returns each
   call `conn.close()` themselves. A future exit that forgets one leaks a
   SQLite handle, which is how a later write meets "database is locked" — the
   failure mode finding 1 is about. One `closing(...)` makes the leak
   impossible rather than currently-absent.
3. **`citation_table` counts the citations it cannot attribute to a host and
   not the ones it cannot attribute to a brand.** Chunk Y3 added
   "N of M citation(s) carry no readable host". The `brand` column prints `—`
   per row for a citation no `known_brands` entry matched, and nothing says how
   many: a reader cannot tell "this engine cites nobody we track" from "we
   track everybody it cites". The gazetteer is the thing the user is meant to
   extend (`brand_mentions_candidates_*.md` exists for exactly that), so the
   number is the prompt to extend it (P2/P9).
4. **`tests/test_y1_one_definition_each.py::test_no_module_strips_the_prefix_by_hand`
   matches source literals.** It greps for three spellings of the `www.` strip.
   A fourth spelling (`split("www.")`, a slice, a regex) passes, and the guard
   breaks green on any reformat. The Y4 host guard was converted to an AST walk
   for this reason; this one was left.
5. **Five modules carry their own `REQUEST_TIMEOUT`, and the retry budget
   beside them became editorial in chunk Y4 while the timeout did not.**
   `gsc_client`, `dataforseo_client`, `moz_client`, `moz_jsonrpc` (30s),
   `probe_ai_visibility` (60s), `url_enricher` (10s) and `http_retry`'s own
   `timeout=30` default. "How long the tool may spend on one flaky host" is the
   same judgement as "how many times it tries", and `serpapi.timeout_seconds`
   has been configurable since the start — so after Y4 the tool had one
   outbound policy that could be tuned in three halves. `moz_jsonrpc.query`
   also binds `timeout: int = REQUEST_TIMEOUT` as a **default argument**, the
   trap Y4 fixed in `http_retry` (P4/P25).

Not in this chunk, and why: **`serp_audit`'s in-pipeline pivot pass runs before
`keyword_profiles` exists**, so it calls `generate_hyper_local_pivot` without
`serp_intent` or `entity_distribution` while the standalone `run_feasibility.py`
passes both. The measured intent is documented to outrank the keyword-token
guess, and in the pipeline it does not — but fixing it means reordering a
2192-line module's main loop, which is a chunk of its own (Y6), not a line in
this one.

## The fixes

1. Each migration asks the table for its columns (`PRAGMA table_info`) and
   issues the `ALTER` only for a column that is genuinely absent, so **no**
   `OperationalError` is expected and none is swallowed. A missing table is
   reported with the table named.
2. `get_volatility_metrics` holds the connection in `contextlib.closing`, and
   every `conn.close()` in the function goes.
3. `citation_table.unattributed_brands(table)` returns
   `(attributed, unattributed, total)` by cite count, and the section prints
   "N of M citation(s) are from a brand not in `known_brands`" with the
   pointer to the gazetteer.
4. The Y1 guard walks the AST: no module in `HOST_MODULES` may call
   `removeprefix` / `lstrip` / `strip` / `replace` / `split` with a `www.`
   argument, whatever the spelling.
5. `http_retry` carries the three timeout classes — API call, ranked-page
   fetch, LLM answer — resolved through the repo's own
   `timeouts.seconds_from_config` and applied by the same `apply_retry_policy`
   every entry point already calls. The helpers resolve `timeout=None` in
   their bodies; each client keeps its constant as the documented default and
   stops passing it, so one setting reaches every call site.
   `moz_jsonrpc.query`'s default argument becomes `None`.

   **Changed while building:** only the API wait becomes an `http_retry` key.
   The other two already had a config home and keep it (Y1 — one definition
   each): `enrichment.timeout_seconds`, which `serp_audit` has always passed
   to `UrlEnricher`, and `ai_visibility.timeout_seconds`, new, beside the
   engine list it belongs to. Adding `page_fetch_timeout_seconds` beside an
   existing `enrichment.timeout_seconds` would have been two homes for one
   number, which is the defect Y1 fixed. `http_retry.TIMEOUT_SOURCES` is the
   one table mapping each class to its section, and `serp_audit` stops passing
   `timeout=` so there is a single config→argument mapping (P25).

## Verification

- Full suite by exit code: `python3 -m pytest test_*.py tests/ -q` →
  `EXIT=0`, 2084 passed, 68 skipped, 10 subtests passed.
- Guards: `tests/test_y5_an_error_is_not_an_absence.py`, 26 tests, one or more
  per finding.
- Mutation gate: 16 mutations in
  `scratchpad/mutate_y5.py`, each reverting one production change; every one
  failed a guard covering its own criterion. "MUTATIONS THAT FAILED NOTHING:
  (none)".
- One existing guard needed changing:
  `tests/test_y4_config_not_constants.py::test_the_policy_is_read_from_config`
  asserted the whole policy dict, which now carries the three timeout classes;
  it asserts its own three retry keys instead.

## Cold review (learning-qa, pre-push) — 8 findings, 2 high, all fixed

1. **HIGH, P5/P1/P6.** The `except sqlite3.OperationalError: pass` migration
   was fixed in `storage.py` and left in three live siblings —
   `probe_ai_visibility.init_probe_table`,
   `answer_sentiment.init_sentiment_table`,
   `foundational_score.init_foundational_table` — each citing "the storage.py
   convention" as authority for the rule this chunk repudiates. All three now
   call `storage._add_missing_columns`, which accepts a `Connection`
   unchanged. Guards: a patched helper that raises must reach the caller, and
   each table still migrates idempotently.
2. **HIGH, P5/P27.** `ClaudeProbe` built `anthropic.Anthropic(api_key=…)` with
   no timeout, so the new `ai_visibility.timeout_seconds` reached three of the
   four engines and a hung Claude probe waited the SDK's own ten minutes per
   question. The client is now built per request with
   `timeout=http_retry.llm_timeout()`. The guard that missed it asserted the
   string `"http_retry.llm_timeout()"` appeared somewhere in the file; it is
   replaced by a per-engine test that drives all four and asserts each
   outbound call carries the configured value.
3. **MEDIUM, P5/P2.** `storage._init_db` closed its handle by hand at the end,
   and the raise introduced by fix 1 does not reach the end — the fix turned a
   swallowed error into a leak on the same path the chunk had just fixed in
   `metrics.py`. Split into `_init_db` (which holds `closing`) and
   `_create_and_migrate`.
4. **MEDIUM, P27.** Three guards decided on shape, not consequence: an AST
   walk for `close()` calls on a local named `conn` (renaming the local
   restores the leak and keeps the guard green), an assertion that the three
   *shipped* timeout values differ (a legitimate retune would turn the suite
   red over editorial numbers), and the source grep in finding 2. Replaced by
   behavioural tests: the dominance reader's failing path closes, the schema
   builder closes when a migration raises, every class resolves positive, and
   every engine is bounded.
5. **LOW–MEDIUM, P27/P33.** The AST alias guard was blind to `re.sub(r"^www\.")`
   and to `url[4:] if url.startswith("www.")` — the most idiomatic hand-roll —
   while its docstring claimed "every spelling". It now covers `re.sub` /
   `re.match` / `re.search` / `re.fullmatch`, `startswith` (including a tuple
   of prefixes) and a regex-escaped or anchored literal, and the docstring
   says what it covers rather than claiming everything.
6. **LOW, P6.** Two new comments named config keys that do not exist
   (`http_retry.llm_timeout_seconds`, `http_retry.page_fetch_timeout_seconds`).
   They name the real keys, and `probe_ai_visibility.REQUEST_TIMEOUT` says
   plainly that nothing reads it; a guard holds it equal to the policy default
   it documents.
7. **LOW, P2.** Both config comments promised a non-numeric value would be
   reported, but `seconds_from_config` reads `None` as "key absent" and
   returns the default silently — so `timeout_seconds:` written with nothing
   after it was a silent typo. `resolve_retry_policy` now warns on a
   present-but-empty key.
8. **LOW, P9/P2.** The citations line said "carry no brand in the table
   above", which is false past the `top_n=40` truncation, and its denominator
   mixed categories: a directory or a publisher has no brand by design, so the
   figure was high on every run and said nothing. The wording names the
   engine's citations, and the actionable subset is printed beside it — the
   categories a rival would sit in, from the new editorial
   `ai_visibility.brand_relevant_categories`, printed even at zero.

The suite after the fixes: `EXIT=0`, 2087 passed, 68 skipped. The mutation
gate grew from 16 to 27 mutations, all caught.

## Adjacent issues found, not fixed

- **`with sqlite3.connect(...)` is not a close.** About sixty production call
  sites across twenty-five modules use it; the context manager commits or
  rolls back the transaction and leaves the connection open, relying on
  refcount collection at function exit. In practice that is prompt, which is
  why this is not the leak `metrics.py` had — there the handle was held across
  an `except` return for the life of the call. Converting all sixty is its own
  chunk.
- **`visualize_volatility` opens the database with raw `sqlite3.connect`**,
  bypassing `SerpStorage`'s migrations, so it reads a schema nothing
  guarantees it has. Carried over from Y4.
- **`refresh_analysis_outputs.py` is a fifth config loader** and does not apply
  the retry policy, so a run started from it uses the documented defaults
  whatever `config.yml` says. Carried over from Y4.
- **`serpapi.*` and `http_retry.*` are still two retry policies**, with
  separate attempt counts, backoffs and timeouts. Reconciling them is a
  config-contract change, not a line.
- **The new editorial keys have no `config_manager` GUI surface**
  (`http_retry.*`, `ai_visibility.timeout_seconds`, the Y4 `gsc.*` keys), so
  they can only be edited by hand. Carried over from Y4.
- **`compute_sponge_effect` / `find_reformat_candidates` name module constants
  as default arguments** — harmless today because every caller passes the
  resolved value, but the same latent shape as the Y4 trap. Carried over.
- **`keyword_enrich.py` is an untracked sixth entry point** (working tree
  only, not part of this chunk): it calls SerpAPI with a literal `timeout=15`
  and imports `moz_keywords` without applying the retry policy. It belongs to
  other work; if it is kept it needs the `_load_config` treatment.
- **The in-pipeline pivot pass runs before `keyword_profiles` exists**
  (`serp_audit.py`), so the measured intent does not reach
  `generate_hyper_local_pivot` there. This is chunk Y6.
