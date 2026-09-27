"""CFTC Commitments of Traders — Socrata Open Data API (키 불필요).

- 금융선물: TFF(Traders in Financial Futures) futures-only  dataset gpe5-46if
    → Leveraged Funds(헤지펀드·CTA 포함) / Asset Manager / Dealer
- 원자재: Disaggregated futures-only                         dataset 72hh-3qpy
    → Managed Money / Producer·Merchant / Swap Dealer
- 기준일: 화요일 포지션, 금요일 15:30 ET 공표 (미 연방 휴일 주는 하루~이틀 지연)

필드명이 데이터셋·그룹마다 '_all' 접미사가 제각각이라 FIELDS에 명시적으로 매핑한다.
(2026-09-26 API 응답으로 필드명 확인: dealer_positions_long_all, asset_mgr_positions_long,
 lev_money_positions_long, m_money_positions_long_all, swap__positions_short_all 등)
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import requests

from fetch.common import UA, log

BASE = "https://publicreporting.cftc.gov/resource/{ds}.json"
DS_TFF = "gpe5-46if"
DS_DISAGG = "72hh-3qpy"

# key: (dataset, CFTC contract code, 표시명, 자산군, 계약 승수 설명)
MARKETS = {
    # 주식지수
    "ES":  (DS_TFF, "13874A", "S&P 500 E-mini", "주식"),
    "NQ":  (DS_TFF, "209742", "Nasdaq-100 E-mini", "주식"),
    "RTY": (DS_TFF, "239742", "Russell 2000 E-mini", "주식"),
    # 변동성
    "VX":  (DS_TFF, "1170E1", "VIX 선물", "변동성"),
    # 금리
    "ZT":  (DS_TFF, "042601", "UST 2Y", "금리"),
    "ZF":  (DS_TFF, "044601", "UST 5Y", "금리"),
    "ZN":  (DS_TFF, "043602", "UST 10Y", "금리"),
    "TN":  (DS_TFF, "043607", "UST Ultra 10Y", "금리"),
    "ZB":  (DS_TFF, "020601", "UST Bond", "금리"),
    "UB":  (DS_TFF, "020604", "UST Ultra Bond", "금리"),
    # FX (CME 통화선물: 외화 기준 → 순매수 = 해당 통화 롱 / 달러 숏)
    "DX":  (DS_TFF, "098662", "달러인덱스(ICE)", "FX"),
    "6E":  (DS_TFF, "099741", "EUR", "FX"),
    "6J":  (DS_TFF, "097741", "JPY", "FX"),
    "6B":  (DS_TFF, "096742", "GBP", "FX"),
    "6A":  (DS_TFF, "232741", "AUD", "FX"),
    # 원자재
    "CL":  (DS_DISAGG, "067651", "WTI 원유", "원자재"),
    "NG":  (DS_DISAGG, "023651", "천연가스(HH)", "원자재"),
    "GC":  (DS_DISAGG, "088691", "금", "원자재"),
    "SI":  (DS_DISAGG, "084691", "은", "원자재"),
    "HG":  (DS_DISAGG, "085692", "구리", "원자재"),
}

# 그룹 키 → (long 필드, short 필드, 표시명)
FIELDS = {
    DS_TFF: {
        "lev":    ("lev_money_positions_long", "lev_money_positions_short", "Leveraged Funds"),
        "am":     ("asset_mgr_positions_long", "asset_mgr_positions_short", "Asset Manager"),
        "dealer": ("dealer_positions_long_all", "dealer_positions_short_all", "Dealer"),
    },
    DS_DISAGG: {
        "mm":     ("m_money_positions_long_all", "m_money_positions_short_all", "Managed Money"),
        "pm":     ("prod_merc_positions_long", "prod_merc_positions_short", "Producer/Merchant"),
        "swap":   ("swap_positions_long_all", "swap__positions_short_all", "Swap Dealer"),
    },
}
# 헤드라인(투기 포지션) 그룹: 금융=Leveraged Funds, 원자재=Managed Money
HEADLINE = {DS_TFF: "lev", DS_DISAGG: "mm"}

LOOKBACK_WEEKS = 156  # 백분위·z-score 기준 3년


def _get(ds: str, code: str, since: str) -> list[dict]:
    params = {
        "$where": f"cftc_contract_market_code='{code}' AND report_date_as_yyyy_mm_dd >= '{since}'",
        "$order": "report_date_as_yyyy_mm_dd ASC",
        "$limit": 5000,
    }
    r = requests.get(BASE.format(ds=ds), params=params, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_market(key: str, years: int = 4) -> pd.DataFrame | None:
    """주간 시계열: date, oi, <grp>_long, <grp>_short, <grp>_net (그룹별). 실패 시 None."""
    ds, code, name, _ = MARKETS[key]
    since = (pd.Timestamp.today() - pd.DateOffset(years=years)).strftime("%Y-%m-%dT00:00:00")
    try:
        rows = _get(ds, code, since)
    except Exception as e:  # noqa: BLE001
        log.warning("COT %s(%s) 실패: %s", key, code, e)
        return None
    if not rows:
        log.warning("COT %s(%s) 결과 없음", key, code)
        return None
    out = []
    for r in rows:
        rec = {"date": r["report_date_as_yyyy_mm_dd"][:10],
               "oi": float(r.get("open_interest_all") or np.nan),
               "market_name": r.get("market_and_exchange_names", "")}
        for g, (lf, sf, _) in FIELDS[ds].items():
            lo = float(r.get(lf) or np.nan)
            sh = float(r.get(sf) or np.nan)
            rec[f"{g}_long"], rec[f"{g}_short"], rec[f"{g}_net"] = lo, sh, lo - sh
        out.append(rec)
    df = pd.DataFrame(out).drop_duplicates("date", keep="last").reset_index(drop=True)
    return df


def summarize(key: str, df: pd.DataFrame) -> dict:
    """최신 주 스냅샷 + 3년 백분위/z-score + 주간 히스토리(헤드라인 그룹)."""
    ds, code, name, cls = MARKETS[key]
    groups = {}
    for g, (_, _, gname) in FIELDS[ds].items():
        net = df[f"{g}_net"]
        hist = net.tail(LOOKBACK_WEEKS)
        cur = float(net.iloc[-1])
        prev = float(net.iloc[-2]) if len(net) > 1 else np.nan
        m4 = float(net.iloc[-5]) if len(net) > 4 else np.nan
        std = float(hist.std(ddof=0))
        dstd = float(net.diff().tail(LOOKBACK_WEEKS).std(ddof=0))
        groups[g] = {
            "chg_1w_z": _r((cur - prev) / dstd, 2) if dstd > 0 else None,
            "name": gname,
            "long": _i(df[f"{g}_long"].iloc[-1]),
            "short": _i(df[f"{g}_short"].iloc[-1]),
            "net": _i(cur),
            "chg_1w": _i(cur - prev),
            "chg_4w": _i(cur - m4),
            "net_pct_oi": _r(cur / df["oi"].iloc[-1] * 100, 1),
            "pctile_3y": _r((hist <= cur).mean() * 100, 0),
            "z_3y": _r((cur - hist.mean()) / std, 2) if std > 0 else None,
            "max_3y": _i(hist.max()), "min_3y": _i(hist.min()),
        }
    hg = HEADLINE[ds]
    tail = df.tail(LOOKBACK_WEEKS)
    return {
        "key": key, "name": name, "class": cls, "code": code,
        "market_name": df["market_name"].iloc[-1],
        "dataset": "TFF" if ds == DS_TFF else "Disaggregated",
        "report_date": df["date"].iloc[-1],
        "oi": _i(df["oi"].iloc[-1]),
        "oi_chg_1w": _i(df["oi"].iloc[-1] - df["oi"].iloc[-2]) if len(df) > 1 else None,
        "headline": hg,
        "groups": groups,
        "history": {
            "date": tail["date"].tolist(),
            **{f"{g}_net": [_i(v) for v in tail[f"{g}_net"]] for g in FIELDS[ds]},
        },
    }


def collect(keys: list[str] | None = None) -> dict:
    res, fails = {}, []
    for k in keys or MARKETS:
        df = fetch_market(k)
        if df is None or len(df) < 10:
            fails.append(k)
        else:
            res[k] = summarize(k, df)
            log.info("COT %-4s %s  기준 %s  net(%s)=%s",
                     k, res[k]["market_name"][:40], res[k]["report_date"],
                     res[k]["headline"], res[k]["groups"][res[k]["headline"]]["net"])
        time.sleep(0.3)
    return {"markets": res, "failed": fails,
            "report_date": max((v["report_date"] for v in res.values()), default=None),
            "source": "CFTC Public Reporting (TFF gpe5-46if · Disaggregated 72hh-3qpy), futures-only"}


def _i(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else int(round(float(v)))


def _r(v, n):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), n)
