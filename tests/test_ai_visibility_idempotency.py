"""Idempotency of the AI-visibility save functions (harden the class, P8).

save_citations / save_aivi / save_brand_mentions (keyed per run_ts+engine) and
save_sentiment / save_transfer / save_foundational_score (per run_ts) previously
used a bare INSERT, so re-saving the same key appended duplicates. Each now DELETEs
its key first (mirroring aio_exposure / commodity_score). A re-save must not double
the rows, and the per-engine deletes must not clobber a different engine's rows.
"""
import sqlite3

import aivi
import answer_sentiment as sentiment
import brand_mentions
import citation_table
import engine_transfer
import foundational_score


def _count(db, table, where="", params=()):
    with sqlite3.connect(db) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table} {where}", params).fetchone()[0]


def test_save_citations_idempotent_and_engine_scoped(tmp_path):
    db = str(tmp_path / "s.db")
    row = [{"url": "u", "domain": "d", "category": "c", "brand": "b",
            "is_client": True, "cite_count": 1}]
    citation_table.save_citations(db, "R1", "openai", row)
    citation_table.save_citations(db, "R1", "openai", row)          # re-save same key
    assert _count(db, citation_table.CITATIONS_TABLE,
                  "WHERE run_ts=? AND engine=?", ("R1", "openai")) == 1
    citation_table.save_citations(db, "R1", "gemini", row)          # a different engine
    assert _count(db, citation_table.CITATIONS_TABLE,
                  "WHERE run_ts=? AND engine=?", ("R1", "openai")) == 1   # not clobbered
    assert _count(db, citation_table.CITATIONS_TABLE, "WHERE run_ts=?", ("R1",)) == 2


def test_save_aivi_idempotent(tmp_path):
    db = str(tmp_path / "s.db")
    res = {"aivi": 50, "axes": {"mentions": 50, "ranking": 50, "citations": 50, "sentiment": None},
           "weights_used": {}}
    aivi.save_aivi(db, "R1", "openai", res)
    aivi.save_aivi(db, "R1", "openai", res)
    aivi.save_aivi(db, "R1", "gemini", res)
    assert _count(db, aivi.AIVI_TABLE, "WHERE run_ts=? AND engine=?", ("R1", "openai")) == 1
    assert _count(db, aivi.AIVI_TABLE, "WHERE run_ts=?", ("R1",)) == 2   # both engines kept


def test_save_sentiment_idempotent(tmp_path):
    db = str(tmp_path / "s.db")
    rows = [{"engine": "openai", "brand": "X", "polarity": "positive",
             "positive_aspects": [], "negative_aspects": [], "answer_excerpt": "hi"}]
    sentiment.save_sentiment(db, "R1", rows)
    sentiment.save_sentiment(db, "R1", rows)
    assert _count(db, sentiment.SENTIMENT_TABLE, "WHERE run_ts=?", ("R1",)) == 1


def test_save_brand_mentions_idempotent_and_engine_scoped(tmp_path):
    db = str(tmp_path / "s.db")
    lb = {"questions_total": 3, "rows": [{"brand": "X", "mention_count": 2,
                                          "is_client": True, "source": "gaz"}]}
    brand_mentions.save_brand_mentions(db, "R1", "openai", lb)
    brand_mentions.save_brand_mentions(db, "R1", "openai", lb)
    brand_mentions.save_brand_mentions(db, "R1", "gemini", lb)
    assert _count(db, brand_mentions.BRAND_MENTIONS_TABLE,
                  "WHERE run_ts=? AND engine=?", ("R1", "openai")) == 1
    assert _count(db, brand_mentions.BRAND_MENTIONS_TABLE, "WHERE run_ts=?", ("R1",)) == 2


def test_save_foundational_idempotent(tmp_path):
    db = str(tmp_path / "s.db")
    res = {"score": 70, "subscores": {"accessibility": 70, "structure": 70, "authority": 70},
           "weights_used": {}}
    foundational_score.save_foundational_score(db, "R1", res)
    foundational_score.save_foundational_score(db, "R1", res)
    assert _count(db, foundational_score.FOUNDATIONAL_TABLE, "WHERE run_ts=?", ("R1",)) == 1


def test_save_transfer_idempotent(tmp_path):
    db = str(tmp_path / "s.db")
    res = {"engines": ["openai"], "measurable": False, "reason": "single"}
    engine_transfer.save_transfer(db, "R1", res)
    engine_transfer.save_transfer(db, "R1", res)
    assert _count(db, engine_transfer.TRANSFER_TABLE, "WHERE run_ts=?", ("R1",)) == 1
