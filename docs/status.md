# 현재 상태 (2026-09-28 월요일 기준)

다음 세션에서 이어가기 위한 요약. 수치는 모두 실제 실행 결과.

## 링크
- 저장소: https://github.com/Isangyou/market-dashboard (public, main)
- 시장 모니터: https://isangyou.github.io/market-dashboard/
- 장중 모니터: https://isangyou.github.io/market-dashboard/intraday.html

## 구성 요약
| 구분 | 파일 | 상태 |
|---|---|---|
| 일별 수집 | `fetch/run.py` (+naver/yf/fred/krx) | 동작 확인. 로컬 py3.9, Actions py3.11 |
| 장중 수집 | `fetch/intraday.py` | 휴장일 skip, `--force` 백필, 증분 페이지 수집 확인 |
| 휴장일 판정 | `fetch/market_day.py` | 네이버 market-status `today.isTradingDay`. 실패 시 평일=거래일 |
| 일별 배치 | `.github/workflows/update.yml` | 매시 정각 + 거래일 장중 :15/:30/:45. 푸시 후 pages.yml 호출 |
| 장중 배치 | `.github/workflows/intraday.yml` + `scripts/intraday_loop.sh` | **시작 트리거 = 외부 스케줄러(cron-job.org → workflow_dispatch API, 08:35/08:50/09:05, 사용자 등록 대기)** + GitHub cron 08:35(+08:50~15:35 15분마다 예비, 보조) → 08:50까지 대기 → **3분 루프**(수집·커밋·푸시, 09-28 오전까지 5분). 오전(~12:10)·오후(~15:40, 15:40 회차 보장) 두 잡. 먼저 시작된 실행이 진행 중이면 새 실행은 calendar 잡에서 dup 판정 후 종료. 수동 `mode=loop/once/once-force` |
| 배포 | `.github/workflows/pages.yml` | Actions 배포(deploy-pages). 사람 푸시=push 이벤트, 봇 푸시=워크플로가 `gh workflow run pages.yml` 호출 |
| 화면 | `index.html`(일별·라이트), `intraday.html`(장중·다크) | 상호 링크에 테마 표기. 일별에 VIX 독립 차트(3개월 기본·20일 이평·range slider, 보이는 구간에 y축 맞춤), 유가는 WTI·Brent만(유가 | VIX 한 줄). **ADR 차트 비활성 — 20일 누적 후 활성화 가능**(`index.html` `ADR_ENABLED = true`로 켜면 유가가 한 줄 전체 폭 + VIX | ADR, 3개월·range slider·120·75 연회색 점선, 20거래일 전엔 '누적 중 (n/20일)'). 상단 카드 9개 3×3(모바일 2열, VKOSPI 추가). **VIX | VKOSPI**(유가 한 줄 전체 폭, VKOSPI 원값만 — ND 조항으로 이평선 없음, 아래 'KRED, CC BY-NC-ND 4.0'). 장중 페이지 카드 7개 4+3, VKOSPI 전일 종가 + 직전 60거래일 분위(장중값 아님). **증시자금동향 행**(유가 | VIX 아래, 3열 카드: 고객예탁금·신용잔고·주식형펀드 기본 + 혼합형·채권형 토글, 최신값·전주대비(7일 전 이하 마지막 값)·기준일·지연 거래일 수(투자자 일별 날짜로 셈), 3개월, 1만억 이상 조, 신용잔고 90일 고점 대비). 빈 데이터·부분 누락 상태에서 에러 없음(데스크톱 1440/모바일 390) |
| 엔드포인트 | `docs/endpoints.md` | E1~E23 일별, E24~E28 장중, E29~E30 등락 종목 수, E31~E32 증시자금동향, E33 VKOSPI(KRED) |
| VKOSPI | `fetch/kred.py`(E33) → `data/series/vkospi.json` (source=kred:KRVKOSPI, 2010-01-04~, 4,118행) | 요청 1회 = 전체 이력. update.yml 안에서 `kred_due`로 하루 ≤2회(16:30 이후 1회 + 당일값 없으면 20:00 이후 1회). 실패 시 카드 stale. 09-28은 로컬 확인 2회로 소진 → Actions 첫 요청은 09-29 16:30 이후 |
| 증시자금동향 | `fetch/naver.py deposit_trend`(E32) → `data/series/deposit.json` (고객예탁금·신용잔고·주식형/혼합형/채권형 펀드, 억원) | 2002-05-03~2026-09-22 6,006일 백필(로컬 1회). update.yml 매 실행 최신 1페이지, `asof`=기준일이라 값이 같으면 파일 안 씀(재실행 0건 변경 확인). 2거래일 지연. 파일 1.26MB(gzip 약 170KB) — 화면이 전체를 읽음 |
| ADR | `fetch/naver.py breadth`(E29) → `data/series/breadth_*.json` → `fetch/run.py adr_from_breadth` → `data/series/adr_*.json` | 네이버는 당일 스냅샷만 → **09-28 장 마감분부터 누적**. 첫 ADR = 20거래일째(약 10-27). **과거분 없음**(adrinfo 403, 아래). **ADR 차트 비활성 — 20일 누적 후 활성화 가능** (수집은 계속) |

