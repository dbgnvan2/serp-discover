# Chunk Y12 — one database, named once

Carried as "Adjacent issues found, not fixed" by chunk Y11 (the eight
literals) and by its cold review (F5: two entry points that load no config, so
the configured lock wait never reaches them).

## The fault

`"serp_data.db"` is a Python literal at **24 sites in 17 modules** — a default
argument in `storage.SerpStorage`, `storage.migrated_connection`,
`DataForSEOClient`, `GSCClient`, `MozClient`, `MozCompetitorClient`,
`MozKeywordClient`, a module constant in `metrics`, `visualize_volatility`,
`export_history` and `verify_enrichment`, an `argparse` default in five
scripts, and a literal passed by `serp_audit` at two call sites. `config.yml`
has no key for it at all.

Two consequences, and the second is the one that costs a run:

1. **It cannot be configured.** Every other operational setting in this tool
   is in `config.yml`; the file every one of them is about is not (P4). A
   second client, a copy of the database for a test run, a database on another
   volume: all of them mean editing 17 modules.
2. **Every one of those literals is relative to the current working
   directory.** Run `python3 metrics.py`, `export_history.py` or
   `generate_insight_report.py` from anywhere but the repo root and SQLite
   creates a new, empty `serp_data.db` in that directory rather than reporting
   that the history is missing — so the volatility section reports "no history
   database yet" while the history sits one directory up (P6/P16). Tool 2 had
   exactly this bug: `ReportGenerator`'s literal default opened a
   CWD-relative `competitor_history.db`, a different file from the one the
   audit wrote, and every section read a stale database. The comment recording
   that fix is in `Serp-compete/src/reporting.py` today.

And `export_history.py` and `verify_enrichment.py` call no config loader at
all, so the lock wait chunk Y11 made configurable never reaches them: set
`database.lock_timeout_seconds: 30` and those two still wait 5, with nothing
saying so (Y11 cold review F5).

## What is built

**One name.** `config.yml database.path` (default `serp_data.db`), in the
block Y11 added. `db_connect.database_path()` returns it; `apply_database_path`
is called by `process_config.apply`, so the one function every loader already
calls carries this too. A relative path resolves against the directory
`config.yml` lives in — the repo root — not against the current working
directory, which is the half of the fault that loses data. An absolute path is
used as given. Tool 2 resolves its own `technical.database_path` the same way
(`database.load_db_path`), so the two tools now agree on what a relative
database path means.

**One accessor, never a default argument.** Every `db_path="serp_data.db"`
becomes `db_path=None`, resolved inside the body with
`db_connect.database_path()`. A default argument binds at `def` time, before
any config has been read — the trap chunk Y4 was about — so a configured path
would have reached no caller that omitted the argument. The `argparse`
defaults become `None` and resolve after parsing, for the same reason.

**The two unmanaged entry points get a loader.** `export_history.py` and
`verify_enrichment.py` read `config.yml` through `process_config.apply`, so
they take the configured database and the configured lock wait like every
other entry point.

**A third unmanaged entry point.** `export_ai_visibility.py` read
`config.yml` for the client slug alone and applied no policy, so it was in the
same state as the two above. Its `_load_config` now applies the policies and
`_read_client_identity` takes the loaded dict, which also removes the second
`yaml.safe_load` of the same file.

**The loader walk widened.** Chunk Y11's structural guard found a config
loader by the `'config.yml'` literal inside it. `export_ai_visibility._load_config`
takes its path as an argument and names no file, so it escaped the walk. The
walk now also matches a module-level function that calls `yaml.safe_load` and
takes a `config_path`/`config_file` parameter, which catches that shape;
`brief_data_extraction.load_yaml_config`, a generic reader for the editorial
`.yml` files, is the one documented exemption it adds.

**The GUI gets the help text.** The Configuration Manager renders every key
in a `config.yml` section, so adding `database.path` added a field — and a
field with no help text is a path an operator can change with nothing telling
them what it does, or that pointing it somewhere new means an empty history
(P2). `HELP_BY_FIELD` has the entry and a guard asserts it.

