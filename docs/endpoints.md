# stock.naver.com 비공식 JSON API 엔드포인트

- 캡처: 2026-09-26 (토), Playwright(Chromium headless)로 페이지 Network XHR/fetch 캡처
- 검증: 같은 날 `requests`로 1회씩 호출, 전부 `200 application/json` (아래 "검증 결과")
- Base: `https://stock.naver.com/api`
- 공통 헤더: `User-Agent`(일반 브라우저), `Referer: https://stock.naver.com/`. 쿠키·인증 불필요
- 숫자는 대부분 **문자열**로 옴 → 수집 시 float/int 변환 필요
- 캡처 시점 기준 국내 최종 거래일은 2026-09-23 (09-24~26 추석 휴장)

## 캡처한 화면

| 화면 | URL | 누른 탭 |
|---|---|---|
| 투자자별 매매동향 | `/market/stock/kr/trend/trader?tradeType=0&marketType=kospi` | 코스피/코스닥 × 1일/1주/1개월/3개월, 시간별/일자별 |
| 외국인 매매 상위 | `/market/stock/kr/trend/foreigner?tradeType=0&marketType=kospi&periodType=segment-1day` | 코스피/코스닥 × 1일/1주/1개월/3개월 |
| 국채수익률 | `/market/marketindex/bondAndInterest/bond` | 미국/한국/유로/영국/일본/중국/독일 |
| 환율 | `/market/marketindex/exchangeRate`, `/exchangeRate/exchange`, `/exchangeRate/exchangeWorld` | 환전고시/국제시장 |
| 상세(추가) | `/marketindex/exchange/FX_USDKRW`, `/marketindex/bond/US10YT=RR`, `/marketindex/exchangeWorld/USDJPY`, `/marketindex/exchange/.DXY`, `/marketindex/energy/CLcv1`, `LCOcv1`, `/worldstock/index/.VIX` | 기간 탭 |

---

## 1. 투자자별 순매수

### 투자자 코드 (`investorGubun`) — 화면 표와 대조해 확인

| 코드 | 투자자 | 화면 표시 |
|---|---|---|
| 8000 | 개인 | 개인 |
| 9000 | 외국인 | 외국인 = 9000 + 9001 |
| 9001 | 기타외국인 | 〃 |
| 1000 | 금융투자 | 기관계 = 1000~7000 합 |
| 2000 | 보험 | |
| 3000 | 투신 | 투신(사모) = 3000 + 3100 |
| 3100 | 사모 | 〃 |
| 4000 | 은행 | |
| 5000 | 기타금융 | |
| 6000 | 연기금등 | |
| 7000 | 국가·지자체 (추정, 캡처 시 0) | 기관계에 포함 |
| 7100 | 기타법인 | 기타법인 |

대조 예 (KOSPI 2026-09-23): 외국인 -490,428 + -3,791 = -494,219백만 → 화면 "-4,942억" ✓, 기관계 합 318,861백만 → "3,189억" ✓. 12개 코드 합계 = 0.

`netAmounts[]` 항목 필드 (원 단위, 문자열):
```json
{"investorGubun":"9000","diffValue":"-490428000000","sellQuant":"73296544","sellPrice":"8113438000000","buyQuant":"61598650","buyPrice":"7623010000000"}
```
`diffValue`=순매수 금액(원), `buyPrice`/`sellPrice`=매수/매도 금액(원), `*Quant`=수량(주)

### E1. 당일 누적 (1일 탭 차트)
`GET /domestic/market/trend/chart/time`

| 파라미터 | 값 |
|---|---|
| tradeType | `KRX` |
| marketType | `KOSPI` \| `KOSDAQ` |
| selectedRange | `1일` (URL 인코딩) |
| bizdate, startDate, endDate | `YYYYMMDD` (오늘 날짜. 휴장일이면 직전 거래일 데이터 반환) |

응답: `{"bizdate":"20260923","time":"214537","netAmounts":[...12개]}`