## 소스 상태
| 소스 | 상태 |
|---|---|
| 네이버 | 1차. 로컬·Actions(미국 IP) 모두 403/429 없음 |
| yfinance | 폴백 동작. 단 `CNH=X` 이력이 1행뿐 → usdcnh는 매 실행 누적 중(전일대비는 2일치 쌓인 뒤) |
| FRED | `FRED_API_KEY` 없음 → 꺼짐. 키 없는 fredgraph.csv는 봇 차단 |
| pykrx | 기본 비활성(`run.py DEFAULT_DISABLED`). Actions의 새 pykrx가 `KRX_ID/KRX_PW` 환경변수 로그인 요구 메시지를 냄 → Secrets로 되살릴 수 있을지 미검증 |

## 알려진 값 차이 (의도된 것)
### 외국인 현물 순매수: 장중 페이지 vs 일별 페이지
09-23 KOSPI 외국인(9000+9001):

| 시각 | E25 `trend/time` 누적 | 반영 세션 |
|---|---|---|
| 15:30 | -6,844.0억 | 정규장 |
| 15:33 | -5,101.4억 | 장 마감 동시호가(종가 단일가) |
| **15:40** | **-5,101.5억** | ← 장중 페이지 저장 기준(`KEEP_UNTIL`) |
| 16:00 | -5,107.1억 | 시간외 종가 |
| 16:10 | -5,100.8억 | (이전 저장 기준이었음) |
| 18:00 | -4,858.1억 | 시간외 단일가 종료 |
| 20:04 | **-4,942.2억** | 18시 이후 변동 원인 미확인. = E3 일별값 |

- 일별 페이지: E3 `trend/daily`(tradeType=KRX) = **KRX 일별 최종치(정규장+시간외, NXT 제외)** = -4,942.19억
- 장중 페이지: E25 `trend/time`(tradeType=KRX) **~15:40 잠정치(시간외·NXT 제외)** = -5,101.5억
- NXT는 `tradeType=NXT`로 별도(09-23 +568.9억). 두 페이지 모두 미포함. (`tradeType=ALL/UNIFIED`는 500)
- 화면 표기: index.html 카드·메인 차트 부제 "KRX 일별 최종치…", intraday.html 카드 "장중 잠정" 태그+기준 문구, 60일 위치에 "기준 다름" 명시

### 기타
- 미국채 10Y: 카드(E6 현재값 5.165) vs 차트(E9 일별 종가 5.181) — 스냅샷 시각 차
- USD/KRW: naver = 하나은행 고시(1,359.0), yfinance 폴백 = 시장가(1,354.4). 폴백 구간은 점선, 카드 태그 변경

## 2026-09-28 (첫 거래일) 확인 결과
- **intraday 스케줄 미실행**: 08:35 KST(`35 23 * * 0-4` UTC) cron으로 생성된 실행 0건. UTC 변환·cron 문법·요일 모두 정상, 휴장일 판정도 `trading: true`. 실행 자체가 안 만들어졌으므로 게이트 문제도 아님(게이트였다면 skip된 실행이 남음) → **GitHub schedule 누락**
  - 같은 현상이 update-data에도 있음: 09-26 19:53Z 이후 매시 cron 기대 ~48회 중 schedule 실행 6회(지연 29~46분). 09-28 08:00·08:30·08:45·09:00 KST 회차 모두 없음
  - 대응: 하루 1회 트리거 → 15분마다 예비 트리거(KST 08:35~15:35, 29회) + 중복 실행 판정. workflow concurrency는 제거(예비 트리거가 pending으로 쌓였다 15:40 후 빈 실행이 되는 것 방지)
