"""
metrics.py
Calculates SEO metrics (Volatility, Dominance) from the SQLite history.
"""
import pandas as pd
import os
import logging

import db_connect
import storage

def _db_path():
    """The database this process opens, resolved at call time.

    A module constant bound at import, and relative to the current working
    directory: run from anywhere but the repo root and SQLite created a new
    empty file beside the caller rather than reporting that the history was
    missing (P4/P16, review chunk Y12). Kept as a callable with the same name
    so a reader of these modules sees the resolution happen.
    """
    return db_connect.database_path()

#: Rank history is only comparable across the primary query. AI-alternative
#: ("A.1"/"A.2") and pivot ("P") rows are stored under the same root keyword,
#: so merging on (keyword_text, url) without this filter produced
#: cross-products and invented rank deltas (finding D-C-22).
PRIMARY_QUERY_LABEL = "A"

#: One definition of "a run whose history can be trusted": it wrote every
#: output. Rows written before the completed_at migration carry NULL, which
#: means unknown — they are skipped, and the skip is counted and logged rather
#: than passed off as "no history" (P2: surface, never silently drop).
_RUNS_SQL = "SELECT run_id, run_date, completed_at FROM runs ORDER BY run_date DESC"

_ORGANIC_SQL = """
    SELECT keyword_text, url, rank
    FROM serp_results
    WHERE run_id = ? AND result_type = 'organic' AND query_label = ?
"""


def _previous_completed_run(runs_df, current_date):
    """The most recent completed run strictly before *current_date*.

    Returns ``(run_id, skipped_count)``; ``run_id`` is None when there is
    none. *skipped_count* is how many runs were passed over because they
    never recorded a completion — the caller reports that number instead of
    silently comparing against an aborted run.

    The count is scoped to what the caller's message claims. With a baseline,
    it counts only the incomplete runs **between** that baseline and the
    current run, which is what "N more recent run(s) skipped" means; counting
    every earlier incomplete run would report the whole pre-migration history
    (54 runs on this client's database) as if it sat in that window. With no
    baseline at all, every earlier run was indeed passed over, so all of them
    are counted.
    """
    earlier = runs_df[runs_df["run_date"] < current_date]
    if earlier.empty:
        return None, 0
    completed = earlier[earlier["completed_at"].notna()]
    if completed.empty:
        return None, len(earlier)
    baseline = completed.iloc[0]
    between = earlier[(earlier["run_date"] > baseline["run_date"])
                      & earlier["completed_at"].isna()]
    return baseline["run_id"], len(between)


def _incomplete_history_msg(skipped):
    """Why there is no baseline, naming how many runs were passed over."""
    if skipped:
        return (f"No completed prior run found: {skipped} earlier "
                f"run(s) have no completion record (aborted, or written "
                f"before run completion was tracked). Deltas need a run that "
                f"wrote all of its outputs.")
    return "No prior run found."


def _rank_frames(conn, runs_df, current_run_id):
    """``{"current": df, "previous": df}``, or a status dict saying why not.

    Every read of the history lives here, so `get_volatility_metrics` holds
    the connection for exactly as long as the reads take (review chunk Y5).
    """
    if len(runs_df) < 2:
        return {"status": "insufficient_history",
                "msg": "Need at least 2 runs to calculate volatility."}

    current_run_date_row = runs_df[runs_df['run_id'] == current_run_id]
    if current_run_date_row.empty:
        # Every exit carries a status and a msg: the caller renders the
        # reason, and a bare None made report section 6 vanish with no note
        # at all (P2, review chunk Y3).
        return {"status": "run_not_found",
                "msg": (f"run {current_run_id} is not in the run history, "
                        f"so there is nothing to compare it against.")}

    current_date = current_run_date_row.iloc[0]['run_date']

    # Find the previous *completed* run (D-C-22)
    prev_run_id, skipped = _previous_completed_run(runs_df, current_date)
    if prev_run_id is None:
        if skipped:
            logging.warning(
                "Volatility: %d earlier run(s) skipped with no completion "
                "record.", skipped)
        return {"status": "insufficient_history",
                "msg": _incomplete_history_msg(skipped)}
    if skipped:
        logging.info(
            "Volatility: baseline is run %s; %d more recent run(s) skipped "
            "with no completion record.", prev_run_id, skipped)

    # Ranks for current and previous — primary query only (D-C-22)
    return {
        "current": pd.read_sql(_ORGANIC_SQL, conn,
                               params=(current_run_id, PRIMARY_QUERY_LABEL)),
        "previous": pd.read_sql(_ORGANIC_SQL, conn,
                                params=(prev_run_id, PRIMARY_QUERY_LABEL)),
    }


