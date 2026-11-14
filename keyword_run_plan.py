"""keyword_run_plan.py — decide what a run will do to the keyword file, then do it.

No tkinter. The launcher makes a plan first (nothing is written), runs every
check that can still cancel the run, and applies the plan immediately before
the process starts. A cancelled run therefore changes no file.

Spec: docs/plan_checkpoint_resume_and_m3_2026-11-14.md (M1, M4, M5)
Tests: tests/test_keyword_run_plan.py
"""

import os
import re

INPUT_CSV_ENV = "SERP_INPUT_CSV"


def keyword_slug(keyword):
    slug = keyword.strip().lower().replace(" ", "_")
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "custom"


def read_keywords(path):
    """Keywords in a keyword CSV, one per line, without the optional header."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        values = [line.strip() for line in f]
    return [v for v in values if v and v.lower() != "keyword"]


def _merge(existing, new):
    seen = {value.lower() for value in existing}
    merged, added = list(existing), []
    for keyword in new:
        if keyword.lower() not in seen:
            seen.add(keyword.lower())
            merged.append(keyword)
            added.append(keyword)
    return merged, added


def plan_keyword_run(selected_path, new_keywords, folder):
    """What the run would use and write. Reads files; writes nothing.

    Returns a dict:
      keyword_file    path the run will read
      keywords        its contents once the plan is applied
      added_keywords  keywords the plan adds to an existing file
      write           whether applying the plan changes the file
      existing_count  set only when a new-keywords run would land on a file
                      that already exists with other contents; the caller must
                      ask before going on (M4). None otherwise.
    """
    if not selected_path and not new_keywords:
        raise ValueError("Please select an existing keyword file or enter new keywords.")

    if selected_path and not new_keywords:
        return {"keyword_file": selected_path, "keywords": read_keywords(selected_path),
                "added_keywords": [], "write": False, "existing_count": None}

    if selected_path:
        existing = read_keywords(selected_path)
        merged, added = _merge(existing, new_keywords)
        return {"keyword_file": selected_path, "keywords": merged, "added_keywords": added,
                "write": bool(added), "existing_count": None}

    path = os.path.join(folder, f"keywords_{keyword_slug(new_keywords[0])}.csv")
    if not os.path.exists(path):
        return {"keyword_file": path, "keywords": list(new_keywords), "added_keywords": [],
                "write": True, "existing_count": None}
    existing = read_keywords(path)
    merged, added = _merge(existing, new_keywords)
    if sorted(k.lower() for k in existing) == sorted({k.lower() for k in new_keywords}):
        return {"keyword_file": path, "keywords": existing, "added_keywords": [],
                "write": False, "existing_count": None}
    # Different contents: the run would use the file's keywords as well as the
    # new ones, so the caller asks first, even when nothing needs adding.
    return {"keyword_file": path, "keywords": merged, "added_keywords": added,
            "write": bool(added), "existing_count": len(existing)}


def apply_keyword_plan(plan):
    """Write the keyword file if the plan changes it. Returns True when written."""
    if not plan["write"]:
        return False
    path = plan["keyword_file"]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for keyword in plan["keywords"]:
            f.write(f"{keyword}\n")
    os.replace(tmp, path)
    return True
