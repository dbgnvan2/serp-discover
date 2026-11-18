# Review chunk Y10 — Tool 2 closes its handles too

Chunk Y9 fixed `with sqlite3.connect(path) as conn:` across Tool 1
(`serp-discover`): it commits on a clean exit and rolls back on an exception,
but never closes the handle, and the obvious fix
(`closing(sqlite3.connect(path))`) closes the handle and discards the commit.
Tool 2 has the same class, one level further in.

## Where it is

- `DatabaseManager._get_connection()` (`Serp-compete/src/database.py:107`)
  returns a bare `sqlite3.connect(self.db_path)`. 37 sites in `database.py`
  and two in `reporting.py` use it as `with self.db._get_connection() as
  conn:` — committed, never closed.
- `VelocityTracker._get_connection()`
  (`Serp-compete/src/velocity_module.py:56`) is the same factory with four
  such sites.
- Two callers take the connection **bare** and never close it at all:
  `eeat_scorer.save_to_database` (`eeat_scorer.py:392`) and
  `cluster_detector` (`cluster_detector.py:172`). Both write, so neither can
  simply be wrapped in `closing`.

This matters more here than in Tool 1: `database.py`'s writes run per
competitor and per URL inside the audit loop, and `reporting.py` opens the
database again while rendering.

## What is built

- **`Serp-compete/src/db_connect.py`** — `connection(db_path, **kwargs)`, the
  same helper Tool 1 got in chunk Y9: commit on a clean exit, rollback on an
  exception, close in a `finally`.
- `DatabaseManager` and `VelocityTracker` expose `connection()` — a managed
  context manager — and `_get_connection` is **removed** rather than kept as
  an alias, so there is one door, not two. The `with` sites change only their
  method name; the two bare callers become `with` blocks.
- A guard that no module in `Serp-compete/src` opens a connection outside the
  helper, in any spelling, and that a run of real writes and reads releases
  every descriptor it opened — the quantity the bug is about, which chunk Y9's
  cold review established a shape guard cannot stand in for (P30).

## Acceptance criteria

1. `db_connect.connection` commits a write made inside the block, rolls back
   on an exception, and closes the handle in both cases.
2. No module in `Serp-compete/src` opens `sqlite3.connect` outside the helper.
3. A sequence of real `DatabaseManager` writes and reads leaves the process
   holding no extra open descriptors.
4. Both suites pass unchanged: the caches and history tables are still
   written.

## What was built

- **`Serp-compete/src/db_connect.py`** — the same 36-line helper Tool 1 got in
  chunk Y9.
- `DatabaseManager.connection()` and `VelocityTracker.connection()` return it.
  `_get_connection` is gone, not aliased, and a guard asserts that: two doors
  is how one of them stays unfixed (P32).
- 41 `with self._get_connection() as conn:` sites (37 in `database.py`, 4 in
  `velocity_module.py`) and the two in `reporting.py` changed method name only
  — the `with` statement and the body are untouched, because the helper yields
  the connection exactly as `sqlite3.connect` did.
- `eeat_scorer.save_to_database` and `cluster_detector`'s persistence took the
  connection bare, wrote through it, called `conn.commit()` and never closed
  it. Both are now `with db_manager.connection() as conn:` blocks, and their
  hand-written `commit()` and local `import sqlite3` are gone with them.
- 18 test files used `db._get_connection()`; they call `db.connection()` now.
  `tests/test_risk_radar.py`'s three `patch.object(db, "_get_connection", ...)`
  fakes patch `connection` instead — their own docstring explains why they must
  raise *inside* the guarded block rather than at the factory, and that still
  holds.
- `tests/test_y10_tool2_closes_its_handles.py` — 8 tests: the helper's three
  behaviours, the source walk (driven by `git ls-files`, matching every
  spelling of the import), the removed alias, a real 50-iteration
  write/read loop that asserts no descriptor is left open, and a committed
  write read back through a second connection.

## Verification

- Core suite: **EXIT=0**, 822 passed. Root suite: **EXIT=0**, 162 passed.
  Both were 814 / 162 before, so nothing regressed and 8 tests are new.
- Mutation gate: `scratchpad/mutate_y10.py`, 9 mutations, **all caught, none
  vacuous** — each half of the helper separately, a committed rollback, both
  factories reverted to a bare connection, the old name kept as an alias on
  each of the two classes, one of the bare writers reverted to never closing
  its handle, and a connection opened as `from sqlite3 import connect`.
