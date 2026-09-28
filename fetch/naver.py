"""stock.naver.com 비공식 JSON API 수집. 엔드포인트 번호(E1..)는 docs/endpoints.md 참조.

- 요청 간격 1초 이상, 브라우저 UA
- 403/429를 한 번이라도 받으면 이번 실행의 네이버 호출을 모두 중단(None 반환) → run.py가 폴백
- 모든 공개 함수는 DataFrame 또는 None 반환
"""
import re
import time
from urllib.parse import quote

import pandas as pd
import requests

from .common import UA, log, now_kst, safe, to_kst_iso, ymd_to_iso

BASE = "https://stock.naver.com/api"
MIN_INTERVAL = 1.1

_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept": "application/json",
                         "Referer": "https://stock.naver.com/"})
_last_call = 0.0
_blocked = False


def is_blocked() -> bool:
    return _blocked


def _get(path: str, params: dict = None):
    global _last_call, _blocked
    if _blocked:
        return None
    wait = MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    try:
        r = _session.get(BASE + path, params=params, timeout=15)
    except requests.RequestException as e:
        log.warning("naver %s 요청 실패: %s", path, e)
        return None
    finally:
        _last_call = time.monotonic()
    if r.status_code in (403, 429):
        _blocked = True
        log.error("naver %s → %s. 이번 실행의 네이버 수집 중단, 폴백 전환", path, r.status_code)
        return None
    if not r.ok:
        log.warning("naver %s → HTTP %s: %s", path, r.status_code, r.text[:120])
        return None
    return r.json()


def _num(v):
    if v is None or v in ("", "-", "N/A"):
        return None
    return float(str(v).replace(",", ""))


# ── 투자자별 순매수 ───────────────────────────────────────────────

# investorGubun → 컬럼. 화면 표시 기준: 외국인 = 9000+9001, 기관계 = 1000~7000 합
INVESTOR_CODES = {
    "8000": "individual", "9000": "foreign_only", "9001": "other_foreign",
    "1000": "fin_invest", "2000": "insurance", "3000": "trust", "3100": "private_fund",
    "4000": "bank", "5000": "other_fin", "6000": "pension", "7000": "gov",
    "7100": "other_corp",
}
INSTITUTION = ["fin_invest", "insurance", "trust", "private_fund", "bank",
               "other_fin", "pension", "gov"]


def _investor_row(item: dict) -> dict:
    """netAmounts → 억원 단위 행."""
    raw = {INVESTOR_CODES[x["investorGubun"]]: int(x["diffValue"])
           for x in item["netAmounts"] if x["investorGubun"] in INVESTOR_CODES}
    row = {k: raw.get(k, 0) for k in INVESTOR_CODES.values()}
    row["foreign"] = row["foreign_only"] + row["other_foreign"]
    row["institution"] = sum(row[k] for k in INSTITUTION)
    return {k: round(v / 1e8, 2) for k, v in row.items()}


@safe
def investor_daily(market: str, pages: int = 1, page_size: int = 30):
    """E3. 일자별 순매수 (억원). market: KOSPI|KOSDAQ. 최신일부터."""
    rows = []
    bizdate = now_kst().strftime("%Y%m%d")
    for page in range(pages):
        b = _get("/domestic/market/trend/daily",
                 {"tradeType": "KRX", "marketType": market, "bizdate": bizdate,
                  "startIdx": page, "pageSize": page_size})
        if b is None:
            if not rows:
                return None
            break
        for it in b["content"]:
            d = ymd_to_iso(it["bizdate"])
            rows.append({"date": d, **_investor_row(it),
                         "source": "naver:trend_daily", "asof": d})
        if b.get("last") in (True, "true"):
            break
    return pd.DataFrame(rows)


