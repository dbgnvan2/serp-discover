# Chunk Y3 — a zero is a measurement, a drop is a fact

Adjacent-issue batch 3, from the "Adjacent issues found, not fixed" lists of
chunks D3b, D4b, D4c, D5, X, Y1 and Y2. One rule: a figure the run did not
measure must not print as a number, and a row the run dropped must be counted
where the reader can see it (P1, P2/P9, P6).

## The findings, reproduced

1. **Report section 6 disappears, or prints its heading and nothing else.**
   `metrics.get_volatility_metrics` already returns `{"status": ..., "msg":
   ...}` for every reason there is no volatility figure — fewer than two runs,
   no completed prior run, no primary-query rows — and returns `None` when the
   run id is unknown or the query raised. `generate_insight_report` renders the
   section only `if vol and vol.get("status") == "success"`, so all four
   reasons produce no section at all; the `msg` the metric built for the reader
   reaches nothing. And on a successful comparison where no (keyword, url) pair
   is shared, `merged` is empty, so `volatility_score` is NaN; the NaN branch
   requires `comparability_warning`, which is `None` when the keyword sets are
   identical but every URL moved, and then neither branch runs — the report
   prints `## 6. Market Volatility` followed by a blank line.
2. **A foundational readiness of 0.0 that was never measured.**
   `compute_foundational_score`'s docstring says an n/a sub-score is "never
   counted as 0", and with one or two n/a axes that holds. With all three n/a
   it returns `score: 0.0`, which `render_foundational_section` prints as
   "**Foundational readiness: 0.0/100**" and `save_foundational_score` writes
   to `foundational_score` as a real row — so the next run's Δ is computed
   against a fabricated zero. The same 0.0 comes back when every configured
   weight is zero, which is a configuration error, not a measurement.
3. **The outreach shortlist drops citations without counting them.**
   `citation_table.top_cited_domains` skips any row whose `domain` is falsy —
   a URL the parser could not read a host from — with no count, so the
   shortlist is built over fewer citations than the table above it shows (P2).
   `render_citation_section` separately truncates the table at `top_n=40` with
   no "40 of N" line.
4. **`refresh_xlsx` counts a row it did not touch as updated, and
   `refresh_json` writes the file twice.** The xlsx pass increments `updated`
   on a row with no usable domain and then `continue`s, so the caller's "N
   rows updated" counts rows nothing was written to; the json pass prints an
   honest "N of M carry no usable domain" line and the xlsx pass prints
   nothing. Separately, `refresh_json` ends with a direct `json.dump` onto the
   live file — the truncating write `_write_json_atomically` was added to
   replace — and the caller then writes the same data again through the helper.
5. **One bad validation rule disables every validation rule.**
   `load_validation_rules` wraps the file read, the per-field parse and the
   demand phrases in a single `except Exception`, so a bad `tolerance` on the
   fourth of five fields discards the three already built and the
   `market_size_phrases` list with them. The empty result is then cached for
   the life of the process, and the only trace is one log warning: the brief's
   `.validation.md` says nothing, so a brief that passed no numeric check
   reads exactly like a brief that passed them all (P6).

## The fixes

1. `metrics.get_volatility_metrics` returns a status for every path,
   `no_database` / `run_not_found` / `query_failed` included, each with its
   `msg`; an empty merge returns `status: "no_shared_urls"` rather than a NaN
   score. `generate_insight_report` renders section 6 for every status: the
   figures on success, the reason otherwise.
2. `compute_foundational_score` returns `score: None` with a `score_reason`
   when no sub-score was measured or the weights sum to zero. The renderer
   prints the reason, `save_foundational_score` writes NULL, and the trend
   already skips a None score, so no Δ is computed against it.
3. `top_cited_domains` is paired with a count of the citations it could not
   attribute to a host, and the section states it; the table states "showing
   40 of N" when it truncates.
4. `refresh_xlsx` counts skipped rows separately, reports "N of M", and no
   longer calls them updated. `refresh_json` classifies and returns; the
   single write is the caller's, atomic, on both the rebuild and the
   rebuild-failed path.
5. `load_validation_rules` parses each field in its own `try`, so one bad
   field costs that field; the result carries `load_error` and
   `fields_loaded`, and `validate_llm_report` appends an issue naming the
   checks that were inactive, so the sidecar states it.

## Cold review (learning-qa, after the build)

Tier: Full. 1 high and 4 medium findings, all fixed, plus five lows that were
one-line corrections and are fixed too. One low is listed as adjacent below.

