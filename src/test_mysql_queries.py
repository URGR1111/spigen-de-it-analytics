"""
sql/mysql/*.sql 을 로컬에서 검증하는 스크립트 (MySQL 서버 없이).
MySQL 문법 → sqlglot으로 SQLite 변환 → 합성 데이터 orders(user_id, order_date, amount)에서 실행.
sqlglot이 변환하지 못하는 TIMESTAMPDIFF(MONTH, a, b)는 같은 계산을 하는 함수로 대체한다.
"""
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import sqlglot

ROOT = Path(__file__).resolve().parents[1]


def month_diff(a, b):
    ya, ma = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    return (yb * 12 + mb) - (ya * 12 + ma)


def to_sqlite(mysql_sql: str) -> list[str]:
    src = mysql_sql.replace("TIMESTAMPDIFF(MONTH,", "_MDIFF(")
    src = re.sub(r"DATE_SUB\((.+?), INTERVAL (\d+) DAY\)", r"DATE_ADD(\1, INTERVAL -\2 DAY)", src)
    stmts = sqlglot.transpile(src, read="mysql", write="sqlite", pretty=True)
    # sqlglot은 CAST(x AS DATE)를 그대로 두는데, SQLite에서는 숫자로 변환되므로 DATE(x)로 바꾼다
    stmts = [s for s in stmts if re.sub(r"/\*.*?\*/", "", s, flags=re.S).strip()]  # 주석만 있는 문장 제외
    return [re.sub(r"CAST\((STRFTIME\([^()]*\([^()]*\)[^()]*\)) AS DATE\)", r"DATE(\1)", s) for s in stmts]


def main():
    con = sqlite3.connect(":memory:")
    con.create_function("_MDIFF", 2, month_diff)
    src = sqlite3.connect(ROOT / "data" / "spigen_synth.db")
    df = pd.read_sql_query("SELECT user_id, DATE(order_ts) AS order_date, net_amount_eur AS amount FROM orders", src)
    df.to_sql("orders", con, index=False)
    print(f"orders: {len(df):,} rows, {df.order_date.min()} ~ {df.order_date.max()}\n")
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    for f in sorted((ROOT / "sql" / "mysql").glob("*.sql")):
        for i, stmt in enumerate(to_sqlite(f.read_text(encoding="utf-8")), 1):
            out = pd.read_sql_query(stmt, con)
            out.to_csv(ROOT / "outputs" / f"mysql_{f.stem}_{i}.csv", index=False)
            print(f"== {f.name} [{i}] → {len(out)} rows")
            print(out.head(int(sys.argv[1]) if len(sys.argv) > 1 else 12).to_string(index=False), "\n")


if __name__ == "__main__":
    main()