def get_volatility_metrics(current_run_id):
    """
    Compares the current run against the immediate previous run to calculate
    rank volatility.

    Always returns a dict carrying ``status``. On ``"success"`` it carries the
    figures; on every other status it carries ``msg``, the reason the caller
    renders in its place: ``no_database``, ``insufficient_history``,
    ``run_not_found``, ``empty_data``, ``no_shared_urls``, ``query_failed``.
    Four of those used to be a bare ``None``, and report section 6 then
    vanished with no note, which reads as "the market did not move" rather
    than "this run could not be compared" (P1/P2, review chunk Y3).
    """
    if not os.path.exists(_db_path()):
        return {"status": "no_database",
                "msg": f"no history database at {_db_path()} yet "
                       f"(config.yml database.path names this file)."}

    try:
        # One `closing` around every read, not a `close()` on each of this
        # function's seven exits: a leaked sqlite handle is how a later write
        # meets "database is locked", and the next exit added is the one that
        # forgets (review chunk Y5).
        with storage.migrated_connection(_db_path()) as conn:
            runs_df = pd.read_sql(_RUNS_SQL, conn)
            frames = _rank_frames(conn, runs_df, current_run_id)
        if "status" in frames:
            return frames
        curr_df, prev_df = frames["current"], frames["previous"]

        if curr_df.empty or prev_df.empty:
            return {"status": "empty_data",
                    "msg": ("No primary-query organic results found in one of "
                            "the runs. Rows stored before the query_label "
                            "migration carry no label and are not comparable; "
                            "re-run to rebuild the history.")}

        # Ensure ranks are numeric (handle "N/A" or other artifacts)
        curr_df['rank'] = pd.to_numeric(curr_df['rank'], errors='coerce')
        prev_df['rank'] = pd.to_numeric(prev_df['rank'], errors='coerce')
        curr_df = curr_df.dropna(subset=['rank'])
        prev_df = prev_df.dropna(subset=['rank'])

        current_keywords = set(curr_df['keyword_text'].dropna().unique())
        previous_keywords = set(prev_df['keyword_text'].dropna().unique())
        comparability_warning = None
        if current_keywords != previous_keywords:
            missing_from_prev = sorted(current_keywords - previous_keywords)
            missing_from_curr = sorted(previous_keywords - current_keywords)
            parts = ["Volatility is based on non-identical keyword sets."]
            if missing_from_prev:
                parts.append(f"Only in current run: {', '.join(missing_from_prev)}.")
            if missing_from_curr:
                parts.append(f"Only in previous run: {', '.join(missing_from_curr)}.")
            comparability_warning = " ".join(parts)

        # Merge on keyword + url
        merged = pd.merge(curr_df, prev_df, on=[
                          'keyword_text', 'url'], suffixes=('_curr', '_prev'))

        # Calculate Delta
        # Positive means improved (rank went down numerically)
        merged['rank_delta'] = merged['rank_prev'] - merged['rank_curr']

        if merged.empty:
            # No (keyword, url) pair is in both runs, so the mean below would
            # be NaN and the section printed its heading and nothing else.
            # Not a volatility of zero: nothing was compared (P1).
            return {"status": "no_shared_urls",
                    "msg": ("no URL ranked for the same keyword in both runs, "
                            "so there is no rank change to measure. The SERP "
                            "turned over completely, or the two runs covered "
                            "different keywords."),
                    "comparability_warning": comparability_warning,
                    "keywords_current": sorted(current_keywords),
                    "keywords_previous": sorted(previous_keywords)}

        # Volatility Score (Average absolute change)
        volatility_score = merged['rank_delta'].abs().mean()

        # Winners & Losers
        winners = merged[merged['rank_delta'] > 0].sort_values(
            'rank_delta', ascending=False).head(5)
        losers = merged[merged['rank_delta'] < 0].sort_values(
            'rank_delta', ascending=True).head(5)

        return {
            "status": "success",
            "volatility_score": round(volatility_score, 2),
            "stable_urls_count": len(merged[merged['rank_delta'] == 0]),
            "total_compared": len(merged),
            "comparability_warning": comparability_warning,
            # D-C-18 / D4.5: report section 6 prints these two when the
            # keyword sets differ. They were never returned, so the section
            # read "This run: unknown / Previous run: unknown" on exactly the
            # runs where the sentence promises the two lists.
            "keywords_current": sorted(current_keywords),
            "keywords_previous": sorted(previous_keywords),
            "winners": winners[['keyword_text', 'url', 'rank_curr', 'rank_delta']].to_dict('records'),
            "losers": losers[['keyword_text', 'url', 'rank_curr', 'rank_delta']].to_dict('records')
        }

    except Exception as e:
        logging.error(f"Error calculating volatility: {e}")
        # `closing` has already released the handle, whichever line raised
        # (review chunk Y5 — this used to be a hand-written close).
        return {"status": "query_failed",
                "msg": (f"the volatility query failed ({e}); the figures could "
                        f"not be computed for this run.")}