### E2. 기간 합계 (1주/1개월/3개월 탭 차트)
`GET /domestic/market/trend/chart/daily` — E1과 파라미터 동일, `selectedRange`=`1주`|`1개월`|`3개월`, `startDate`=기간 시작
응답: `{"bizdate":"20260917~20260923","time":"","netAmounts":[...]}` — 기간 **합계 1건**만 옴 (일별 아님)

### E3. 일자별 시계열 ★ 메인 차트용
`GET /domestic/market/trend/daily`

| 파라미터 | 값 |
|---|---|
| tradeType | `KRX` |
| marketType | `KOSPI` \| `KOSDAQ` |
| bizdate | `YYYYMMDD` |
| startIdx | **페이지 번호** (0부터). offset = startIdx × pageSize |
| pageSize | 30(화면 기본), 100 동작 확인, 500은 거부 |

응답 (Spring Page 형식):
```json
{"content":[{"bizdate":"20260923","time":"","netAmounts":[...]} , ...],
 "totalElements":"5361","totalPages":"179","last":false,"first":true, ...}
```
최신일부터 내림차순. 총 5,361 거래일 이력.

### E4. 시간별 (당일 장중 스냅샷)
`GET /domestic/market/trend/time` — E3과 파라미터 동일. `content[].time`=`HHMMSS`

---

## 2. 외국인 순매수·순매도 상위 종목

### E5. `GET /domestic/market/trend/trendForeignOrg`

| 파라미터 | 값 |
|---|---|
| investorType | `FOREIGNER` |
| tradeType | `KRX` |
| marketType | `KOSPI` \| `KOSDAQ` |
| periodType | `DAY` \| `WEEK` \| `MONTH` \| `THREE_MONTH` |
| startIdx, pageSize | `0`, `20`(화면) / 10 동작 확인 |

응답:
```json
{"sections":{"buyRankList":[...],"sellRankList":[...]}}
```
항목 예:
```json
{"itemcode":"005930","itemname":"삼성전자","bizdateFrom":"20260923","bizdateTo":"20260923",
 "accTradeVolume":"4513767","accTradeAmount":"1283305594000","dailyTradeVolume":"19385053",
 "nowPrice":"286500","prevChangeRate":"3.62","prevChangePrice":"10000","type":"ST",
 "estimated":false,"toRankingAt":"2026-09-23T00:00:00+09:00"}
```
`accTradeAmount`=외국인 순매수 금액(원, 매도 리스트는 음수), `accTradeVolume`=순매수 수량, `estimated`=장중 잠정치 여부

---

## 3. 국채 수익률

### E6. 국가별 전 만기 ★ 커브용
`GET /securityService/marketindex/bond/nation/{NATION}?sortType=maturityDesc`

NATION: `USA`(12개: 1M,2M,3M,6M,1Y,2Y,3Y,5Y,7Y,10Y,20Y,30Y), `KOR`(9개: 1Y~50Y), `EUZ`, `GBR`, `JPN`, `CHN`, `DEU`

항목 주요 필드:
```json
{"reutersCode":"US30YT=RR","name":"미국 국채 30년","localTradedAt":"2026-09-25T17:05:00-04:00",
 "closePrice":"5.4900","fluctuations":"0.0285","fluctuationsRatio":"0.52",
 "fluctuationsType":{"code":"2","name":"RISING"},"marketStatus":"CLOSE","priceDataType":"REALTIME",
 "delayTimeName":"실시간","statementSource":"레피니티브 기준","openPrice":5.478,"highPrice":5.532,"lowPrice":5.452}
```
코드 규칙: `{US|KR}{n}{M|Y}T=RR`. 일본은 `delayTimeName:"2시간 지연"`.

### E7. 개별 채권 상세
`GET /securityService/economic/bond/{reutersCode}` (예: `US10YT=RR`)
필드: `closePriceYield`, `yieldChange`, `yieldChangePercent`, `open/high/lowPriceYield`, `high/lowPriceYieldOf52weeks`, `maturityDate`, `localDate`

