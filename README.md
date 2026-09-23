# Spigen EU 퍼포먼스 마케팅 분석: 독일·이탈리아 수요-예산 미스매치

[![Live Dashboard](https://img.shields.io/badge/Live%20Dashboard-Spigen%20EU%20Case%20Study-4fd1c5?style=flat-square)](https://claude.ai/artifact/TjzqGqNScLv8CtGTe4QWZr)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![Status](https://img.shields.io/badge/status-portfolio%20project-lightgrey?style=flat-square)

> Spigen 글로벌 퍼포먼스 마케팅 신입 인턴 지원 포트폴리오. 공개 실측 데이터로 독일(DE)·이탈리아(IT) 시장을 조사하고, 자체 설계한 합성 고객 데이터(30,000명)로 가설을 직접 계산·검증한 뒤, 실행 가능한 액션플랜까지 제시합니다.
>
> **실측 vs 합성 표기 원칙**: 이 문서와 대시보드의 모든 수치는 🟢 **실측**(공개 데이터에서 직접 수집) 또는 🟣 **합성**(제가 설계한 가상 데이터 분석 결과, 실제 Spigen 내부 데이터 아님)으로 표시합니다. 두 성격을 한 문장에 섞지 않는 것을 전체 작업의 원칙으로 삼았습니다.

**라이브 대시보드**: [Spigen EU Case Study](https://claude.ai/artifact/TjzqGqNScLv8CtGTe4QWZr) — 시장조사 → 원인진단 → 시뮬레이션 검증 → 액션 플래너까지 한 화면에서 인터랙티브하게 확인할 수 있습니다.

---

## 1. 프로젝트 개요 & 비즈니스 문제

Spigen은 유럽 시장 확장을 진행 중이며, 그중 독일(DE)·이탈리아(IT)는 규모와 성장성 면에서 핵심 시장입니다. 이 프로젝트는 "두 시장에 같은 방식으로 마케팅해도 되는가?"라는 질문에서 출발해, 실측 데이터로 두 시장의 실제 차이를 규명하고, 다음 질문으로 좁혔습니다.

> **핵심 비즈니스 문제** — 두 시장의 검색 수요(아이폰 신모델 출시·블랙프라이데이·크리스마스 성수기)는 계절에 따라 크게 출렁이는데, 광고 예산은 연중 거의 균등하게 배분되고 있습니다. **예산이 실제 수요를 따라가지 못해 성수기의 저렴한 획득 기회를 놓치고 있는 것은 아닌가?**

접근 순서는 이렇습니다.

1. **시장 조사(실측)** — 기기 시장·경쟁사·브랜드 검색·광고 라이브러리 5종 공개 데이터로 DE·IT 차이를 확인
2. **문제 정의 & 원인 진단** — 발견한 문제를 Plan·Execute·Check 3단계 MECE 원인으로 분해
3. **시뮬레이션 검증(합성)** — 가설을 말로 남기지 않고, 직접 설계한 30,000명 합성 고객 데이터로 회귀·상관분석·재배분 시뮬레이션 수행
4. **액션 플랜** — 원인별 실행 방안을 담당·기한·우선순위까지 포함한 트래커로 제시

## 2. 데이터 소스 & 규모

### 🟢 실측 데이터 (공개 데이터 5종, 2026-09-23 전후 조회)

| 소스 | 내용 | 활용 |
|---|---|---|
| Statcounter Global Stats | 모바일 기기 벤더 점유율 (12개월 평균) | 시장별 기기 구성 차이 |
| Google Trends | 주간 검색지수, 104주(2년)치 | 계절성, 브랜드 검색 관심도 |
| Meta 광고 라이브러리 | 광고주별 게재 현황, 연령·성별 도달 | 경쟁사 메시징, 타겟 갭 분석 |
| TikTok Commercial Content Library | 시장별 노출 광고 수 | 채널 진입 여부 확인 |
| Amazon.de / Amazon.it | 케이스 카테고리 베스트셀러 순위 | 경쟁 구도, 상위권 브랜드 |

### 🟣 합성 데이터 (`spigen-synthetic-data` 파이프라인, Python, seed=42로 재현 가능)

실제 Spigen 내부 데이터에 접근할 수 없어, 국내 D2C 모바일 액세서리 스토어를 가정한 가상 고객 데이터를 직접 설계·생성했습니다. 계절성(Google Trends 가중)과 기기 구성(Statcounter)만 실측값을 반영하고, 나머지는 `config/taxonomy.py`에 정의한 비즈니스 규칙(VIP 세그먼트, 이탈 패턴, 채널별 품질 차이, A/B 실제 효과)으로 생성됩니다.

| 테이블 | 규모 |
|---|---|
| users | 30,000명 |
| products | 574 SKU |
| orders / order_items | 55K / 96K |
| sessions / events | 403K / 1.9M |
| marketing_spend | 5,800행 (일별 × 채널) |
| ab_assignments | 5,700건 |

상세 스키마와 생성 로직은 [docs/PIPELINE.md](docs/PIPELINE.md)에 정리했습니다.

## 3. 분석 방법 & 기술 스택

| 분석 | 방법 | 사용처 |
|---|---|---|
| 수요-지출 관계 | 선형회귀, 피어슨 상관 (R², 상관계수) | 예산이 수요를 따라가는지 검증 |
| 고객 가치 세그멘테이션 | RFM 스코어링 | 상위 고객군 매출 기여도 |
| 비지도 군집화 | K-Means (실루엣 계수로 k 선택) | 핵심 고객 군집 식별 |
| 리텐션 | 코호트 분석 | 채널별 재구매율 비교 |
| 실험 검증 | A/B 테스트 (t-검정, 카이제곱, 95% CI) | 번들 업셀 기능 출시 여부 판단 |
| 시계열 예측 | Prophet (주간 계절성 분해) | 수요 패턴 구조 확인 |
| 예산 재배분 시뮬레이션 | 탄력성 가정 기반 what-if 모델링, ±50% 상한 제약 | 재배분 효과 정량화 |

**기술 스택**: Python(pandas·numpy·scikit-learn·Prophet·Faker·matplotlib) · SQLite/SQL(집계·RFM·코호트 쿼리) · 바닐라 JS/SVG(인터랙티브 대시보드, 라이브러리 없이 직접 구현한 차트 엔진)

## 4. 핵심 발견 사항

### 🟢 시장 차이 (실측)

- **기기 시장**: 두 시장 모두 Apple이 1위이나, 이탈리아는 중저가 안드로이드(Motorola·Oppo) 비중이 **독일의 4~6배**(안드로이드 전체 65.6% vs 61.2%)
- **경쟁 구도**: Spigen Amazon 최고 순위는 두 시장 공통 **#21** — TORRAS·JETech·ESR이 상위권 점유
- **브랜드 검색**: 이탈리아는 Spigen이 경쟁사 대비 검색 1위(브랜드 인지도 이미 확보), 독일은 Rhinoshield가 신모델 시즌마다 앞섬
- **타겟 갭**: Meta 도달 기준 독일 18–24세는 **0.9%**뿐 — 가장 젊은 층이 크게 소외. 이탈리아는 도달의 **57%가 18–34세**인데도 TikTok 광고는 EU 전체 434건 중 **0건**

### 🟣 수요-예산 미스매치 (합성 데이터로 계산)

- **지출-수요 탄력성**: R²=**0.032**(DE) / **0.001**(IT) — 광고비가 수요와 사실상 무관하게 집행되고 있음을 직접 계산으로 확인
- **배분 격차**: 수요 상위 8주가 연간 수요의 **20~21%**를 차지하는데, 실제 광고비는 이 기간에 **14.8~14.9%**뿐 (격차 DE 5.4%p / IT 6.3%p)
- **놓친 효율**: 수요 최상위 분위(Q5)의 고객획득단가(CAC)가 최하위 분위(Q1) 대비 **DE –36% / IT –45%** 저렴한데도 예산이 몰리지 않음
- **채널 효율 역전**: 지출 비중이 가장 큰 채널(Meta 광고)이 오히려 **가장 낮은 효율** — LTV/CAC 기준 DE는 Google 검색 6.35×(최고) vs Meta 4.24×(최저), IT는 Google 7.70×(최고) vs TikTok 5.27×(최저)
- **리텐션 채널 격차**: 6개월 재구매율이 추천 유입 **40.8%** vs TikTok 유입 **19.4%** — 채널 간 2배 차이
- **고객 가치 집중도**: RFM 상위 5% 고객이 매출의 **36%**, K-Means 핵심 군집이 매출의 **62.8%** 차지
- **A/B 테스트**: 장바구니 번들 업셀 도입 시 사용자당 매출(RPU) **+15.1%**(p=0.0003, 통계적으로 유의) — 전환율 하락은 유의하지 않음(p=0.47)

## 5. 비즈니스 제안 & 예상 임팩트

배분 격차의 원인을 Plan(계획)·Execute(실행)·Check(점검) 3단계 MECE로 분해하고, 단계별 제안을 연결했습니다.

| 원인 | 근거 | 제안 | 담당 | 우선순위 |
|---|---|---|---|---|
| ① Plan 경직성 — 월별 균등 배분이 사전 확정 | R²<0.04, 배분격차 5.4~6.3%p | 수요지수 연동 **주간 동적 예산 편성**으로 전환 | 미디어플래닝팀 | 높음 |
| ② Execute 경직성 — Daily Cap으로 피크 주에도 증액 불가 | DE 최고수요 분위 지출이 오히려 최저(-8.6%) | **수요 임계치 기반 자동 증액 룰** 도입 | 퍼포먼스팀 | 높음 |
| ③ Check 부재 — 주간 효율 리포팅 없음 | 최대 지출 채널이 최저 효율(0.67~0.70배) | **주간 CAC·LTV/CAC 대시보드** + 분기 채널 리밸런싱 | 그로스분석팀 | 중간 |

시장별 차별화 제안도 함께 제시합니다 — 이탈리아는 이미 브랜드 인지도가 높으므로 **전환 중심 메시징 + TikTok 신규 진입**(18–34세 도달 갭 해소), 독일은 Rhinoshield 대응 **인지도 캠페인 강화 + 18–24세 타겟 확대**가 필요합니다.

**예상 임팩트 (🟣 합성 시뮬레이션, 총예산 동일·탄력성 가정 b=0.5·주간 변경폭 ±50% 상한)**

- 수요 연동 재배분만으로 신규 고객 **+1.44%(DE) ~ +1.96%(IT)** 증가 추정
- 번들 업셀 기능은 A/B 테스트로 이미 유의성이 확인되어(RPU +15.1%, p<0.001) **즉시 실행 가능한 항목**으로 별도 분류

## 6. 기술 스택

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Pandas](https://img.shields.io/badge/pandas-150458?style=for-the-badge&logo=pandas&logoColor=white)
![NumPy](https://img.shields.io/badge/NumPy-013243?style=for-the-badge&logo=numpy&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-F7931E?style=for-the-badge&logo=scikit-learn&logoColor=white)
![Prophet](https://img.shields.io/badge/Prophet-0467DF?style=for-the-badge&logo=meta&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)
![Matplotlib](https://img.shields.io/badge/Matplotlib-11557C?style=for-the-badge&logo=plotly&logoColor=white)
![Faker](https://img.shields.io/badge/Faker-synthetic%20data-6E56CF?style=for-the-badge)
![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black)
![SVG](https://img.shields.io/badge/SVG-dashboards-FFB13B?style=for-the-badge&logo=svg&logoColor=white)

---

## 부록: 재현 방법

`data/`는 용량 문제로 저장소에 포함하지 않았습니다. 아래로 재생성합니다(약 1분, seed 고정으로 동일 결과).

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python run_pipeline.py                      # 기본 30,000명
```

```
config/        비즈니스 택소노미 + 숨은 규칙(계절성·세그먼트·이탈·A/B 실제 효과)
src/           데이터 생성 · SQLite 적재 · 분석 실행
sql/           품질 점검 · RFM · 코호트 · A/B · 예산 분석 쿼리 (SQLite + MySQL)
analysis/      A/B · K-Means · Prophet · EDA 분석 스크립트
dashboard/     실측+합성 인터랙티브 대시보드 HTML
docs/          파이프라인 스키마·비즈니스 패턴 상세 문서
```

**한계**: 합성 데이터에서는 광고비가 성과에 인과적으로 영향을 주지 않도록 설계되어 있어, 예산 시뮬레이션의 반응 탄력성(b)은 가정값이며 민감도 범위로 제시합니다. 로그인 고객 세션만 생성하므로 비회원 트래픽을 포함하는 실제 사이트보다 전환율이 높게 나타납니다. 자세한 내용은 [docs/PIPELINE.md](docs/PIPELINE.md)를 참고하세요.
