"""
export_history.py
Exports the SQLite database tables to CSV files for external analysis.
"""
import pandas as pd
import os
import logging

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
EXPORT_DIR = "exports"


def export_tables():
    if not os.path.exists(_db_path()):
        print(f"Database {_db_path()} not found.")
        return

    os.makedirs(EXPORT_DIR, exist_ok=True)
    with db_connect.connection(_db_path()) as conn:
        tables = [
            "runs",
            "keywords",
            "serp_results",
            "url_features",
            "domain_features"
        ]

        print(f"Exporting tables to '{EXPORT_DIR}/'...")

        for table in tables:
            try:
                df = pd.read_sql(f"SELECT * FROM {table}", conn)
                if not df.empty:
                    csv_path = os.path.join(EXPORT_DIR, f"{table}.csv")
                    df.to_csv(csv_path, index=False)
                    print(f"  - {table}: {len(df)} rows -> {csv_path}")
                else:
                    print(f"  - {table}: [Empty]")
            except Exception as e:
                print(f"  - {table}: Error exporting ({e})")

    print("Done.")


if __name__ == "__main__":
    load_config()
    export_tables()
