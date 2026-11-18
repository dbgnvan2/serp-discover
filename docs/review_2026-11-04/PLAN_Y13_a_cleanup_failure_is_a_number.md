# Chunk Y13 — a cleanup failure is a number, not a line on stderr

Carried as "Adjacent issues found, not fixed" by chunk Y11's cold review
(finding F8) and repeated in chunk Y12's plan.

## The fault

Chunk Y11 made `rollback()` and `close()` unable to replace the exception that
caused them: `db_connect._safely` logs and carries on, in both repos. That was
the right call — a failing cleanup is a second fact, not the diagnosis — but
the second fact then goes nowhere a reader looks:

1. **`logger.exception` writes to stderr.** The GUI operator runs the audit
   through `serp-me.py`, which shows the step's output in a window, and reads
   the workbook afterwards. A `close()` that failed on row 300 of 1,000 is a
   line somewhere in a scrollback, in among every other log line. Nothing in
   the JSON, the workbook or the report says it happened (P2 — surface, never
   silently drop).
2. **A repeating failure is invisible as a repetition.** In Tool 2 the audit
   opens and closes a connection inside its per-domain loop. A `close()` that
   fails once probably failed every time, and every failed close is a leaked
   file descriptor; the process runs out of them long before anyone reads the
   log. One line per occurrence is not the same as "this happened 437 times",
   and only the second is actionable.

Neither repo counts them, so neither can say so.

## What is built

**One counter, beside the helper that already knows.** `db_connect` keeps a
per-process tally keyed by `(what, db_path)` — `what` being `roll back` or
`close`, the two cleanup steps — incremented by `_safely` where it already
logs. `cleanup_failures()` returns it; `reset_cleanup_failures()` clears it,
for the entry points that run more than one step in a process (the GUI).

**The tally reaches the reader.** In Tool 1 the audit adds a
`parsing_warnings` row — the project's existing channel for "what this run
could not do" — which lands in the JSON and the workbook's Parsing_Warnings
sheet. In Tool 2 the audit's run summary carries the same count.

**The words are editorial.** `serp_vocab.yml` gets a `db_cleanup` block, like
`fetch_status` beside it: a cleanup failure that an operator has to act on
needs wording an operator can read, and the repo's rule is that such wording
lives in config, not in a Python literal. `db_connect.cleanup_failure_warning()`
renders it, importing `pattern_matching` inside the function body — this module
is what every other one opens the database through, and it does not load YAML to
do that. A missing block or a template that lost a placeholder degrades to the
same sentence as a Python default rather than aborting a run whose data is fine,
the contract `enrichment.status_text` already has.

Tool 2 has no editorial text file at all, so its copy of the sentence is a
constant in its own `db_connect` and the two have to be changed together. That
is recorded below, not fixed here: giving Tool 2 a vocabulary file is its own
chunk.

**The count is not an error.** A failed cleanup after a successful commit does
not make the run's data wrong — that is the whole point of chunk Y11 — so the
run's exit code does not change. It is reported, not raised.

## Verification

Full suite by exit code in both repos, plus the mutation gate: each production
change reverted on its own must fail a guard covering its own criterion. The
guards that matter are consequences: a connection whose `close()` fails, and
then the warning row in the audit's own output — not an assertion that a
counter variable exists.

## Cold review (both halves) and what it changed

Sixteen findings, none high. The seven that were fixed:

* **The sentence claimed a success it had not checked.** It said the run's
  writes were committed and its figures stand in every case, including a
  counted `roll back` — which by construction means a block raised and
  abandoned its transaction. The consequence is now chosen by the step that
  failed, in both repos (P6).
* **The tally was read before the run's last database work.** Tool 1 built the
  row ~250 lines before the report's trend reads and the write that marks the
  run complete; Tool 2 took its snapshot before the report generator's own six
  reads. Tool 1 now reports again at the end, naming what arrived after the
  output was written, and Tool 2 reports in a `finally`, which also covers its
  abort paths (an unwritable database file is a plausible cause of exactly
  such an abort).
* **One of fifteen consumers reported anything.** Every module opens the
  database through `db_connect`, and only the audit renders the sentence. An
  `atexit` hook in each repo's `db_connect` is the floor for the rest, and
  stays quiet when a caller has already reported.
* **The Python fallback was not the file's text.** It stopped at "its figures
  stand", so in the one situation it exists for — an unreadable
  `serp_vocab.yml` — the operator got the sentence without the diagnosis. The
  two are now verbatim equal, and a test asserts it (P32).
* **The sentence discarded the paths it was keyed on.** The reader's next
  action is to check a file, and since chunk Y12 the path is configurable, so
  more than one database involved is now named.
* **The tally could be lost or raise.** The increment was an unsynchronised
  read-modify-write and the readers iterated the live dict; the GUI has a
  worker thread beside its Tk thread, where a count could be lost and a copy
  could raise `RuntimeError: dictionary changed size during iteration` — a
  diagnostic aborting the run it was diagnosing. One lock now covers both. The
  counting is also inside the exception handler, so it is wrapped: it must not
  escape and replace the caller's exception, which is the defect Y11 removed.
* **Guards that asserted source text where a consequence was observable.**
  Tool 2 already had a harness that runs the real `run_audit` against fakes,
  so its "reaches the briefing" tests now read the briefing's markdown; its
  ordering guard compared offsets in an `ast.dump` string, which stayed green
  under the regression it existed to catch. Tool 1's row shape moved beside
  the tally, so the workbook contract is asserted against a real row. The
  remaining structural guards are anchored on call nodes. The test about
  leaked handles leaked three of them and its temp directories; both are now
  cleaned up.

Two docs claims were corrected rather than coded around: that every entry
point clears the tally (only the audit does — the others are separate
processes), and that the GUI runs several steps in one process (it launches
them with `subprocess`).

The suite then found a real bug in Tool 2's exit floor: `reset_cleanup_failures`
cleared the tally but not "already reported", so a second run in one process
could never report at exit.

## What the tally does not cover

Only the audits write the tally into an artefact. Every other entry point in
both repos — the AI probe, the feasibility run, a report render,
`recalculate_scores` — reports it at exit on the console instead, which is
better than the log and worse than a row the reader keeps. Carrying it into
those steps' own outputs is listed below.

## Adjacent issues found, not fixed

* **Tool 2 has no editorial text file.** Every reader-facing sentence in that
  repo is a Python literal, so the rule that editorial wording lives in config
  does not hold there at all. This chunk's sentence had to follow the local
  convention rather than introduce a vocabulary file for one string.
* **Only the audit reports the tally.** The other entry points in both repos
  count their cleanup failures and print nothing: each would need a line in its
  own output.
* Still open from Y11 and Y12: `moz_keywords.py`'s two duplicated
  `_cache_lookup` / `_cache_store` pairs, a `config_manager` tab for the Y1–Y6
  editorial keys, Tool 2's two divergent `shared_config.json` readers and its
  double read per `DatabaseManager`, and the untracked `keyword_enrich.py`.

## What is NOT in this chunk

* The adjacent issues still open from Y11 and Y12: `moz_keywords.py`'s two
  duplicated `_cache_lookup` / `_cache_store` pairs, a `config_manager` tab
  for the Y1–Y6 editorial keys, Tool 2's two divergent `shared_config.json`
  readers and its double read per `DatabaseManager`, and the untracked
  `keyword_enrich.py`.