@safe
def investor_today(market: str):
    """E1. 당일(또는 직전 거래일) 누적 순매수 스냅샷, 1행. asof에 집계 시각 포함."""
    today = now_kst().strftime("%Y%m%d")
    b = _get("/domestic/market/trend/chart/time",
             {"tradeType": "KRX", "marketType": market, "selectedRange": "1일",
              "bizdate": today, "startDate": today, "endDate": today})
    if b is None:
        return None
    d, t = ymd_to_iso(b["bizdate"]), b.get("time") or "000000"
    asof = f"{d}T{t[:2]}:{t[2:4]}:{t[4:6]}+09:00"
    return pd.DataFrame([{"date": d, **_investor_row(b),
                          "source": "naver:trend_time", "asof": asof}])


@safe
def foreign_top(market: str, period: str = "DAY", n: int = 10):
    """E5. 외국인 순매수(side=buy)·순매도(side=sell) 상위 n. 금액 억원."""
    b = _get("/domestic/market/trend/trendForeignOrg",
             {"investorType": "FOREIGNER", "tradeType": "KRX", "marketType": market,
              "startIdx": 0, "pageSize": n, "periodType": period})
    if b is None:
        return None
    rows = []
    for side, key in (("buy", "buyRankList"), ("sell", "sellRankList")):
        for i, it in enumerate(b["sections"][key][:n], 1):
            rows.append({
                "side": side, "rank": i, "code": it["itemcode"], "name": it["itemname"],
                "net_amount": round(int(it["accTradeAmount"]) / 1e8, 1),
                "net_volume": int(it["accTradeVolume"]),
                "price": _num(it["nowPrice"]), "change_pct": _num(it["prevChangeRate"]),
                "date_from": ymd_to_iso(it["bizdateFrom"]), "date_to": ymd_to_iso(it["bizdateTo"]),
                "estimated": bool(it.get("estimated")),
                "source": "naver:trend_foreign", "asof": to_kst_iso(it["toRankingAt"]),
            })
    return pd.DataFrame(rows)


# ── 현재값 목록 (채권·환율·에너지) ─────────────────────────────────

def _index_item(it: dict, source: str) -> dict:
    return {"code": it["reutersCode"], "name": it["name"],
            "value": _num(it["closePrice"]), "change": _num(it["fluctuations"]),
            "change_pct": _num(it["fluctuationsRatio"]),
            "source": source, "asof": to_kst_iso(it["localTradedAt"])}


@safe
def marketindex_list(category: str):
    """E15/E16/E19. category: 'exchangeWorld' | 'majors/exchange' | 'energy'.
    반환 컬럼: code, name, value, change, change_pct, source, asof"""
    b = _get(f"/securityService/marketindex/{category}")
    if b is None:
        return None
    src = "naver:" + category.replace("/", "_")
    return pd.DataFrame([_index_item(it, src) for it in b])


_TENOR = re.compile(r"^(US|KR)(\d+)([MY])T=RR$")


@safe
def bond_curve(nation: str = "USA"):
    """E6. 국채 전 만기 현재값. key 컬럼 = ust_10y / ktb_3y 형식."""
    b = _get(f"/securityService/marketindex/bond/nation/{nation}",
             {"sortType": "maturityDesc"})
    if b is None:
        return None
    rows = []
    for it in b:
        m = _TENOR.match(it["reutersCode"])
        if not m:
            continue
        prefix = {"US": "ust", "KR": "ktb"}[m.group(1)]
        tenor = f"{m.group(2)}{m.group(3)}"
        rows.append({"key": f"{prefix}_{tenor.lower()}", "tenor": tenor,
                     **_index_item(it, "naver:bond_nation")})
    return pd.DataFrame(rows)


@safe
def vix_latest():
    """E21. 1행."""
    b = _get("/securityService/index/.VIX/basic")
    if b is None:
        return None
    return pd.DataFrame([{"code": ".VIX", "name": "VIX", "value": _num(b["closePrice"]),
                          "change": _num(b["compareToPreviousClosePrice"]),
                          "change_pct": _num(b["fluctuationsRatio"]),
                          "source": "naver:vix_basic", "asof": to_kst_iso(b["localTradedAt"])}])


