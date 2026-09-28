# 현재 상태 (2026-09-28 월요일 14:40 KST 기준)

다음 세션에서 이어가기 위한 요약. 수치는 모두 실제 실행 결과.

## 링크
- 저장소: https://github.com/Isangyou/market-dashboard (public, main)
- 시장 모니터: https://isangyou.github.io/market-dashboard/
- 장중 모니터: https://isangyou.github.io/market-dashboard/intraday.html

## 구성 요약
| 구분 | 파일 | 상태 |
|---|---|---|
| 일별 수집 | `fetch/run.py` (+naver/yf/fred/krx) | 동작 확인. 로컬 py3.9, Actions py3.11 |
| 장중 수집 | `fetch/intraday.py` | 휴장일 skip, `--force` 백필, 증분 페이지 수집 확인. **미국 선물 1분봉**(`us_futures`: NQ=F·CL=F, `fetch/yf.py us_future_1m`) — 3분 루프마다 yfinance 5일치 1분봉을 받아 KST 06:00(전일 미국장 마감, 17:00 ET 서머타임 기준) 이후만 저장, 같은 t는 덮어쓰기. 기준가 = 06:00 이하 마지막 1분봉 종가(정산가 아님). 실패 시 이전 값 + stale. 09-28 16:15 확인: 각 536봉, 약 10분 지연, NQ 30,613.5(기준 30,889.25, -0.89%) · CL 93.99(기준 92.41, +1.71%). `--force`로 지난 날을 채울 땐 받지 않음 |
| 휴장일 판정 | `fetch/market_day.py` | 네이버 market-status `today.isTradingDay`. 실패 시 평일=거래일 |
| 일별 배치 | `.github/workflows/update.yml` | 매시 정각 + 거래일 장중 :15/:30/:45. 푸시 후 pages.yml 호출 |
| 장중 배치 | `.github/workflows/intraday.yml` + `scripts/intraday_loop.sh` + `scripts/intraday_guard.sh` | **장중 루프 시작은 당분간 수동(Actions → intraday → Run workflow, mode=loop), 외부 스케줄러는 추후** (2026-09-28 결정). GitHub cron 보조(08:35~15:35 15분마다)는 유지 — 뜨면 자동 시작 → 08:50까지 대기 → **3분 루프**(수집 timeout 150초, 단계별 로그). 오전(~12:10)·오후(~15:40, 15:40 회차 보장) 두 잡. 중복 판정: 먼저 시작된 실행이 살아 있으면 skip, 10분 넘게 활동 없으면 cancel(→force-cancel) 후 새로 시작. 수동 `mode=loop/once/once-force` |
| 배포 | `.github/workflows/pages.yml` | Actions 배포(deploy-pages). 사람 푸시=push 이벤트, 봇 푸시=워크플로가 `gh workflow run pages.yml` 호출 |
| 화면 | `index.html`(일별·라이트), `intraday.html`(장중·다크) | 상호 링크에 테마 표기. 일별에 VIX 독립 차트(3개월 기본·20일 이평·range slider, 보이는 구간에 y축 맞춤), 유가는 WTI·Brent만(유가 | VIX 한 줄). **ADR 차트 비활성 — 20일 누적 후 활성화 가능**(`index.html` `ADR_ENABLED = true`로 켜면 유가가 한 줄 전체 폭 + VIX | ADR, 3개월·range slider·120·75 연회색 점선, 20거래일 전엔 '누적 중 (n/20일)'). 상단 카드 8개 4×2(모바일 2열): 코스피 외인 · 코스닥 외인 · USD/KRW · VKOSPI / 국고 10Y · 미국채 10Y · WTI · VIX. DXY 카드는 빼고 환율 스파크라인에만 둠(09-29). 메인 차트 아래 **삼성전자 | SK하이닉스**(각각 상하 2패널 x축 공유, 6개월 기본·range slider: 위 종가 + 50일 이평 점선, 아래 50일 이격도 + 100·105·95 연회색 점선(간격 좁으면 100 라벨만), 제목 옆 현재 이격도, 이평·이격도 자체 계산 표기, 범위 바꾸면 두 y축 모두 재조정). 09-23 기준 이격도 삼성전자 112.1 · SK하이닉스 109.9. **코스피·코스닥 이격도 차트는 비활성**(`index.html` `INDEX_GAP_ENABLED = true`로 켜면 그 아래 줄에 추가, 09-23 코스피 105.9 · 코스닥 105.2) — kospi/kosdaq.json 수집은 계속. **VIX | VKOSPI**(유가 한 줄 전체 폭, VKOSPI 원값만 — ND 조항으로 이평선 없음, 아래 'KRED, CC BY-NC-ND 4.0'). 장중 페이지 카드 7개 4+3, VKOSPI 전일 종가 + 직전 60거래일 분위(장중값 아님). 장중 페이지 **자동 갱신**: 장중(08:50~15:50 KST) 60초·그 외 10분마다 `?t=` 붙여 오늘 파일을 다시 받아 내용이 바뀐 경우만 Plotly.react, '갱신 HH:MM:SS' 잠깐 강조, 탭 숨김 시 정지·복귀 시 즉시 1회, `uirevision`(거래일)으로 사용자 확대 유지. 장중 페이지 그리드 = 선물 투자자 | 프로그램 → **나스닥100 선물 | WTI 선물**(1분봉 선, x 06:00~15:45, 전일 마감 기준선·09:00 세로선 연회색 점선, 제목 옆 현재값·전일 마감 대비 %, '지연 시세 · 마지막 봉 HH:MM', 카드 추가 없음) → USD/KRW | 60일 위치. **증시자금동향 행**(유가 | VIX 아래, 3열 카드: 고객예탁금·신용잔고·주식형펀드 기본 + 혼합형·채권형 토글, 최신값·전주대비(7일 전 이하 마지막 값)·기준일·지연 거래일 수(투자자 일별 날짜로 셈), 3개월, 1만억 이상 조, 신용잔고 90일 고점 대비). 빈 데이터·부분 누락 상태에서 에러 없음(데스크톱 1440/모바일 390) |
| 엔드포인트 | `docs/endpoints.md` | E1~E23 일별, E24~E28 장중, E29~E30 등락 종목 수, E31~E32 증시자금동향, E33 VKOSPI(KRED), E34 국내 지수 일별, E35 종목 일별 |
| 종목 일별(이격도용) | `naver.stock_daily`(E35), 종목 목록 `naver.STOCKS` = 삼성전자 005930·SK하이닉스 000660 → `data/series/stock_{코드}.json` (source=naver:stock_trend, 원) | 첫 실행 3페이지(300행, 2025-07-04~), 이후 1페이지. 오늘 행은 15:40 이후만 |
| 코스피·코스닥 일별 | `naver.prices_history`(E34) → `data/series/kospi.json`·`kosdaq.json` (source=naver:index_price) | 첫 실행 5페이지(299행, 2025-07-07~), 이후 매 실행 1페이지. 오늘 행은 15:40 KST 이후만 저장(장중 실시간값 제외), asof=그날 15:30. latest.json items에도 들어가나 상단 카드는 추가 안 함 |
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

