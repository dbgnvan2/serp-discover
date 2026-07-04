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
}


def load_serp_vocab(path=_SERP_VOCAB_PATH):
    """Load the editorial SERP vocabulary (stop words, PAA category
    triggers, service tokens, AI-alternative templates).

    Spec: seo_geo_review_20260704.md C.4 — these lists are editorial and
    live in serp_vocab.yml, not in Python. Missing file or missing keys
    raise so configuration mistakes surface loudly.
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
