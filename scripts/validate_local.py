"""Check the pipeline's SELECT logic against reference CSVs using SQLite.

This executes the SELECT portions of the checked-in Hive SQL, not Hive's
partition DDL or INSERT syntax. It is useful before a Hive runtime is available
and must not be described as a Hive end-to-end test.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SQL = ROOT / "sql"


def rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


def insert_selects(path: Path) -> list[tuple[str, str]]:
    content = path.read_text(encoding="utf-8")
    matches = re.findall(
        r"INSERT\s+OVERWRITE\s+TABLE\s+([a-z_][a-z_0-9]*)\s*"
        r"(?:PARTITION\s*\([^)]*\)\s*)?(SELECT\b.*?);",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not matches:
        raise AssertionError(f"No INSERT OVERWRITE ... SELECT found in {path}")
    return matches


def compare_export(conn: sqlite3.Connection, table: str, expected_file: str,
                   columns: tuple[str, ...]) -> None:
    actual = conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY dt").fetchall()
    with (DATA / expected_file).open(newline="", encoding="utf-8") as handle:
        expected = list(csv.DictReader(handle))
    assert len(actual) == len(expected), (table, len(actual), len(expected))

    money_columns = {"gmv", "gmv_3d"}
    rate_columns = {"pay_rate", "gmv_dod_rate"}
    for actual_row, expected_row in zip(actual, expected):
        for name in columns:
            got = actual_row[name]
            want = expected_row[name]
            if want == "":
                assert got is None, (table, actual_row["dt"], name, got, want)
            elif name in money_columns:
                assert abs(Decimal(str(got)) - Decimal(want)) < Decimal("0.005"), (
                    table, actual_row["dt"], name, got, want
                )
            elif name in rate_columns:
                assert abs(Decimal(str(got)) - Decimal(want)) < Decimal("0.000051"), (
                    table, actual_row["dt"], name, got, want
                )
            elif name == "dt":
                assert got == want, (table, name, got, want)
            else:
                assert int(got) == int(want), (table, actual_row["dt"], name, got, want)


def main() -> None:
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE ods_orders_raw (
          order_id INTEGER, user_id INTEGER, order_time TEXT, amount REAL,
          status TEXT, updated_at TEXT, ingest_seq INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE ods_events_raw (
          event_id INTEGER, user_id INTEGER, event_time TEXT,
          event_type TEXT, ingest_seq INTEGER
        )
    """)
    order_rows = rows(DATA / "orders_raw.csv")
    event_rows = rows(DATA / "events_raw.csv")
    assert len(order_rows) == manifest["raw_order_rows"]
    assert len(event_rows) == manifest["raw_event_rows"]

    conn.executemany(
        "INSERT INTO ods_orders_raw VALUES (?, ?, ?, ?, ?, ?, ?)",
        ((int(r[0]), int(r[1]), r[2], float(r[3]), r[4], r[5], int(r[6]))
         for r in order_rows),
    )
    conn.executemany(
        "INSERT INTO ods_events_raw VALUES (?, ?, ?, ?, ?)",
        ((int(r[0]), int(r[1]), r[2], r[3], int(r[4])) for r in event_rows),
    )

    for filename in ("03_build_dwd.sql", "04_build_dws.sql", "05_build_ads.sql"):
        for table, select_sql in insert_selects(SQL / filename):
            conn.execute(f"CREATE TABLE {table} AS {select_sql}")

    for table, count_key in (
        ("dwd_orders", "valid_dwd_orders"),
        ("dwd_events", "valid_dwd_events"),
        ("dws_daily_metrics", "daily_metric_rows"),
        ("ads_daily_dashboard", "daily_metric_rows"),
    ):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count == manifest[count_key], (table, count, manifest[count_key])

    compare_export(
        conn, "dws_daily_metrics", "expected_daily_metrics.csv",
        ("dt", "dau", "pay_users", "paid_orders", "gmv", "pay_rate"),
    )
    compare_export(
        conn, "ads_daily_dashboard", "expected_dashboard.csv",
        ("dt", "dau", "pay_users", "paid_orders", "gmv", "pay_rate",
         "gmv_3d", "gmv_dod_rate"),
    )

    # The anomaly queries in the checked-in Hive SQL should return no rows.
    check_sql = (SQL / "06_quality_checks.sql").read_text(encoding="utf-8")
    statements = [part.strip() for part in check_sql.split(";") if part.strip()]
    anomaly_results: list[int] = []
    for statement in statements:
        statement = re.sub(r"(?m)^\s*--.*$", "", statement).strip()
        if statement.upper().startswith("USE ") or not statement:
            continue
        result = conn.execute(statement).fetchall()
        anomaly_results.append(len(result))
    assert len(anomaly_results) == 7, anomaly_results
    assert anomaly_results[1:6] == [0, 0, 0, 0, 0], anomaly_results
    assert anomaly_results[6] == manifest["daily_metric_rows"], anomaly_results

    print("PASS: checked-in SELECT logic matches independent reference outputs")
    print("PASS: 5 anomaly queries returned zero rows")
    print("PASS: DWD, DWS, and ADS row counts match the data manifest")
    print("NOTE: Hive-specific DDL, INSERT, and partition behavior were not run locally")


if __name__ == "__main__":
    main()
