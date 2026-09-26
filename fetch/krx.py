"""pykrx 폴백 (기본 비활성 — run.py DEFAULT_DISABLED): 투자자별 순매수 일별, 외국인 순매수 상위.

2026-09 기준 KRX 데이터포털이 로그인을 요구해 pykrx가 빈 DataFrame을 반환함
(→ @safe가 None 처리). 복구되면 그대로 동작하도록 컬럼 매핑은 유지.
"""
import pandas as pd
from pykrx import stock

from .common import safe

# pykrx 컬럼 → naver.py와 같은 컬럼명
COLS = {"개인": "individual", "외국인": "foreign_only", "기타외국인": "other_foreign",
        "금융투자": "fin_invest", "보험": "insurance", "투신": "trust", "사모": "private_fund",
        "은행": "bank", "기타금융": "other_fin", "연기금": "pension", "기타법인": "other_corp"}
INSTITUTION = ["fin_invest", "insurance", "trust", "private_fund", "bank", "other_fin", "pension"]


@safe
def investor_daily(market: str, start: str, end: str):
    """start/end: YYYYMMDD. 억원 단위."""
    df = stock.get_market_trading_value_by_date(start, end, market, detail=True)
    if df is None or df.empty:
        return None
    df = df.rename(columns=COLS)
    out = pd.DataFrame({"date": [d.strftime("%Y-%m-%d") for d in df.index]})
    for c in COLS.values():
        out[c] = (df[c].values / 1e8).round(2) if c in df else 0.0
    out["gov"] = 0.0
    out["foreign"] = out["foreign_only"] + out["other_foreign"]
    out["institution"] = out[INSTITUTION].sum(axis=1).round(2)
    out["source"] = "pykrx"
    out["asof"] = out["date"]
    return out


@safe
def foreign_top(market: str, date: str, n: int = 10):
    """date: YYYYMMDD. naver.foreign_top과 같은 컬럼."""
    df = stock.get_market_net_purchases_of_equities(date, date, market, "외국인")
    if df is None or df.empty:
        return None
    d = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    rows = []
    for side, part in (("buy", df.sort_values("순매수거래대금", ascending=False).head(n)),
                       ("sell", df.sort_values("순매수거래대금").head(n))):
        for i, (code, r) in enumerate(part.iterrows(), 1):
            rows.append({"side": side, "rank": i, "code": code, "name": r["종목명"],
                         "net_amount": round(r["순매수거래대금"] / 1e8, 1),
                         "net_volume": int(r["순매수거래량"]), "price": None, "change_pct": None,
                         "date_from": d, "date_to": d, "estimated": False,
                         "source": "pykrx", "asof": d})
    return pd.DataFrame(rows)
