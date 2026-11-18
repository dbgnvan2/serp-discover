"""brief_validation.py — LLM output validation for content brief pipeline.

Spec: serp_tool1_improvements_spec.md#I.5
"""
import logging
import os
import re

import yaml

import keyword_demand
from brief_data_extraction import _normalize_text
# recommended_play vocabulary is shared with the report renderers (single source
# of truth in play_routing.yml). Spec: seo_geo_review_20260704.md (T.4).
from play_rendering import load_play_vocab as _load_play_vocab

logger = logging.getLogger(__name__)


#: Marks an issue that is about the TOOL, not the brief: a validation rule
#: that could not be read. `partition_validation_issues` routes these to the
#: notes, because the correction loop cannot fix a YAML file and an abort
#: would mean an unreadable editorial file stops every brief — the opposite of
#: what `load_validation_rules` promises (cold review of chunk Y3).
INACTIVE_CHECK_PREFIX = "Validation checks were inactive:"

DEFAULT_RULES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "brief_validation_rules.yml")

_RULES_CACHE: dict | None = None


def load_validation_rules(path: str | None = None) -> dict:
    """Load brief_validation_rules.yml: numeric-claim phrasings + demand phrases.

    Spec: review_2026-11-04 D4.16 (D-M-27)

    A missing or malformed file degrades to no numeric rules and says so once,
    rather than aborting a run — but it never degrades silently, because a rule
    that is off is indistinguishable from a brief that passed it (P6).

    Each field is parsed in its own ``try``, so one bad rule costs that rule
    and not the rest; the result carries ``load_error`` (the file) and
    ``fields_skipped`` (the individual rules, `market_size_phrases` included)
    and ``patterns_dropped`` (a rule kept on fewer phrasings than the file
    declares), which `validate_llm_report` states in the brief's
    `.validation.md` prefixed with ``INACTIVE_CHECK_PREFIX`` so the issue is
    carried as a note rather than sent to the correction loop (review chunk
    Y3 and its cold review).
    """
    global _RULES_CACHE
    if _RULES_CACHE is not None and path is None:
        return _RULES_CACHE
    rules = {"numeric_claims": {}, "market_size_phrases": [],
             "load_error": None, "fields_skipped": []}
    try:
        with open(path or DEFAULT_RULES_PATH, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception as exc:
        # The file itself. Everything below depends on it, so this is the one
        # failure that does take every check with it — and it is now stated on
        # the result, not only in the log (P6, review chunk Y3).
        rules["load_error"] = (
            f"{INACTIVE_CHECK_PREFIX} brief_validation_rules.yml did not load "
            f"({exc}), so the numeric-claim and demand-language checks did not "
            f"run on this brief.")
        logger.warning("%s", rules["load_error"])
        if path is None:
            _RULES_CACHE = rules
        return rules

    claims = {}
    skipped = []
    dropped: dict[str, int] = {}
    for field, spec in (raw.get("numeric_claims") or {}).items():
        # Per field, so a bad tolerance on the fourth of five fields costs
        # that field. One `except` around the whole loop discarded the fields
        # already built and the demand phrases with them (review chunk Y3).
        try:
            pats = []
            for pat in (spec or {}).get("patterns") or []:
                try:
                    compiled = re.compile(pat, re.IGNORECASE)
                except re.error as exc:
                    logger.warning("brief_validation_rules.yml: %s pattern %r "
                                   "is not a valid regex (%s) — skipped.",
                                   field, pat, exc)
                    continue
                if compiled.groups != 1:
                    logger.warning("brief_validation_rules.yml: %s pattern %r "
                                   "needs exactly one capture group — skipped.",
                                   field, pat)
                    continue
                pats.append(compiled)
            declared = len((spec or {}).get("patterns") or [])
            if not pats:
                skipped.append(str(field))
                continue
            if declared > len(pats):
                # The field is checked, but on fewer phrasings than the file
                # declares, and 1-of-3 read in the sidecar exactly like 3-of-3
                # (cold review of chunk Y3).
                dropped[str(field)] = declared - len(pats)
            claims[field] = {
                "label": str((spec or {}).get("label") or field),
                "tolerance": float((spec or {}).get("tolerance") or 0),
                "patterns": pats,
            }
        except Exception as exc:
            logger.warning("brief_validation_rules.yml: the %s rule did not "
                           "load (%s) — that one check is inactive; the "
                           "others are unaffected.", field, exc)
            skipped.append(str(field))

    if not (raw.get("numeric_claims") or {}):
        # A file that parses and declares no rules at all: every numeric check
        # is off and the per-field list is empty, so nothing said so. Deleting
        # `numeric_claims:` passed the config editor cleanly and the sidecar
        # reported no skipped fields (the cold review of chunk Y15, finding
        # 3). An absent section is the same fact as an unreadable file: the
        # checks did not run.
        rules["load_error"] = (
            f"{INACTIVE_CHECK_PREFIX} brief_validation_rules.yml declares no "
            f"numeric_claims, so none of the numeric-claim checks ran on this "
            f"brief.")
        logger.warning("%s", rules["load_error"])
    rules["numeric_claims"] = claims
    rules["fields_skipped"] = sorted(skipped)
    rules["patterns_dropped"] = dropped
    try:
        rules["market_size_phrases"] = [
            str(x) for x in (raw.get("market_size_phrases") or [])]
    except Exception as exc:
        logger.warning("brief_validation_rules.yml: market_size_phrases did "
                       "not load (%s) — the demand-language check is "
                       "inactive; the numeric checks are unaffected.", exc)
        # Recorded, not only logged: it is one of the checks the sidecar
        # claims to account for (cold review of chunk Y3).
        rules["fields_skipped"] = sorted(skipped + ["market_size_phrases"])
    if path is None:
        _RULES_CACHE = rules
    return rules


def _claimed_numbers(regions, patterns):
    """Every number the regions state through these patterns, as (text, float)."""
    found = []
    for region in regions:
        for pattern in patterns:
            for m in pattern.finditer(region):
                raw = m.group(1)
                try:
                    found.append((m.group(0), float(raw.replace(",", ""))))
                except (TypeError, ValueError):
                    continue
    return found


def _check_numeric_claims(issues, keyword, actuals, regions, rules):
    """A number the brief states for a measured field must match the field.

    Spec: review_2026-11-04 D4.16 (D-M-27)

    The validator could check the brief's wording but not its arithmetic, so a
    client rank or SERP DA the brief restated wrongly was written as fact. Only
    fields that were actually MEASURED are checked: an unmeasured field has no
    number to disagree with, and that case belongs to the gates that already
    cover it.
    """
    for field, spec in (rules.get("numeric_claims") or {}).items():
        actual = actuals.get(field)
        if actual is None:
            continue
        try:
            actual_f = float(actual)
        except (TypeError, ValueError):
            continue
        tol = spec["tolerance"]
        for quote, claimed in _claimed_numbers(regions, spec["patterns"]):
            if abs(claimed - actual_f) > tol:
                issues.append(
                    f"The {spec['label']} the report states for '{keyword}' "
                    f"contradicts the data ({quote!r} vs {actual}) — the brief "
                    f"may only restate the measured figure."
                )
                break


def missing_serp_keywords(data) -> list:
    """Keywords the run asked for that produced no SERP data, in run order.

    Spec: review_2026-11-04 D4.14 (D-C-13)

    `serp_audit` persists `analysed_keywords` (the CSV list). A keyword whose
    fetch failed after retries has no overview row and no profile, so it
    disappeared from every count — "7 keywords analysed" for a run of 8, with
    nothing saying which one was missing (P2).
    """
    asked = [str(k) for k in (data.get("analysed_keywords") or []) if str(k).strip()]
    if not asked:
        return []
    profiles = data.get("keyword_profiles") or {}
    have = {_normalize_text(k) for k in profiles}
    have |= {_normalize_text(r.get("Source_Keyword") or r.get("Keyword") or "")
             for r in (data.get("overview") or [])}
    return [k for k in asked if _normalize_text(k) not in have]


# Review chunk Y1: one definition, in `keyword_demand`, shared with
# `brief_data_extraction`. These were a second copy of the same two
# predicates; the names stay because this module's checks read well with them.
_keyword_volume = keyword_demand.measured_volume
_any_demand_measured = keyword_demand.any_measured


def _check_keyword_demand(issues, keyword, profile, regions, rules):
    """Market-size language inside ONE keyword's section needs ITS volume.

    Spec: review_2026-11-04 D4.16 cold review (D-M-27)

    The run-wide gate below licenses demand language for every keyword as soon
    as one of them has a volume. The claim is per keyword; so is the evidence.
    """
    if _keyword_volume(profile) is not None or not regions:
        return
    for phrase in rules.get("market_size_phrases") or []:
        if any(re.search(phrase, region) for region in regions):
            issues.append(
                f"Report describes search demand for '{keyword}' ({phrase!r}) "
                f"but that keyword carries no measured monthly volume."
            )
            return


def _play_assignment_phrase(label):
    """Return the regex that matches the report ASSIGNING a play via its canonical
    verdict statement — "Recommended play: <label>". This anchored form is what the
    prompt instructs the LLM to emit, so it detects a genuinely different *verdict*
    without false-positiving on ordinary prose that merely *discusses* another play
    (e.g. "a rank play would normally chase the ranking, but that is out of reach").
    Returns None when there is no label to anchor on."""
    if not label:
        return None
    # D-C-07 / D4.11: match the label's BASE, with the parenthetical suffix
    # optional and markdown emphasis allowed. The rule used to require the
    # exact configured string, so the real brief's "Recommended play:
    # **Extraction play**" was missed while only "Extraction play (GEO)"
    # tripped it — a HARD rule that could not fire on anything the model writes.
    base = re.split(r"\s*\(", str(label).strip())[0].strip().lower()
    if not base:
        return None
    # Review chunk Y1: the label is `play_routing.yml`'s British spelling
    # ("Deprioritise"), and a HARD rule built from it could not fire on a
    # draft that wrote "Deprioritize". `s` and `z` are interchangeable in the
    # pattern, so the rule holds whichever spelling the model used — the
    # alternative is a parity rule a spelling evades.
    pattern = "".join("[sz]" if ch in "sz" else re.escape(ch) for ch in base)
    return (rf"recommended play[:\-\s]*\**\s*{pattern}"
            rf"(?:\s*\([^)]*\))?")


#: Headings under which a play statement is attributed to a keyword. The brief's
#: prompt puts "Recommended play: <label>" in Section 7, under a per-keyword
#: heading, NOT in the Section-2 keyword block the other rules scan — so a rule
#: that only read that block could never see the statement (D-C-07 / D4.11).
_KEYWORD_SECTION_RE = r"\*\*{kw} \([^\n]+\)\*\*(.*?)(?:\n\n\*\*|\n### |\Z)"


def _names_keyword(text, keyword) -> bool:
    """True when ``text`` contains ``keyword`` as a phrase, not a fragment.

    Spec: review_2026-11-04 D4.11 (D-C-07)

    A plain ``in`` test made "counselling" a match inside "couples
    counselling", so one keyword's heading was read as another's.
    """
    return re.search(rf"(?<![\w-]){re.escape(keyword)}(?![\w-])", text) is not None


def _keyword_regions(report_text, keyword, other_keywords=()):
    """Every stretch of the report that speaks about ONE keyword, normalised.

    Spec: review_2026-11-04 D4.11 (D-C-07)

    Two shapes count as attribution: the Section-2 profile block
    (``**<kw> (intent)**`` up to the next block), and any markdown heading that
    names the keyword, up to the next heading of the same or a higher level.

    ``other_keywords`` is the rest of the run's keywords. Real keyword files
    overlap — `couples counselling` and `couples counselling for trust issues`
    are both in one CSV — so a heading is attributed to the LONGEST keyword it
    names, and only on a phrase boundary. Matching the shorter keyword as a
    substring made the longer keyword's section its own, and the HARD rules
    that read these regions then aborted a report whose every statement was
    true.
    """
    regions = []
    block = re.search(_KEYWORD_SECTION_RE.format(kw=re.escape(keyword)),
                      report_text, flags=re.IGNORECASE | re.DOTALL)
    if block:
        regions.append(_normalize_text(block.group(1)))

    longer = [k for k in (other_keywords or ())
              if k and k.lower() != keyword.lower()
              and len(k) > len(keyword)
              and _names_keyword(k.lower(), keyword.lower())]
    for head in re.finditer(r"^(#{1,6})[ \t]*(.*)$", report_text, flags=re.MULTILINE):
        level, title = len(head.group(1)), head.group(2)
        title_l = title.lower()
        if not _names_keyword(title_l, keyword.lower()):
            continue
        # The heading names a longer keyword that contains this one: it is that
        # keyword's section, not this one's.
        if any(_names_keyword(title_l, k.lower()) for k in longer):
            continue
        rest = report_text[head.end():]
        nxt = re.search(rf"^#{{1,{level}}}[ \t]", rest, flags=re.MULTILINE)
        regions.append(_normalize_text(rest[:nxt.start()] if nxt else rest))
    return regions


def _mixed_keyword_dominance_profiles(extracted_data):
    """Keywords whose entity mix is too close to call one entity dominant.

    Yields ``(keyword, top_entities, top_count, second_count, top_share)``.
    ``top_entities`` is every entity tied on the top count, not one of them:
    the sort used to break a tie on the order the entities happened to appear
    in the JSON, and the caller tests for "<top entity> … dominates" in that
    keyword's section — so with `clinic: 4, directory: 4` and a brief saying
    "directories dominate", the contradiction went unreported whenever dict
    order picked `clinic` (P12/P19, review chunk Y4).
    """
    profiles = []
    for keyword, profile in (extracted_data.get("keyword_profiles", {}) or {}).items():
        distribution = profile.get("entity_distribution", {}) or {}
        ranked = sorted(
            [(entity, count) for entity, count in distribution.items() if count],
            # Count first, then the name: a stated tie-break, so two runs over
            # the same data report the same thing.
            key=lambda item: (-item[1], str(item[0])),
        )
        if len(ranked) < 2:
            continue
        top_count = ranked[0][1]
        top_entities = [entity for entity, count in ranked if count == top_count]
        # The runner-up's count, ties included. Taking the next *strictly
        # lower* count instead dropped the most contested mix there is: with
        # `clinic: 4, directory: 4` the runner-up became 0 and the
        # `second_count >= 3` gate below discarded the keyword, so a brief
        # calling a 4-4 split dominant passed with no issue at all (cold
        # review of chunk Y4).
        second_count = ranked[1][1]
        classified_total = sum(count for _entity, count in ranked)
        if classified_total <= 0:
            continue
        top_share = top_count / classified_total
        if second_count >= 3 and top_share <= 0.60:
            profiles.append((keyword, top_entities, top_count, second_count,
                             top_share))
    return profiles


def _label_requires_mixed(entity_label):
    return str(entity_label or "").startswith("mixed_")


def _label_requires_plurality(entity_label):
    return str(entity_label or "").endswith("_plurality")


def _check_play_parity(issues, keyword, profile, regions):
    """recommended_play parity (RP-C.4, HARD-FAIL) across every region.

    Spec: seo_geo_review_20260704.md (T.4); review_2026-11-04 D4.11 (D-C-07)

    The brief may only NARRATE the pre-computed play; asserting a DIFFERENT play
    is a mechanically checkable contradiction. The play is a deterministic
    verdict, so parity is enforced whenever one is present. Detection is
    anchored to the canonical "Recommended play: <label>" statement, so the
    brief can add honesty caveats in prose without a false contradiction.
    """
    rp = profile.get("recommended_play") or {}
    pre_play = rp.get("play")
    if not pre_play or not regions:
        return
    play_vocab = _load_play_vocab()
    labels = play_vocab.get("play_labels", {}) or {}
    pre_label = labels.get(pre_play) or rp.get("label")
    for other_play, other_label in labels.items():
        if other_play == pre_play:
            continue
        phrase = _play_assignment_phrase(other_label)
        if not phrase:
            continue
        if any(re.search(phrase, region) for region in regions):
            issues.append(
                f"Report assigns a different play to '{keyword}' "
                f"({other_label}), but keyword_profiles.recommended_play "
                f"shows play='{pre_play}' (label='{pre_label}')."
            )
            return


def validate_llm_report(report_text, extracted_data):
    issues = []
    report_l = _normalize_text(report_text)
    query_count = len(extracted_data.get("queries", []))
    keyword_profiles = extracted_data.get("keyword_profiles", {}) or {}
    queries_with_aio = sum(
        1 for profile in keyword_profiles.values()
        if profile.get("has_ai_overview")
    ) or sum(1 for q in extracted_data.get("queries", []) if q.get("has_ai_overview"))

    _rules = load_validation_rules()
    if _rules.get("load_error"):
        # The sidecar says which checks did not run. A check that is off is
        # indistinguishable from a brief that passed it (P6, review chunk Y3).
        issues.append(_rules["load_error"])
    elif _rules.get("fields_skipped"):
        issues.append(
            f"{INACTIVE_CHECK_PREFIX} these rules in "
            f"brief_validation_rules.yml could not be read, so the figures "
            f"they cover were not checked against the data: "
            + ", ".join(_rules["fields_skipped"]) + ".")
    if _rules.get("patterns_dropped"):
        issues.append(
            f"{INACTIVE_CHECK_PREFIX} some phrasings of these rules in "
            f"brief_validation_rules.yml could not be read, so the check ran "
            f"on fewer phrasings than the file declares: "
            + ", ".join(f"{field} ({n} dropped)" for field, n
                        in sorted(_rules["patterns_dropped"].items())) + ".")
    # One row per keyword, primary label only: a pivot row ("P") measures a
    # different keyword and its DA must not be compared against this one.
    _feasibility_by_keyword = {}
    for _row in extracted_data.get("keyword_feasibility") or []:
        if (_row.get("Query_Label") or _row.get("query_label")) == "P":
            continue
        _kw = _row.get("Keyword") or _row.get("keyword")
        if _kw:
            _feasibility_by_keyword.setdefault(_normalize_text(_kw), _row)

    speculative_patterns = [
        r"indicating (?:technical|content|data|system)\w*",
        r"suggesting (?:a |that |some )?(?:bug|issue|problem|filter)",
        r"possibly due to",
        r"likely (?:because|due|caused)",
        r"technical issues? or content filtering",
        r"content filtering",
    ]
    for pattern in speculative_patterns:
        if re.search(pattern, report_l):
            issues.append(
                f"Report contains speculative causal language matching pattern: {pattern}"
            )
            break

    paa_cross_questions = {
        _normalize_text(item.get("question"))
        for item in extracted_data.get("paa_analysis", {}).get("cross_cluster", [])
    }
    if "cross-cutting" in report_l and "toxic" in report_l:
        toxic_cross_cluster = any("toxic" in question for question in paa_cross_questions)
        toxic_autocomplete = bool(extracted_data.get("autocomplete_summary", {}).get("trigger_word_hits", {}).get("toxic", []))
        if not toxic_cross_cluster and not toxic_autocomplete:
            issues.append(
                "Report claims a cross-cutting 'toxic' opportunity, but verified PAA/autocomplete evidence is absent."
            )

    for rec in extracted_data.get("tool_recommendations_verified", []):
        pattern_name = rec.get("pattern_name", "")
        verdict = rec.get("verdict_inputs", {})
        total_hits = verdict.get("total_trigger_occurrences", 0)
        if not pattern_name:
            continue
        section_match = re.search(
            rf"\*\*{re.escape(pattern_name)}\*\*:\s*([A-Z ]+)\.",
            report_text,
            flags=re.IGNORECASE,
        )
        if total_hits == 0 and section_match:
            label = section_match.group(1).strip().upper()
            if label in {"SUPPORTED", "PARTIALLY SUPPORTED"}:
                issues.append(
                    f"Report marks '{pattern_name}' as {label}, but verified trigger evidence count is zero."
                )
            paragraph_match = re.search(
                rf"(\*\*{re.escape(pattern_name)}\*\*:[^\n]*(?:\n(?!\*\*).*)*)",
                report_text,
                flags=re.IGNORECASE,
            )
            paragraph_text = paragraph_match.group(1) if paragraph_match else ""
            if re.search(
                r"(appear frequently|multiple autocomplete suggestions include|trigger[s]? found|heavy presence)",
                paragraph_text,
                flags=re.IGNORECASE,
            ):
                issues.append(
                    f"Report cites specific trigger evidence for '{pattern_name}' despite zero verified trigger evidence."
                )

    toxic_hits = extracted_data.get("autocomplete_summary", {}).get("trigger_word_hits", {}).get("toxic", [])
    if not toxic_hits and "high search volume term from autocomplete data" in report_l and "toxic" in report_l:
        issues.append(
            "Report cites 'toxic' as a high-volume autocomplete term, but autocomplete_summary shows no toxic hits."
        )

    aio_all_patterns = [
        rf"ai overviews appear for all {query_count} queries",
        rf"ai overviews appear across all {query_count} queries",
        rf"all {query_count} queries trigger ai overviews",
    ]
    if query_count and queries_with_aio != query_count:
        for pattern in aio_all_patterns:
            if re.search(pattern, report_l):
                issues.append(
                    f"Report claims AI Overviews appear for all {query_count} queries, but verified data shows {queries_with_aio} of {query_count}."
                )
                break
    aio_count_match = re.search(
        r"(\d+)\s+of\s+(\d+)\s+quer(?:y|ies)\s+(?:feature|have|show|trigger)",
        report_text,
        flags=re.IGNORECASE,
    )
    if aio_count_match:
        reported_with_aio = int(aio_count_match.group(1))
        reported_total = int(aio_count_match.group(2))
        if query_count and reported_total == query_count and reported_with_aio != queries_with_aio:
            issues.append(
                f"Report says {reported_with_aio} of {reported_total} queries have AI Overviews, but keyword_profiles shows {queries_with_aio} of {query_count}."
            )

    if re.search(r"data collection issue|potential data collection issue|suggesting .*data collection issue", report_l):
        issues.append(
            "Report speculates about a data collection issue without verified extraction evidence."
        )

    # D4.16: demand language is permitted when a demand figure exists. It was
    # banned outright, which was right while the only "volume" in the data was
    # Google's indexed-page count — but Moz keyword metrics now supply real
    # monthly volumes, so the ban would reject a true statement. The rule is now
    # about whether anything measured demand.
    if not _any_demand_measured(keyword_profiles):
        for _phrase in _rules.get("market_size_phrases") or []:
            if re.search(_phrase, report_l):
                issues.append(
                    "Report describes search demand (%r) but no keyword in this "
                    "run carries a measured monthly volume — Google's "
                    "total-results figure counts indexed pages, not searchers."
                    % _phrase
                )
                break

    # The keyword-specific "estrangement" rule was removed in D4.16: it was dead
    # weight for every other keyword set, and the generic rules it duplicated
    # (_mixed_keyword_dominance_profiles, _label_requires_mixed) cover the same
    # contradiction for all keywords.

    for keyword, top_entities, top_count, second_count, top_share in _mixed_keyword_dominance_profiles(extracted_data):
        section_match = re.search(
            rf"\*\*{re.escape(keyword)} \([^\n]+\)\*\*(.*?)(?:\n\n\*\*|\n### |\Z)",
            report_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not section_match:
            continue
        section_text = section_match.group(1)
        for _entity in top_entities:
            # Every entity tied at the top is tested, so the contradiction is
            # found whichever of the tied names the brief used.
            if re.search(rf"\b{re.escape(_entity)} (?:entities )?(?:heavily )?dominat",
                         section_text, flags=re.IGNORECASE):
                _tie = ("" if len(top_entities) < 2 else
                        f" — and {top_count} is a tie between "
                        f"{', '.join(top_entities)}")
                issues.append(
                    f"Report labels '{keyword}' as {_entity}-dominant, but the "
                    f"classified entity mix is too close ({top_count} vs "
                    f"{second_count}; {top_share:.0%} share) and should be "
                    f"described as mixed or contested{_tie}."
                )
                break

    for keyword, profile in keyword_profiles.items():
        entity_label = profile.get("entity_label")
        if not entity_label:
            continue
        section_match = re.search(
            _KEYWORD_SECTION_RE.format(kw=re.escape(keyword)),
            report_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not section_match:
            continue
        section_l = _normalize_text(section_match.group(1))
        if _label_requires_mixed(entity_label) and re.search(r"\bdominat(?:e|ed|es|ing)\b", section_l):
            issues.append(
                f"Report contradicts keyword_profiles.entity_label for '{keyword}': {entity_label} should be described as mixed or contested, not dominant."
            )
        if _label_requires_plurality(entity_label) and re.search(r"\bdominat(?:e|ed|es|ing)\b", section_l):
            issues.append(
                f"Report contradicts keyword_profiles.entity_label for '{keyword}': {entity_label} should be described as a plurality, not dominant."
            )

    # ── Spec v2 Gap 1: SERP intent verdict contradiction (HARD-FAIL) ─────────
    # ── Spec v2 Gap 2: title_patterns.dominant_pattern contradiction (SOFT) ──
    # Strong-claim phrases per intent. We only flag when the report makes an
    # explicit "this SERP is primarily X" type of claim — not casual mentions.
    INTENT_CLAIM_PHRASES = {
        "informational": [
            r"primarily informational",
            r"informational[- ]intent serp",
            r"informational intent dominates",
            r"primary intent[: ]\s*informational",
        ],
        "transactional": [
            r"primarily transactional",
            r"transactional[- ]intent serp",
            r"transactional intent dominates",
            r"primary intent[: ]\s*transactional",
            r"purchase[- ]intent serp",
        ],
        "commercial_investigation": [
            r"primarily commercial[- ]investigation",
            r"commercial investigation intent dominates",
            r"primary intent[: ]\s*commercial",
            r"investigative[- ]intent serp",
        ],
        "navigational": [
            r"primarily navigational",
            r"navigational[- ]intent serp",
            r"primary intent[: ]\s*navigational",
            r"branded serp",
        ],
        "local": [
            r"primarily local[- ]intent",
            r"local[- ]intent serp",
            r"primary intent[: ]\s*local",
        ],
    }
    PATTERN_CLAIM_PHRASES = {
        "how_to": [r"how[- ]to (?:guides? )?dominat", r"dominated by how[- ]to"],
        "what_is": [r"what[- ]is (?:guides? )?dominat", r"dominated by what[- ]is"],
        "best_of": [r"best[- ]of dominat", r"dominated by best[- ]of"],
        "vs_comparison": [r"vs\.? comparison.{0,20}dominat", r"dominated by vs"],
        "listicle_numeric": [r"listicles? dominat", r"dominated by listicles?", r"listicle[- ]dominated"],
        "brand_only": [r"brand[- ]only.{0,20}dominat", r"dominated by brand"],
        "question": [r"questions? dominat", r"dominated by questions?"],
    }

    for keyword, profile in keyword_profiles.items():
        # Every region that speaks about this keyword — the Section-2 profile
        # block AND any heading naming it. The play verdict and the DA-direction
        # claim are checked across all of them, because the prompt puts the
        # play statement in Section 7 (D4.11); the prose rules below stay on the
        # Section-2 block, the only place they are written.
        play_regions = _keyword_regions(report_text, keyword,
                                        other_keywords=keyword_profiles.keys())
        rp = profile.get("recommended_play") or {}
        pre_play = rp.get("play")
        _check_play_parity(issues, keyword, profile, play_regions)
        # D4.16: the numbers the brief restates must be the measured ones.
        # client_rank / total_results come from the profile; the DA figures from
        # the keyword's feasibility row, when feasibility ran.
        _feas = _feasibility_by_keyword.get(_normalize_text(keyword), {})
        _check_keyword_demand(issues, keyword, profile, play_regions, _rules)
        _check_numeric_claims(issues, keyword, {
            "volume": _keyword_volume(profile),
            "client_rank": profile.get("client_rank"),
            "total_results": (profile.get("total_results")
                              if profile.get("total_results_measured") else None),
            "avg_serp_da": _feas.get("avg_serp_da"),
            "gap": _feas.get("gap"),
        }, play_regions, _rules)

        section_match = re.search(
            _KEYWORD_SECTION_RE.format(kw=re.escape(keyword)),
            report_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not section_match:
            section_l = ""
        else:
            section_l = _normalize_text(section_match.group(1))

        # ── serp_intent contradictions ──
        si = profile.get("serp_intent") or {}
        primary = si.get("primary_intent")
        is_mixed = si.get("is_mixed", False)
        confidence = si.get("confidence", "low")
        # Only enforce on confident, single-intent verdicts. Low confidence and
        # mixed verdicts permit the LLM more interpretive latitude.
        if primary and primary not in ("uncategorised",) and confidence != "low" and not is_mixed:
            for claimed_intent, phrases in INTENT_CLAIM_PHRASES.items():
                if claimed_intent == primary:
                    continue
                for phrase in phrases:
                    if re.search(phrase, section_l):
                        issues.append(
                            f"Report claims '{keyword}' is {claimed_intent} intent, "
                            f"but keyword_profiles shows serp_intent.primary_intent='{primary}' "
                            f"(confidence={confidence}, is_mixed=False)."
                        )
                        break

        # is_mixed contradiction (separate hard-fail)
        if confidence != "low":
            if is_mixed and re.search(r"single[- ]intent serp|uniform intent|cleanly (?:informational|transactional|navigational)", section_l):
                issues.append(
                    f"Report describes '{keyword}' as single-intent, "
                    f"but keyword_profiles shows serp_intent.is_mixed=True."
                )
            if not is_mixed and re.search(r"mixed[- ]intent serp|mixed intent", section_l):
                issues.append(
                    f"Report describes '{keyword}' as mixed-intent, "
                    f"but keyword_profiles shows serp_intent.is_mixed=False."
                )

        # ── Spec v2 Gap 4: mixed_intent_strategy contradictions ──
        mixed_strategy = profile.get("mixed_intent_strategy")
        si_is_mixed = (profile.get("serp_intent") or {}).get("is_mixed", False)
        # HARD-FAIL: invoking mixed-intent framing on a non-mixed keyword.
        if not si_is_mixed:
            if re.search(r"backdoor (?:strategy|opportunity|approach|angle|content)|compete on (?:the )?dominant intent", section_l):
                issues.append(
                    f"Report invokes mixed-intent strategy language for '{keyword}', "
                    f"but keyword_profiles shows serp_intent.is_mixed=False "
                    f"(no mixed_intent_strategy applies)."
                )
        else:
            # SOFT-FAIL: contradicts the computed strategy.
            STRATEGY_PHRASES = {
                "compete_on_dominant": [r"backdoor", r"avoid this keyword|skip this keyword"],
                "backdoor": [r"compete on (?:the )?dominant", r"avoid this keyword|skip this keyword"],
                "avoid": [r"backdoor", r"compete on (?:the )?dominant"],
            }
            if mixed_strategy and mixed_strategy in STRATEGY_PHRASES:
                for contradicting in STRATEGY_PHRASES[mixed_strategy]:
                    if re.search(contradicting, section_l):
                        issues.append(
                            f"Report contradicts keyword_profiles.mixed_intent_strategy "
                            f"for '{keyword}': computed='{mixed_strategy}', report uses "
                            f"different framing."
                        )
                        break

        # ── title_patterns.dominant_pattern contradictions (SOFT-FAIL) ──
        tp = profile.get("title_patterns") or {}
        dominant = tp.get("dominant_pattern")
        if dominant:
            for claimed_pattern, phrases in PATTERN_CLAIM_PHRASES.items():
                if claimed_pattern == dominant:
                    continue
                for phrase in phrases:
                    if re.search(phrase, section_l):
                        issues.append(
                            f"Report contradicts keyword_profiles.title_patterns for '{keyword}': "
                            f"claims {claimed_pattern} dominance, but dominant_pattern='{dominant}'."
                        )
                        break
        else:
            # If dominant_pattern is null, the LLM should not assert one.
            for claimed_pattern, phrases in PATTERN_CLAIM_PHRASES.items():
                for phrase in phrases:
                    if re.search(phrase, section_l):
                        issues.append(
                            f"Report contradicts keyword_profiles.title_patterns for '{keyword}': "
                            f"claims {claimed_pattern} dominance, but no pattern reached the dominance threshold."
                        )
                        break


        # ── DA-gap claim with no feasibility measured (HARD-FAIL) ────────────
        # D-M-07 / D4.3: the extraction and local-pivot plays are reachable on
        # feasibility `unknown`, and their strategy text used to assert a
        # "high DA gap" regardless. The text is fixed (play_routing.yml's
        # strategy_text_unknown_feasibility), but the LLM narrates the play in
        # its own words, so the claim can come back from the model. A DA
        # direction for a keyword whose DA was never fetched is a
        # mechanically checkable contradiction of the profile.
        if pre_play and (rp.get("data_available") or {}).get("feasibility") is False:
            patterns = _load_play_vocab().get("da_gap_claim_phrases") or []
            if not patterns:
                # P6: the rule is only as live as its editorial list. An empty
                # list means play_routing.yml did not load, or its validation
                # block was emptied — either way this check is off, and that
                # must be visible (D4a cold review, finding 5).
                logger.warning(
                    "No da_gap_claim_phrases loaded from play_routing.yml: "
                    "the DA-gap-without-DA check is inactive for '%s'.",
                    keyword)
            # The same blind spot as the play rule: the model narrates the
            # play wherever it likes, so every region counts (P5).
            for pattern in patterns:
                hit = next((m for m in (pattern.search(r) for r in play_regions)
                            if m), None)
                if hit:
                    issues.append(
                        f"Report states a Domain Authority direction for "
                        f"'{keyword}' ({hit.group(0)!r}), but "
                        f"keyword_profiles.recommended_play.data_available."
                        f"feasibility is false — no DA was measured for this "
                        f"keyword."
                    )
                    break

        # ── confidence upgrade contradiction (SOFT-FAIL) ─────────────────────
        # LLM may downplay confidence but not upgrade it.
        HIGH_CONFIDENCE_PHRASES = [
            r"confidence[:\s]+high",
            r"high[- ]confidence",
            r"highly confident",
        ]
        MEDIUM_CONFIDENCE_PHRASES = [
            r"confidence[:\s]+medium",
            r"medium[- ]confidence",
        ]
        if confidence == "low":
            for phrase in HIGH_CONFIDENCE_PHRASES + MEDIUM_CONFIDENCE_PHRASES:
                if re.search(phrase, section_l):
                    issues.append(
                        f"Report upgrades confidence for '{keyword}' above computed level, "
                        f"but keyword_profiles.serp_intent.confidence='{confidence}'."
                    )
                    break
        elif confidence == "medium":
            for phrase in HIGH_CONFIDENCE_PHRASES:
                if re.search(phrase, section_l):
                    issues.append(
                        f"Report upgrades confidence for '{keyword}' to 'high', "
                        f"but keyword_profiles.serp_intent.confidence='{confidence}'."
                    )
                    break

    return issues


def validate_extraction(data):
    warnings = []
    if not data.get("root_keywords"):
        warnings.append("No root keywords extracted.")

    for kw in data.get("root_keywords", []):
        if kw not in data.get("keyword_profiles", {}):
            warnings.append(f"No keyword profile built for root keyword: {kw}")

    # D-C-13 / D4.14: `root_keywords` are derived from the overview rows, so a
    # keyword whose SERP fetch failed is not a root keyword and the check above
    # cannot see it. The run's own keyword list can: a keyword that was asked
    # for and produced nothing is the one case that must not pass in silence.
    for kw in missing_serp_keywords(data):
        warnings.append(
            f"No SERP data returned for '{kw}': it was analysed but produced "
            f"no results. Every figure in this report excludes it.")

    client_summary = data.get("client_position", {}).get("summary", {})
    if client_summary.get("total_organic_appearances", 0) == 0 and client_summary.get("total_aio_citations", 0) == 0 and client_summary.get("total_aio_text_mentions", 0) == 0 and client_summary.get("total_local_pack", 0) == 0:
        warnings.append("Client was not detected in organic, AIO citations, AIO text, or local pack.")

    queries_with_aio = sum(1 for q in data.get("queries", []) if q.get("has_ai_overview"))
    total_queries = len(data.get("queries", []))
    if total_queries > 0 and queries_with_aio == 0:
        warnings.append("No queries triggered AI Overviews.")

    if data.get("paa_analysis", {}).get("summary", {}).get("total_unique_questions", 0) < 5:
        warnings.append("Very low PAA coverage (<5 questions).")

    summary = data.get("organic_summary", {})
    total = summary.get("total_rows", 0)
    unclassified = summary.get("entity_unclassified_count", 0)
    if total > 0 and (unclassified / total) > 0.4:
        warnings.append(
            f"High unclassified entity share: {unclassified}/{total} ({unclassified/total:.0%})."
        )
    return warnings


def validate_advisory_briefing(report_text, extracted_data):
    issues = []
    report_l = _normalize_text(report_text)
    strategic_flags = extracted_data.get("strategic_flags", {})
    priorities = strategic_flags.get("content_priorities", [])
    first_priority = priorities[0] if priorities else {}
    skip_keywords = {item.get("keyword") for item in priorities if item.get("action") == "skip"}

    if strategic_flags.get("defensive_urgency") == "high":
        headline = report_text.split("## Action 1", 1)[0]
        first_block = report_text.split("## Action 1", 1)[1] if "## Action 1" in report_text else report_text
        first_block = first_block.split("## Action 2", 1)[0]
        expected_keyword = _normalize_text(first_priority.get("keyword"))
        if expected_keyword and expected_keyword not in _normalize_text(headline + "\n" + first_block):
            issues.append(
                f"Advisory briefing does not make the top defensive keyword '{first_priority.get('keyword')}' the first action."
            )

    for kw in skip_keywords:
        if kw and _normalize_text(kw) in report_l and "stop thinking about" not in report_l:
            issues.append(
                f"Advisory briefing references skip keyword '{kw}' outside the stop-thinking section."
            )

    overconfident_patterns = [
        r"you'?ll lose your rank #\d+ position entirely",
        r"will lose .*ai overview citation",
        r"will disappear entirely",
    ]
    for pattern in overconfident_patterns:
        if re.search(pattern, report_l):
            issues.append(
                "Advisory briefing uses unsupported certainty language where the data supports risk, not certainty."
            )
            break

    # Same rule as the brief's, on the same editorial list (D4.16): demand
    # language is permitted when a demand figure exists, and the keyword-specific
    # estrangement rule is gone.
    if not _any_demand_measured(extracted_data.get("keyword_profiles") or {}):
        for _phrase in (load_validation_rules().get("market_size_phrases") or []):
            if re.search(_phrase, report_l):
                issues.append(
                    "Advisory briefing describes search demand (%r) but no "
                    "keyword in this run carries a measured monthly volume."
                    % _phrase
                )
                break

    if re.search(r"eliminate your digital presence entirely|complete loss of (?:your )?digital presence", report_l):
        issues.append(
            "Advisory briefing overstates the consequence scope beyond measured search visibility."
        )

    return issues


def has_hard_validation_failures(validation_issues):
    hard_patterns = [
        "queries have ai overviews",
        "claims ai overviews appear for all",
        "cites 'toxic' as a high-volume autocomplete term",
        "cross-cutting 'toxic' opportunity",
        "marks '",
    ]
    for issue in validation_issues:
        normalized = _normalize_text(issue)
        if "despite zero verified trigger evidence" in normalized:
            return True
        if "but keyword_profiles shows" in normalized:
            return True
        if "but keyword_profiles.recommended_play shows" in normalized:
            return True
        if "contradicts keyword_profiles.title_patterns" in normalized:
            return True
        if "but verified data shows" in normalized:
            return True
        # D4.3: a DA direction stated for a keyword whose DA was never
        # measured. Mechanically checkable against the profile, so HARD.
        if "data_available.feasibility is false" in normalized:
            return True
        if any(pattern in normalized for pattern in hard_patterns):
            return True
    return False


def partition_validation_issues(validation_issues):
    blocking = []
    notes = []
    inactive = _normalize_text(INACTIVE_CHECK_PREFIX)
    for issue in validation_issues:
        normalized = _normalize_text(issue)
        if inactive in normalized:
            # About the tool, not the brief. A correction prompt cannot fix a
            # YAML file, and sending it there spent a second LLM call and then
            # aborted the run (cold review of chunk Y3).
            notes.append(issue)
        elif "contradicts keyword_profiles.entity_label" in normalized:
            notes.append(issue)
        elif "contradicts keyword_profiles.mixed_intent_strategy" in normalized:
            notes.append(issue)
        elif "keyword_profiles.serp_intent.confidence" in normalized:
            notes.append(issue)
        # title_patterns.dominant_pattern contradiction is a HARD-FAIL (Fix 7).
        # Falls through to blocking.append below.
        else:
            blocking.append(issue)
    return blocking, notes