## 2026-09-28 (월, 첫 거래일) 상태

### 장중 배치
| 시각(KST) | 일 |
|---|---|
| 08:35 | GitHub cron으로 생성된 intraday 실행 **0건**. cron·UTC 변환·요일·휴장일 판정(`trading: true`) 모두 정상 → GitHub schedule 누락. update-data도 09-26 19:53Z 이후 매시 기대 ~48회 중 6회(29~46분 지연), 이날 08:00~09:00 회차 없음 |
| 09:06 | 수동 `mode=loop`(run 36360908144) → 09:06·09:10·09:15… 5분 간격 정상 |
| 09:19 | 15분 예비 cron 추가·루프 3분 전환 푸시. 이후 09:20·09:35·09:50 예비 회차도 0건 → 외부 스케줄러로 전환 결정 |
| 09:44 | `workflow_dispatch` API(외부 스케줄러가 보낼 요청과 동일) → 204, 중복 판정으로 skip 확인 |
| 12:10~13:50 | **장애**: pm 잡이 루프 단계에서 무응답, 커밋 0건(13:30 수동 once 1회만). cancel 4분+ 무응답 → force-cancel, pm 로그 유실. 원인 미확정(추적 보류) |
| 13:50 | `mode=loop` 재시작(run 36379276217) → 3분 간격 푸시 확인(13:50·13:51·13:54 … 14:36) |
| 14:37 | 새 중복 판정(`scripts/intraday_guard.sh`) Actions 실확인: "마지막 활동 69s 전 → 살아 있음, 건너뜀" |

