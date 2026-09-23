"""CSV → SQLite 적재. 분석용 인덱스를 함께 만든다."""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

TABLES = ["products", "users", "orders", "order_items", "sessions", "events",
          "ab_assignments", "marketing_spend", "dim_calendar"]
INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_orders_user ON orders(user_id, order_ts)",
    "CREATE INDEX IF NOT EXISTS ix_orders_ts ON orders(order_ts)",
    "CREATE INDEX IF NOT EXISTS ix_items_order ON order_items(order_id)",
    "CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id, session_start_ts)",
    "CREATE INDEX IF NOT EXISTS ix_events_session ON events(session_id)",
    "CREATE INDEX IF NOT EXISTS ix_events_name_ts ON events(event_name, event_ts)",
    "CREATE INDEX IF NOT EXISTS ix_events_order ON events(order_id)",
    "CREATE INDEX IF NOT EXISTS ix_orders_id ON orders(order_id)",
    "CREATE INDEX IF NOT EXISTS ix_users_id ON users(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_truth_user ON _truth_users(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_ab_user ON ab_assignments(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_cal ON dim_calendar(date, country)",
    "CREATE INDEX IF NOT EXISTS ix_spend ON marketing_spend(date, country)",
]


def load(data_dir: Path, db_path: Path, with_truth: bool = True) -> None:
    t0 = time.time()
    db_path.unlink(missing_ok=True)
    con = sqlite3.connect(db_path)
    for name in TABLES:
        df = pd.read_csv(data_dir / "raw" / f"{name}.csv", low_memory=False)
        df.to_sql(name, con, index=False, chunksize=50_000)
        print(f"  loaded {name:<16} {len(df):>9,}")
    if with_truth:  # 검증 전용 테이블: 이름 앞의 밑줄로 분석 테이블과 구분
        pd.read_csv(data_dir / "truth" / "truth_users.csv").to_sql("_truth_users", con, index=False)
    for stmt in INDEXES:
        con.execute(stmt)
    con.commit()
    con.close()
    print(f"  sqlite ready in {time.time() - t0:.1f}s → {db_path}")


if __name__ == "__main__":
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data"
    load(data, data / "spigen_synth.db")
