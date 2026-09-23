# 합성 데이터 파이프라인 기술 문서

`spigen-synthetic-data`가 가상 고객 데이터를 어떻게 생성하고, 어떤 비즈니스 패턴을 심어 두었는지에 대한 상세 문서입니다. 결과 요약과 비즈니스 해석은 루트 [README.md](../README.md)를 참고하세요.

독일·이탈리아에서 운영되는 모바일 액세서리 D2C 스토어를 가정한 **합성(synthetic) 데이터**를 만든다.
그 데이터로 RFM, 리텐션 코호트, A/B 테스트, 수요 기반 광고 예산 배분을 분석한다.

> ⚠️ 모든 주문·고객·행동 데이터는 `config/taxonomy.py`의 가정으로 생성한 가상 데이터이며, 실제 기업 데이터가 아니다.
> 실측값은 두 가지뿐이다: Google Trends 주간 검색지수(계절성)와 Statcounter 기기 점유율(기기 구성).

## 실행

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python run_pipeline.py                      # 기본 30,000명, 약 1분
```

결과: `data/raw/*.csv`, `data/spigen_synth.db`(SQLite), `outputs/*.csv`, `outputs/summary.md`

## 구조

```
config/taxonomy.py        비즈니스 택소노미 + 숨은 규칙(계절성·세그먼트·이탈·A/B 실제 효과)
data_seed/                실측 Google Trends 주간 지수
src/generate.py           데이터 생성 (Faker de_DE / it_IT)
src/load_sqlite.py        CSV → SQLite 적재
sql/01–05_*.sql           품질 점검 · RFM · 코호트 · A/B · 예산 분석
src/analyze.py            SQL 실행, A/B 통계 검정, 예산 재배분 시뮬레이션
run_pipeline.py           전체 실행
analysis/                 A/B·K-Means·Prophet·EDA 분석 스크립트, 공통 스타일(style.py)
sql/mysql/                MySQL 8.0 버전 코호트·RFM·AARRR 쿼리
dashboard/                실측+합성 대시보드 HTML (게시본 링크는 루트 README 참고)
```

## 생성 테이블 (30,000명 기준)

| 테이블 | 행 수(약) | 내용 |
|---|---|---|
| users | 30K | 가입일, 국가, 유입채널, 연령대, 기기, Faker 이름·도시 (이메일은 example.com) |
| products | 574 | 기종 × 케이스 시리즈 × 컬러, 강화유리, 범용 액세서리 |
| orders / order_items | 55K / 96K | 금액·할인코드·배송비·반품·실험군 |
| sessions / events | 403K / 1.9M | session_start → product_view → add_to_cart → begin_checkout → purchase |
| ab_assignments | 5.7K | 장바구니 번들 업셀 실험 노출·배정 |
| marketing_spend | 5.8K | 일별 채널 광고비·노출·클릭 (월 예산 균등 배분) |
| dim_calendar | 1.5K | 일별 국가 수요지수·프로모션 |

## 데이터에 심어 둔 비즈니스 패턴

| 패턴 | 구현 방식 |
|---|---|
| 계절성 | 가입·재구매·방문을 실측 검색지수로 가중 (DE 블랙프라이데이, IT 크리스마스, 아이폰 출시 주) |
| 신모델 업그레이드 구매 | 브랜드별 신기종 출시 시 기존 고객이 확률적으로 기기 교체 → 케이스+강화유리 구매 |
| VIP 클러스터 | 숨은 세그먼트 4종(vip 5%·loyal 15%·regular 40%·one_off 40%): 재구매율, 품목 수, 액세서리 선호, 할인 민감도가 다름 |
| 이탈 | 세그먼트·채널별 지수분포 활동기간, 이탈 후 구매 없는 잔존 방문 |
| 채널 품질 차이 | TikTok 유입은 젊고 1회 구매자 비중·반품률이 높음, 추천·오가닉 유입은 충성도가 높음 |
| A/B 실제 효과 | 번들 제안: 구매 3% 손실, 번들 수락률 34%(첫 7일) → 22%, 번들 주문 반품률 ×1.35 |

숨은 정답은 `data/truth/`에 따로 저장된다. 분석에는 쓰지 않고, 분석 방법이 이 정답을 다시 찾아내는지 검증하는 데만 쓴다.

## 한계

- 합성 데이터에서는 광고비가 성과에 인과적으로 영향을 주지 않는다. 그래서 예산 시뮬레이션의 반응곡선 탄력성(b)은 가정값이며, 결과를 b별 민감도로 제시한다.
- 로그인 고객의 세션만 생성하므로, 비회원 트래픽을 포함한 실제 사이트보다 세션 전환율이 높다.
