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


# 장중 페이지용 미국 선물 1분봉 (지연 시세)
US_FUT = {"NQ": ("NQ=F", "나스닥100 선물"), "CL": ("CL=F", "WTI 선물")}


def us_future_1m(sym: str, now):
    """전일 미국장 마감(KST 06:00 = 선물 일일 마감 17:00 ET, 서머타임 기준)부터 지금까지 1분봉.
    기준가 prev_close = 06:00 KST 이하 마지막 1분봉 종가(공식 정산가 아님). 주말을 넘기려고 5일치를 받는다.
    실패하면 None (호출 측이 이전 값 유지 + stale)."""
    ticker, name = US_FUT[sym]
    try:
        df = yf.Ticker(ticker).history(period="5d", interval="1m", prepost=True)
    except Exception as e:  # noqa: BLE001
        log.warning("yfinance %s 1m 실패: %s", ticker, e)
        return None
    if df is None or df.empty:
        log.warning("yfinance %s 1m 결과 없음", ticker)
        return None
    s = df["Close"].dropna()
    s.index = s.index.tz_convert("Asia/Seoul")
    start = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now < start:
        start -= pd.Timedelta(days=1)
    prev, cur = s[s.index <= start], s[s.index > start]
    if prev.empty:
        log.warning("yfinance %s: 기준가(06:00 이전 봉) 없음", ticker)
        return None
    rows = [{"t": ts.strftime("%H:%M"), "c": round(float(v), 2)} for ts, v in cur.items()]
    last_at = cur.index[-1] if len(cur) else prev.index[-1]
    return {"symbol": ticker, "name": name, "source": f"yfinance:{ticker} 1m",
            "asof": last_at.isoformat(), "since": start.isoformat(),
            "prev_close": round(float(prev.iloc[-1]), 2), "prev_close_at": prev.index[-1].isoformat(),
            "delay_min": round((now - last_at).total_seconds() / 60), "rows": rows}
