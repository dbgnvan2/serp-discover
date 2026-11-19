"""Where a run's keyword list comes from.

Extracted from `serp_audit.py` on 2026-11-18. The extraction was not the
point: hardening this function's CSV read cost eighteen lines, `serp_audit.py`
sat at exactly the 2200-line cap
(`tests/test_serp_audit_split.py::TestI63MainModuleSize`), and raising the cap
to fit a fix is how a 2200-line module got there — one reasonable addition at
a time. Reading the keyword file is a self-contained concern with one caller,
so it moved instead.

`serp_audit.load_keywords` is still the name every caller and test uses; it is
bound to this module's function there.

Spec: docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md (live-run finding)
"""
import logging
import os

import pandas as pd

#: How the keyword CSV is read. Not pandas' defaults, for two reasons:
#:
#: `keep_default_na=False` with an empty `na_values` — pandas' default
#: missing-value list contains "N/A", "NA", "None", "null", "-" and "nan", so
#: a keyword cell holding any of those came back as `float('nan')` and was
#: handed on as a search query: a paid SerpAPI call on the string "nan". This
#: is the sibling of the defect the first live run after the 2026-11-04 review
#: found in `validate_xlsx_vs_json.py`, swept in the same change because it is
#: one class of defect with two sites (P5).
#:
#: `skip_blank_lines=False` — pandas drops blank lines before the caller sees
#: them, so a keyword file with a gap in it ran shorter than the operator
#: wrote and nothing said so. Dropping them here instead makes the count
#: reportable (P2).
READ_OPTIONS = {
    "header": None,
    "keep_default_na": False,
    "na_values": [],
    "skip_blank_lines": False,
}


#: The first cell of a header row, lowercased. Editorial: a non-developer
#: maintaining keyword files is who decides what a header column is called,
#: and `config.yml` `files.keyword_csv_header_tokens` overrides this default.
#:
#: Why it exists: `keywords_family-of-origin-seo-phrases.csv` is a three-column
#: file with the header `keyword,intent,why_it_matters`, and the other six
#: keyword files in the repo have no header at all. Read with `header=None`,
#: which is right for the six, the word "keyword" became the run's first
#: search term — a paid SerpAPI call, a row in every output sheet, and a
#: keyword in the market report that no human typed. Found on 2026-11-18 while
#: checking that file before a real run.
DEFAULT_HEADER_TOKENS = ("keyword", "keywords", "term", "terms", "query",
                         "queries", "phrase", "phrases", "search term",
                         "search_term")


def load_keywords(input_file, single_keyword_override="", header_tokens=None):
    """The keywords to search, or `None` if the file could not be read.

    `None` and `[]` are different answers: no readable input is an operator
    error the caller aborts on, while an empty list is a file that holds no
    keywords. The caller distinguishes them (P1/P2).
    """
    if single_keyword_override:
        print("Using single keyword override from SERP_SINGLE_KEYWORD...")
        return [single_keyword_override]

    if not os.path.exists(input_file):
        logging.error(f"{input_file} not found.")
        return None

    print("Reading keywords...")
    try:
        df_input = pd.read_csv(input_file, **READ_OPTIONS)
        raw = df_input[0].tolist()
    except Exception as e:
        logging.error(f"Error reading CSV: {e}")
        return None

    keywords = [str(k).strip() for k in raw if str(k).strip()]
    dropped = len(raw) - len(keywords)
    if dropped:
        logging.warning(
            "%d of %d line(s) in %s were blank and were not searched.",
            dropped, len(raw), input_file)

    tokens = tuple(t.lower() for t in (header_tokens
                                       or DEFAULT_HEADER_TOKENS))
    if keywords and keywords[0].lower() in tokens:
        # Said out loud, not dropped quietly: a file whose first row is being
        # skipped has a shape the operator may not have intended, and a run
        # that silently searches one keyword fewer than the file lists is the
        # same class of defect as one that silently searches one more (P2).
        logging.warning(
            "%s begins with the header row %r; it was not searched. "
            "%d keyword(s) remain.",
            input_file, keywords[0], len(keywords) - 1)
        keywords = keywords[1:]

    return keywords
