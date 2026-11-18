# Chunk Y11 — a rollback is not the diagnosis, and five seconds is not a decision

Carried as "Adjacent issues found, not fixed" by chunks Y9 (F6) and Y10 (F7).
Both repos share one helper, so both are changed in one chunk.

## The faults

**1. The cleanup replaces the diagnosis.** `db_connect.connection` is:

```python
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
```

`conn.rollback()` and `conn.close()` can both raise — a disk I/O error, a
database file that has gone away, a connection already closed by a `with`
block the caller nested inside this one. When either does, its exception
*replaces* the one the caller needs to see: the `IntegrityError` that says
which write was wrong becomes an `OperationalError` from the rollback, and the
original is reduced to a `__context__` nobody prints. A failure in the cleanup
is a second fact, not the diagnosis.

The `finally` branch is the worse of the two, because it fires on the clean
path as well. A `close()` that fails *after* a successful `commit()` raises out
of a block whose write is already durable, so the caller records the write as
failed and the run reports an absence where there is a row (P1 in reverse, P6).

**2. The lock wait is a hidden five seconds.** `sqlite3.connect` takes a
`timeout` argument — how long a writer waits for another writer's lock before
raising `database is locked` — and defaults it to 5.0. No call site passes it,
so the wait is a number nobody chose and nobody can change. It matters here:
Tool 1 has seven entry points and the GUI runs `refresh_analysis_outputs`
in-process while a run writes, and in Tool 2 the Streamlit orchestrator and an
audit write the same file. `database is locked` arrives as an
`OperationalError` — a transient failure with no retryable state anywhere
(P1) — and the only lever that would fix it is the one argument the code never
names (P4: config, not magic constants).

## What is built

**Both repos, the helper itself.** Each cleanup step is guarded so it cannot
displace the exception the block raised:

```python
    except BaseException:
        _safely(conn.rollback, "roll back", db_path)
        raise
    finally:
        _safely(conn.close, "close", db_path)
```

`_safely` catches `Exception` — not `BaseException`, so a `KeyboardInterrupt`
during cleanup still reaches the user — logs it with `logger.exception`, and
returns. The original exception propagates from the `raise`; on the clean path,
a failed close is logged and the committed write stands.

**Both repos, the wait.** `connection()` passes `timeout=` to
`sqlite3.connect`, taken from config, with sqlite3's own 5.0 as the documented
default. `kwargs.setdefault`, so a call site that passes its own `timeout` is
still honoured.

**Tool 1, where the number comes from.** `config.yml` gets a `database` block
with `lock_timeout_seconds`, read through `timeouts.seconds_from_config` — the
repo's one rule for "a positive number of seconds, else the default with a
warning" (P32). `db_connect.lock_timeout()` is a function, not a constant read
at import, because `apply_lock_timeout` rebinds the module global and a default
argument would bind before any config was read (the Y4 trap).

Applying it is the part that would rot. Six loaders in this repo read
`config.yml`, and five of them call `http_retry.apply_retry_policy` — a list
that the cold review of chunk Y4 had to extend once already, and
`generate_insight_report._load_config` is still not on it although it opens the
database. A second policy to apply at each of six sites is a second thing to
forget, so there is one function instead: `process_config.apply(cfg)` sets
every process-wide policy, and each loader calls that. The guard is a
consequence test over every loader — write a `config.yml` carrying a non-
default retry budget *and* a non-default lock wait, call the loader, and assert
both reached the process — so a loader added later without the call fails a
test rather than running on the defaults.

**Tool 2, where the number comes from.** `shared_config.json`
`technical.db_lock_timeout_seconds`, resolved per `DatabaseManager` /
`VelocityTracker` instance in `__init__` and passed to `connection()`. Tool 2
is plumbed differently on purpose: it has one gateway class in front of every
connection and reads its editorial thresholds on demand through
`load_shared_config()` (`position_thresholds`, `magnet_thresholds`,
`load_db_path`), so a process-wide global set from an entry point would be a
pattern the repo does not otherwise use. Tool 1 has no gateway class and 61
call sites, so there the global is the only place one setting reaches them all.

## Verification

Full suite by exit code in both repos, plus the mutation gate: each production
change reverted on its own must fail a guard that covers its own criterion.

## What is NOT in this chunk

Recorded here, not fixed:

* **One database, eight literals.** `"serp_data.db"` is a default argument in
  `dataforseo_client`, `gsc_client`, `export_history`, `metrics`,
  `generate_insight_report`, `export_ai_visibility` and `keyword_enrich`, and
  `config.yml` has no key for it. The new `database` block is where it belongs.
* **Two readers of `shared_config.json` in Tool 2.**
  `database.load_shared_config` raises on a corrupt file;
  `scoring_logic.load_shared_config` swallows the error and returns `{}`, which
  scores every page against an empty vocabulary. `config_io`'s docstring names
  the second one's behaviour as the reason its own loader raises — so the
  difference is known and deliberate at one of the three, and unexamined at the
  other two.
