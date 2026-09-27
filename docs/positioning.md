# 주간 포지셔닝 리포트 (weekly.html)

위클리 노트 [매크로] 섹션용. CTA 수급(모델) · 콜/풋옵션 포지셔닝 · 선물 포지션(COT)을 주 단위로 누적.

## 실행
```bash
cd ~/Documents/dash
.venv/bin/python -m positioning.run                        # 전체 → data/positioning/ 갱신, 결론 마크다운 출력
.venv/bin/python -m positioning.run --only cot             # 일부만 (나머지는 이번 주 기존 값 유지)
.venv/bin/python -m positioning.run --data-dir /tmp/pos    # 저장소 밖에 테스트
gh workflow run positioning-weekly -R Isangyou/market-dashboard   # Actions 수동 실행
```
Actions: `.github/workflows/positioning.yml` — KST 화~토 07:10 (UTC 월~금 22:10). 푸시 후 pages.yml 호출.

## 파일
| 경로 | 내용 |
|---|---|
| `positioning/cta.py` | 추세추종 복제 모델 (yfinance 연속 선물 17종) |
| `positioning/options.py` | CBOE 지연 체인 → P/C, OI 벽, 25Δ 스큐, ATM IV, 딜러 GEX·zero-gamma |
| `positioning/cot.py` | CFTC Socrata API — TFF(금융) · Disaggregated(원자재) |
| `positioning/report.py` | 결론 문장(규칙 기반, 임계값 `THRESH`) · Notion 마크다운 · CTA×COT 교차 |
| `positioning/run.py` | 진입점. 주차 키·확정 판정·실패 섹션 보충·옵션 일별 누적 |
| `data/positioning/weeks/YYYY-MM-DD.json` | 주간 스냅샷 (키 = 미국 기준 그 주 금요일) |
| `data/positioning/options_daily.json` | 옵션 스칼라 지표 일별 누적 (최근 800일) |
| `data/positioning/index.json` | 주차 목록 |

## 주차·확정 규칙
- 실행 시각(KST) −14시간 = 미국 거래일. 그 주 금요일이 파일 키
- `확정` = CTA 기준일이 금요일 && COT 기준일이 그 주 화요일 && 실패 섹션 없음. 아니면 `진행 중`
- 휴일로 COT가 다음 주 월요일 공표 → 월요일 실행이 전주 파일에 COT 반영 후 확정
- 한 소스 실패 시: 이번 주 기존 값 → 없으면 전주 값을 쓰고 `stale`에 기록 (화면 상단 표시)

## 모델·가정 (요약 — 상세는 각 모듈 docstring)
- CTA: 룩백 20/60/125/250일 위험조정 모멘텀 tanh 평균 × 변동성 레버리지(3년 중앙 σ/60일 σ, 상한 1.5). ±100% = 정상 변동성 풀 포지션.
  전환가 = 다음 주말 기준 P_{t+5−L}. 시나리오 = 1주 ±1·2σ 로그 선형 경로 재계산
- 옵션 GEX: 딜러 콜 롱·풋 숏(naive) 가정, BS 감마(r=q=0) 재계산, $/지수 1%. VIX는 GEX 미계산
- COT: 헤드라인 = Leveraged Funds(금융)/Managed Money(원자재). 백분위·z 3년(156주), 주간 σ = 주간 변화/3년 주간 변화 표준편차
- 교차: 롱 크라우딩 = CTA 3년 ≥80p & COT ≥80p, 숏 = 둘 다 ≤20p, 괴리 = 부호 불일치 & |COT z|≥1

## COT 계약 코드 (2026-09 기준)
ES 13874A · NQ 209742 · RTY 239742 · VX 1170E1 · ZT 042601 · ZF 044601 · ZN 043602 · TN 043607 · ZB 020601 · UB 020604 ·
DX 098662 · 6E 099741 · 6J 097741 · 6B 096742 · 6A 232741 · CL 067651 · NG 023651 · GC 088691 · SI 084691 · HG 085692
(실행 로그에 `market_and_exchange_names`가 찍힘 — 이름이 기대와 다르면 코드 교체)

## 1차 실데이터 실행에서 고친 것 (2026-09-27)
- SPX GEX +53.5$bn/1%를 '과대'로 봤으나 **정정: 계산 오류 아님**. 진단 결과(2026-09-25 체인)
  - BS 재계산 감마 ≈ CBOE 제공 감마 (예: 12/18 8000C 7.55e-4 vs 8e-4), CBOE 감마로 계산한 GEX +71.5$bn — 같은 규모
  - 규모 원인 = 전 만기 포함: 12/31 +23.6$bn, 9/30 +7.3$bn, 10/16 +4.4$bn … 공개 툴은 근월물 위주라 작게 나옴
  - 부호·zero-gamma는 공개치와 일치 방향: QuantWheel 9/25 gamma flip 7,721 vs 본 모델 7,687 (현물 7,743, 둘 다 양감마)
  - 반영: 당일 만기 제외(dte≥1), 행사가 ±25%·IV<150%·매도호가 존재만, 35일 이내 GEX 별도 표기, 벽은 순GEX 기준
    (콜·풋 단독 최대로 잡으면 8000 라운드 행사가에 콜·풋 OI가 같이 몰려 둘 다 8000이 됨)
- VIX 스큐 +50vp·ATM IV 115% → VIX 옵션은 선물 기준이라 현물 대비 계산 무의미. VIX는 P/C·OI 벽만
- 교차 확인에서 국채(금리)는 판정 제외 — Lev Funds 숏 = 베이시스 트레이드 비중이 커서 백분위 상승 ≠ 롱 전환

## 미검증 (작성 환경에서 외부 API 접근 불가 → 합성 데이터로 코드 경로만 확인)
1. CBOE JSON에 `data.current_price` 존재 여부 (없으면 풋콜 패리티로 추정 — 로그 spot 값 확인)
2. COT 계약 코드 20개 전부 조회되는지 (특히 VX 1170E1, TN 043607, DX 098662, NG 023651)
3. yfinance `ZT=F` 등 금리 선물·`6A=F` 이력 길이(≥550행 필요)
4. SPX 체인 크기(수 MB) 처리 시간 — Actions 20분 제한 내인지
5. GEX 부호·규모를 외부 공개치(예: SpotGamma·Barchart 등 공개 GEX)와 대략 비교