## Verification

Full suite green by exit code: **2227 passed, 68 skipped**. Mutation gate
over the production changes: **33 mutations, 33 caught, 0 vacuous**
(`scratchpad/mutate_y12.py`).

Two of the first mutations came back vacuous, and both were worth the time:

* Commenting `database.path` out of `config.yml` changed nothing, because the
  code's default resolves to the same file. The consequence is not behavioural
  — it is that a setting nobody can find in `config.yml` is a constant — so
  the guard added is that the key is declared and documented
  (`test_config_yml_declares_the_setting`,
  `test_the_config_reference_documents_the_setting`).
* The first Y4-trap mutation added an unused parameter to `database_path()`,
  which is itself a no-op: a bad mutation, not a missing guard. Replaced with
  the real shape of that bug — `migrated_connection(db_path=db_connect.database_path())`
  — which `test_migrated_connection_takes_the_configured_database` catches,
  since it rebinds the path after import and expects a `FileNotFoundError`
  naming the new one.

Tool 2's half: both suites green by exit code (**848** core, **162** root), and
an 8-mutation gate, **8 caught**. The sixth is vacuous for a real reason:
deleting the `if os.path.isabs(db_name): return db_name` early return changes
nothing, because `os.path.join(directory, "/abs/path")` already discards the
directory. The branch states the contract the test asserts, so it stays; the
same redundancy exists in Tool 1's `resolve_database_path`.

The guard that matters most is the consequence test
`TestAReaderRunFromElsewhereFindsTheHistory`: it seeds a database, writes a
`config.yml` naming it relatively, chdirs elsewhere, and asserts the reader
exports the seeded row — and that no `serp_data.db` appeared beside the
caller. Its sibling asserts that a configured path which does not exist is
*reported*, with no file created at either end (P2/P16).

## Cold review

A cold `learning-qa` pass over each repo's diff. **Twelve findings, five of
them high; eleven fixed with a guard each, one recorded below.** Two of the
high ones were the chunk's own bug surviving inside the fix.

**Tool 1 (seven findings).**

* **F1 (high, P4/P16).** `generate_insight_report.main` never called
  `_load_config`. The first load on that path was *inside* `generate_report`,
  after `main` had already read the import-time default, so with a configured
  `database.path` the run's rows went to the configured database and the
  AIO-exposure write went to the default one — the trend split across two
  files with nothing logged, reachable from the GUI's auto-regenerate. `main`
  calls the (cached) loader first. Guard:
  `TestTheReportResolvesAfterItsLoader`.
* **F2 (high, P6).** `run_pipeline`'s closing summary printed
  `db_connect.database_path()` while the function set no policy at all, so it
  named the import-time default and not the database its child wrote. It
  applies the policies now, and the `_EXEMPT` entry that allowed it — "makes
  no call and opens no database" — moved into `_LOADERS`, because the diff
  itself made that reason false.
* **F3 (high, P5/P16).** Eight loaders defaulted to the bare `"config.yml"`,
  cwd-relative, and the GUI launches `serp_audit.py` with `cwd=os.getcwd()`:
  start the tool from any other directory and no config was found, every
  policy silently reset, and a configured `database.path` was abandoned for
  the built-in one — which on an installation that has ever run before exists
  and reads as a real, stale history. Y12 had fixed this for the two scripts
  it gave a loader and left it in the five it did not touch. There is now one
  `process_config.config_path()`; a path a caller passes is still cwd-relative,
  which is what a person typing `--config` means. Guard:
  `TestEveryLoaderNamesTheSameConfig`, including a consequence test that calls
  each loader from another directory.
* **F4 (medium, P1/P2/P6).** `sqlite3.connect` creates whatever path it is
  handed. While the name was a literal that could not be wrong this did not
  matter; now that the path is editable, a typo or an unmounted volume
  produces a new empty history that every reader reports as "no history yet" —
  a mistake and a transient condition both delivered as a fact about the
  client. `db_connect` says so once per database per process, and the readers'
  message names `database.path` instead of the working directory, which no
  longer decides anything.