@safe
def usdkrw_latest():
    """E11. 하나은행 고시 매매기준율, 1행."""
    b = _get("/stockSecurity/exchange-rates/v2/market-index/FX_USDKRW/latest")
    if b is None:
        return None
    return pd.DataFrame([{"code": "FX_USDKRW", "name": "USD/KRW",
                          "value": _num(b["saleBaseRate"]), "change": _num(b["changePrice"]),
                          "change_pct": _num(b["changeRate"]),
                          "high": _num(b.get("highPriceOfDay")), "low": _num(b.get("lowPriceOfDay")),
                          "source": "naver:hana", "asof": to_kst_iso(b["announcedAt"])}])


DEPOSIT_FIELDS = {"deposit": "customerDeposit", "credit": "creditLoan", "fund_stock": "beneficiaryCertificateStock",
                  "fund_mixed": "beneficiaryCertificateMixing", "fund_bond": "beneficiaryCertificateBond"}


@safe
def deposit_trend(max_pages: int = 1):
    """E32. 증시자금동향 일별 (억원): 고객예탁금·신용잔고·주식형/혼합형/채권형 펀드. 최신순 페이지(pageSize 최대 100).
    전체 이력 2002-05-03~ 약 61페이지. 금투협 집계라 통상 2거래일 지연.
    asof = 데이터 기준일(수집 시각이 아님) → 값이 같으면 파일도 같음."""
    rows = []
    for page in range(max_pages):
        b = _get("/domestic/market/trendDeposit", {"startIdx": page, "pageSize": 100})
        if b is None:
            if not rows:
                return None
            break
        for it in b.get("content", []):
            date = ymd_to_iso(it["bizdate"])
            rows.append({"date": date, **{k: int(_num(it.get(f))) for k, f in DEPOSIT_FIELDS.items()},
                         "source": "naver:trend_deposit", "asof": date})
        if b.get("last") in (True, "true"):
            break
    return pd.DataFrame(rows)

# 이격도 차트용 개별 종목 (코드 → 이름)
STOCKS = {"005930": "삼성전자", "000660": "SK하이닉스"}


@safe
def stock_daily(code: str, pages: int = 1):
    """E35. 종목 일별 시세 (KRX, 최신순, 100행/페이지, startIdx=페이지 번호). 종가만 사용(원).
    오늘 행은 15:40 KST 이후만 (장중 값 방지), asof = 그날 15:30."""
    now = now_kst()
    today, before_close = now.strftime("%Y-%m-%d"), now.strftime("%H:%M") < KRX_CLOSE_FINAL
    rows = []
    for page in range(pages):
        b = _get(f"/domestic/detail/{code}/trend", {"tradeType": "KRX", "startIdx": page, "pageSize": 100})
        if not b:
            break
        for it in b:
            date = ymd_to_iso(it["bizdate"])
            if date == today and before_close:
                continue
            rows.append({"date": date, "value": _num(it["closePrice"]), "source": "naver:stock_trend",
                         "asof": f"{date}T15:30:00+09:00"})
        if len(b) < 100:
            break
    return pd.DataFrame(rows)

@safe
def breadth():
    """E29. 코스피·코스닥 상승·하락·보합 종목 수 (당일 스냅샷만, 이력 없음).
    장 마감(marketStatus=CLOSE) 뒤 값만 반환 — 장중 값은 누적하지 않는다. 장중이면 None(@safe)."""
    b = _get("/securityService/integration/v1/indicators",
             {"domesticIndexCodes": "KOSPI,KOSDAQ", "includeBreadth": "true"})
    if b is None:
        return None
    now = now_kst()
    rows = []
    for m in ("KOSPI", "KOSDAQ"):
        it = b["domesticIndex"][m]
        pr, br = it["price"], it["breadth"]
        asof = to_kst_iso(pr["localTradedAt"])
        # 같은 날짜는 15:30 이후만 (장 시작 전 CLOSE 상태에서 당일 날짜로 0/전일 값이 오는 경우 방지)
        if pr.get("marketStatus") != "CLOSE" or (asof[:10] == now.strftime("%Y-%m-%d") and now.strftime("%H:%M") < "15:30"):
            continue
        r = {k: int(_num(br[f])) for k, f in (("rise", "risingCount"), ("fall", "fallingCount"),
             ("steady", "unchangedCount"), ("upper", "upperLimitCount"), ("lower", "lowerLimitCount"))}
        if r["rise"] + r["fall"] + r["steady"] == 0:
            continue
        rows.append({"market": m, "date": asof[:10], **r, "source": "naver:indicators_breadth", "asof": asof})
    return pd.DataFrame(rows, columns=["market", "date", "rise", "fall", "steady", "upper", "lower", "source", "asof"])