- **수동 실행**: 09:06 KST `workflow_dispatch`(run 36360908144, mode=loop). 스냅샷 09:06 → 09:10 → 09:15 정상 누적, 커밋 3건(`intraday: 2026-09-28 09:06/09:10/09:15 KST`)
- **예비 cron도 누락**: 새 cron 푸시(09:19) 뒤 09:20·09:35·09:50 회차 모두 실행 0건 → GitHub schedule만으로는 시작 보장 불가. 외부 스케줄러로 전환 결정
- **workflow_dispatch API 경로 확인**: `POST /repos/Isangyou/market-dashboard/actions/workflows/intraday.yml/dispatches` `{"ref":"main","inputs":{"mode":"loop"}}` → 204, run 36363289132 생성. calendar 잡이 "먼저 시작된 실행 진행 중(36360908144) → 이번 실행은 건너뜀", am·pm skipped (중복 판정 동작 확인)
- **ADR 과거분(adrinfo.kr)**: 09:5x·10:10 KST 두 번 접속 모두 403 "Blocked due to excessive traffic. Please avoid crawling or frequent access during market hours" → **과거분 포기, 09-28부터 네이버 누적만**. 이 사이트는 다시 호출하지 않음
- **장애: 장중 오후 잡 무응답 (12:10~13:50, 약 100분 공백)**
  - run 36360908144(09:06 수동 loop)의 pm 잡이 12:10:29 루프 단계 진입 후 커밋·푸시 0건. 12:05 → 13:30(아래 once) 사이 장중 데이터 없음
  - 13:30 `mode=once` 1회(run 36377957317)는 같은 코드로 정상(수집 15초, 푸시 1회) → 네이버 403 아님
  - 일반 cancel에 4분 넘게 무응답 → `force-cancel`로 종료. pm 잡 로그는 GitHub에 남지 않음("log not found")
  - 13:50 `mode=loop` 재시작(run 36379276217): 13:50 → 13:51 → 13:54 … 3분 간격 푸시 확인(14:21까지 12회)
  - 원인 미확정 — 추적 보류(사용자 지시). 대응: 루프에 수집 1회 `timeout 150`(초과 시 rc=124 경고 후 다음 회차) + 단계별 로그(fetch 시작/끝·rc·소요, commit, push 시도·소요, 다음 대기). 이 변경은 **다음 실행부터** 적용(지금 도는 pm 잡은 이전 스크립트)
  - 알아둘 점: 먹통 실행이 `in_progress`로 남아 있으면 예비 트리거가 중복 판정으로 모두 건너뜀 → 이번에도 자동 복구 안 됨
- **장중 간격 5분 → 3분** (09-28 커밋 이후). 오늘 오전 잡은 이미 체크아웃한 5분 스크립트로 계속, 12:10 오후 잡부터 3분. 1회 수집 약 13초(요청 간격 1.1초 유지)

## 미검증 (다음 거래일 09-29에 확인)
0-2. **루프 단계별 로그**: 09-29 실행 로그에서 `fetch 끝 rc=… Ns`, `push 성공 (… Ns)` 소요 분포 확인. 멈추면 마지막 단계 로그로 원인 판단
0-1. **KRED 첫 자동 요청**: 09-29 16:30 이후 update-data 실행에서 `meta.kred_fetches`에 1건, vkospi.json에 09-28·09-29가 붙는지. KRED가 당일 값을 몇 시에 올리는지 미확인
0. **ADR 첫 누적**: 09-28 장 마감 후 update-data 실행에서 `breadth_kospi/kosdaq.json`에 09-28 1행이 생기는지(15:30 이전·장중엔 저장 안 함이 정상). update-data schedule도 누락이 심하므로 마감 후~익일 개장 전 사이 1회라도 돌아야 함
1. **예비 트리거 동작**: 08:35/08:50 중 어느 회차가 실제로 떴는지, 이후 예비 회차가 dup으로 끝나는지(calendar 로그 "먼저 시작된 실행 진행 중"), 누락 시 몇 분 늦게 이어받는지
2. **3분 루프**: 오전 약 68회·오후 약 72회, 마지막 회차 15:40:05. 로그 마지막 줄 `루프 종료 … 실행 N회 · 푸시 M회`
3. **장 시작 전(08:50~09:00) 동작**: API가 전일 데이터를 줄 때 대상일 필터로 버려지는지(파일이 전일 값으로 오염되지 않는지)
4. **Pages 배포(Actions 방식)**: 3분 루프로 시간당 최대 20회 호출. pages concurrency로 중간 건 취소되는지·배포 지연
5. **update.yml 장중 15분 실행** — 09-28 schedule 누락 심함(위). intraday 루프와 같은 브랜치 동시 푸시(rebase·재시도) 충돌 여부
6. **장중 투자자 잠정치 → 일별 확정치 대체**: update.yml이 장중에 E1(당일 잠정) 행을 넣고, 장 마감 후 E3 확정치로 덮는지
7. **휴장일 게이트**: 다음 평일 휴장일(2026-10-05 개천절 대체휴일로 추정, 미확인)에 update.yml 장중 cron이 생략되고 intraday 잡이 skip되는지(예비 트리거 29회 모두 calendar 잡만 돌고 끝나야 함)

