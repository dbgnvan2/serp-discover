#!/usr/bin/env python3
"""yaml_io.py — comment-preserving YAML save (the single home for the fix).

Every YAML config in this repo (``config.yml`` + the editorial ``*.yml`` files)
carries load-bearing documentation/gating comments. PyYAML's ``yaml.safe_dump``
strips ALL of them, so any load→modify→save cycle silently wipes the docs. This
module is the ONE ruamel round-trip save that keeps comments + key order, used by
every writer of a tracked config:

  * ``config_manager.BaseConfigTab.save_to_disk`` (the GUI editor, all 8 tabs),
  * ``serp_audit`` (writes ``files.output_*`` back into config.yml every run),
  * ``apply_domain_override_candidates.write_overrides`` (domain_overrides.yml).

(``serp-me.py`` has its own equivalent ``_yaml`` — the original 2026-07-04 fix,
which loads→mutates→saves the same CommentedMap so it needs no merge; it may be
migrated here later.)
"""
from __future__ import annotations

import logging
import os
import tempfile

from ruamel.yaml import YAML

logger = logging.getLogger(__name__)

def _yaml_rt():
    """A FRESH ruamel round-trip YAML per call — NOT a shared singleton. On a
    mid-dump failure ruamel leaves its reused emitter bound to the (now closed)
    stream, so a shared instance would raise "I/O operation on closed file" on EVERY
    later save across all callers until the process restarts (P1/P15). A fresh
    instance per call can't be poisoned. ``width`` is large so long value lines are
    not folded (avoids cosmetic churn/trailing space vs the old ``safe_dump``)."""
    rt = YAML()                 # typ='rt' by default
    rt.preserve_quotes = True
    rt.width = 4096
    return rt


def _merge_into_commented(dst, src):
    """Update ``dst`` (a ruamel CommentedMap loaded from disk) to hold exactly
    ``src``'s keys/values, preserving comments + order on keys that survive: keys
    absent from ``src`` are deleted and new ones added, so the DATA outcome equals
    the old ``yaml.safe_dump(src)`` while block/inline comments on retained keys are
    kept. Nested mappings recurse; a replaced list value keeps its mapping-key
    comment above it but not inner-item comments."""
    if not isinstance(dst, dict) or not isinstance(src, dict):
        return src
    for key in list(dst.keys()):
        if key not in src:
            del dst[key]
    for key, value in src.items():
        if key in dst and isinstance(dst[key], dict) and isinstance(value, dict):
            _merge_into_commented(dst[key], value)
        else:
            dst[key] = value
    return dst


def save_yaml_preserving_comments(file_path, data):
    """Write ``data`` to ``file_path`` as YAML, preserving existing comments + key
    order on retained keys (ruamel round-trip). Same DATA outcome as
    ``yaml.safe_dump(data)`` but comments survive.

    Handles both mapping-topped files (deep-merge) and sequence-topped files (e.g.
    strategic_patterns.yml — replace items in place so the document-level comment on
    the loaded CommentedSeq is kept; inner per-item comments are not merged). A
    symlinked ``file_path`` is followed to its real target (so the multi-client
    symlink workflow keeps working). The write is **atomic** (temp file +
    ``os.replace``) so a failed dump can never truncate the existing config (P2).

    Latent caveat: callers typically build ``data`` with PyYAML ``yaml.safe_load``
    while the on-disk file is re-read here with ruamel — the two disagree on YAML-1.1
    bool-like keys (``on/off/yes/no``), so such a divergent key would be treated as
    removed and re-added, dropping its comment. No repo config uses such a key today
    (guarded by ``tests/test_yaml_io.py``); align the parsers if one ever does."""
    yaml_rt = _yaml_rt()
    # Follow a symlink to its target so the atomic replace updates the shared file
    # instead of detaching the link (multi-client setups symlink these configs).
    target = os.path.realpath(file_path)
    doc = None
    if os.path.exists(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                doc = yaml_rt.load(f)
        except Exception as exc:
            # A genuinely-unparseable file OR a transient read failure both land
            # here; surface it (never silently re-strip the comments — P2).
            logger.warning("Could not read %s to preserve comments (%s) — writing "
                           "fresh; any comments already in that file are lost.",
                           target, exc)
            doc = None

    if isinstance(doc, dict) and isinstance(data, dict):
        _merge_into_commented(doc, data)
        out = doc
    elif isinstance(doc, list) and isinstance(data, list):
        doc[:] = data          # keep the CommentedSeq (its document-level comment)
        out = doc
    else:
        out = data             # absent / unparseable / type-mismatch → fresh write

    directory = os.path.dirname(target)
    fd, tmp = tempfile.mkstemp(prefix=".yamlio_", suffix=".yml", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml_rt.dump(out, f)
        if os.path.exists(target):
            try:   # keep the original file's permissions (mkstemp creates 0600)
                os.chmod(tmp, os.stat(target).st_mode & 0o777)
            except OSError:
                pass
        os.replace(tmp, target)        # atomic swap — original survives a failed dump
    except Exception:
        try:
            os.close(fd)               # in case os.fdopen never took ownership of fd
        except OSError:
            pass
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