# ── 시계열 ────────────────────────────────────────────────────────

@safe
def bond_history(code: str, months: int = 1):
    """E9. 국채 일별 종가. code 예: US10YT=RR, KR3YT=RR. months: 1|3|12."""
    b = _get(f"/securityService/chart/foreign/governmentBond/{quote(code, safe='')}",
             {"periodType": "month", "range": months})
    if b is None:
        return None
    return pd.DataFrame([{"date": ymd_to_iso(p["localDate"]), "value": float(p["closePrice"]),
                          "source": "naver:bond_chart", "asof": ymd_to_iso(p["localDate"])}
                         for p in b["priceInfos"]])


@safe
def usdkrw_history(months: int = 3):
    """E13. USD/KRW(하나은행 고시) 일별 종가. months 1~12 (charts/year는 주간이라 사용 안 함)."""
    b = _get("/stockSecurity/exchange-rates/v2/USD/charts/month",
             {"bankType": "hana", "range": min(max(months, 1), 12)})
    if b is None:
        return None
    return pd.DataFrame([{"date": ymd_to_iso(p["localDate"]), "value": _num(p["closingPrice"]),
                          "source": "naver:hana", "asof": ymd_to_iso(p["localDate"])}
                         for p in b["priceInfos"]])


# E17/E18/E20/E22 경로. 모두 pageSize ≤ 60
PRICE_PATHS = {
    "usdjpy": "/securityService/marketindex/exchangeWorld/USDJPY/prices",
    "eurusd": "/securityService/marketindex/exchangeWorld/EURUSD/prices",
    "dxy": "/securityService/marketindex/exchange/.DXY/prices",
    "wti": "/securityService/marketindex/energy/CLcv1/prices",
    "brent": "/securityService/marketindex/energy/LCOcv1/prices",
    "vix": "/securityService/index/.VIX/price",
    # 국내 지수 일별 (E34). 날짜만 옴(시각 없음), 장중엔 첫 행이 오늘 실시간 값
    "kospi": "/securityFe/api/index/KOSPI/price",
    "kosdaq": "/securityFe/api/index/KOSDAQ/price",
}
KRX_INDEX = {"kospi", "kosdaq"}
KRX_CLOSE_FINAL = "15:40"   # 이 시각 전의 오늘 행은 장중 값이라 버림 (종가 아님)


@safe
def prices_history(key: str, pages: int = 1):
    """E17/E18/E20/E22/E34. 일별 종가 (최신순 페이지, 60행/페이지). date는 현지 거래일."""
    rows = []
    now = now_kst()
    today, before_close = now.strftime("%Y-%m-%d"), now.strftime("%H:%M") < KRX_CLOSE_FINAL
    for page in range(1, pages + 1):
        b = _get(PRICE_PATHS[key], {"page": page, "pageSize": 60})
        if not b:
            break
        if key in KRX_INDEX:   # asof = 그날 15:30 (정규장 종가)
            rows += [{"date": p["localTradedAt"][:10], "value": _num(p["closePrice"]),
                      "source": "naver:index_price", "asof": f"{p['localTradedAt'][:10]}T15:30:00+09:00"}
                     for p in b if not (p["localTradedAt"][:10] == today and before_close)]
        else:
            rows += [{"date": p["localTradedAt"][:10], "value": _num(p["closePrice"]),
                      "source": f"naver:prices", "asof": to_kst_iso(p["localTradedAt"])}
                     for p in b]
        if len(b) < 60:
            break
    return pd.DataFrame(rows) if rows else None
