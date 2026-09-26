"""FRED 확정치: 미 국채 만기별 수익률 (DGS*). 환경변수 FRED_API_KEY 필요.

키 없는 fredgraph.csv는 봇 차단으로 연결이 끊겨(2026-09 확인) 사용하지 않음.
"""
import os

import pandas as pd
import requests

from .common import UA, log, safe

SERIES = {"ust_1m": "DGS1MO", "ust_3m": "DGS3MO", "ust_6m": "DGS6MO", "ust_1y": "DGS1",
          "ust_2y": "DGS2", "ust_3y": "DGS3", "ust_5y": "DGS5", "ust_7y": "DGS7",
          "ust_10y": "DGS10", "ust_20y": "DGS20", "ust_30y": "DGS30"}
_warned = False


@safe
def history(key: str, start: str):
    """start: YYYY-MM-DD. date, value, source, asof."""
    global _warned
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        if not _warned:
            log.info("FRED_API_KEY 없음 → FRED 건너뜀")
            _warned = True
        return None
    if key not in SERIES:
        return None
    r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                     params={"series_id": SERIES[key], "api_key": api_key,
                             "file_type": "json", "observation_start": start},
                     headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    obs = [o for o in r.json()["observations"] if o["value"] not in (".", "")]
    return pd.DataFrame([{"date": o["date"], "value": float(o["value"]),
                          "source": f"fred:{SERIES[key]}", "asof": o["date"]} for o in obs])