1. **High — the new "a check was inactive" issue aborted brief generation.**
   `validate_llm_report`'s new issue fell through `partition_validation_issues`
   to `blocking`, which in `brief_rendering` means one retry with a correction
   prompt — asking the model to fix a YAML file it cannot see — and then
   `sys.exit(2)` with no brief written. So an unreadable editorial file stopped
   every brief and cost a second LLM call, the opposite of what
   `load_validation_rules` promises. These issues now carry
   `brief_validation.INACTIVE_CHECK_PREFIX` and the partitioner routes them to
   the notes: they reach the brief and the sidecar, not the correction loop.
2. **Medium — the row-counting fix was applied to one of the two siblings.**
   `refresh_xlsx` stopped counting an untouched row as updated;
   `refresh_json` still did, so the two figures printed over the same data
   meant different things and the manual's new sentence was false for the JSON
   file (P5 half-applied). Both now count only the rows they wrote.
3. **Medium — the zero-weight reason was false in the only reachable case.**
   `weight_sum` is summed over the *measured* axes, and `resolve_weights`
   replaces an all-zero config with equal thirds, so what actually happens is
   that the axes measured this run carry zero weight. The report told the owner
   every weight was zero and to set one above zero, which they had. Split into
   two messages, chosen from `weights_used` rather than from `weight_sum`.
4. **Medium — the "N of M carry no readable host" line was nested inside the
   shortlist block,** so the case it exists for — nothing attributable at all,
   hence no shortlist — printed nothing. Moved out, and it says so when the
   engine's answers produced no outreach target at all.
5. **Medium — two sub-cases of the same P6 were still invisible.** A
   `market_size_phrases` parse failure was logged and not recorded, so the
   demand-language check silently passed every brief; and a field kept on
   fewer phrasings than the file declares read in the sidecar exactly like one
   checked on all of them. Both are now recorded (`fields_skipped`,
   `patterns_dropped`) and stated.
6. **Low, fixed** — section 6 still disappeared when the metrics module could
   not be imported and when the overview rows carry no `Run_ID`; both now
   print the reason. The dead NaN sub-tree in the renderer is gone, since an
   empty merge is `no_shared_urls` and the ranks are `dropna`'d — that branch
   was the one that printed the heading and a blank line.
7. **Low, fixed** — the manual said nothing is stored for an unmeasured run; a
   row *is* stored with a NULL score, which is right (the run happened) and
   what the guard pins. Sentence corrected.
8. **Low, fixed** — the definition-change note is no longer gated on both
   trend scores being present: the incomparability is a fact about the two
   rows, not about this run's score, and as wired the branch was unreachable.
9. **Low, fixed** — `refresh_xlsx` returned `(0, 0)` silently when the
   workbook is missing, has no `Organic_Results` sheet or lacks a column, so
   "0 rows updated" read as "nothing needed changing". Each says why.
10. **Low, fixed** — the `query_failed` return leaked the sqlite connection
    every other exit closes; the renderer's shortlist limit was expressed
    twice (a literal `[:5]` beside `top_cited_domains(limit=5)`).

Guard quality, from the review: the "does not write the file" guard compared
`st_size` only and now compares exact bytes and `st_mtime_ns`; the
inactive-check guards asserted the wording and not the consequence, so the
partition and `has_hard_validation_failures` are now pinned directly.

Mutation gate: 23 mutations, every one fails at least one guard.

## Adjacent issues found, not fixed

- `metrics.get_volatility_metrics` builds and closes its connection by hand on
  seven paths. A `with contextlib.closing(...)` would remove the class, but
  that is a refactor of the whole function rather than this chunk's rule.
- Carried forward from Y2's list and still open:
  `compute_sponge_effect.MIN_BUCKET_SIZE` and `DEFAULT_POSITION_BANDS` are
  Python constants (P4); the top-competitor tie-break is alphabetical and
  `_mixed_keyword_dominance_profiles` breaks a tie on dict order;
  `serp_audit`'s in-pipeline pivot pass runs before `keyword_profiles` exists;
  `storage.py`'s `ALTER TABLE` migrations swallow lock and missing-table
  errors along with the already-exists case; `visualize_volatility.py` has no
  `query_label` filter, so alternative-query rows enter the chart;
  `citation_table.build_citation_table`'s unattributable-brand drop (the
  `brand` field, distinct from the host drop fixed here);
  `tests/test_y1_one_definition_each.py::test_no_module_strips_the_prefix_by_hand`
  matches source literals rather than walking the AST; `serp_audit.py:1517`
  still calls `urlparse(url).netloc` itself; the page fetch has no
  configurable run-level retry budget; `enrichment.NOT_DESTINATION_PAGE` is
  not in `FAILED_FETCH_STATES`.
