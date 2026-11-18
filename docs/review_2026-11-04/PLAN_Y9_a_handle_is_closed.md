# Review chunk Y9 — a committed write is not a closed handle

Adjacent issue carried by the Y5 and Y6 plans, and the reason the Y6 guard
(`TestTheTwoHistoryReadersCloseTheirHandles`) names two files instead of the
repo: `with sqlite3.connect(path) as conn:` commits on a clean exit and rolls
back on an exception, but it **never closes the connection**. The handle is
released whenever the object is collected, which is not a guarantee the code
makes. 53 production sites across 19 modules use that form.

## Why it matters here

A run opens the database per cached lookup, not once: `moz_client`,
`dataforseo_client`, `moz_keywords`, `gsc_client`, `aivi`, `aio_exposure`,
`brand_mentions`, `citation_table`, `commodity_score`, `foundational_score`,
`engine_transfer`, `answer_sentiment` and `probe_ai_visibility` each open and
close around single statements, inside per-keyword and per-engine loops. The
leak is not a crash, which is why it has survived: CPython collects the
connection at the end of the function in most of these cases. It is a
correctness claim the code does not make, and it is the kind of thing that
turns into "database is locked" once anything runs two of these at once.

## The trap in the obvious fix

`with closing(sqlite3.connect(path)) as conn:` closes the handle **and drops
the commit**: `closing` does not run the connection's own `__exit__`, so every
write inside the block is rolled back by the close. Converting 61 sites that
way would silently stop the caches being written. The conversion has to keep
both behaviours.

## What is built

- **`db_connect.py`** (new) — `connection(db_path)`, a context manager that
  yields a connection, commits on a clean exit, rolls back on an exception,
  and closes the handle on every path. One definition, so the next module does
  not have to get the pairing right (P32).
- Every production `with sqlite3.connect(...) as conn:` becomes
  `with db_connect.connection(...) as conn:`. Tests keep the plain form: they
  run in a process that exits, and converting them would double the diff for
  no behavioural claim.
- The Y6 guard widens from two files to every production module, with the two
  files' own test folded into it.

## Acceptance criteria

1. `db_connect.connection` commits a write made inside the block, rolls back
   on an exception, and closes the handle in both cases.
2. No production module opens `sqlite3.connect` in a `with` that does not
   close it.
3. The caches are still written: the full suite passes unchanged.

## What was built

- **`db_connect.py`** — `connection(db_path, **kwargs)`: commit on a clean
  exit, rollback on an exception, `close()` in a `finally`. 36 lines.
- 61 `with sqlite3.connect(...) as conn:` sites in 20 modules became
  `with db_connect.connection(...) as conn:` — `storage` (9), `moz_keywords`
  (6), `aio_exposure` (4), and three each in `aivi`, `brand_mentions`,
  `citation_table`, `commodity_score`, `dataforseo_client`, `engine_transfer`,
  `foundational_score`, `gsc_client`, `gsc_demand`, `moz_client`,
  `moz_competitor`, `probe_ai_visibility`, two in `answer_sentiment`, one each
  in `ai_visibility_export` and `demand_dashboard`.
- Two more sites the adjacent issue had not counted, found by the new
  repo-wide guard: `export_history.py` opened a bare connection and closed it
  only on the happy path (an exception in `pd.read_sql` left it open), and
  `verify_enrichment.py` never closed its handle at all. Both now use the
  helper, which meant indenting the function bodies.
- No site used its connection after the block, so closing it changes nothing
  else: checked with an AST walk over every converted `with`, looking for a
  later reference to the bound name inside the same function.
- Tests keep the plain `sqlite3.connect` form. They run in a process that
  exits, and the guard is scoped to production modules, which is what the
  claim is about.
- `tests/test_y6_the_pipeline_agrees_with_the_run.py`'s
  `TestTheTwoHistoryReadersCloseTheirHandles` is replaced by a comment
  pointing at the repo-wide guard — its own docstring recorded that it was
  scoped to two files only because this diff had not been done.

## Verification

- Full suite: **EXIT=0**, 2170 passed, 68 skipped, 46 subtests passed. The
  caches are what would break if the commit had been lost, and the cache
  round-trip tests across `moz_*`, `gsc_*`, `aivi` and `ai_visibility_*` pass
  unchanged.
- Mutation gate: `scratchpad/mutate_y9.py`, 10 mutations, **all caught, none
  vacuous** — the two halves separately (commit dropped, close dropped), a
  committed rollback, three converted sites reverted to the leaking form, both
  `storage` sites reverted to `closing(sqlite3.connect(...))`, a connection
  opened as `from sqlite3 import connect`, and the repo walk itself widened to
  skip nothing.
