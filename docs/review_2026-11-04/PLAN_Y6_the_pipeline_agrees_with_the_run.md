# Review chunk Y6 — the pipeline agrees with the standalone run

Adjacent issues logged by earlier chunks' cold reviews (global rule 10). Each
is the same shape: a fact the tool measures is not the fact the pipeline acts
on, because the pipeline reaches the decision before the measurement exists.

## The findings

### 1. The in-pipeline pivot decides without the measured intent (the chunk's reason)

`serp_audit.py` decides every keyword's neighbourhood pivot inside the SERP
fetch loop, one keyword at a time, before `keyword_profiles` exists. It
therefore calls `feasibility.generate_hyper_local_pivot` with neither
`serp_intent` nor `entity_distribution`:

```
pivot_result = feasibility_module.generate_hyper_local_pivot(
    primary_keyword=source_keyword, ...
    is_service_like=kw_service_like,
    pivotable_intents=FEASIBILITY_PIVOTABLE_INTENTS,
)
```

while the standalone `run_feasibility.py` passes both, from the profiles the
audit JSON already carries. Two consequences, both of them the function's own
documented behaviour reversed:

- **The token guess decides the gate.** `generate_hyper_local_pivot`'s
  docstring says that when `serp_intent` carries a verdict "that verdict
  decides the gate and `is_service_like` is only a fallback: the run has
  already classified this SERP from its own results, and a token guess from
  the keyword string should not overrule it (D-M-19 / D4.10)". In the pipeline
  there is no verdict, so `query_variants.is_service_like(source_keyword, …)`
  — a word-list test on the keyword string — is the whole gate. A keyword
  whose SERP the run measured as `local` gets no pivot if its words do not
  look service-like, and a keyword measured `informational` gets one if they
  do. The refusal text then names the token guess as the reason.
- **The strategy paragraph omits the composition the run measured.** With
  `entity_distribution` the paragraph opens "The city-wide market for 'North
  Vancouver' is dominated by directory results (8 of 10)"; with `None` it
  opens "is out of reach on domain authority alone". **Checked and corrected
  while reproducing:** the first draft of this plan said `None` restores the
  unconditional directory claim that D-M-09 removed. It does not — `None`
  degrades honestly, and the fix for that finding is sound. What the pipeline
  loses is the measured evidence: the same keyword gets a weaker reason from
  the pipeline than from the standalone run, over the same SERP, and a reader
  comparing the two reports sees two different explanations.

Both are measured facts the run already has — every organic row in the loop
carries `Entity_Type` from the enrichment pass, and `intent_verdict`
classifies the SERP from those rows. The pipeline simply asks before it looks.

### 2. `refresh_analysis_outputs.py` is a fifth config loader that applies no retry policy

Chunk Y4 made the outbound retry policy editorial and had every entry point
apply it at startup — `serp_audit`, `run_feasibility`, `run_gsc_analysis`,
`probe_ai_visibility`, and `report_llm` for the brief's route.
`refresh_analysis_outputs.py` loads `config.yml` and never calls
`http_retry.apply_retry_policy`, so a rebuild started from it uses the
documented defaults whatever `config.yml` says. That is the exact failure the
Y4 note describes: a setting that changes four scripts and silently does
nothing in the fifth (P5/P25).

### 3. `visualize_volatility.py` opens the database behind `SerpStorage`'s back

It calls `sqlite3.connect(DB_PATH)` directly and reads `serp_results.rank`,
`query_label` and `runs.completed_at` — three columns that exist because
`SerpStorage._init_db` created or migrated them. On a database that predates a
migration the query fails with `OperationalError` rather than running the
migration the rest of the tool runs on open, and chunk Y5 made those migrations
raise rather than pass silently, so the failure is now louder and still
unhandled.

### 4. Two sponge helpers name module constants as default arguments

`run_gsc_analysis.compute_sponge_effect` and `find_reformat_candidates` take
`min_bucket_size=MIN_BUCKET_SIZE`-style defaults. Harmless today because every
caller passes the resolved value, but it is the shape of the Y4 trap: a default
argument binds when the module is imported, so a configured value never reaches
a caller that omits it. Y4 fixed the same shape in `http_retry` after it bit.

## Deliberately not in this chunk

- **`serpapi.*` and `http_retry.*` are two retry policies.** Reconciling them
  changes the config contract (which keys an existing `config.yml` must carry),
  so it is a chunk with its own migration note, not a line here.
- **The new editorial keys have no `config_manager` GUI surface.** A GUI tab is
  its own piece of work with its own initialisation-order guard.
- **The ~60 `with sqlite3.connect(...)` sites** that commit rather than close.
  Logged by Y5's cold review; converting them all is a sweeping diff.

## The fixes