오늘 반영된 장중 변경 (다음 실행부터 적용 — 지금 도는 pm 잡은 13:50 체크아웃본):
- 루프 5분 → **3분**(수집·커밋·푸시), 15:40 회차 보장. 1회 수집 약 13~15초(요청 간격 1.1초 유지)
- 수집 1회 `timeout 150`(rc=124 경고 후 다음 회차) + 단계별 로그(`[HH:MM:SS] #n fetch 끝 rc=… Ns`, `commit`, `push 성공 (시도 i, Ns)`, `대기 Ns → HH:MM:SS`)
- 중복 판정: 먼저 시작된 실행의 마지막 활동 = max(마지막 장중 커밋, 그 실행 시작, 08:50) 이 **600초 이상**이면 cancel → 60초 무응답이면 force-cancel → 새 실행 진행. 살아 있으면 skip. 조회 실패 시 진행. 가짜 gh로 5개 경우 검증(없음/08:50 대기 중/활동 3분 전/25분 무활동→cancel/무응답→force-cancel). **죽은 실행 취소 경로는 실환경 미확인**
- 시작 트리거: **장중 루프 시작은 당분간 수동(Actions → intraday → Run workflow, mode=loop), 외부 스케줄러는 추후**. GitHub cron(보조, 08:35~15:35 15분마다)은 유지

### 외부 스케줄러 (cron-job.org) 등록값 — **보류(추후 등록)**, 토큰은 사용자가 직접 입력
- 토큰: fine-grained PAT, 저장소 `Isangyou/market-dashboard`만, Repository permissions → **Actions: Read and write** (Metadata read-only 자동)
- 3건: 월~금 **08:35 / 08:50 / 09:05**, 시간대 **Asia/Seoul**
- `POST https://api.github.com/repos/Isangyou/market-dashboard/actions/workflows/intraday.yml/dispatches`
- 헤더: `Accept: application/vnd.github+json`, `Authorization: Bearer <토큰>`, `X-GitHub-Api-Version: 2022-11-28`, `Content-Type: application/json`
- 본문: `{"ref":"main","inputs":{"mode":"loop"}}` → 성공 **204**. 휴장일엔 calendar 잡이 skip
- (선택) update-data 마감 후 보장: 같은 토큰으로 `…/workflows/update.yml/dispatches` 본문 `{"ref":"main"}`, 월~금 15:50·18:05

### 그 밖의 오늘 변경
- ADR: 네이버 등락 종목 수 장 마감 후 누적 시작(과거분 없음 — adrinfo.kr 403 2회), 일별 차트는 비활성(`ADR_ENABLED=false`)
- 증시자금동향 행(2002-05-03~ 6,006일), VKOSPI(KRED, 2010-01-04~ 4,118행, 원값만), 상단 카드 9개

## 09-29 (화) 확인할 점
0. **미국 선물 1분봉**: 3분 루프에서 yfinance 호출(회당 2건) 소요·실패율(단계별 로그 `fetch 끝 … Ns`), 09-28 파일에는 없음(루프 종료 후 추가) → 09-29부터 쌓임. 월요일 외 평일은 기준 봉이 당일 06:00 KST 직전인지
1. **루프 시작(수동)**: 장중 루프 시작은 당분간 수동(Actions → intraday → Run workflow, mode=loop), 외부 스케줄러는 추후. 08:50 전에 실행해도 됨(08:50까지 대기 후 시작). GitHub 보조 cron이 먼저 떴으면 수동 실행은 calendar 로그 `[guard] … 살아 있음, 건너뜀`으로 끝나는 게 정상
2. **08:50 전 시작한 실행의 대기**: 이후 뜬 트리거(보조 cron·수동)가 대기 중인 실행을 죽이지 않는지(guard 로그 "마지막 활동 Ns 전"이 600 미만)
3. **3분 루프 전체**: 오전 약 68회·오후 약 72회, 마지막 15:40:05, 로그 끝 줄 `루프 종료 … 실행 N회 · 푸시 M회`. 단계별 로그로 fetch·push 소요 분포, `rc=124`(timeout) 발생 여부
4. **멈춤 재발 시**: 10분 뒤 다음 트리거(GitHub 보조 cron 또는 수동 실행)가 cancel/force-cancel 후 새로 시작하는지. 보조 cron이 누락되면 자동 복구 안 됨 → 커밋이 10분 넘게 없으면 수동으로 mode=loop 실행
5. **update-data**: 마감 후 1회라도 돌아서 `breadth_*.json`에 09-28·09-29 행이 생기는지, KRED 첫 자동 요청(16:30 이후, `meta.kred_fetches` 1건)으로 vkospi.json에 09-24 이후 값이 붙는지(KRED 당일 반영 시각 미확인)
6. **Pages 배포**: 3분 루프로 시간당 최대 20회 dispatch — pages concurrency로 중간 건 취소·배포 지연
7. **장 시작 전(08:50~09:00)**: 전일 데이터가 대상일 필터로 버려지는지
8. update.yml 장중 투자자 잠정치 → 장 마감 후 E3 확정치로 덮이는지
9. 휴장일 게이트(2026-10-05 추정)에서 외부 트리거·예비 cron이 모두 calendar에서 끝나는지

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