* **F6 (high, P32).** The new `_EXEMPT` entry for
  `brief_data_extraction.load_yaml_config` claimed its path "is never
  config.yml". It is: `brief_rendering`'s CLI passes `--config`, whose default
  is `config.yml`. The honest reason — it is a reader, not an entry point, and
  the CLI that passes it config.yml applies the policies itself — replaced the
  wrong one.
* **F7 (high, P34).** Y12's test base restored the database path alone while
  its tests reset the retry policy and the lock wait process-wide; Y11's base
  restored one of the eight retry globals. `http_retry.POLICY_GLOBALS` /
  `current_retry_policy()` / `install_retry_policy()` name the set once, both
  bases use them, and a guard asserts the set equals what
  `apply_retry_policy` actually rebinds.
* Three notes, all acted on: a vacuous getter test (deleted — the real
  assertion is the `migrated_connection` one), two stale comments beside
  guards, and `docs/methodology.md`'s `--db serp_data.db` example.

**Tool 2 (five findings).**

* **F1 (high, P5/P32).** `VelocityTracker.__init__` was a second hand-rolled
  copy of `load_db_path`'s body with a *different* default name, so a config
  with `database_path` deleted sent the competitor rows to
  `competitor_history.db` and the velocity reads to `living_systems_intel.db`
  — one component writing an empty file while the other read the live one,
  no warning either side, the two built one line apart in `main.py`. The
  highest-severity finding of the chunk was in a file the diff had not
  touched. There is now one `resolve_db_path(config, config_path)`.
* **F2 (high, P2/P16).** The config-absent branch reported nothing, so a
  checkout with no `shared_config.json` two levels up produced a briefing of
  zero competitors at exit 0. It warns, naming the config it looked for and
  the database it fell back to.
* **F3 (high, P16/P6).** That branch now opens the repo-root
  `competitor_history.db` where it used to open `Serp-compete/competitor_history.db`
  — a different file, because `run_audit.sh` `cd`s into `Serp-compete` first.
  Stated in `compete-spec.md`, which the diff had edited while leaving the old
  sentence standing.
* **F4 (high, P5).** The new guard checked the leaf and not the section, so
  `"technical": null` was an `AttributeError` from a `.get` on `None` while a
  blank leaf got the designed warning. Both are guarded now, as is a
  top-level config that is not a dict at all.
* **F5 (medium, P32).** The "no second literal" guard matched one quote style
  inside one slice of one file; it is a regex over every module in `src/`.

## What is NOT in this chunk

* **`keyword_enrich.py`** is untracked and is a separate entry point with its
  own `--db` default, no config load, and a bare `requests.get` that records a
  transient failure as "no suggestions" (P1/P2). It is not in the repository,
  so changing it here would commit it; recorded for its owner.
* **A cleanup failure is still reported only to stderr** (Y11 cold review F8),
  which a GUI operator never reads. It needs a counter in the run summary.
* **`keyword_enrich.py` holds a 25th copy of the name** (the cold review's F5)
  — its own `--db` default, no config load, so it ignores `database.path` and
  caches Moz rows into a different database than the run reads. The guard
  `TestTheNameLivesInOnePlace` lists `git ls-files`, so it cannot see the file
  today and **will go red the moment the file is committed**. That is
  deliberate: committing it is the moment to fix it, and the guard says so in
  its own comment.
* **Tool 2 reads `shared_config.json` twice per `DatabaseManager`**, and the
  two reads disagree about whether a corrupt file is fatal:
  `config_for_lock_timeout()` warns and defaults, `load_db_path()` on the next
  expression raises `JSONDecodeError`. Pre-existing, and the same split as
  `database.load_shared_config` versus `scoring_logic.load_shared_config`.
* **Two `competitor_history.db` files exist on disk**, and after this chunk
  only the repo-root one is reachable. Both are gitignored local state; which
  is safe to delete was not established.
