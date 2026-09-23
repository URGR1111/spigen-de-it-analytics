"""
전체 파이프라인: 데이터 생성 → CSV 저장 → SQLite 적재 → SQL 분석·통계 → outputs/summary.md

  python run_pipeline.py                 # 기본 30,000명
  python run_pipeline.py --users 60000   # 규모 확대 (A/B 검정력 ↑)
"""
import argparse
import time
from pathlib import Path

from config import taxonomy as T
from src.analyze import analyze
from src.generate import generate
from src.load_sqlite import load

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=30_000)
    ap.add_argument("--seed", type=int, default=T.SEED)
    a = ap.parse_args()
    data = ROOT / "data"
    t0 = time.time()
    print("[1/3] 데이터 생성")
    generate(a.users, a.seed, data)
    print("[2/3] SQLite 적재")
    load(data, data / "spigen_synth.db")
    print("[3/3] 분석")
    analyze(data, ROOT / "outputs")
    print(f"\n완료 ({time.time() - t0:.0f}s). 결과: outputs/summary.md")
