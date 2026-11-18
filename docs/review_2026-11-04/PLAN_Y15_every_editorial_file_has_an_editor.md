# Chunk Y15 — every editorial file has an editor

Carried as "Adjacent issues found, not fixed" by the cold reviews of chunks
Y1–Y6 and repeated in the Y13 and Y14 plans ("no `config_manager` tab for the
editorial keys added in Y1–Y6").

## The fault

`CLAUDE.md` says editorial content — anything a non-developer might reasonably
want to change — belongs in a YAML or JSON file rather than in Python, and the
review chunks moved a great deal of it out. The Configuration Manager is how a
non-developer reaches those files, and it was never extended: it registers nine
tabs, and the repo now holds nineteen editable editorial files.

Covered by a tab today:

`domain_overrides.yml`, `classification_rules.json`, `intent_mapping.yml`,
`strategic_patterns.yml`, `brief_pattern_routing.yml`,
`intent_classifier_triggers.yml`, `config.yml`, `url_pattern_rules.yml`,
`client_profiles.yml`.

Reachable only by opening the file in a text editor:

| File | What a reader would want to change |
|---|---|
| `feasibility_messages.yml` | status labels + icons, the "why there is no verdict" sentences, the coverage phrases printed beside every mean |
| `gsc_messages.yml` | the words for the three Search Console fetch outcomes |
| `ai_visibility_messages.yml` | the words for every "not measured" state in the AI-visibility family |
| `serp_vocab.yml` | stop words, PAA triggers, service tokens, probe templates, `fetch_status`, `db_cleanup` |
| `glossary.yml` | the plain-English definition of every term of art the report prints |
| `play_routing.yml` | the Recommended Play decision table and each play's strategy text |
| `engine_profiles.yml` | per-engine source bias and the "what to change here" advice |
| `report_writing_directives.yml` | the "When you write:" line under each report section |
| `brief_validation_rules.yml` | what the validator checks the brief's numbers against |
| `schema_recommendations.yml` | the schema.org markup the brief recommends |

So the rule "editorial content lives in config files" was followed, and the
consequence it exists for — that somebody other than a developer can change it
— was not delivered for ten of them. The honest statement of the fault is that
the editorial surface grew and its editor did not.

## What is built

**One tab per uncovered file, from one declaration.** The nine existing tabs
are hand-written classes, several of them 200–400 lines of bespoke widgets for
a particular file's shape. Ten more of those would double the module and is not
what this is worth. `BaseConfigTab` already owns load / validate / save /
dirty-tracking; what a subclass adds is the rendering. So:

* One `EditorialSourceTab` that edits the file's own text, declared from a
  table in `config_tab_models.EDITORIAL_SOURCE_FILES` — file name, type,
  title — so adding the eleventh file is a row, not a class.
* **Source rather than a widget form, deliberately.** These ten files nest
  arbitrarily: `engine_profiles.yml` and `report_writing_directives.yml` are
  three and four levels deep with prose leaves, and the existing
  `ConfigSettingsTab` renderer handles exactly two levels. Generalising a
  widget tree to arbitrary nesting is more GUI surface — and more GUI risk, in
  a module whose own history is initialisation-order bugs — than the editorial
  benefit justifies. A form for a particular file stays available as a later
  per-file upgrade; that is what the nine bespoke tabs are.
* What a source tab adds over opening the file in a text editor, which is the
  whole claim: the file is discoverable in the window with help text saying
  what it decides; its YAML is parsed before the write, so a syntax error is
  reported with its line instead of breaking the next run and a file that does
  not parse is never saved; its own validator runs; it joins Save All, Discard
  and the unsaved-changes prompt; and the text is written verbatim, so comments
  — including ones the user adds — survive exactly, and an edit to a comment
  alone counts as a change.
* `ConfigSettingsTab` keeps its own class: it has the `?` per-field help, the
  positive-only floors and the per-field parse reporting, none of which a
  source editor has.

**A standing guard that the table is complete.** The reason this chunk exists
is that a file was added without an editor and nothing said so. A test walks
the repo's editorial YAML/JSON files, excludes the ones that are schemas or
generated artefacts by an explicit list (so the exclusion is a decision on the
record, not a pattern), and fails when any remaining file has no tab. This is
the part that stops the fault recurring; the ten tabs only clear the backlog.

## Verification

Business logic without tkinter, per `CLAUDE.md`: the declaration table, the
completeness guard, the round-trip (load a file, change a value, save, read it
back and compare) and comment preservation are all testable with no widgets.
The initialisation-order inspection test
(`tests/test_config_manager.py::TestTabInitializationOrder`) must cover every
new tab, since that is the bug class this GUI has produced before. tkinter is
available in the venv, so the widget tests run locally too.

Full suite by exit code, plus the mutation gate: each production change
reverted on its own must fail a guard covering its own criterion.

## What is NOT in this chunk

* Changing any editorial content. This chunk builds the editor; the words stay
  as they are.
* `handoff_schema.json`, `ai_visibility_export_schema.json` — contracts between
  the two tools, not editorial text; hand-editing them in a GUI is how the two
  sides drift. They go on the explicit exclusion list with that reason.
* `diff_report.json` — a generated artefact, excluded for that reason.
* The adjacent issues still open: Tool 2's two divergent `shared_config.json`
  readers and its double read per `DatabaseManager`, Tool 2 having no editorial
  text file at all, and the untracked `keyword_enrich.py`.

## Cold review and what it changed

A cold `learning-qa` pass over the chunk's diff returned seven findings — four
high, three medium. All seven are fixed, each with a guard. The first mutation
gate over the fix batch had two vacuous results; both were real gaps and both
are closed below. Final gate: **18 mutations, 18 caught, 0 vacuous**. Full
suite by exit code: **2325 passed, 68 skipped, 196 subtests, EXIT=0**.

**1 (high, P2/P6) — the repair was discarded and the warning was invisible.**
`TabFileState.has_unsaved_changes` returns `False` when `load_error` is set, so
a syntax repair typed into a source tab was dropped on close with no prompt;
and the red banner was packed after `render_ui`'s `expand=True` frame, so Tk
squeezed it to one pixel (`winfo_ismapped()` returned 0). The base's rule —
never write over a file that was never read — belongs to a form that would
re-dump a structure it could not parse. A source tab writes the user's own text
and re-parses it first, so there is nothing to lose. `EditorialSourceTab` now
overrides `has_unsaved_changes` and `save_blocker` (a file changed on disk still
blocks) and says in the banner that the fix can be made and saved here. The
banner is packed before the body in `BaseConfigTab.__init__` and
`revert_to_disk`, and a guard asserts it is mapped and more than 5px high.

**2 (high, P3/P6) — the editor wrote to the current directory.**
`BaseConfigTab.file_path` was `os.path.join(os.getcwd(), file_name)` while nine
of the ten readers anchor on `os.path.dirname(os.path.abspath(__file__))`.
Measured: with the cwd elsewhere the Glossary tab showed blank, `load_error`
was `None`, and Save All reported success while creating a new file in the cwd.
`config_tab_models.editorial_file_path` is now the one resolver, anchored on
`EDITORIAL_DIR`, with a `directory` argument for tests; a declared file that is
not there sets a real `load_error` instead of showing an empty editor. The
guard runs from another directory on purpose — the suite's own cwd *is* that
directory, which is why asserting it from here proved nothing and the first
mutation came back vacuous. Two side effects worth recording: the six
`TestEditorialSourceTab` tests that `os.chdir`'d had pinned the old behaviour
and now pass `directory=`; and a run of `tests/test_config_manager_save.py` in
the intermediate state overwrote `config.yml`, `strategic_patterns.yml` and
`brief_pattern_routing.yml` in the working tree, because the fixture only
chdir'd. Those were restored from git, the fixture now points `EDITORIAL_DIR`
at its copies, and a new guard asserts no tab in that fixture can write outside
the test's own directory.

**3 (high, P5/P2) — valid YAML is not a valid rule table.** None of the ten
files is in `VALIDATORS_BY_FILE`, so the tabs checked syntax only. Deleting
`rules:` from `play_routing.yml` saved cleanly and the next run died in
`brief_data_extraction`; deleting `numeric_claims:` from
`brief_validation_rules.yml` left every numeric check off with
`fields_skipped=[]` and `load_error=None`, so nothing said so.
`EDITORIAL_SOURCE_FILES` gained a fourth element naming a `module:function`
structural check, and `structural_errors_for_text` hands the edit — written to
a temp file, never the real one — to the file's own loader, which already knows
the rules (P32, no second copy). Populated for those two files; `None` for the
rest, where the readers already degrade loudly. The second vacuous result was
here: `load_validation_rules` had no way to say "this file declares no checks
at all", so that is now reported on the result like any other inactive check,
which the brief's `.validation.md` already states.

**4 (high, P2) — the guard listed untracked files.** It walked every
`*.yml`/`*.json` at the repo root, so `touch zz_scratch.yml` failed the suite
and the gitignored `diff_report.json` read as an editorial file nobody had
wired up. The inventory is now the files git tracks at that root, with a
directory-listing fallback for the temp directories the tests of the function
use. Scope stated in the test and in `docs/config_reference.md`.

**5 (high, P2) — every save appended a blank line.** A Tk text widget carries
an implicit final newline, so `get("1.0", tk.END)` returned the content plus
one and `save_to_disk` wrote it verbatim: `a: 1\n` → `a: 1\n\n` → `\n\n\n`
across three saves of an unchanged file. `has_unsaved_changes` rstrips both
sides, so a user deleting the accumulated blanks was told nothing had changed.
Now `get("1.0", "end-1c")`, guarded through the widget path rather than through
`write_source`.

**6 (medium, P2) — a non-OSError lost the partial-save report.** The override
caught `OSError` where the base catches `Exception`, so anything else escaped
`save_changed_tabs` and the user was never told which files had already been
written. Matched to the base.

**7 (medium, P2) — the temp file.** A fixed `<file>.tmp` left partial content
beside the file when the write failed, with nothing to clean it up or mention
it, and two writers of one file collided on the name. Now `tempfile.mkstemp` in
the target directory, `flush` + `fsync` before `os.replace`, and the temp file
removed on any failure. Two guards: a failed write leaves only the original,
and two writes of one file do not share a temp name.

Also noted and acted on: `revert_to_disk` now clears `_parse_error`;
`tests/test_config_manager.py::test_tabs_created` still asserts `9 +
len(EDITORIAL_SOURCE_FILES)`, which is the count of bespoke forms and is
checked against the files beside it.

## Adjacent issues found, not fixed

* `validate_cross_file_constraints` is imported at `config_manager.py:41` and
  called nowhere. Pre-existing dead code; it covers none of the ten files.
* `test_every_declared_source_file_has_help_text` uses `len(text) > 120` as a
  proxy for usefulness. It catches an absent entry, not a useless one.
* `config_manager.py` is now past 2900 lines. `serp_audit.py` has a size cap
  enforced by a test and this module has none.
* Tool 2's three divergent `shared_config.json` readers and its import-time
  read (chunk Y16, planned in `PLAN_Y16_one_reader_for_the_shared_config.md`).
* Tool 2 has no editorial text file at all — every reader-facing sentence is a
  Python literal. The direct analogue of this chunk, and a chunk of its own.
* The untracked `keyword_enrich.py`: a 25th copy of the database name, its own
  `--db` default, no config load, and a bare `requests.get` recording a
  transient failure as "no suggestions" (P1/P2). Out of scope because fixing it
  means committing a file the owner has kept local.