## 열린 이슈 / 다음 할 일 후보
- 증시자금동향: `totalElements` 6,007 vs 저장 6,006(날짜 중복 1건 추정, 미확인). 카드 차트는 3개월 고정(줌·range slider 없음)
- **ADR 차트 비활성 — 20일 누적 후 활성화 가능** (2026-09-28): `breadth_*.json`이 20행 이상이면 `index.html`의 `ADR_ENABLED = true`로 켜기. 코드(renderAdr·패널 HTML)는 그대로 있음
- **ADR 계산 기준 미확인**: `risingCount`에 상한가 포함 여부, ETF·우선주 포함 여부. 외부 대조 소스 없음(adrinfo 403) → 공개 시황 기사 등의 등락 종목 수와 수기 대조가 필요할 수 있음
- **ADR 누락일**: 마감 후 update-data가 한 번도 안 돈 날은 breadth가 빠지고, ADR 창이 20거래일보다 길어짐(미보정)
- **VKOSPI 해결 (2026-09-28)**: 네이버·KRX 대신 KRED(kred.dev) 재공표 계열 사용(E33). 이전 보류 사유: 네이버 미제공(VKOSPI 코드 빈 배열·409), KRX는 로그인·인증키 필요 (상세는 git 이력의 이 파일 09-27판)
  - 라이선스 CC BY-NC-ND 4.0: 출처 표기함(일별 차트 아래·장중 카드). ND 조항 때문에 일별 차트의 20일 이평선은 제거(09-28), **원값만** 표시. 장중 카드의 60일 분위(파생 수치)는 남아 있음. 공개 저장소에 전체 이력(vkospi.json)을 원형 그대로 재배포 중
- **선물 최종치 누락**: 선물 정규장 15:45 마감. 09-23 외국인 선물 15:40 = +152계약 vs 16:06 최종 = +1,356계약. 수집 창(08:50~15:40) 밖이라 장중 페이지 선물값은 마감 전 잠정. 창을 15:50 이상으로 늘리거나 마감 후 1회 추가 수집 검토
- update-data schedule 누락 대응 후보: 장중엔 intraday 루프가 15분마다 `gh workflow run update-data` 호출 (미적용)
- 장중 파일 크기 약 190KB/일(indent=1) → 연 50MB 수준. 3분 루프로 스냅샷은 늘지만 이력(1분 행)이 대부분이라 크기 변화 작을 것(미확인). 필요 시 indent 제거·gzip·오래된 날짜 정리
- FRED 키 등록(`gh secret set FRED_API_KEY`) 시 미국채 폴백 11개 만기
- pykrx `KRX_ID/KRX_PW` Secrets 검토
- 메인 차트는 CLAUDE.md 사양대로 우축 USD/KRW(이중축) 유지 중

## 자주 쓰는 명령
```bash
cd ~/Documents/dash
.venv/bin/python -m fetch.run                     # 일별 수집 (로컬)
.venv/bin/python -m fetch.intraday --force --data-dir /tmp/x   # 장중 백필 테스트(저장소 밖)
.venv/bin/python -m fetch.market_day              # 거래일 판정
.venv/bin/python -m http.server 8000              # 로컬 확인 http://localhost:8000

export PATH="$HOME/.local/bin:$PATH"              # gh 위치
gh workflow run intraday -R Isangyou/market-dashboard -f mode=once        # 조건 적용 1회
gh workflow run intraday -R Isangyou/market-dashboard -f mode=once-force  # 최근 거래일 백필 1회
gh run list -R Isangyou/market-dashboard -L 10

# 전역 credential.helper 미설정(의도). 로컬 푸시는 명령 단위로 gh 인증 사용:
git -c credential.helper= -c "credential.helper=!$HOME/.local/bin/gh auth git-credential" push
```