#: Why a result set is not comparable, for callers to render instead of
#: dropping a report section silently (finding D-C-22 follow-up, P2).
_NO_PRIMARY_ROWS_MSG = (
    "no primary-query (query_label = 'A') organic rows for this run. Rows "
    "stored before the query_label migration carry no label and are not "
    "comparable; re-run to rebuild the history.")


def get_entity_dominance(run_id):
    """
    Aggregates Entity Type and Content Type dominance for the current run.

    On success the result carries ``entity_dominance`` / ``content_dominance``.
    Otherwise it carries ``status`` and ``msg`` so the caller can print why the
    section is missing: a bare ``{}`` made report section 5 disappear with no
    note, which reads as "the SERP has no composition" rather than "this run's
    rows cannot be interpreted".
    """
    if not os.path.exists(_db_path()):
        return {"status": "no_database",
                "msg": f"no history database at {_db_path()} yet "
                       f"(config.yml database.path names this file)."}

    try:
        # `closing`, like `get_volatility_metrics`: the `except` path below
        # returned without closing, so a failing dominance query left a reader
        # open (P5 — the sibling of the same call is fixed in the same change,
        # review chunk Y5).
        query = """
        SELECT 
            s.rank,
            d.entity_type,
            u.content_type
        FROM serp_results s
        LEFT JOIN domain_features d ON s.domain = d.domain
        LEFT JOIN url_features u ON s.url = u.url
        WHERE s.run_id = ? AND s.result_type = 'organic'
          AND s.query_label = ? AND s.rank <= 10
        """
        # `rank <= 10` is the real top 10 since ranks became absolute
        # (D-C-01), and the label keeps alternative-query rows out (D-C-22).
        with storage.migrated_connection(_db_path()) as conn:
            df = pd.read_sql(query, conn,
                             params=(run_id, PRIMARY_QUERY_LABEL))

        if df.empty:
            return {"status": "empty_data", "msg": _NO_PRIMARY_ROWS_MSG}

        entity_counts = df['entity_type'].value_counts(
            normalize=True).to_dict()
        content_counts = df['content_type'].value_counts(
            normalize=True).to_dict()

        return {
            "entity_dominance": {k: round(v * 100, 1) for k, v in entity_counts.items()},
            "content_dominance": {k: round(v * 100, 1) for k, v in content_counts.items()}
        }

    except Exception as e:
        logging.error(f"Error calculating dominance: {e}")
        return {"status": "error", "msg": f"dominance query failed: {e}"}


