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

* A generic `StructuredYamlTab` that renders any mapping of scalars, lists and
  nested mappings with the type-aware widgets `ConfigSettingsTab` already has —
  the widget code is lifted into one place rather than copied, since
  `ConfigSettingsTab` is itself an instance of exactly this (P32).
* A declaration table — file name, tab title, help text — so adding the
  eleventh file is a row, not a class.
* `ConfigSettingsTab` keeps its own class only if it needs behaviour the
  generic tab does not have; if it does not, it becomes a row in the table and
  its bespoke renderer is deleted.

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