### E8. 일별 시세 (페이지)
`GET /securityService/marketindex/bond/{reutersCode(URL인코딩 %3D)}/prices?page=1&pageSize=60`
응답: 배열 `[{"localTradedAt","closePrice","fluctuations","fluctuationsRatio","openPrice","highPrice","lowPrice"}]` 최신순. pageSize=60 동작 확인

### E9. 차트 시계열 ★ 1주전/1개월전 커브, 10y·2y 시계열용
`GET /securityService/chart/foreign/governmentBond/{reutersCode(%3D)}?periodType={day|month}&range={n}`
- 화면 탭: 1일=`day&range=1`, 1개월=`month&range=1`, 3개월=`month&range=3`, 1년=`month&range=12`
- 응답: `{"code","infoType":"governmentBond","periodType","priceInfos":[{"localDate":"20260625","closePrice":4.392,"openPrice","highPrice","lowPrice"}]}` 오래된순, 숫자형
- 한국물(KR3YT=RR)도 같은 경로로 동작 확인

⚠ 같은 US10Y인데 E6/E7 = 5.165, E8/E9 최신 = 5.181 (2026-09-25). 엔드포인트별 스냅샷 시각 차이로 추정 → 레코드마다 source·asof 분리 저장

---

## 4. 환율

### E10. 환전고시 전체 (하나은행)
`GET /stockSecurity/exchange-rates/v2/latest`
`{"items":[{"currencyCode":"USD","marketIndexCode":"FX_USDKRW","saleBaseRate":"1359.00","changePrice":"3.50","changeRate":"0.26","date":"2026-09-23","round":"6255","announcedAt":"2026-09-26T05:45:27+09:00", ...}]}` 57개 통화

### E11. USD/KRW 최신 + 일중 고저
`GET /stockSecurity/exchange-rates/v2/market-index/FX_USDKRW/latest`
E10 필드 + `openingPrice`, `highPriceOfDay`, `lowPriceOfDay`, `high/lowPriceOf52Weeks`

### E12. 통화별 일별 (커서 페이지)
`GET /stockSecurity/exchange-rates/v2/{CUR}/daily?bankType=hana&size=20` → `{"hasNext","items":[...E10 형식],"cursor":"MjAyNjA4Mjc"}` (다음 페이지는 cursor, 파라미터명 미확인)

### E13. 통화별 차트 ★ USD/KRW 우축용
`GET /stockSecurity/exchange-rates/v2/{CUR}/charts/{month|year}?bankType=hana&range={n}`
- 3개월=`month&range=3`, 1년=`year&range=1`
- `{"startDate","endDate","highPrice","lowPrice","priceInfos":[{"localDate":"20260623","closingPrice":"1533.50","highPrice","lowPrice"}]}`

### E14. 당일 회차별 고시
`GET /stockSecurity/exchange-rates/v2/{CUR}/charts/round?bankType=hana` — 응답 650KB(6,255회차). 대시보드에선 불필요

### E15. 국제시장 환율 전체 (레피니티브)
`GET /securityService/marketindex/exchangeWorld` — 113개. `reutersCode`=`EURUSD`,`USDJPY`,`USDCNY` 등. 필드는 E6과 동일 계열(`closePrice`,`fluctuations`,`localTradedAt`,`priceDataType:"CLOSING_PRICE"`)
- ⚠ **USD/CNH 없음** (USDCNY만 존재, `/exchangeWorld/USDCNH` 상세 페이지는 홈으로 리다이렉트) → CNH는 yfinance `CNH=X` 폴백 필요

### E16. 주요 환율 (DXY 포함)
`GET /securityService/marketindex/majors/exchange` → `.DXY`, `FX_USDKRW`, `FX_EURKRW`, `FX_JPYKRW`, `FX_CNYKRW` 5개. DXY는 ICE 10분 지연

### E17/E18. 개별 일별 시세
- `GET /securityService/marketindex/exchange/.DXY/prices?page=1&pageSize=60`
- `GET /securityService/marketindex/exchangeWorld/{USDJPY|EURUSD|USDCNY}/prices?page=1&pageSize=20`
응답 형식은 E8과 동일

