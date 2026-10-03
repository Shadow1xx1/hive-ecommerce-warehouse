"""Generate deterministic, synthetic CSV inputs and reference outputs.

No third-party packages are required. CSV files intentionally have no header,
matching the Hive TEXTFILE tables in sql/01_create_tables.sql.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


START_DAY = date(2026, 9, 24)
DAYS = 7
DEFAULT_SEED = 20261003
MONEY = Decimal("0.01")
RATE = Decimal("0.0001")


def stamp(day: date, rng: random.Random) -> datetime:
    return datetime.combine(day, datetime.min.time()).replace(
        hour=rng.randint(8, 21), minute=rng.randint(0, 59), second=rng.randint(0, 59)
    )


def fmt_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def write_csv(path: Path, rows: list[tuple], header: tuple[str, ...] | None = None) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        if header:
            writer.writerow(header)
        writer.writerows(rows)


def build_reference(order_rows: list[tuple], event_rows: list[tuple]) -> tuple[list[tuple], list[tuple], dict]:
    # Independent Python reference for checking the SQL result. Rank before
    # quality filtering, so a bad latest version does not revive an old one.
    latest_orders: dict[int, tuple] = {}
    for row in order_rows:
        order_id = int(row[0])
        if order_id <= 0:
            continue
        previous = latest_orders.get(order_id)
        if previous is None or (row[5], int(row[6])) > (previous[5], int(previous[6])):
            latest_orders[order_id] = row

    valid_orders = [
        row for row in latest_orders.values()
        if int(row[1]) > 0
        and Decimal(row[3]) > 0
        and len(row[2]) == 19
        and row[4] in {"paid", "cancelled", "refunded"}
    ]

    latest_events: dict[int, tuple] = {}
    for row in event_rows:
        event_id = int(row[0])
        if event_id <= 0:
            continue
        previous = latest_events.get(event_id)
        if previous is None or int(row[4]) > int(previous[4]):
            latest_events[event_id] = row

    valid_events = [
        row for row in latest_events.values()
        if int(row[1]) > 0 and len(row[2]) == 19
        and row[3] in {"view", "search", "cart"}
    ]

    active_by_day: dict[str, set[int]] = defaultdict(set)
    paid_users_by_day: dict[str, set[int]] = defaultdict(set)
    paid_orders_by_day: dict[str, int] = defaultdict(int)
    gmv_by_day: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))

    for row in valid_events:
        active_by_day[row[2][:10]].add(int(row[1]))
    for row in valid_orders:
        if row[4] == "paid":
            day = row[2][:10]
            paid_users_by_day[day].add(int(row[1]))
            paid_orders_by_day[day] += 1
            gmv_by_day[day] += Decimal(row[3])

    daily_rows: list[tuple] = []
    dashboard_rows: list[tuple] = []
    previous_gmv: Decimal | None = None
    prior_gmvs: list[Decimal] = []
    for day in sorted(active_by_day):
        dau = len(active_by_day[day])
        pay_users = len(paid_users_by_day[day] & active_by_day[day])
        paid_orders = paid_orders_by_day[day]
        gmv = gmv_by_day[day].quantize(MONEY)
        pay_rate = (Decimal(pay_users) / Decimal(dau)).quantize(RATE, rounding=ROUND_HALF_UP)
        daily_rows.append((day, dau, pay_users, paid_orders, f"{gmv:.2f}", f"{pay_rate:.4f}"))

        prior_gmvs.append(gmv)
        gmv_3d = sum(prior_gmvs[-3:], Decimal("0.00"))
        dod = ""
        if previous_gmv is not None and previous_gmv > 0:
            dod_value = ((gmv - previous_gmv) / previous_gmv).quantize(RATE, rounding=ROUND_HALF_UP)
            dod = f"{dod_value:.4f}"
        dashboard_rows.append((day, dau, pay_users, paid_orders, f"{gmv:.2f}", f"{pay_rate:.4f}", f"{gmv_3d:.2f}", dod))
        previous_gmv = gmv

    summary = {
        "raw_order_rows": len(order_rows),
        "distinct_order_ids": len(latest_orders),
        "valid_dwd_orders": len(valid_orders),
        "raw_event_rows": len(event_rows),
        "distinct_event_ids": len(latest_events),
        "valid_dwd_events": len(valid_events),
        "daily_metric_rows": len(daily_rows),
    }
    return daily_rows, dashboard_rows, summary


def generate(seed: int) -> tuple[list[tuple], list[tuple]]:
    rng = random.Random(seed)
    users = list(range(1001, 1301))
    orders: list[tuple] = []
    events: list[tuple] = []
    next_order_id = 50001
    next_event_id = 90001
    order_ingest_seq = 0
    event_ingest_seq = 0

    def add_order(order_id: int, user_id: int, order_time: str, amount: str,
                  status: str, updated_at: str) -> None:
        nonlocal order_ingest_seq
        order_ingest_seq += 1
        orders.append((order_id, user_id, order_time, amount, status, updated_at, order_ingest_seq))

    def add_event(event_id: int, user_id: int, event_time: str, event_type: str) -> None:
        nonlocal event_ingest_seq
        event_ingest_seq += 1
        events.append((event_id, user_id, event_time, event_type, event_ingest_seq))

    for offset in range(DAYS):
        day = START_DAY + timedelta(days=offset)
        active_users = rng.sample(users, rng.randint(145, 185))

        for user_id in active_users:
            for _ in range(rng.randint(1, 4)):
                event_time = fmt_time(stamp(day, rng))
                event_type = rng.choice(("view", "view", "search", "cart"))
                event_id = next_event_id
                next_event_id += 1
                add_event(event_id, user_id, event_time, event_type)
                if rng.random() < 0.025:
                    add_event(event_id, user_id, event_time, event_type)

        for _ in range(rng.randint(90, 120)):
            order_id = next_order_id
            next_order_id += 1
            user_id = rng.choice(active_users)
            order_dt = stamp(day, rng)
            amount = f"{Decimal(rng.randint(1000, 50000)) / 100:.2f}"
            final_status = rng.choices(
                ("paid", "cancelled", "refunded"), weights=(72, 18, 10), k=1
            )[0]
            if rng.random() < 0.25:
                initial_status = "paid" if final_status == "refunded" else "pending"
                add_order(order_id, user_id, fmt_time(order_dt), amount,
                          initial_status, fmt_time(order_dt + timedelta(minutes=1)))
                add_order(order_id, user_id, fmt_time(order_dt), amount,
                          final_status, fmt_time(order_dt + timedelta(minutes=90)))
            else:
                add_order(order_id, user_id, fmt_time(order_dt), amount,
                          final_status, fmt_time(order_dt + timedelta(minutes=2)))

        # Dirty data is intentional: invalid user, amount, and status.
        invalid_time = stamp(day, rng)
        add_order(next_order_id, 0, fmt_time(invalid_time), "19.90", "paid",
                  fmt_time(invalid_time + timedelta(minutes=1)))
        next_order_id += 1
        add_order(next_order_id, rng.choice(active_users), fmt_time(invalid_time),
                  "0.00", "paid", fmt_time(invalid_time + timedelta(minutes=1)))
        next_order_id += 1
        add_order(next_order_id, rng.choice(active_users), fmt_time(invalid_time),
                  "23.40", "unknown", fmt_time(invalid_time + timedelta(minutes=1)))
        next_order_id += 1
        add_event(next_event_id, 0, fmt_time(invalid_time), "view")
        next_event_id += 1
        add_event(next_event_id, rng.choice(active_users), fmt_time(invalid_time), "unknown")
        next_event_id += 1

    return orders, events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    orders, events = generate(args.seed)
    daily, dashboard, summary = build_reference(orders, events)
    write_csv(args.out / "orders_raw.csv", orders)
    write_csv(args.out / "events_raw.csv", events)
    write_csv(args.out / "expected_daily_metrics.csv", daily,
              ("dt", "dau", "pay_users", "paid_orders", "gmv", "pay_rate"))
    write_csv(args.out / "expected_dashboard.csv", dashboard,
              ("dt", "dau", "pay_users", "paid_orders", "gmv", "pay_rate", "gmv_3d", "gmv_dod_rate"))
    manifest = {
        "synthetic": True,
        "seed": args.seed,
        "start_day": START_DAY.isoformat(),
        "days": DAYS,
        **summary,
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