- Effort tier: **Full** — it changes how every database write in Tool 2
  commits. Production: a 36-line new module, two rewritten factories, 43
  renamed call sites, two converted blocks. Tests: 170 new lines plus 18 files
  renamed mechanically. Doc prose: 10 lines.


## Cold review of this chunk

A cold `learning-qa` pass over the diff returned 8 findings. None was a
semantic break in the conversion: the reviewer swept all five changed modules
for a cursor, `Row` or generator escaping a block (none; the only value read
off a cursor is `lastrowid`, inside its block), confirmed the transaction
boundaries are unchanged at all 43 renamed sites, that the removed
`conn.commit()` calls in `eeat_scorer` and `cluster_detector` were the last
statements in their functions and their callers still count a failure, that
`from src import db_connect` resolves under both of this repo's PYTHONPATH
conventions and that the one entry point where `src/` is `sys.path[0]` never
imports either module, that the `patch.object(db, "connection", ...)` fakes
still model what production does inside the guarded block, and that no raw
`sqlite3.connect` or `_get_connection` is left in Tool 2's production code. It
also measured the leak on python 3.14: the pre-fix shape left **57** extra
descriptors open over 50 write/read iterations, because the connection↔cursor
cycle defers the close to a garbage-collection pass.

Fixed:

- **F1 · medium (P32/P19)** — `test_the_old_factory_is_gone_rather_than_kept_as_an_alias`
  asked `hasattr` of `DatabaseManager` only and then needled the source for the
  string `_get_connection()`, which an alias written as
  `def _get_connection(self): return self.connection()` does not contain. So
  the exact regression it exists to stop passed on the velocity side. It now
  asks both classes and walks the AST for a definition or assignment of that
  name, and both aliases are mutations in the gate.
- **F2 · medium (P30/P10)** — the descriptor assertion drove `DatabaseManager`
  alone, the least leaky third of the change. It now also exercises
  `EEATScorer.save_to_database` and `ClusterDetector.save_to_database` — the
  two that took the connection bare and never closed it, per URL and per
  domain inside the audit loop — and `VelocityTracker`'s write and read.
- **F3 · medium** — `reporting.py`'s Excel export opened a connection, began a
  transaction and closed it again for **zero statements**: every sheet below it
  is a DataFrame built under the earlier block. The rename carried the dead
  `with` forward and it read as though the sheets were queried there. Deleted.
  No guard: it is a deletion of dead code whose only effect is one fewer
  handle, and both suites cover the briefing path.
- **F4 · medium-low (P31/P3)** — the absence claim was computed over
  `Serp-compete/src` only, so it said nothing about `recalculate_scores.py`, an
  entry point that constructs `DatabaseManager` against the live database. The
  walk now covers `Serp-compete/*.py` too, with `:(glob)` pathspec magic so
  `*` does not cross into `tests/`, which keeps the raw form on purpose to
  build pre-migration schemas.
- **F5 · low** — `docs/tool2_review_bundle/` holds frozen copies of these
  modules and is the copy somebody would paste from. Its README now says so,
  dated, and names this drift specifically.
- **F6 · low (P6 applied to the record)** — the plan and the new docstring
  named `VelocityModule`; the class is `VelocityTracker`. Corrected
  throughout.
- **F8 · low** — both new files (`Serp-compete/src/db_connect.py`,
  `Serp-compete/tests/test_y10_tool2_closes_its_handles.py`) are named
  explicitly in the commit, checked against `git show --stat` afterwards. A
  missing helper would raise `ImportError` at `src.database` import, which
  seven modules catch around `from src.database import load_shared_config` and
  answer with a hardcoded default (P40).

## Adjacent issues found, not fixed

- `db_connect.connection` calls `conn.rollback()` inside
  `except BaseException:`. If the rollback itself raises, its exception is the
  one the caller sees and the original survives only as `__context__`. Latent:
  no site closes the connection inside its own block. The same helper is in
  Tool 1, so the fix belongs in both at once (cold review, F7).
- The SQLite busy timeout is still a hidden 5 seconds, and Tool 2 is the tool
  that meets it: `reporting.py` holds one connection open across the whole
  briefing while each `self.db.get_*` inside opens another. Carried from chunk
  Y9's cold review (F6 there).
