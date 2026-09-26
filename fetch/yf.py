"""yfinance 폴백: 환율·유가·VIX·일부 미 국채 만기. 일별 종가만 사용."""
import logging

import pandas as pd
import yfinance as yf

from .common import log, safe

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

TICKERS = {
    "usdkrw": "KRW=X", "usdjpy": "JPY=X", "usdcnh": "CNH=X", "eurusd": "EURUSD=X",
    "dxy": "DX-Y.NYB", "wti": "CL=F", "brent": "BZ=F", "vix": "^VIX",
    # 미 국채 수익률 지수(%). yfinance에는 이 4개 만기만 있음
    "ust_3m": "^IRX", "ust_5y": "^FVX", "ust_10y": "^TNX", "ust_30y": "^TYX",
}


@safe
def history(key: str, period: str = "3mo"):
    """date, value, source, asof. key는 TICKERS 키."""
    ticker = TICKERS[key]
    df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    if df is None or df.empty:
        return None
    s = df["Close"].dropna()
    dates = [d.strftime("%Y-%m-%d") for d in s.index]
    return pd.DataFrame({"date": dates, "value": s.round(4).values,
                         "source": f"yfinance:{ticker}", "asof": dates})
