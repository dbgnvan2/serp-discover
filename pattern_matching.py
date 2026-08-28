"""pattern_matching.py — N-gram analysis and Bowen pattern matching for SERP data.

Spec: serp_tool1_improvements_spec.md#I.6
"""
import os
import re
import yaml

try:
    from textblob import TextBlob
    TEXTBLOB_AVAILABLE = True
except ImportError:
    TextBlob = None
    TEXTBLOB_AVAILABLE = False

_SERP_VOCAB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "serp_vocab.yml")

_VOCAB_REQUIRED_KEYS = {
    "stop_words",
    "paa_category_triggers",
    "service_like_tokens",
    "ai_alternative_templates",
    "eeat_signals",
    "situational_templates",
}


def load_serp_vocab(path=_SERP_VOCAB_PATH):
    """Load the editorial SERP vocabulary (stop words, PAA category
    triggers, service tokens, AI-alternative templates, E-E-A-T
    credential/review vocab, situational probe templates).

    Spec: seo_geo_review_20260704.md C.4 — these lists are editorial and
    live in serp_vocab.yml, not in Python. Missing file or missing keys
    raise so configuration mistakes surface loudly. The eeat_signals
    section is required per seo_geo_deferred_spec_v1.md#G.3; the
    situational_templates section per seo_geo_deferred_spec_v1.md#T.5.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"serp_vocab.yml not found at {path} — the editorial SERP "
            "vocabulary file is required (see CLAUDE.md, editorial content)."
        )
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    missing = _VOCAB_REQUIRED_KEYS - set(data)
    if missing:
        raise ValueError(
            f"serp_vocab.yml is missing required key(s): {', '.join(sorted(missing))}"
        )
    return data


SERP_VOCAB = load_serp_vocab()
STOP_WORDS = set(SERP_VOCAB["stop_words"])

_STRATEGIC_PATTERNS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategic_patterns.yml")

_PATTERN_REQUIRED_FIELDS = {"Pattern_Name", "Triggers", "Status_Quo_Message", "Bowen_Bridge_Reframe", "Content_Angle"}


def get_ngrams(text, n):
    if not isinstance(text, str):
        return []
    # Clean: lowercase, replace non-alphanumeric with space (prevents "highly-trained" -> "highlytrained")
    text = re.sub(r'[^\w\s]', ' ', text.lower())
    words = [w for w in text.split() if w not in STOP_WORDS and len(w) > 2]
    return [" ".join(words[i:i+n]) for i in range(len(words)-n+1)]


def get_display_ngrams(text, n):
    """Extract n-grams that read as English, for display to a human.

    Purpose: Produce readable competitor phrases for the market report's
             "words the competitors use" section.
    Spec:    report_content_direction_spec.md#CD.3
    Tests:   tests/test_report_content_direction.py::test_cd3_1_internal_stopwords_preserved
             tests/test_report_content_direction.py::test_cd3_2_no_cross_connector_phrases

    This is deliberately NOT get_ngrams(). get_ngrams deletes stop words *before*
    joining, which is correct for trigger matching (a smaller, denser haystack) but
    produces non-phrases for display: "family of origin" collapses to "family
    origin", and "Family Institute at Greater Vancouver" yields the phrase
    "family greater", which nobody wrote.

    Here the span is taken over the RAW word sequence, so a phrase is always a
    contiguous quote from the source text. Stop words are then used only to decide
    which spans are worth showing:

      - a span starting or ending on a stop word is dropped ("of origin work")
      - a span needs at least two content words, so "the of a" style spans go
      - content words of two characters or fewer are dropped, matching get_ngrams'
        len(w) > 2 rule, so initials and stray letters do not become "phrases"

    get_ngrams is left exactly as it is: it feeds analyze_strategic_opportunities'
    trigger matching and the word cloud, and changing a shared function to fix one
    consumer's display is a regression waiting to happen.
    """
    if not isinstance(text, str):
        return []
    cleaned = re.sub(r'[^\w\s]', ' ', text.lower())
    words = cleaned.split()

    spans = []
    for i in range(len(words) - n + 1):
        span = words[i:i + n]
        if span[0] in STOP_WORDS or span[-1] in STOP_WORDS:
            continue
        content = [w for w in span if w not in STOP_WORDS]
        if len(content) < 2:
            continue
        if any(len(w) <= 2 for w in content):
            continue
        spans.append(" ".join(span))
    return spans


SNIPPET_OVERVIEW_KEYS = [
    "Featured_Snippet_Snippet", "AI_Overview",
    "Rank_1_Snippet", "Rank_2_Snippet", "Rank_3_Snippet",
]


def _row_matches_keyword(row, keyword):
    """True when a snippet row belongs to `keyword` (None = accept every row)."""
    if keyword is None:
        return True
    for field in ("Source_Keyword", "Root_Keyword"):
        value = row.get(field)
        if value and str(value).strip().lower() == str(keyword).strip().lower():
            return True
    return False


def collect_snippet_texts(overview=None, competitors=None, expansion=None,
                          autocomplete=None, keyword=None):
    """Gather every piece of SERP-visible text used for phrase analysis.

    Purpose: One definition of "which fields are competitor text", shared by the
             producer (serp_audit) and the report generator.
    Spec:    report_content_direction_spec.md#CD.3
    Tests:   tests/test_report_content_direction.py::test_cd3_6_display_phrases_wired_to_report

    serp_audit calls this with its in-flight lists while building the run; the
    report generator calls it with the same lists read back off the JSON, so a
    report rendered from an older JSON (written before serp_display_phrases
    existed) still produces the same phrases. Keeping one definition is the point:
    two copies of "which keys hold snippet text" is exactly how a producer and its
    consumer drift apart without either one erroring.

    Note this is SERP-visible text — the snippets, ads, related searches and
    autocomplete Google displays — not the body text of competitor pages.

    Pass `keyword` to restrict the result to rows from that search, which is how
    the content plan gives each option its own vocabulary rather than repeating one
    global list under every keyword. Rows match on Source_Keyword, falling back to
    Root_Keyword. `keyword=None` — the default, and what serp_audit uses for the
    run-wide analysis — accepts every row.
    """
    texts = []

    for row in overview or []:
        if not _row_matches_keyword(row, keyword):
            continue
        for key in SNIPPET_OVERVIEW_KEYS:
            val = row.get(key)
            if val and val != "N/A":
                texts.append(val)

    # Paid ads only: map-pack rows carry ratings, which are just numbers.
    for row in competitors or []:
        if not _row_matches_keyword(row, keyword):
            continue
        if row.get("Type") == "Paid Ad" and row.get("Snippet"):
            texts.append(row["Snippet"])

    for row in expansion or []:
        if not _row_matches_keyword(row, keyword):
            continue
        if row.get("Term"):
            texts.append(row["Term"])

    for row in autocomplete or []:
        if not _row_matches_keyword(row, keyword):
            continue
        if row.get("Suggestion"):
            texts.append(row["Suggestion"])

    return texts


def _tokenize_for_echo(text):
    """Lowercase word list used to compare a phrase against a search keyword."""
    if not isinstance(text, str):
        return []
    return re.sub(r'[^\w\s]', ' ', text.lower()).split()


def is_keyword_echo(phrase, keywords):
    """True when `phrase` is just the search term handed back.

    Purpose: Stop the competitor-language section reporting the keyword as its own
             finding.
    Spec:    report_content_direction_spec.md#CD.3.3
    Tests:   tests/test_report_content_direction.py::test_cd3_3_keyword_echo_suppressed

    A phrase is an echo when its words appear as a contiguous run inside any
    analysed keyword. Searching "family of origin work" makes "family of origin"
    an echo — true of the query, and therefore no evidence about competitors.
    """
    phrase_tokens = _tokenize_for_echo(phrase)
    if not phrase_tokens:
        return False
    for kw in keywords or []:
        kw_tokens = _tokenize_for_echo(kw)
        span = len(phrase_tokens)
        for i in range(len(kw_tokens) - span + 1):
            if kw_tokens[i:i + span] == phrase_tokens:
                return True
    return False


def get_display_phrases(texts, keywords=None, min_count=2, limit=10):
    """Count readable competitor phrases across `texts`, minus keyword echo.

    Purpose: Build the market report's competitor-vocabulary list.
    Spec:    report_content_direction_spec.md#CD.3
    Tests:   tests/test_report_content_direction.py::test_cd3_*

    Returns a list of {"Phrase": str, "Count": int} sorted by count descending then
    alphabetically, capped at `limit`.

    Returning [] is a real answer, not a failure: on a small keyword set almost
    every recurring phrase IS the keyword, and the honest output is an empty list
    that the report renders as "not enough distinct competitor language" rather
    than a padded list of restated search terms. The caller distinguishes the two
    cases by whether `texts` was empty to begin with.
    """
    from collections import Counter

    counter = Counter()
    for text in texts or []:
        for n in (2, 3):
            counter.update(get_display_ngrams(text, n))

    kept = [
        {"Phrase": phrase, "Count": count}
        for phrase, count in counter.items()
        if count >= min_count and not is_keyword_echo(phrase, keywords)
    ]
    kept.sort(key=lambda row: (-row["Count"], row["Phrase"]))
    return kept[:limit]


def count_syllables(word):
    word = word.lower()
    count = 0
    vowels = "aeiouy"
    if len(word) == 0:
        return 0
    if word[0] in vowels:
        count += 1
    for index in range(1, len(word)):
        if word[index] in vowels and word[index - 1] not in vowels:
            count += 1
    if word.endswith("e"):
        count -= 1
    if count == 0:
        count += 1
    return count


def calculate_reading_level(text):
    if not text or not isinstance(text, str) or text == "N/A":
        return "N/A"
    # Basic cleaning and tokenization
    clean_text = re.sub(r'[^\w\s.?!]', '', text)
    sentences = [s for s in re.split(r'[.?!]+', clean_text) if s.strip()]
    words = clean_text.split()
    if not sentences or not words:
        return "N/A"
    num_syllables = sum(count_syllables(w) for w in words)
    # Flesch-Kincaid Grade Level Formula
    score = 0.39 * (len(words) / len(sentences)) + 11.8 * \
        (num_syllables / len(words)) - 15.59
    return round(score, 1)


def calculate_sentiment(text):
    if not TEXTBLOB_AVAILABLE or not text or not isinstance(text, str) or text == "N/A":
        return "N/A"
    try:
        # Returns a float between -1.0 (Negative) and 1.0 (Positive)
        return round(TextBlob(text).sentiment.polarity, 2)
    except Exception:
        return "N/A"


def calculate_subjectivity(text):
    if not TEXTBLOB_AVAILABLE or not text or not isinstance(text, str) or text == "N/A":
        return "N/A"
    try:
        # Returns a float between 0.0 (Objective) and 1.0 (Subjective)
        return round(TextBlob(text).sentiment.subjectivity, 2)
    except Exception:
        return "N/A"


def _dataset_topic_profile(keywords):
    text = " ".join((keywords or [])).lower()
    return {
        "estrangement_family": any(term in text for term in [
            "estrangement", "adult children", "family cutoff", "reunification"
        ]),
        "marriage_couples": any(term in text for term in [
            "marriage", "couples", "partner", "relationship"
        ]),
    }


def _validate_strategic_patterns(patterns, source="strategic_patterns.yml"):
    """Raise ValueError if any pattern entry is malformed.

    Checked at load time so bad config fails loudly rather than silently
    producing wrong output or missing patterns at runtime.
    """
    if not isinstance(patterns, list) or not patterns:
        raise ValueError(f"{source}: must be a non-empty list of pattern entries")
    seen_names = set()
    for i, p in enumerate(patterns):
        label = f"{source} entry {i + 1}"
        missing = _PATTERN_REQUIRED_FIELDS - set(p.keys())
        if missing:
            raise ValueError(f"{label}: missing required fields: {sorted(missing)}")
        name = (p.get("Pattern_Name") or "").strip()
        if not name:
            raise ValueError(f"{label}: Pattern_Name must not be empty")
        if name in seen_names:
            raise ValueError(f"{source}: duplicate Pattern_Name '{name}'")
        seen_names.add(name)
        triggers = p.get("Triggers")
        if not isinstance(triggers, list) or not triggers:
            raise ValueError(f"{label} ({name!r}): Triggers must be a non-empty list")
        for t in triggers:
            if not isinstance(t, str) or not t.strip():
                raise ValueError(f"{label} ({name!r}): each trigger must be a non-empty string")
            if len(t.strip()) < 4:
                raise ValueError(
                    f"{label} ({name!r}): trigger {t!r} is too short (minimum 4 characters); "
                    "short triggers match too broadly even with word boundaries"
                )


def _load_strategic_patterns(path=None):
    """Load and validate Bowen pattern definitions from strategic_patterns.yml."""
    fpath = path or _STRATEGIC_PATTERNS_PATH
    with open(fpath, encoding="utf-8") as f:
        patterns = yaml.safe_load(f) or []
    _validate_strategic_patterns(patterns, source=os.path.basename(fpath))
    return patterns


def analyze_strategic_opportunities(ngram_results, keywords=None, patterns_path=None):
    """
    Maps detected N-Gram patterns to Bowen Theory strategic recommendations.
    Returns a list of dictionaries for the 'Strategic_Recommendations' sheet.
    Patterns are loaded from strategic_patterns.yml; add new patterns there.
    """
    strategies = _load_strategic_patterns(patterns_path)
    all_phrases = " ".join([item["Phrase"] for item in ngram_results]).lower()

    recommendations = []
    for strategy in strategies:
        found_triggers = [t for t in strategy["Triggers"]
                         if re.search(r'\b' + re.escape(t) + r'\b', all_phrases)]
        if found_triggers:
            rec = strategy.copy()
            rec["Detected_Triggers"] = ", ".join(found_triggers[:5])
            recommendations.append(rec)

    if not recommendations:
        recommendations.append({
            "Pattern_Name": "General Differentiation",
            "Detected_Triggers": "N/A",
            "Status_Quo_Message": "Standard symptom-focused advice.",
            "Bowen_Bridge_Reframe": "Focus on defining a self within the system.",
            "Content_Angle": "How to be yourself in your important relationships."
        })

    return recommendations
