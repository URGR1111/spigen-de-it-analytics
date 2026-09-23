"""
분석 차트 공통 스타일 + Tableau Public 내보내기.

색상: Okabe–Ito 팔레트 (Okabe & Ito, 2008). 적록색맹(1·2형)과 청황색맹(3형)에서도 서로 구분되도록
설계된 8색 팔레트다. 색만으로 구분하지 않도록 선 모양·마커·직접 라벨을 함께 쓴다.
"""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "outputs" / "figures"
TABLEAU = ROOT / "outputs" / "tableau"

# ---------------------------------------------------------------------------
# 색상 (Okabe–Ito)
# ---------------------------------------------------------------------------
OI = dict(black="#000000", orange="#E69F00", sky="#56B4E9", green="#009E73",
          yellow="#F0E442", blue="#0072B2", vermillion="#D55E00", purple="#CC79A7")
COUNTRY = {"DE": OI["blue"], "IT": OI["orange"]}                 # 국가: 파랑 / 주황 (색맹에서도 명도·색상 차이 큼)
VARIANT = {"control": "#999999", "treatment": OI["blue"]}        # 실험군: 회색(기준) / 파랑(처치)
CATEGORICAL = [OI["blue"], OI["orange"], OI["green"], OI["purple"], OI["sky"], OI["vermillion"]]  # 순서 고정
MARKERS = ["o", "s", "^", "D", "v", "P"]                          # 색과 함께 쓰는 보조 구분
DIVERGING = "PuOr_r"                                              # 발산형: 보라↔주황 (빨강–초록 금지)
INK, MUTED, GRID = "#222222", "#6b6b6b", "#e6e6e6"
HIGHLIGHT = OI["vermillion"]                                      # 인사이트 강조색 (시리즈 색과 겹치지 않게 사용)


def setup() -> None:
    """한글 폰트 + 읽기 쉬운 기본값."""
    installed = {f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams.update({
        "font.family": next((f for f in ["Malgun Gothic", "AppleGothic", "NanumGothic"] if f in installed),
                            "DejaVu Sans"),
        "axes.unicode_minus": False,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 10,
        "axes.labelsize": 10, "legend.frameon": False, "legend.fontsize": 9,
        "figure.dpi": 110, "savefig.dpi": 150, "savefig.bbox": "tight",
    })
    FIG.mkdir(parents=True, exist_ok=True)


def headline(fig, title: str, subtitle: str) -> None:
    """그림 전체 제목 = 핵심 결론 한 문장, 부제 = 데이터·기간·지표 정의.
    간격을 인치 단위로 계산해 그림 높이가 달라도 제목과 부제가 겹치지 않게 한다."""
    h = fig.get_figheight()
    fig.suptitle(title, x=0.01, y=1 - 0.08 / h, ha="left", va="top", fontsize=15, fontweight="bold", color=INK)
    fig.text(0.01, 1 - 0.46 / h, subtitle, ha="left", va="top", fontsize=10, color=MUTED)


def finish(fig, path) -> None:
    """제목 영역(약 0.8인치)을 남기고 레이아웃 정리 후 저장."""
    fig.tight_layout(rect=(0, 0, 1, 1 - 0.8 / fig.get_figheight()))
    fig.savefig(path)


def insight(ax, text: str, xy=(0.02, 0.97), ha="left", va="top") -> None:
    """차트 안에 인사이트 문장을 박스로 표시."""
    ax.text(*xy, text, transform=ax.transAxes, ha=ha, va=va, fontsize=9, color=INK, linespacing=1.5,
            bbox=dict(boxstyle="round,pad=0.5", fc="white", ec=HIGHLIGHT, lw=1.1, alpha=0.95), zorder=10)


def eur(x, pos=None) -> str:
    """축 눈금: 1,000 이상은 k 단위 (예: €12k)."""
    return f"€{x / 1000:,.0f}k" if abs(x) >= 1000 else f"€{x:,.0f}"


# ---------------------------------------------------------------------------
# Tableau Public 내보내기
# ---------------------------------------------------------------------------
def _snake(name: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z]+", "_", str(name)).strip("_").lower()
    return name or "col"


def export_tableau(df: pd.DataFrame, name: str, notes: str = "") -> Path:
    """
    Tableau가 읽기 좋은 CSV로 저장한다.
    - 열 이름: 영문 snake_case (한글·공백·기호 열 이름은 Tableau 계산식에서 다루기 불편)
    - 날짜: ISO(YYYY-MM-DD 또는 YYYY-MM-DD HH:MM:SS) → Tableau가 날짜형으로 자동 인식
    - 형식: 긴(long) 형식 권장. 측정값은 숫자형, 범주는 문자열
    - 인코딩: UTF-8 (한글 값 유지)
    ⚠ Tableau Public에 올린 데이터는 누구나 내려받을 수 있다. 이름·이메일 같은 개인정보 열은 넣지 않는다.
    """
    TABLEAU.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = ["_".join(map(str, c)) for c in out.columns]
    out.columns = [_snake(c) for c in out.columns]
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            has_time = (out[c].dropna().dt.normalize() != out[c].dropna()).any()
            out[c] = out[c].dt.strftime("%Y-%m-%d %H:%M:%S" if has_time else "%Y-%m-%d")
        elif pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].round(4)
        elif pd.api.types.is_bool_dtype(out[c]):
            out[c] = out[c].astype(int)
    blocked = {"first_name", "last_name", "email", "postcode", "city"} & set(out.columns)
    assert not blocked, f"개인정보 열은 내보내지 않습니다: {blocked}"
    path = TABLEAU / f"{name}.csv"
    out.to_csv(path, index=False, encoding="utf-8")
    with open(TABLEAU / "_catalog.md", "a", encoding="utf-8") as f:     # 파일 설명 목록 누적
        f.write(f"| {name}.csv | {len(out):,} | {', '.join(out.columns)} | {notes} |\n")
    print(f"  Tableau CSV: {path.name:<32} {len(out):>7,} rows")
    return path


def reset_catalog(script: str) -> None:
    """스크립트 시작 시 해당 스크립트의 카탈로그 행을 지우고 다시 쓴다."""
    TABLEAU.mkdir(parents=True, exist_ok=True)
    cat = TABLEAU / "_catalog.md"
    head = "| 파일 | 행 수 | 열 | 설명 |\n|---|---|---|---|\n"
    lines = cat.read_text(encoding="utf-8").splitlines()[2:] if cat.exists() else []
    keep = [l for l in lines if not l.startswith(f"| {script}_")]
    cat.write_text(head + "".join(l + "\n" for l in keep), encoding="utf-8")