1. **The pivot pass moves out of the fetch loop.** The loop keeps computing
   `feas` (it needs the Moz batch it has in hand) and records what the pivot
   decision will need — the feasibility figures, `client_da_source`, the
   service-token guess — in one `pending_feasibility` entry per label-A
   keyword. After the loop, and before the pivot *fetch* pass that consumes
   its output, `serp_audit` assembles the label-A SERP lists it has collected,
   builds `keyword_profiles` from them with the one shared builder
   (`brief_data_extraction.build_keyword_profiles` — the same call the end of
   the run makes), and runs the pivot decision per keyword with `serp_intent`
   and `entity_distribution` passed, in the call shape `run_feasibility.py`
   uses. The feasibility rows, the storage write, the printed line and the
   pivot queue all move with it. Nothing about the pivot fetch pass changes:
   it still reads `pending_pivot_jobs`.
2. `refresh_analysis_outputs.py` applies the retry policy where it loads the
   config, like the other four.
3. `visualize_volatility.py` opens the database through `SerpStorage`, so the
   migrations run before it reads a migrated column.
4. The two sponge helpers take `None` and resolve in the body.

## Guards (one per finding)

- The pipeline's pivot decision is made with the measured intent: a keyword
  whose SERP measures `local` but whose words are not service-like gets a
  pivot, and one measured `informational` whose words are service-like does
  not — the opposite of what the token gate alone produces.
- The pipeline's strategy paragraph names the measured composition ("dominated
  by directory results (8 of 10)") where the standalone run's does, and still
  says nothing about composition when no distribution was measured.
- Both entry points produce the same pivot decision from the same SERP.
- `refresh_analysis_outputs` applies the configured policy at startup.
- `visualize_volatility` works against a database created before a migration.
- Each sponge helper sees a value applied after import.

## Verification

Effort tier **Full** (`~/.claude/standards/effort-budget.md`): the change moves
a decision that spends money (a pivot queues a paid SerpAPI fetch) and touches
four entry points, so it can break something.

- **Reproduction.** A probe ran both call paths over the same SERP facts for
  `"bowen theory explained"` (no service token in the keyword, a measured
  `local` SERP intent). The pipeline's path returned
  `No pivot — non-service (no SERP intent verdict — judged from the keyword
  text)`; the standalone path returned `Pivoting to Hyper-Local` with
  `gate_source=serp_intent.primary_intent`. SAME DECISION? False.
- **One plan claim was wrong and is corrected above.** `entity_distribution=None`
  does *not* restore the old unconditional "dominated by high-authority
  directories" sentence — `_market_composition_clause` degrades honestly to
  "is out of reach on domain authority alone". The real loss was narrower: the
  pipeline's strategy paragraph could not name the composition the run had
  measured.
- **Suite:** `python3 -m pytest test_*.py tests/ -q` → EXIT=0, 2117 passed,
  68 skipped, 10 subtests passed. Judged by exit code (P24).
- **Mutation gate:** 24 mutations, each reverting one production change,
  each run against the guard covering its own criterion. All 24 caught; none
  vacuous. Two rounds were needed: mutation 18's anchor matched two functions
  (widened), and two mutations failed nothing on the first pass —
  - the pivot queue losing its `Low Feasibility` condition changed nothing
    observable, because `generate_hyper_local_pivot` suggests no keyword
    without that verdict. The condition is defence in depth over a paid
    fetch, so it stayed and got a guard that reaches it directly (the pivot
    function patched to suggest a keyword beside a Moderate verdict);
  - `bands = bands or _active["position_bands"]` needed a guard that applies
    a *different* band list after import, since the active default equals the
    documented one.
- **Two pre-existing guards went red on the extraction** and were converted
  rather than re-pointed: `test_d2a8_serp_audit_gates_its_pivot_queue_on_a_verdict`
  grepped `serp_audit.py` for the gate's literal text, and the D6 minima guard
  grepped it for `**feas,`. Both now run `pivot_pass.decide_pivots` and assert
  the consequence (P27). This is the third chunk in which a source-text guard
  broke on a refactor that changed no behaviour.
- **`serp_audit.py` is 2199 lines** against the 2200-line ceiling
  (`tests/test_serp_audit_split.py::TestI63MainModuleSize`). The extraction is
  what brought it under; the next addition to that file needs its own split.
- **Effort budget.** Production: 166 added / 90 deleted across six files plus
  the 144-line `pivot_pass.py`, much of it code moved out of the fetch loop.
  Tests: 458 lines (1.5x, under the 2x ceiling). Doc prose: 31 lines (0.1x).

## Cold `learning-qa` review of the diff

Ten findings. Every medium-or-higher one is fixed with a guard; the two
findings about scope and duplication are recorded here rather than swept.

1. **MEDIUM — the "how many were measured" counter counted a dict, not a
   verdict.** `compute_serp_intent` always returns a block, with
   `primary_intent: None` when fewer than five of the ten URLs classified, so
   `if serp_intent: measured += 1` reported "N of N decided on a measured SERP
   intent" in exactly the degraded case the line exists to make loud. The
   count now reads the `gate_source` the function returned, and
   `generate_hyper_local_pivot` reports `gate_source` from **every** branch
   (two of the four omitted it). The guard now uses the shape the real builder
   produces, not a hand-written block that is never missing a verdict.
