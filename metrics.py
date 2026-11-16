"""
metrics.py
Calculates SEO metrics (Volatility, Dominance) from the SQLite history.
"""
import sqlite3
import pandas as pd
import os
import logging

DB_PATH = "serp_data.db"

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
    none. *skipped_count* is how many earlier runs were passed over because
    they never recorded a completion — the caller reports that number instead
    of silently comparing against an aborted run.
    """
    earlier = runs_df[runs_df["run_date"] < current_date]
    if earlier.empty:
        return None, 0
    completed = earlier[earlier["completed_at"].notna()]
    skipped = len(earlier) - len(completed)
    if completed.empty:
        return None, skipped
    return completed.iloc[0]["run_id"], skipped


def _incomplete_history_msg(skipped):
    """Why there is no baseline, naming how many runs were passed over."""
    if skipped:
        return (f"No completed prior run found: {skipped} earlier "
                f"run(s) have no completion record (aborted, or written "
                f"before run completion was tracked). Deltas need a run that "
                f"wrote all of its outputs.")
    return "No prior run found."


def get_volatility_metrics(current_run_id):
    """
    Compares the current run against the immediate previous run to calculate rank volatility.
    Returns a dictionary of metrics or None if insufficient history.
    """
    if not os.path.exists(DB_PATH):
        return None

    try:
        conn = sqlite3.connect(DB_PATH)

        # 1. Get Run History
        runs_df = pd.read_sql(_RUNS_SQL, conn)
        if len(runs_df) < 2:
            conn.close()
            return {"status": "insufficient_history", "msg": "Need at least 2 runs to calculate volatility."}

        # Current is index 0 (if passed run_id matches), Previous is index 1
        # Verify current_run_id is actually the latest or find it

        # Simple approach: Get data for current_run_id and the one immediately preceding it in time
        current_run_date_row = runs_df[runs_df['run_id'] == current_run_id]
        if current_run_date_row.empty:
            conn.close()
            return None

        current_date = current_run_date_row.iloc[0]['run_date']

        # Find the previous *completed* run (D-C-22)
        prev_run_id, skipped = _previous_completed_run(runs_df, current_date)
        if prev_run_id is None:
            conn.close()
            if skipped:
                logging.warning(
                    "Volatility: %d earlier run(s) skipped with no completion record.",
                    skipped)
            return {"status": "insufficient_history",
                    "msg": _incomplete_history_msg(skipped)}
        if skipped:
            logging.info(
                "Volatility: baseline is run %s; %d more recent run(s) skipped "
                "with no completion record.", prev_run_id, skipped)

        # 2. Get Ranks for Current and Previous — primary query only (D-C-22)
        curr_df = pd.read_sql(_ORGANIC_SQL, conn,
                              params=(current_run_id, PRIMARY_QUERY_LABEL))
        prev_df = pd.read_sql(_ORGANIC_SQL, conn,
                              params=(prev_run_id, PRIMARY_QUERY_LABEL))

        conn.close()

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
            "winners": winners[['keyword_text', 'url', 'rank_curr', 'rank_delta']].to_dict('records'),
            "losers": losers[['keyword_text', 'url', 'rank_curr', 'rank_delta']].to_dict('records')
        }

    except Exception as e:
        logging.error(f"Error calculating volatility: {e}")
        return None


def get_entity_dominance(run_id):
    """
    Aggregates Entity Type and Content Type dominance for the current run.
    """
    if not os.path.exists(DB_PATH):
        return {}

    try:
        conn = sqlite3.connect(DB_PATH)

        # Join serp_results with domain_features and url_features
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
        df = pd.read_sql(query, conn, params=(run_id, PRIMARY_QUERY_LABEL))
        conn.close()

        if df.empty:
            return {}

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
        return {}


def get_rank_deltas(current_run_id):
    """
    Returns a dictionary of {url: rank_delta} for the current run compared to the previous one.
    """
    if not os.path.exists(DB_PATH):
        return {}

    try:
        with sqlite3.connect(DB_PATH) as conn:
            runs_df = pd.read_sql(_RUNS_SQL, conn)

            if len(runs_df) < 2:
                return {}

            # Identify previous run
            current_run_date_row = runs_df[runs_df['run_id'] == current_run_id]
            if current_run_date_row.empty:
                return {}

            current_date = current_run_date_row.iloc[0]['run_date']
            # Previous *completed* run only (D-C-22).
            prev_run_id, skipped = _previous_completed_run(runs_df, current_date)
            if prev_run_id is None:
                if skipped:
                    logging.warning(
                        "Rank deltas: no baseline; %d earlier run(s) have no "
                        "completion record.", skipped)
                return {}

            # Keep keyword + url to avoid collisions when the same URL ranks for
            # multiple keywords, and the primary query only, so a URL ranking in
            # both the root and an alternative query cannot cross-product
            # (D-C-22).
            curr_df = pd.read_sql(_ORGANIC_SQL, conn,
                                  params=(current_run_id, PRIMARY_QUERY_LABEL))
            prev_df = pd.read_sql(_ORGANIC_SQL, conn,
                                  params=(prev_run_id, PRIMARY_QUERY_LABEL))

        if curr_df.empty or prev_df.empty:
            return {}

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
            return {}

        merged['rank_delta'] = merged['rank_prev'] - merged['rank_curr']
        return {
            (row['keyword_text'], row['url']): row['rank_delta']
            for _, row in merged.dropna(subset=['rank_delta']).iterrows()
        }

    except Exception as e:
        logging.error(f"Error getting rank deltas: {e}")
        return {}
