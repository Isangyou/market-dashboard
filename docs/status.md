# 현재 상태 (2026-09-27 일요일 기준)

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
| 장중 배치 | `.github/workflows/intraday.yml` + `scripts/intraday_loop.sh` | cron 08:35 KST → 08:50까지 대기 → 5분 루프. 오전(~12:10)·오후(~15:40) 두 잡. 수동 `mode=loop/once/once-force` |
| 배포 | `.github/workflows/pages.yml` | Actions 배포(deploy-pages). 사람 푸시=push 이벤트, 봇 푸시=워크플로가 `gh workflow run pages.yml` 호출 |
| 화면 | `index.html`, `intraday.html` | 상호 링크. 빈 데이터·부분 누락 상태에서 에러 없음(데스크톱 1440/모바일 390) |
| 엔드포인트 | `docs/endpoints.md` | E1~E23 일별, E24~E28 장중 |

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

## 미검증 (월요일 2026-09-28 첫 거래일에 확인)
1. **장중 워크플로 스케줄 실행**: 08:35 cron 시작(지연 폭) → 08:50 대기 종료 → 5분 루프 → 12:10 오전→오후 잡 전환 → 15:40 종료. 실행 횟수·푸시 횟수(로그 마지막 줄 `루프 종료 … 실행 N회 · 푸시 M회`)
2. **장 시작 전(08:50~09:00) 동작**: API가 전일 데이터를 줄 때 대상일 필터로 버려지는지(파일이 전일 값으로 오염되지 않는지)
3. **실시간 스냅샷**: `snapshots[]`가 5분 간격으로 쌓이는지 (지금까지 실시간 스냅샷 0건 — 백필만 해봄)
4. **Pages 배포(Actions 방식)**: 봇 푸시 → `gh workflow run pages.yml` 호출 → 배포 완료까지 지연. 시간당 16회 수준 배포가 문제없는지
5. **update.yml 장중 15분 실행** + intraday 루프와 같은 브랜치 동시 푸시(rebase·재시도) 충돌 여부
6. **장중 투자자 잠정치 → 일별 확정치 대체**: update.yml이 장중에 E1(당일 잠정) 행을 넣고, 장 마감 후 E3 확정치로 덮는지
7. **휴장일 게이트**: 다음 평일 휴장일(2026-10-05 개천절 대체휴일로 추정, 미확인)에 update.yml 장중 cron이 생략되고 intraday 잡이 skip되는지

## 열린 이슈 / 다음 할 일 후보
- **선물 최종치 누락**: 선물 정규장 15:45 마감. 09-23 외국인 선물 15:40 = +152계약 vs 16:06 최종 = +1,356계약. 수집 창(08:50~15:40) 밖이라 장중 페이지 선물값은 마감 전 잠정. 창을 15:50 이상으로 늘리거나 마감 후 1회 추가 수집 검토
- 장중 파일 크기 약 190KB/일(indent=1) → 연 50MB 수준. 필요 시 indent 제거·gzip·오래된 날짜 정리
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