- Effort tier: **Full** — it changes how every database write in the tool
  commits. Production: a 36-line new module plus 55 changed call-site lines in
  20 files. Tests: 180 new lines, 30 removed (≈1.3x). Doc prose: 12 lines.

## Adjacent issues found, not fixed

- The SQLite busy timeout (`sqlite3.connect`'s implicit 5 seconds) is a hidden
  constant, now reachable from one place. Chunk Y5 promoted every other wait in
  this tool to config on the ground that one number cannot be right for
  different waits, and `demand_dashboard.py` already names "database is locked"
  as a degradation it swallows (cold review of this chunk, F6).
- `moz_keywords.py` holds two near-identical `_cache_lookup` / `_cache_store`
  pairs (`MozKeywordClient` at line 386, `MozIntentClient` at 549) differing
  only in the table and the columns. Their shared base `_KeywordSignalClient`
  is where one of them belongs. The Y9 mutation that reverts the connection
  form has to be applied to both to be caught once, which is how the
  duplication surfaced.
- Still open from Y8: no `config_manager` tab for the editorial keys added by
  chunks Y1–Y6, and untracked `keyword_enrich.py` is a sixth entry point that
  loads no config and so applies none of the startup policy.


## Cold review of this chunk

A cold `learning-qa` pass over the diff returned 7 findings, every one of them
in the **guards** rather than the conversion. The reviewer measured the premise
rather than taking it: on python 3.12, 50 iterations of the old form leak 46
file descriptors on the happy path, and none through the helper. It verified as
sound: no cursor or row object escapes a converted block (an AST walk over all
61, which catches what my own walk on the bound name would have missed), no
nesting or reentrancy, no `with` inside a loop, `except BaseException` matching
what `sqlite3.Connection.__exit__` already did on Ctrl-C, the 32 remaining
hand-written `conn.commit()` calls redundant rather than wrong, both
hand-indented files correct, no import cycle possible, and `serp-compete`
unaffected because it reads the export by file glob and never imports the
module. It also counted 61 sites in 20 modules, not the 53 in 18 I had
reported; the figures above are the reviewer's.

Fixed, each with a mutation that the guards catch:

- **F1 · high (P30)** — every guard asserted spelling or the helper's own
  behaviour; none asserted the quantity the bug was about. A test now runs 50
  real `aivi` write/read pairs and asserts the process holds no more open
  descriptors at the end than at the start. Verified both ways: it fails with
  the helper's `close()` removed.
- **F2 · high (P5/P2)** — `storage.migrated_connection` still returned
  `closing(sqlite3.connect(db_path))`, the other half of the trap, sanctioned
  for `metrics.py` and `visualize_volatility.py`. Harmless while those two only
  read, and a silently discarded write the day one of them does not. Both
  `storage` sites now use the helper, the `closing` import is gone, and the
  guard no longer excuses a `closing(...)` argument.
- **F3 · high (P29)** — the anti-vacuity floor was 40 against a real 82, and
  the membership list named 6 of the 20 modules that open the database, so 15
  could fall out of the walk unnoticed. The expectation is now derived: every
  module whose source contains a `db_connect.connection` call must be one the
  walk reached.
- **F4 · medium (P27)** — the walk was an unrestricted `rglob`, so a
  `.claude/worktrees/<name>` holding a pre-Y9 branch would have made the guard
  report offenders in code outside the tree under review. It is driven by
  `git ls-files` (plus the chunk's own untracked modules) and skips any
  dot-prefixed path.
- **F5 · medium** — the walk matched only `sqlite3.connect`, so
  `from sqlite3 import connect` or `import sqlite3 as db` would have
  reintroduced the leak past it, and the `closing` whitelist was keyed on line
  number rather than node identity. `_connect_calls` now resolves the module's
  own aliases and matches by node.
- **F7 · low** — 14 modules kept an `import sqlite3` with no remaining use.
  Removed, because a file that still imports it is the invitation for the next
  author's `sqlite3.connect`. Kept where it is still used: `storage`
  (`sqlite3.Row`), `demand_dashboard` (`sqlite3.OperationalError`),
  `ai_visibility_export`, `probe_ai_visibility`, `db_connect`.

**F6 · medium, not fixed, recorded as adjacent** — `sqlite3.connect`'s
implicit 5-second busy timeout is now behind one door and could become
editorial config, the way chunk Y5 promoted the three other waits in this tool.
It is a pre-existing constant and not something this chunk introduced, so it is
listed below rather than widening the diff.