---

## 5. 유가·VIX (CLAUDE.md 수집 항목 5, 상세 페이지에서 추가 캡처)

- E19 `GET /securityService/marketindex/energy` — 13개, `CLcv1`(WTI), `LCOcv1`(Brent). NYMEX 10분 지연
- E20 `GET /securityService/marketindex/energy/{CLcv1|LCOcv1}/prices?page=1&pageSize=20` — E8 형식
- E21 `GET /securityService/index/.VIX/basic` — `closePrice`, `compareToPreviousClosePrice`, `fluctuationsRatio`, `localTradedAt` (15분 지연)
- E22 `GET /securityService/index/.VIX/price?page=1&pageSize=20` — 일별, 필드명 `compareToPreviousClosePrice`
- E23 `GET /securityService/integration/indicators?indicatorCodes=FX_USDKRW,CLcv1,.VIX,US10YT=RR` — 여러 지표 현재값 한 번에 (`currentPrice`, `fluctuations`, `localTradedAt`). 카드용으로 유용

---

## 검증 결과 (requests, 2026-09-26, 간격 1.1초)

| # | 엔드포인트 | 상태 | 확인값 |
|---|---|---|---|
| E1 | trend/chart/time KOSPI | 200 | 20260923 외국인 -4,942억 / 개인 -14,649억 / 기관계 3,189억 |
| E2 | trend/chart/daily KOSDAQ 1주 | 200 | 0917~0923 외국인 -2,843억 / 개인 3,151억 / 기관계 -457억 |
| E3 | trend/daily KOSPI | 200 | 30행, total 5,361, 0923~0812 |
| E3 | 〃 startIdx=1,pageSize=100 | 200 | 100행, 20260428~20251201 (offset=100) |
| E4 | trend/time KOSDAQ | 200 | 30행, 최신 0923 20:04:00 |
| E5 | trendForeignOrg KOSPI DAY | 200 | 매수1 삼성전자 12,833억 / 매도1 SK하이닉스 -11,797억, n=10 |
| E5 | 〃 KOSDAQ THREE_MONTH | 200 | 매수1 실리콘투 (0630~0923) |
| E6 | bond/nation/USA | 200 | 1M 3.969, 3M 4.178, 6M 4.362, 1Y 4.478, 2Y 4.860, 5Y 4.993, 10Y 5.165, 30Y 5.490 |
| E6 | bond/nation/KOR | 200 | 3Y 3.998, 10Y 4.409 (asof 09-23 18:46 KST) |
| E7 | economic/bond/US2YT=RR | 200 | 4.86, -0.0351 |
| E8 | bond/KR10YT=RR/prices 60 | 200 | 60행, 0923=4.409 ~ 0630=4.100 |
| E9 | governmentBond US10Y month 3 | 200 | 63행, 0625=4.392 ~ 0925=5.181 |
| E9 | governmentBond KR3Y month 12 | 200 | 241행, 0923=3.998 |
| E10 | exchange-rates/v2/latest | 200 | USD 1,359.00, 57개 통화 |
| E11 | FX_USDKRW/latest | 200 | 1,359.00 (+3.50) H 1,378.70 L 1,347.20 |
| E12 | USD/daily | 200 | 20행, 0923=1,359.00 |
| E13 | USD/charts/month 3 | 200 | 65행, 0923=1,359.00 |
| E14 | USD/charts/round | 200 | 6,255행 (650KB) |
| E15 | exchangeWorld | 200 | EURUSD 1.1391, USDJPY 157.26, USDCNY 6.7128 |
| E16 | majors/exchange | 200 | DXY 100.97 |
| E17 | .DXY/prices 60 | 200 | 60행, 0925=100.97 |
| E18 | USDJPY / EURUSD prices | 200 | 157.26 / 1.1391 |
| E19 | energy | 200 | WTI 92.41, Brent 104.32 |
| E20 | CLcv1 / LCOcv1 prices | 200 | 92.41 / 104.32 |
| E21 | .VIX/basic | 200 | 14.87 (-0.80) |
| E22 | .VIX/price | 200 | 20행, 0925=14.87 |
| E23 | integration/indicators | 200 | USDKRW 1359.00, WTI 92.41, VIX 14.87, US10Y 5.1650 |

