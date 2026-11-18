"""
visualize_volatility.py
Visualizes rank history for a specific keyword using matplotlib.
"""
import pandas as pd
import matplotlib.pyplot as plt
import argparse
import sys

import os

import metrics
import storage

DB_PATH = "serp_data.db"

#: The primary SERP's query label. Taken from `metrics` so the two modules
#: cannot disagree about which rows are the rank history.
PRIMARY_QUERY_LABEL = metrics.PRIMARY_QUERY_LABEL


#: The row filter the chart plots, in one place so the keyword list and the
#: chart cannot disagree about what counts as rank history (cold review of
#: chunk Y4: `get_keywords` had no rank clause, so it offered keywords whose
#: only rows sit at 12 and then printed "no data").
PLOTTABLE_ROWS = """
    FROM serp_results s
    JOIN runs r ON s.run_id = r.run_id
    WHERE s.result_type = 'organic'
      AND s.rank <= 10
      AND s.query_label = ?
      AND r.completed_at IS NOT NULL
"""


def _no_database() -> bool:
    """True, with the reason said out loud, when there is no history to read.

    `SerpStorage` creates the file and the whole schema, so opening an absent
    path through `storage.migrated_connection` would answer every query with
    "nothing found" and leave a new empty database behind — "no history yet,
    or the wrong working directory" reported as "this keyword never ranked"
    (P35, cold review of chunk Y6). `metrics.py` has made the same check
    since chunk D1.
    """
    if os.path.exists(DB_PATH):
        return False
    print(f"No history database at {DB_PATH} yet — run the audit once, or "
          f"check the working directory.")
    return True


def get_keywords():
    """The keywords that have a plottable history.

    Restricted to the same rows `plot_history` charts, so the list does not
    offer a keyword whose only rows are a pivot query, an aborted run, or a
    rank below the chart's depth (review chunk Y4).
    """
    if _no_database():
        return []
    with storage.migrated_connection(DB_PATH) as conn:
        df = pd.read_sql("SELECT DISTINCT s.keyword_text" + PLOTTABLE_ROWS,
                         conn, params=(PRIMARY_QUERY_LABEL,))
        excluded = pd.read_sql("""
            SELECT COUNT(*) AS n
            FROM serp_results s
            JOIN runs r ON s.run_id = r.run_id
            WHERE s.result_type = 'organic'
              AND (s.rank > 10 OR s.query_label IS NOT ?
                   OR r.completed_at IS NULL)
        """, conn, params=(PRIMARY_QUERY_LABEL,)).iloc[0]["n"]
    if excluded:
        # P2 — an empty or short menu is not an empty database.
        print(f"  {int(excluded)} stored organic row(s) are not plottable "
              f"rank history (not the primary query, not a completed run, or "
              f"deeper than rank 10) and are not offered.")
    return df['keyword_text'].tolist()


def plot_history(keyword):
    # The same two filters `metrics.py` has applied since chunk D1 (D-C-22):
    # a pivot ("P") or AI-alternative ("S") row carries the same keyword text
    # as the primary SERP but measures a different query, and an aborted run
    # has no complete set of rows. Without them a pivot's rank 1 plotted as if
    # the client had reached rank 1 for the keyword itself (review chunk Y4).
    query = ("SELECT r.run_date, s.rank, s.domain" + PLOTTABLE_ROWS
             + "      AND s.keyword_text = ?\n ORDER BY r.run_date ASC")
    # Each reason is counted on its own. Rows written before the
    # run-completion and query-label migrations carry NULL, which means
    # unknown — not "a pivot" and not "an aborted run" — so naming them as
    # either would be an invented cause (P35, cold review of chunk Y4).
    if _no_database():
        return
    with storage.migrated_connection(DB_PATH) as conn:
        counts = pd.read_sql("""
        SELECT
            COUNT(*) AS stored,
            SUM(CASE WHEN s.rank > 10 THEN 1 ELSE 0 END) AS deep,
            SUM(CASE WHEN s.query_label IS NULL
                       OR r.completed_at IS NULL THEN 1 ELSE 0 END) AS unknown,
            SUM(CASE WHEN s.query_label IS NOT NULL
                      AND s.query_label != ? THEN 1 ELSE 0 END) AS other_query,
            SUM(CASE WHEN s.query_label = ?
                      AND r.completed_at IS NULL THEN 1 ELSE 0 END) AS aborted
        FROM serp_results s
        JOIN runs r ON s.run_id = r.run_id
        WHERE s.keyword_text = ? AND s.result_type = 'organic'
        """, conn, params=(PRIMARY_QUERY_LABEL, PRIMARY_QUERY_LABEL,
                           keyword)).iloc[0]
        df = pd.read_sql(query, conn, params=(PRIMARY_QUERY_LABEL, keyword))

    stored = int(counts["stored"] or 0)
    reasons = []
    for key, text in (("other_query", "measure a different query (a "
                                      "neighbourhood pivot or an AI-likely "
                                      "alternative)"),
                      ("aborted", "belong to a run that did not finish"),
                      ("deep", "sit deeper than rank 10"),
                      ("unknown", "were written before the query-label and "
                                  "run-completion migrations, so which query "
                                  "they measure is unknown")):
        n = int(counts[key] or 0)
        if n:
            reasons.append(f"{n} {text}")
    if reasons:
        # P2 — say what was left out, and why, so a thin chart is not read as
        # a thin history. The reasons can overlap (a deep pivot row counts in
        # both), so they are listed rather than summed.
        print(f"  Of {stored} stored row(s) for '{keyword}', "
              f"{len(df)} are plotted: " + "; ".join(reasons) + ".")

    if df.empty:
        print(f"No primary-query data from a completed run for keyword: "
              f"{keyword}" + (f" ({stored} other row(s) exist)"
                              if stored else ""))
        return

    # Pivot for plotting: Index=Date, Columns=Domain, Values=Rank
    pivot = df.pivot_table(index='run_date', columns='domain', values='rank')

    # Plot
    plt.figure(figsize=(12, 6))

    for column in pivot.columns:
        plt.plot(pivot.index, pivot[column], marker='o', label=column)

    plt.gca().invert_yaxis()  # Rank 1 is at top
    plt.title(f"SERP History: {keyword}")
    plt.ylabel("Rank")
    plt.xlabel("Run Date")
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')

    plt.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()

    filename = f"volatility_{keyword.replace(' ', '_')}.png"
    plt.savefig(filename)
    print(f"Chart saved to {filename}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", help="Keyword to visualize")
    parser.add_argument("--list", action="store_true",
                        help="List available keywords")
    args = parser.parse_args()

    if args.list:
        print("Available Keywords:")
        for k in get_keywords():
            print(f" - {k}")
    elif args.keyword:
        plot_history(args.keyword)
    else:
        print("Please specify --keyword or --list")