* **`keyword_enrich.py` is an untracked eighth entry point** that loads no
  config at all.

## Verification as built

* Tool 1: full suite EXIT=0, **2199 passed, 68 skipped**.
* Tool 2: core suite EXIT=0, **837 passed**; root suite EXIT=0, **162 passed**.
* Mutation gate (`scratchpad/mutate_y11.py`): **31 mutations across both
  repos, all caught, none vacuous.**

## Cold review (learning-qa, after the build)

Ten findings: four medium, six low. No correctness defect in the `_safely`
change itself — the reviewer verified that `commit()` still propagates, that a
lost rollback is covered by sqlite's implicit rollback on close, and that
`except Exception` is the right width. Fixed:

**F1 (medium, P2/P5) — a mangled `database:` block was defaulted in silence.**
`{"database": None}`, `{"database": 5}` and `{"database": {}}` all returned 5.0
with nothing in the log. These are the three shapes `http_retry` was fixed for
in the cold review of chunk Y7, and this function was written taking care over
a fourth (`lock_timeout_seconds:` written empty) while missing them. An
indentation typo is enough to produce one. Now reported.

**F2 (medium, P4/P9) — the wait had no ceiling.** `lock_timeout_seconds: 5000`
— a plausible slip for `5.0`, or seconds read as milliseconds — made a
contended write block for 83 minutes, and because the GUI calls
`refresh_analysis_outputs` on the Tk thread the window would freeze with
nothing in the log until the wait ended. The sibling policy bounds its wait for
exactly this reason (`max_retry_after_seconds`); this one, which can block the
UI, had no bound. `MAX_LOCK_TIMEOUT_SECONDS = 300.0`, reported and clamped
rather than refused, because a large number is a wish for a long wait and not a
typo in kind.

**F3 (medium, P2/P25) — the policy was being applied once per keyword.**
`generate_insight_report._report_number` reaches `_load_config` on the
per-keyword narrative path, so the new apply re-parsed `config.yml` and
re-applied both policies for every keyword, re-emitting every config warning
with it: one typo produced N identical lines and the reader could not tell one
problem from N. It also made the doc claim "applies it once at startup" false.
`_load_config` now caches by resolved path.

**F4 (medium, P32/P5) — the "derived" set of fields refused at zero was still
incomplete.** `report_llm.timeout_seconds` is read through the same
`timeouts.seconds_from_config` rule and `report_llm.main_max_tokens` /
`advisory_max_tokens` through `_token_limit`, and none of the three was in any
table, so the GUI saved a typed 0 for a fourth timeout class — the exact Y8
fault, surviving because this chunk extended the set by appending one pair
rather than making each loader name its own keys. `report_llm.GOVERNED_FIELDS`
now exists and the set reads it. Widening the Y7 help-text guard to derive from
`positive_only_fields()` then found four refused fields with no help text in the
GUI, including `serpapi.timeout_seconds` from chunk Y8; all four now have it.

**F6 (low, P2/P40) — an unreadable `config.yml` degraded in silence.** The
report ran on every built-in default — thresholds, retry budget and lock wait —
and said nothing anywhere. Now logged, and `FileNotFoundError` is separated
from a parse failure, because an absent file is not an error.

**F7 (low, P34) — the new config read could newly fail construction.**
`DatabaseManager.__init__` reads the config for the wait even when the caller
supplied its own `db_path`, and `database.load_shared_config` raises on a
corrupt file. `config_for_lock_timeout()` is a tolerant read for the wait
alone; every editorial reader still raises where it is, which is the behaviour
`config_io`'s docstring depends on.

**F9/F10 (low, docs and GUI).** The claim "the one function every loader of
`config.yml` calls" was broader than the guard can back — the GUI's own editor
read is a loader by any plain reading and legitimately sets no policy — so the
wording now says which loaders it means. The new key has help text in the
Settings tab.

### Recorded, not fixed

* **F5 — two DB entry points load no config at all.** `export_history.py` and
  `verify_enrichment.py` open the database and never call a loader, so they
  always use the import default. Harmless today because the shipped value is
  sqlite3's own; set `lock_timeout_seconds: 30` and those two still wait 5 with
  nothing saying so. It is the cost of the process-global design, and the fix
  is to give both an entry-point loader — a chunk of its own, beside the
  `"serp_data.db"` literal they also carry.
* **F8 — a cleanup failure is reported where nobody reads it.** `_safely` logs
  with `logger.exception`, which in the GUI's in-process path goes to the Tk
  process's stderr. The one case this chunk deliberately makes non-fatal —
  cleanup failed, work succeeded — is therefore invisible to a GUI operator,
  and in Tool 2 a repeating `close()` failure inside the audit loop would leak
  descriptors and surface later as `database is locked` whose cause exists only
  in the log. A counter in the run summary is the right fix and needs a home in
  the summary structure.
* The reviewer's one observation from outside the range: untracked
  `keyword_enrich.py` makes a bare `requests.get` with no retry and records a
  transient failure as "no suggestions" (P1/P2). Already recorded above as an
  unmanaged entry point.