def get_rank_deltas(current_run_id, with_reason=False):
    """
    Returns a dictionary of {(keyword, url): rank_delta} for the current run
    compared to the previous one.

    With ``with_reason=True`` returns ``(deltas, reason)``, where *reason* says
    why an empty result is empty. An empty dict alone meant three different
    things — no runs, no completed baseline, no label-A rows — and the caller
    printed "No historical data for rank comparison yet" over a database
    holding thousands of rows (P2).
    """
    def _out(deltas, reason=""):
        return (deltas, reason) if with_reason else deltas

    if not os.path.exists(_db_path()):
        return _out({}, f"no history database at {_db_path()} yet.")

    try:
        # All three reads go through `storage.migrated_connection`: they
        # filter on `runs.completed_at` and `serp_results.query_label`,
        # columns a migration added, and `generate_insight_report.py` calls
        # them standalone with no `SerpStorage` constructed first — so
        # against a database written before those columns the report printed
        # "no such column" instead of bringing the schema forward. The bare
        # `with sqlite3.connect(...)` this one used also commits on exit and
        # never closes the handle (P5, cold review of chunk Y6, finding 5).
        with storage.migrated_connection(_db_path()) as conn:
            runs_df = pd.read_sql(_RUNS_SQL, conn)

            if len(runs_df) < 2:
                return _out({}, "only one run recorded: deltas need two.")

            # Identify previous run
            current_run_date_row = runs_df[runs_df['run_id'] == current_run_id]
            if current_run_date_row.empty:
                return _out({}, f"run {current_run_id} is not in the history "
                                f"table, so it has nothing to compare against.")

            current_date = current_run_date_row.iloc[0]['run_date']
            # Previous *completed* run only (D-C-22).
            prev_run_id, skipped = _previous_completed_run(runs_df, current_date)
            if prev_run_id is None:
                if skipped:
                    logging.warning(
                        "Rank deltas: no baseline; %d earlier run(s) have no "
                        "completion record.", skipped)
                return _out({}, _incomplete_history_msg(skipped))
            if skipped:
                logging.info(
                    "Rank deltas: baseline is run %s; %d more recent run(s) "
                    "skipped with no completion record.", prev_run_id, skipped)

            # Keep keyword + url to avoid collisions when the same URL ranks for
            # multiple keywords, and the primary query only, so a URL ranking in
            # both the root and an alternative query cannot cross-product
            # (D-C-22).
            curr_df = pd.read_sql(_ORGANIC_SQL, conn,
                                  params=(current_run_id, PRIMARY_QUERY_LABEL))
            prev_df = pd.read_sql(_ORGANIC_SQL, conn,
                                  params=(prev_run_id, PRIMARY_QUERY_LABEL))

        if curr_df.empty or prev_df.empty:
            return _out({}, _NO_PRIMARY_ROWS_MSG)

        curr_df['rank'] = pd.to_numeric(curr_df['rank'], errors='coerce')
        prev_df['rank'] = pd.to_numeric(prev_df['rank'], errors='coerce')
        curr_df = curr_df.dropna(subset=['rank'])
        prev_df = prev_df.dropna(subset=['rank'])

        merged = pd.merge(
            curr_df,
            prev_df,
            on=['keyword_text', 'url'],
            suffixes=('_curr', '_prev')
        )
        if merged.empty:
            return _out({}, f"no URL ranks for the same keyword in both run "
                            f"{current_run_id} and run {prev_run_id}.")

        merged['rank_delta'] = merged['rank_prev'] - merged['rank_curr']
        return _out({
            (row['keyword_text'], row['url']): row['rank_delta']
            for _, row in merged.dropna(subset=['rank_delta']).iterrows()
        })

    except Exception as e:
        logging.error(f"Error getting rank deltas: {e}")
        return _out({}, f"rank-delta query failed: {e}")
