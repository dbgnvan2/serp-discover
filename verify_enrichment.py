"""
verify_enrichment.py
Checks the SQLite database to verify that enrichment data (URL features, Domain features)
is being correctly populated.
"""
import os
import sys

import yaml

import db_connect
import process_config

def load_config(config_path=None):
    """config.yml, with this process's policies applied (or reset).

    This script opened the database and called no loader at all, so the
    configured database path and the configured SQLite lock wait never
    reached it: setting `database.lock_timeout_seconds: 30` left this one
    waiting 5 with nothing saying so (P5/P25, review chunk Y11's cold review,
    fixed in Y12).
    """
    config_path = process_config.config_path(config_path)
    if not os.path.exists(config_path):
        process_config.apply(None)
        return {}
    with open(config_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    process_config.apply(config)
    return config


def _db_path():
    """The configured database, resolved at call time (review chunk Y12).

    It was the literal `"serp_data.db"`, relative to the current working
    directory: run this script from anywhere but the repo root and SQLite
    created a new empty file beside the caller rather than reporting that the
    database was missing (P4/P16).
    """
    return db_connect.database_path()


def verify_db():
    if not os.path.exists(_db_path()):
        print(f"Error: Database {_db_path()} not found. Run serp_audit.py first.")
        return

    with db_connect.connection(_db_path()) as conn:
        c = conn.cursor()

        print("--- Verifying Database Population ---")

        # 1. Check Runs
        c.execute("SELECT count(*) FROM runs")
        run_count = c.fetchone()[0]
        print(f"Runs found: {run_count}")

        # 2. Check SERP Results
        c.execute("SELECT count(*) FROM serp_results")
        result_count = c.fetchone()[0]
        print(f"SERP Results found: {result_count}")

        # 3. Check Enriched URL Features
        c.execute("SELECT count(*) FROM url_features")
        url_feat_count = c.fetchone()[0]
        print(f"Enriched URLs found: {url_feat_count}")

        if url_feat_count > 0:
            c.execute(
                "SELECT url, content_type, word_count_est FROM url_features LIMIT 3")
            print("\nSample Enriched URLs:")
            for row in c.fetchall():
                print(f"  - {row[0][:50]}... | Type: {row[1]} | Words: {row[2]}")

        # 4. Check Domain Features
        c.execute("SELECT count(*) FROM domain_features")
        print(f"Classified Domains found: {c.fetchone()[0]}")


if __name__ == "__main__":
    load_config()
    verify_db()
