"""CTA 포지셔닝 추정 — 자체 추세추종(trend-following) 복제 모델.

실제 CTA 포지션은 비공개. 업계 추정치(GS·MS·Nomura 등)도 모두 모델 추정이며, 이 모듈도
같은 방식의 '단순·투명한' 복제 모델이다. 수치는 방향·강도·전환 가격대를 보는 용도.

모델 (자산별 독립, 일별 종가):
  σ_d      = 최근 60거래일 일간 로그수익률 표준편차
  z_L      = ln(P_t / P_{t−L}) / (σ_d·√L)          L ∈ {20, 60, 125, 250} (≈1·3·6·12개월)
  s_L      = tanh(z_L)                              개별 룩백 신호 (−1 ~ +1)
  s        = mean(s_L)                              종합 신호 강도
  lev      = min(σ_ref / σ_ann, 1.5)                변동성 타기팅. σ_ref = 3년 σ_ann 중앙값
  position = s × lev × 100                          '정상 변동성 기준 풀 포지션 대비 %'
                                                    (저변동성 구간엔 최대 150%)
전환 가격(flip level):
  다음 주말(t+5)에 룩백 L 신호 부호는 P_{t+5} 대 P_{t+5−L} 비교로 결정 → flip = P_{t+5−L}.
  종합 신호 s=0이 되는 가격은 1주 경로(로그 선형)를 가정해 이분법으로 계산.
시나리오: 1주 뒤 가격이 ±1σ·±2σ(주간 σ = σ_d·√5) 움직일 때 포지션 변화(%p).

가격: yfinance 연속 선물(=F, 근월 롤 갭 포함). 롤 갭이 큰 원유·천연가스는 신호가 다소 왜곡될 수 있음.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from fetch.common import log

LOOKBACKS = [20, 60, 125, 250]
VOL_WIN = 60
LEV_CAP = 1.5
HORIZON = 5  # 1주 = 5거래일
SCEN = [-2, -1, 0, 1, 2]

# key: (yfinance 티커, 표시명, 자산군)
ASSETS = {
    "ES":  ("ES=F", "S&P 500", "주식"),
    "NQ":  ("NQ=F", "Nasdaq-100", "주식"),
    "RTY": ("RTY=F", "Russell 2000", "주식"),
    "ZT":  ("ZT=F", "UST 2Y 선물", "금리"),
    "ZF":  ("ZF=F", "UST 5Y 선물", "금리"),
    "ZN":  ("ZN=F", "UST 10Y 선물", "금리"),
    "ZB":  ("ZB=F", "UST Bond 선물", "금리"),
    "DX":  ("DX-Y.NYB", "달러인덱스", "FX"),
    "6E":  ("6E=F", "EUR/USD", "FX"),
    "6J":  ("6J=F", "JPY/USD", "FX"),
    "6B":  ("6B=F", "GBP/USD", "FX"),
    "6A":  ("6A=F", "AUD/USD", "FX"),
    "CL":  ("CL=F", "WTI 원유", "원자재"),
    "NG":  ("NG=F", "천연가스", "원자재"),
    "GC":  ("GC=F", "금", "원자재"),
    "SI":  ("SI=F", "은", "원자재"),
    "HG":  ("HG=F", "구리", "원자재"),
}


def load_prices(period: str = "6y") -> dict[str, pd.Series]:
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    out = {}
    for k, (t, _, _) in ASSETS.items():
        try:
            df = yf.Ticker(t).history(period=period, interval="1d", auto_adjust=False)
            s = df["Close"].dropna()
            s = s[s > 0]
            s.index = pd.to_datetime([d.strftime("%Y-%m-%d") for d in s.index])
            if len(s) < max(LOOKBACKS) + 300:
                raise ValueError(f"이력 부족 {len(s)}행")
            out[k] = s
        except Exception as e:  # noqa: BLE001
            log.warning("CTA 가격 %s(%s) 실패: %s", k, t, e)
    return out


# ---- 모델 핵심 (벡터화: 이력 전체) ---------------------------------------------------
def model_series(p: pd.Series) -> pd.DataFrame:
    lp = np.log(p)
    r = lp.diff()
    sd = r.rolling(VOL_WIN).std()
    ann = sd * np.sqrt(252)
    ref = ann.rolling(756, min_periods=250).median()  # 3년 중앙값
    lev = (ref / ann).clip(upper=LEV_CAP)
    sig = {}
    for L in LOOKBACKS:
        z = (lp - lp.shift(L)) / (sd * np.sqrt(L))
        sig[f"s{L}"] = np.tanh(z)
    df = pd.DataFrame(sig)
    df["s"] = df.mean(axis=1, skipna=False)
    df["lev"] = lev
    df["pos"] = df["s"] * df["lev"] * 100
    df["vol_ann"] = ann * 100
    df["px"] = p
    return df


def _position_after(p: pd.Series, ref_vol: float, k_sigma: float) -> tuple[float, float]:
    """1주 뒤 가격이 k·σ_week 움직였을 때(로그 선형 경로) 종합 신호·포지션."""
    lp = np.log(p.values)
    sd_now = np.std(np.diff(lp[-(VOL_WIN + 1):]), ddof=1)
    step = k_sigma * sd_now * np.sqrt(HORIZON) / HORIZON
    path = lp[-1] + step * np.arange(1, HORIZON + 1)
    ext = np.concatenate([lp, path])
    r = np.diff(ext[-(VOL_WIN + 1):])
    sd = np.std(r, ddof=1)
    s = np.mean([np.tanh((ext[-1] - ext[-1 - L]) / (sd * np.sqrt(L))) for L in LOOKBACKS])
    lev = min(ref_vol / (sd * np.sqrt(252)), LEV_CAP)
    return float(s), float(s * lev * 100)


def _composite_flip(p: pd.Series, ref_vol: float) -> float | None:
    """1주 뒤 종합 신호가 0이 되는 가격(±4σ 안에서). 없으면 None."""
    f = lambda k: _position_after(p, ref_vol, k)[0]  # noqa: E731
    lo, hi = -4.0, 4.0
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return None
    for _ in range(40):
        mid = (lo + hi) / 2
        fm = f(mid)
        if flo * fm <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    k = (lo + hi) / 2
    sd_now = np.std(np.diff(np.log(p.values[-(VOL_WIN + 1):])), ddof=1)
    return float(p.iloc[-1] * np.exp(k * sd_now * np.sqrt(HORIZON)))


def analyze(key: str, p: pd.Series) -> dict:
    t, name, cls = ASSETS[key]
    m = model_series(p)
    last = m.iloc[-1]
    px = float(p.iloc[-1])
    ann = np.log(p).diff().rolling(VOL_WIN).std() * np.sqrt(252)
    ref_vol = float(ann.rolling(756, min_periods=250).median().iloc[-1])

    wk_ago = m.iloc[-1 - HORIZON] if len(m) > HORIZON else None
    sd_d = float(np.std(np.diff(np.log(p.values[-(VOL_WIN + 1):])), ddof=1))
    week_sigma_pct = sd_d * np.sqrt(HORIZON) * 100

    flips = []
    for L in LOOKBACKS:
        lvl = float(p.iloc[-1 - L + HORIZON])  # P_{t+5−L}
        flips.append({"lookback": L, "signal": round(float(last[f"s{L}"]), 3),
                      "flip_level": round(lvl, 4),
                      "dist_pct": round((lvl / px - 1) * 100, 2),
                      "dist_sigma": round(np.log(lvl / px) / (sd_d * np.sqrt(HORIZON)), 2)})

    scen = []
    for k in SCEN:
        s_new, pos_new = _position_after(p, ref_vol, k)
        scen.append({"k": k, "price": round(px * np.exp(k * sd_d * np.sqrt(HORIZON)), 4),
                     "pos": round(pos_new, 1), "chg_pp": round(pos_new - float(last["pos"]), 1)})

    cflip = _composite_flip(p, ref_vol)
    hist = m.dropna(subset=["pos"]).resample("W-FRI").last().tail(156)
    pos_hist = m["pos"].dropna().tail(756)
    return {
        "key": key, "ticker": t, "name": name, "class": cls,
        "asof": p.index[-1].strftime("%Y-%m-%d"),
        "price": round(px, 4),
        "signal": round(float(last["s"]), 3),
        "position_pct": round(float(last["pos"]), 1),
        "position_chg_1w_pp": round(float(last["pos"] - wk_ago["pos"]), 1) if wk_ago is not None else None,
        "position_pctile_3y": round(float((pos_hist <= last["pos"]).mean() * 100), 0),
        "vol_ann_pct": round(float(last["vol_ann"]), 1),
        "vol_ref_pct": round(ref_vol * 100, 1),
        "lev": round(float(last["lev"]), 2),
        "week_sigma_pct": round(week_sigma_pct, 2),
        "flips": flips,
        "composite_flip": round(cflip, 4) if cflip else None,
        "composite_flip_dist_pct": round((cflip / px - 1) * 100, 2) if cflip else None,
        "scenarios": scen,
        "history": {"date": [d.strftime("%Y-%m-%d") for d in hist.index],
                    "pos": [round(float(v), 1) for v in hist["pos"]],
                    "px": [round(float(v), 4) for v in hist["px"]]},
    }


def collect(prices: dict[str, pd.Series] | None = None) -> dict:
    prices = prices if prices is not None else load_prices()
    res, fails = {}, [k for k in ASSETS if k not in prices]
    for k, p in prices.items():
        try:
            res[k] = analyze(k, p)
            log.info("CTA %-3s pos=%+6.1f%% (Δ1w %+5.1f) flip(종합)=%s",
                     k, res[k]["position_pct"], res[k]["position_chg_1w_pp"] or 0, res[k]["composite_flip"])
        except Exception as e:  # noqa: BLE001
            log.warning("CTA %s 계산 실패: %s: %s", k, type(e).__name__, e)
            fails.append(k)
    # 자산군 평균
    classes = {}
    for v in res.values():
        classes.setdefault(v["class"], []).append(v)
    agg = {c: {"position_pct": round(float(np.mean([x["position_pct"] for x in xs])), 1),
               "chg_1w_pp": round(float(np.mean([x["position_chg_1w_pp"] or 0 for x in xs])), 1),
               "n": len(xs)} for c, xs in classes.items()}
    return {"assets": res, "classes": agg, "failed": fails,
            "model": {"lookbacks": LOOKBACKS, "vol_window": VOL_WIN, "lev_cap": LEV_CAP, "horizon_days": HORIZON},
            "source": "yfinance 연속 선물 일별 종가 → 자체 추세추종 모델 (positioning/cta.py)"}
