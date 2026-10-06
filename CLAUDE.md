# 시장 모니터 대시보드 (market-dashboard)

## 목적
외국인 수급·금리·환율·유가를 한 화면에 모아 보는 개인 리서치 대시보드.
정적 사이트(GitHub Pages) + GitHub Actions 15분 배치로 운영한다. 서버 없음.

## 폴더 구조
프로젝트 루트 = 이 CLAUDE.md가 있는 폴더(dash). 하위 프로젝트 폴더 없음.
```
./
  CLAUDE.md
  .venv/            # 로컬 가상환경 (playwright, requests, pandas). 커밋 제외
  fetch/
    common.py       # KST 시각·로거·@safe(실패 시 None) 공통 유틸
    naver.py        # stock.naver.com 비공식 JSON API 수집
    yf.py           # yfinance 폴백 (금리·환율·유가·VIX)
    krx.py          # pykrx 폴백 (투자자별 확정치)
    fred.py         # FRED 확정치 (미 국채)
    adrinfo.py      # adrinfo.kr ADR 이력 (HTML 내 배열 정규식, 하루 1회·16:00 이후)
    run.py          # 전체 수집 → data/*.json 갱신 (진입점)
    intraday.py     # 장중 수집 → data/intraday/YYYY-MM-DD.json (평일 08:50~15:40만)
    market_day.py   # 거래일(휴장일) 판정 — update.yml·intraday.yml 공용
  positioning/      # 주간 포지셔닝 리포트 (CTA 모델·CBOE 옵션·CFTC COT) — docs/positioning.md
    cta.py · options.py · cot.py · report.py(근거 수치) · brief.py(결론) · run.py(진입점)
  data/
    latest.json     # 현재값 카드용 (값·전일대비·소스·기준시각)
    series/*.json   # 항목별 시계열 (날짜, 값, 소스)
    intraday/       # 장중 파일(날짜별) + index.json(날짜 목록)
    positioning/    # weeks/YYYY-MM-DD.json(주간, 금요일 키) + options_daily.json + index.json
  docs/
    endpoints.md    # 네이버 API 엔드포인트·파라미터·응답 필드 기록 (장중 E24~E28 포함)
    status.md       # 현재 상태·미검증 항목 (세션 인계용)
    positioning.md  # 주간 포지셔닝: 실행법·모델 가정·확정 규칙·미검증 항목
  scripts/
    intraday_loop.sh  # Actions 장중 루프 (3분 경계마다 intraday.py → 변경 시 커밋·푸시)
  index.html        # 대시보드 화면 (Plotly CDN, 단일 파일)
  intraday.html     # 장중 화면 (index.html과 상호 링크)
  weekly.html       # 주간 포지셔닝 리포트 (라이트, 주차 드롭다운, Notion용 결론 복사)
  technical.html    # 기술적 지표 — 4개 지수 과열/과매도 위치 (쿨 라이트)
  .github/workflows/update.yml    # 매시 + 거래일 장중 15분
  .github/workflows/intraday.yml  # 평일 08:35 시작(+15분마다 예비)→08:50 대기, 오전(~12:10)·오후(~15:40) 두 잡 루프
  .github/workflows/pages.yml     # Pages Actions 배포 (봇 푸시 후 호출됨)
  .github/workflows/positioning.yml  # 주간 포지셔닝: KST 화~토 07:10
  requirements.txt
```

## 주간 포지셔닝 (weekly.html)
- 범위: 미국 지수·VIX·금리·원자재·FX. CTA는 자체 추세추종 모델(실제 포지션 아님을 화면에 명시)
- 결론 = 수치 기반 3블록(positioning/brief.py): (1) 한 줄 요약 — ES CTA 방향·규모·3년 백분위·전주 대비 (2) 변화 포인트 — 전주 대비 기준 단위(`UNIT`) 이상 바뀐 항목만, 전환가 거리·옵션·COT 중 변화 큰 순 최대 3개 (3) 리스크 — 가장 가까운 임계값과 넘으면 기계적으로 바뀌는 것 한 줄. 주차 파일에 `brief` 저장, 다음 주가 그것과 비교해 '변화 없음'을 명시. 해석·가격 전망·목표가 문장 금지. 블록별 근거 수치(report.py)는 접어서
- 차트는 이중축 금지 → 위아래 분리. 상세 규칙·가정은 docs/positioning.md

## 수집 항목
1. 투자자별 순매수 (KOSPI/KOSDAQ): 개인·외국인·기관계·세부기관. 일별 시계열 누적 저장
2. 외국인 순매수·순매도 상위 10종목 (KOSPI/KOSDAQ)
3. 미국 국채수익률 전 만기 (1M~30Y), 한국 국고 3Y/10Y
4. 환율: USD/KRW, USD/JPY, USD/CNH, EUR/USD, DXY
5. WTI, Brent, VIX