403/429 없음.

## 수집 항목 ↔ 엔드포인트 매핑

| CLAUDE.md 항목 | 1차(네이버) | 비고 |
|---|---|---|
| 투자자별 순매수 일별 | E3 (+장중 E1) | 외국인=9000+9001, 기관계=1000~7000 |
| 외국인 상위 10 | E5 `pageSize=10` | |
| 미국채 전 만기 | E6 USA, 이력 E9 | |
| 국고 3Y/10Y | E6 KOR, 이력 E9/E8 | |
| USD/KRW | E11, 이력 E13 | 하나은행 고시 기준 |
| USD/JPY, EUR/USD | E15, 이력 E18 | |
| USD/CNH | **없음** | yfinance `CNH=X` |
| DXY | E16, 이력 E17 | |
| WTI, Brent | E19, 이력 E20 | |
| VIX | E21, 이력 E22 | |
| (추가) 등락 종목 수 → ADR | E29 (당일만) | 이력 없음 → 장 마감 후 직접 누적 |

---

## 6. 장중 (intraday.html용, 2026-09-27 추가 캡처)

캡처 화면: 투자자별 매매동향 "선물" 탭, `/market/stock/kr/trend/program`, `/domestic/index/KOSPI/price`.
휴장일(09-27)에 호출하면 직전 거래일(09-23) 데이터가 옴. 결론: **네 항목 모두 네이버가 장중 이력을 직접 제공**.

### E24. 지수 분봉 (당일 1분)
`GET /securityService/chart/domestic/index/{KOSPI|KOSDAQ}?periodType=day`
```json
{"code":"KOSPI","marketStatus":"CLOSE","openPrice":7153.99,"lastClosePrice":7017.91,
 "tradeBaseAt":"20260923","openTime":"20260923090000","closeTime":"20260923153000",
 "priceInfos":[{"localDateTime":"20260923090000","currentPrice":7144.02,"openPrice":7153.99,"highPrice":7153.99,"lowPrice":7144.02,"accumulatedTradingVolume":4038}, ...],
 "lastPriceInfos":[...전일 분봉...]}
```
09-23: 393개 (09:00~15:32). `tradeBaseAt` ≠ 오늘이면 휴장/장 시작 전.

### E25. 투자자별 장중 누적 (현물) — 기존 E4
`GET /domestic/market/trend/time?tradeType=KRX&marketType={KOSPI|KOSDAQ}&bizdate=YYYYMMDD&startIdx={page}&pageSize=100`
1~2분 간격 누적치, 최신순. 09-23 KOSPI 443행 (09:01~20:04, 15:30 이후는 NXT 시간외 포함). 코드·단위는 E3과 동일(원).

### E26. 선물 투자자별 장중 누적
E25와 같은 경로, `marketType=FUT`. 09-23 422행 (~16:06 확정치).
- `diffValue` = **순매수 계약 수**, `buyPrice`/`sellPrice` = **백만원** (계약당 약 2.8억 = 선물가×25만)
- 코드: 8000 개인, 9000 외국인, 1000 금융투자, 2000 보험, 3000 투신(사모), 4000 은행, 5000 기타금융, 6000 연기금, 7000 국가, 7100 기타법인, 9999 (미확인, 0). 9001 없음
- 화면 대조 (09-23 16:06): 외국인 1,356계약 / 개인 37 / 기관계 -1,402 (=1000~7000 합) ✓
- 당일 합계 1건: `/domestic/market/trend/chart/time?...&marketType=FUT` (E1과 동일 형식)