2. **MEDIUM — an absent database read as an empty history, and the read
   created one.** `SerpStorage` creates the file and the whole schema, so
   `migrated_connection` on a missing path answered every query with "nothing
   found" and left a 64 KB database behind: "no history yet, or the wrong
   working directory" reported as "this keyword never ranked". The helper
   takes `create=False` and raises `FileNotFoundError`; the chart checks first
   and says which it is, as `metrics.py` has since chunk D1.
3. **MEDIUM — a helper documented for read-only consumers performed schema
   *and data* mutation silently.** `_create_and_migrate` also runs the Y1 host
   canonicalisation, which `UPDATE`s `serp_results` and `DELETE`s orphaned
   `domain_features` rows, announced only at `logger.info` — invisible under
   the chart script's level. `SerpStorage` now records what it changed
   (`migrated_columns`, `canonicalised_hosts`) and `migrated_connection`
   reports it. A second open changes nothing and claims nothing.
4. **MEDIUM — the closing guard's name promised the repo and walked two
   files.** The same `with sqlite3.connect(...)` form remains at ~50 sites.
   The guard is renamed to what it covers and its docstring says so; the class
   stays in the adjacent list below rather than being swept into this diff.
5. **MEDIUM-LOW — the fixed defect's sibling sat in a file this diff already
   edited.** All three `metrics.py` reads filter on migration-added columns
   and `generate_insight_report.py` calls them standalone, so a pre-migration
   database made the report print `no such column: s.query_label`. All three
   now go through `storage.migrated_connection`. The two Y5 closing guards
   patch `storage.sqlite3` instead of `metrics.sqlite3` — same criterion, the
   connection is opened one module along.
6. **MEDIUM-LOW — nothing held the wiring.** Every guard called
   `pivot_pass.decide_pivots` directly, so deleting the call from `_run` left
   the suite green while every pivot row, write and queued fetch vanished from
   a real run. An AST guard asserts `serp_audit` makes the call once, uses
   both of its results, and decides no pivot of its own.
7. **LOW, fixed — the new module global leaked across tests and was handed
   out uncopied.** The Y4 loader test applies the repo's real `config.yml` to
   `_ACTIVE_SPONGE_THRESHOLDS` with no cleanup; latent only while those five
   values equal the documented defaults. Cleanup added, and both accessors
   return copies.
8. **LOW, not fixed — `main` still resolves and passes all five thresholds
   explicitly**, so the production path does not exercise the new mechanism:
   two live mappings of the same keys in one process. Recorded below.
9. **LOW, fixed — the docstring stated a fetch this script does not make.**
   `refresh_analysis_outputs` makes no outbound call; `classifiers.py` has no
   HTTP import. The real reason is that the policy is process-wide and the GUI
   calls this function in-process, so a loader that set none left the process
   on whatever the last loader happened to set. The docstring says that now.
10. **LOW, fixed — the builder ran twice behind a catch-all.** A malformed
    `play_routing.yml` is a deliberate HARD error (`ValueError`) and the
    catch-all degraded it to "no profiles", hiding the thing it exists to
    announce; it is re-raised. The builder's per-keyword
    `entity_distribution` warnings were also printed twice per run, so a
    reader counting them double-counted the evidence; this pass keeps them
    quiet and restores the level.

The review also verified, and these are **not** findings: the extraction lost
nothing (field-for-field row, both printed lines, the queue gate, list order,
`"A"` label); the two entry points really do agree on the pivot's inputs,
because every per-keyword map the builder uses is label-A filtered and the
only post-loop mutation of `all_organic` is `Rank_Delta`, which neither field
reads; batching the storage writes after the loop loses nothing on resume,
which reuses raw SerpAPI responses rather than stored rows; and no other
config loader that leads to an outbound call is missing `apply_retry_policy`
(all 31 `yaml.safe_load` modules audited).

Gate after the fixes: suite EXIT=0, 2126 passed / 68 skipped; 35 mutations,
all caught, none vacuous.

## Adjacent issues found, not fixed

- **`serpapi.*` and `http_retry.*` are two retry policies** for one class of
  call (carried forward from Y4/Y5).
- **The new editorial keys have no `config_manager` GUI surface.**
- **~50 `with sqlite3.connect(...)` sites** commit on exit and never close the
  handle, `storage.py`'s own writes among them. Converting them all is a
  sweeping diff; the two rank-history readers are done.
- **`run_gsc_analysis.main` resolves the sponge thresholds a second time** and
  passes all five explicitly, so `_ACTIVE_SPONGE_THRESHOLDS` has no production
  reader. Dropping `main`'s explicit arguments would leave one path, and is a
  behaviour change worth its own chunk.
- **`keyword_enrich.py` is an untracked sixth entry point** in the working
  tree, outside this review's scope.