## 데이터 소스 우선순위와 폴백
- 1차: stock.naver.com/api/* (비문서화 JSON). 2차: yfinance / pykrx. 3차: FRED·ECOS 확정치
- pykrx는 KRX 로그인 요구로 현재 기본 비활성 (`fetch/run.py` DEFAULT_DISABLED, `--enable pykrx`로 켬). 투자자 순매수·상위종목은 naver 단일 소스
- 소스마다 값이 조금 다를 수 있다. 값을 섞지 말고, 각 레코드에 `source`와 `asof`(기준시각, KST ISO8601)를 항상 함께 저장한다
- 한 소스가 실패해도 화면이 깨지지 않아야 한다. 실패 항목은 이전 값 유지 + `stale: true` 표시

## 네이버 API 규칙
- HTML 파싱 금지. 화면이 호출하는 JSON 엔드포인트만 사용
- 엔드포인트 발견은 Playwright로 Network 요청을 캡처해서 docs/endpoints.md에 기록한 뒤, 실제 수집은 requests만 사용
- 요청 간격 1초 이상, User-Agent 일반 브라우저 값, 403/429 응답 시 즉시 중단하고 폴백으로 전환
- 각 수집 함수는 pandas DataFrame 반환, 실패 시 예외 대신 None 반환하고 로그 남김

## 기술적 지표 (technical.html)
- 목적: 네 지수의 과열/과매도 위치만 보는 화면. S&P500(^GSPC)·나스닥 종합(^IXIC)은 yfinance 일봉(`fetch/yf.py index_daily` → `data/series/spx.json`·`ixic.json`, 첫 수집 1년, 미국장 마감 16:20 ET 전 오늘 봉 제외), 코스피·코스닥은 기존 네이버 일봉(`kospi.json`·`kosdaq.json`) 재사용. update.yml 일별 배치(run.py)에 포함
- 지수별 3단 패널(x축 공유, 6개월 기본, range slider): 종가 + 50일 이평 점선 / 50일 이격도 + 110·90 / RSI(20, Wilder) + 70·30. 이격도·RSI 패널의 가로선은 이 참고선 두 줄씩만(연한 회색 점선, 격자선·중심선 없음, 네 지수 동일). 지표는 화면에서 자체 계산
- 배치 2×2(S&P500 | 나스닥 종합 / 코스피 | 코스닥), 제목 옆 현재 이격도·RSI, 상단 요약 카드 4개(지수·등락률·이격도·RSI·기준일 — 미국/한국 장 마감 기준일이 다름)

## 화면 (index.html)
- 단일 HTML 파일. Plotly CDN. 빌드 도구 없음. data/*.json을 fetch로 읽음
- 레이아웃: 상단 카드 8개 → 메인 차트(외국인 일별 순매수 막대 + 20일 누적선, 우축 USD/KRW, 3개월 기본, range slider) → 2열 그리드(미국채 커브 오늘/1주전/1개월전, 10y·2y+2s10s, 국고 3y·10y, 환율 스파크라인 2×2, 유가 WTI·Brent, VIX+20일 이평(3개월 기본, range slider)) → 외국인 상위 종목 테이블 좌우
- 모든 값 옆에 소스·기준시각을 작은 회색 글씨로 표시
- 디자인: 모노톤, 페이지별 테마 구분 — **일별(index.html)=쿨 라이트(슬레이트 블루), 장중(intraday.html)=웜 라이트(세이지 그린)**. 주간(weekly.html)·기술적(technical.html)은 일별과 같은 쿨 라이트
  - 쿨 라이트(일별·주간): 배경 흰색~아주 밝은 회색, 글자 짙은 회색, 카드는 흰 배경+얇은 회색 테두리, 격자선 연한 회색, 소스·기준시각은 중간 회색. 포인트 색 슬레이트 블루(#7b93c4) 한 가지
  - 웜 라이트(장중): 배경 #f7f5f0, 카드 흰색+베이지 테두리 #e6e0d4, 격자선 #ebe6dc, 글자 #2f2b26, 소스·기준시각 #8a8378, 링크 글자 #3f6b4e. 포인트 색 세이지 그린(#5f8f6e) 한 가지(차트 선·막대·현재값 강조)
  - 페이지마다 포인트 색은 위의 한 가지만, 보조선은 회색 계열. 그 외 보라·빨강 등 포인트 사용 금지. 상승/하락 구분은 색이 아니라 부호와 화살표로
  - 상단 상호 링크는 "일별 · 라이트(블루) / 장중 · 라이트(그린) / 주간 포지셔닝 · 라이트(블루) / 기술적 · 라이트(블루)"로 테마를 함께 표기
- 모바일 폭에서도 깨지지 않게 (카드 2열, 차트 1열)

## 배치 (GitHub Actions)
- 15분 간격, 한국 장중(평일 08:30~16:00 KST)은 매 15분, 그 외 시간은 1시간 간격. 휴장일은 fetch/market_day.py로 판정해 매시 정각만 실행
- 장중 페이지용 intraday.yml: 평일 08:50 KST 시작, 3분 간격 루프(수집·커밋·푸시), 휴장일이면 잡 생략. cron 누락 대비 15분마다 예비 트리거 + 중복 실행 판정. 로컬(launchd) 실행은 쓰지 않음
- run.py 실행 후 data/ 변경분만 커밋·푸시. 변경 없으면 커밋하지 않음
- API 키(FRED 등)는 GitHub Secrets. 코드에 하드코딩 금지

## 작업 원칙
- 한 번에 한 단계씩: (1) 엔드포인트 확보 → (2) fetch 모듈 + 로컬 실행 검증 → (3) index.html → (4) Actions
- 각 단계 끝나면 실제로 실행해서 결과 파일을 보여주고 다음 단계로 넘어가기 전에 확인받기
- 검증 없이 "됐다"고 하지 말 것. 수치는 실제 출력값으로 보고
- 설명은 짧게, 결과와 수치 위주로