### E27. 프로그램 매매
- 차트(1회 호출): `GET /domestic/market/trendProgram/chart?tradeType=KRX&krxMarketType={KOSPI|KOSDAQ}&bizdate=YYYYMMDD&startDate=YYYYMMDD&endDate=YYYYMMDD&periodType=TIME` → 배열 65개
- 목록(페이지): `GET /domestic/market/trendProgram?tradeType=KRX&krxMarketType=KOSPI&bizdate=...&startIdx=0&pageSize=30&periodType=TIME` → 669행(1분), `periodType=DATE`는 일자별
- 필드(원 단위, 누적): `diffBuyAmt/diffSellAmt/diffPureBuyAmt`(차익), `biDiff*`(비차익), `totalDiff*`(전체)
- 화면 대조 (09-23 20:05): 차익 순매수 800억 / 비차익 -7,535억 / 전체 -6,734억 ✓

### E28. KOSPI200 선물 현재가
`GET /securityService/integration/indicators?indicatorCodes=FUT` → `currentPrice` 1127.75, `fluctuationsRatio`, `localTradedAt`, 20분 지연

### USD/KRW 장중
E14 `/stockSecurity/exchange-rates/v2/USD/charts/round?bankType=hana` (하나은행 고시 회차별, 당일 6,255회, 650KB) → 1분 단위 마지막 값으로 축약해서 사용

---

## 7. 등락 종목 수 (ADR용, 2026-09-28 추가 캡처)

캡처 화면: `/domestic/index/KOSPI/price`, `/domestic/index/KOSDAQ/price`, `/market/stock/kr`, `/market/stock/kr/stocklist/up`, 홈(`/`). API 응답 109건 중 등락 종목 수가 있는 것은 아래 2개. **둘 다 당일 스냅샷만, 일별 이력 없음** (날짜 파라미터 `bizdate`·`date`·`tradeDate`는 무시되고 당일 값이 옴).

### E29. 지수 지표 + 등락 종목 수 ★ 수집용
`GET /securityService/integration/v1/indicators?domesticIndexCodes=KOSPI,KOSDAQ&includeBreadth=true`
- `domesticIndex.{KOSPI|KOSDAQ}.breadth`: `risingCount`, `fallingCount`, `unchangedCount`, `upperLimitCount`, `lowerLimitCount`, `exchangeType`(KRX)
- `domesticIndex.{…}.price`: `marketStatus`(OPEN/CLOSE), `localTradedAt`(KST), `isHoliday`
- 09-28 09:39: KOSPI 상승 628 · 하락 228 · 보합 54 · 상한 1 · 하한 0 / KOSDAQ 1,116 · 536 · 78 · 8 · 1
- `foreignIndex`(.INX 등)에도 breadth가 있음 (미사용)
- 수집 규칙(`fetch/naver.py breadth`): `marketStatus=CLOSE`이고, 날짜가 오늘이면 15:30 이후일 때만 저장. 합계 0이면 버림

### E30. 지수 통합 (같은 값, 날짜 필드 없음)
`GET /securityFe/api/index/{KOSPI|KOSDAQ}/integration` → `upDownStockInfo.{riseCount,fallCount,steadyCount,upperCount,lowerCount}` (문자열, 쉼표 포함). E29와 같은 시각에 같은 값. 날짜가 없어 E29 사용

### 미확인
- `risingCount`에 상한가(`upperLimitCount`)가 포함되는지. 현재 ADR 계산은 `risingCount`/`fallingCount` 그대로 사용
- 집계 대상(ETF·ETN·우선주·스팩 포함 여부). KOSPI 합계 911(09-28 09:39)

### 외부 (과거분 후보였음 — 사용 안 함)
- `http://adrinfo.kr/chart`: 2026-09-28 Playwright 접속 2회(09:5x, 10:10:37 KST, 사용자 지시로 1회 재시도) 모두 **403** `text/html` 94B:
  `<html><head></head><body>Blocked due to excessive traffic. Please avoid crawling or frequent access during market hours</body></html>`
  robots.txt는 curl에 "who are you?" 응답. 데이터 엔드포인트 미확인. **결론: 과거분 없이 네이버 누적만 사용, 이 사이트는 다시 호출하지 않음**
