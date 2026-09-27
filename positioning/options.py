"""CBOE 지연 옵션 체인(15분 지연, 키 불필요) → 콜/풋 포지셔닝·딜러 감마 추정.

엔드포인트: https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json
  (지수는 '_SPX'처럼 언더스코어 접두. cdn-api.cboe.com으로 302 리다이렉트)
  응답: {"timestamp": "...", "data": {"options": [{option, bid, ask, iv, open_interest,
         volume, delta, gamma, ...}], "current_price"?: ..., "close"?: ...}}
  option 심볼: ROOT + YYMMDD + C/P + 행사가*1000(8자리) 예) SPX261016C00200000

딜러 감마(GEX) 가정 — 업계 통용 'naive GEX':
  딜러는 콜 OI를 롱, 풋 OI를 숏으로 보유 (고객이 콜 매도·풋 매수) → 콜 +, 풋 −
  GEX($, 지수 1% 변동당) = Σ sign × OI × 100 × Γ(S) × S² × 1%
  감마는 BS(r=q=0)로 재계산 — 가격대별 프로파일(zero-gamma 탐색)과 일관성 위해.
  실제 딜러 포지션(고객 콜 매수·오버라이팅 등)과 다를 수 있음 → 방향성 참고 지표.
"""
from __future__ import annotations

import math
import re
import time
from datetime import date, datetime

import numpy as np
import pandas as pd
import requests

from fetch.common import UA, log

URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"

# key: (CBOE 심볼, 표시명, 자산군, GEX 계산 여부)
UNDERLYINGS = {
    "SPX": ("_SPX", "S&P 500 지수", "주식", True),
    "SPY": ("SPY", "SPY ETF", "주식", True),
    "NDX": ("_NDX", "Nasdaq-100 지수", "주식", True),
    "QQQ": ("QQQ", "QQQ ETF", "주식", True),
    "RUT": ("_RUT", "Russell 2000 지수", "주식", True),
    "IWM": ("IWM", "IWM ETF", "주식", True),
    # VIX 옵션은 VIX 선물 기준 가격 → 현물로 BS 감마 계산 부적절. P/C·OI 벽만.
    "VIX": ("_VIX", "VIX", "변동성", False),
    "TLT": ("TLT", "TLT (20Y+ 국채)", "금리", True),
    "GLD": ("GLD", "GLD (금)", "원자재", True),
    "USO": ("USO", "USO (원유)", "원자재", True),
}

SYM_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")
SQRT2PI = math.sqrt(2 * math.pi)


def _fetch(sym: str) -> dict:
    r = requests.get(URL.format(sym=sym), headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    return r.json()


def parse_chain(js: dict, today: date) -> tuple[pd.DataFrame, float | None, str]:
    data = js.get("data", {})
    rows = []
    for o in data.get("options", []):
        m = SYM_RE.match(o.get("option", ""))
        if not m:
            continue
        root, ymd, cp, k = m.groups()
        exp = datetime.strptime(ymd, "%y%m%d").date()
        rows.append({
            "root": root, "exp": exp, "cp": cp, "strike": int(k) / 1000,
            "oi": float(o.get("open_interest") or 0), "vol": float(o.get("volume") or 0),
            "iv": float(o.get("iv") or 0), "delta": float(o.get("delta") or 0),
            "gamma_cboe": float(o.get("gamma") or 0),
            "bid": float(o.get("bid") or 0), "ask": float(o.get("ask") or 0),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df, None, js.get("timestamp", "")
    df["dte"] = (pd.to_datetime(df["exp"]) - pd.Timestamp(today)).dt.days
    # 미국 장 마감 후 실행 → 당일(dte=0) 만기는 이미 소멸. 체인에 OI가 남아 있어도 제외
    df = df[df["dte"] >= 1].copy()
    df["mid"] = (df["bid"] + df["ask"]) / 2
    spot = data.get("current_price") or data.get("close")
    spot = float(spot) if spot else _spot_from_parity(df)
    return df, spot, js.get("timestamp", "")


def _spot_from_parity(df: pd.DataFrame) -> float | None:
    """current_price가 없을 때: 최근월 C−P 절댓값 최소 행사가에서 S ≈ K + C − P."""
    near = df[df["dte"] == df["dte"].min()]
    piv = near.pivot_table(index="strike", columns="cp", values="mid", aggfunc="first").dropna()
    piv = piv[(piv["C"] > 0) & (piv["P"] > 0)]
    if piv.empty:
        return None
    k = (piv["C"] - piv["P"]).abs().idxmin()
    return float(k + piv.loc[k, "C"] - piv.loc[k, "P"])


def bs_gamma(S, K, T, iv):
    """BS 감마(r=q=0). 배열 입력 허용."""
    S, K, T, iv = map(np.asarray, (S, K, T, iv))
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K) + 0.5 * iv ** 2 * T) / (iv * np.sqrt(T))
        g = np.exp(-0.5 * d1 ** 2) / (SQRT2PI * S * iv * np.sqrt(T))
    return np.nan_to_num(g)


def _gex_at(df: pd.DataFrame, s: float) -> float:
    g = bs_gamma(s, df["strike"].values, df["T"].values, df["iv"].values)
    return float((df["sign"].values * df["oi"].values * 100 * g * s * s * 0.01).sum())


def third_friday(y: int, m: int) -> date:
    d = date(y, m, 15)
    return date(y, m, 15 + (4 - d.weekday()) % 7)


def next_monthly_opex(today: date) -> date:
    tf = third_friday(today.year, today.month)
    if tf >= today:
        return tf
    y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return third_friday(y, m)


def analyze(key: str, df: pd.DataFrame, spot: float, today: date) -> dict:
    _, name, cls, do_gex = UNDERLYINGS[key]
    calls, puts = df[df.cp == "C"], df[df.cp == "P"]
    out = {
        "key": key, "name": name, "class": cls, "spot": round(spot, 2),
        "call_oi": int(calls.oi.sum()), "put_oi": int(puts.oi.sum()),
        "call_vol": int(calls.vol.sum()), "put_vol": int(puts.vol.sum()),
    }
    out["pc_oi"] = round(out["put_oi"] / out["call_oi"], 3) if out["call_oi"] else None
    out["pc_vol"] = round(out["put_vol"] / out["call_vol"], 3) if out["call_vol"] else None

    # 행사가별 OI 벽 (±15% 범위, 전 만기 합산)
    band = df[(df.strike > spot * 0.85) & (df.strike < spot * 1.15)]
    oi_k = band.pivot_table(index="strike", columns="cp", values="oi", aggfunc="sum").fillna(0)
    if "C" in oi_k and oi_k["C"].sum() > 0:
        out["call_oi_wall"] = float(oi_k["C"].idxmax())
    if "P" in oi_k and oi_k["P"].sum() > 0:
        out["put_oi_wall"] = float(oi_k["P"].idxmax())

    # ATM IV 기간구조 · 30일 ATM IV · 25Δ 스큐 — 양쪽 호가가 있는 옵션만 (호가 없는 옵션의 IV는 부정확)
    # VIX 옵션은 VIX 선물 기준 가격이라 현물 VIX 대비 ATM·델타가 어긋남 → 계산 안 함
    q = df[(df.bid > 0) & (df.ask > 0) & (df.iv > 0.01) & (df.iv < 3)] if do_gex else df.iloc[0:0]
    term = []
    for exp, g in q.groupby("exp"):
        dte = int(g.dte.iloc[0])
        if dte > 400:
            continue
        k = g.iloc[(g.strike - spot).abs().argsort()[:4]]  # ATM 근처 C/P 2쌍
        iv = float(k.iv.mean())
        if 0 < iv < 3:
            term.append((dte, round(iv * 100, 2)))
    term.sort()
    out["term"] = term
    out["atm_iv_30d"] = _interp_var(term, 30)
    out["skew_25d_30d"] = _skew25(q, 30) if len(q) else None

    if do_gex:
        # 교차검증용: CBOE 제공 감마(현재가 기준) 그대로 쓴 GEX — 필터 없이 OI>0 전체
        a = df[df.oi > 0]
        sgn = np.where(a.cp == "C", 1.0, -1.0)
        out["gex_cboe_usd_bn"] = round(float((sgn * a.oi * 100 * a.gamma_cboe * spot * spot * 0.01).sum()) / 1e9, 3)

        # BS 재계산용 필터: 현재가 ±25% 행사가, IV 1~150%, 매도호가 존재(호가 없는 원거리 옵션의 이상 IV 배제)
        d = df[(df.oi > 0) & (df.iv > 0.01) & (df.iv < 1.5) & (df.ask > 0)
               & (df.strike > spot * 0.75) & (df.strike < spot * 1.25)].copy()
        d["T"] = d.dte / 365.0
        d["sign"] = np.where(d.cp == "C", 1.0, -1.0)
        gex = _gex_at(d, spot)
        out["gex_usd_bn"] = round(gex / 1e9, 3)
        out["gex_n_options"] = int(len(d))
        # 단기(35일 이내) GEX — 공개 GEX 툴 대부분이 근월물 중심이라 비교용. 장기물(분기·연말물)은 규모만 키움
        near = d[d.dte <= 35]
        out["gex_near_usd_bn"] = round(_gex_at(near, spot) / 1e9, 3) if len(near) else None

        # 행사가별 GEX (현재 가격 기준) → 콜/풋 감마 벽
        d["gex"] = d["sign"] * d["oi"] * 100 * bs_gamma(spot, d.strike, d["T"], d.iv) * spot * spot * 0.01
        by_k = d[(d.strike > spot * 0.9) & (d.strike < spot * 1.1)].groupby(["strike", "cp"])["gex"].sum().unstack(fill_value=0)
        if not by_k.empty:
            # 벽 = 행사가별 '순' GEX(콜+풋) 기준. 콜·풋 OI가 같은 행사가에 몰리면(예: 8000 라운드 행사가)
            # 콜 단독·풋 단독 최대가 같은 행사가로 겹쳐 무의미해지므로 순값으로 판단
            by_k["net"] = by_k.sum(axis=1)
            if (by_k["net"] > 0).any():
                out["call_gamma_wall"] = float(by_k["net"].idxmax())
            if (by_k["net"] < 0).any():
                out["put_gamma_wall"] = float(by_k["net"].idxmin())
            # 차트용: 행사가 간격을 적당히 묶기(최대 ~80개 막대)
            step = _nice_step(spot * 0.2 / 80)
            agg = by_k["net"].groupby((by_k.index / step).round() * step).sum()
            out["gex_by_strike"] = {"strike": [round(float(x), 2) for x in agg.index],
                                    "gex_usd_mn": [round(float(v) / 1e6, 1) for v in agg.values]}

        # 가격대별 GEX 프로파일 · zero-gamma
        grid = np.linspace(spot * 0.88, spot * 1.12, 97)
        prof = np.array([_gex_at(d, s) for s in grid])
        out["gex_profile"] = {"spot": [round(float(s), 2) for s in grid],
                              "gex_usd_bn": [round(float(v) / 1e9, 3) for v in prof]}
        out["zero_gamma"] = _zero_cross(grid, prof, spot)

        # 진단: 만기별 GEX 상위 · 행사가별 기여 상위 (값이 튀면 원인 추적용)
        d["gamma_bs"] = bs_gamma(spot, d.strike, d["T"], d.iv)
        be = d.groupby("exp").agg(gex=("gex", "sum"), oi=("oi", "sum"), dte=("dte", "first"))
        be = be.reindex(be.gex.abs().sort_values(ascending=False).index).head(8)
        out["diag_gex_by_expiry"] = [{"exp": e.isoformat(), "dte": int(r.dte), "gex_usd_bn": round(float(r.gex) / 1e9, 3), "oi": int(r.oi)} for e, r in be.iterrows()]
        top = d.reindex(d.gex.abs().sort_values(ascending=False).index).head(12)
        out["diag_top_options"] = [{"exp": r.exp.isoformat(), "dte": int(r.dte), "cp": r.cp, "strike": float(r.strike), "oi": int(r.oi),
                                    "iv": round(float(r.iv), 4), "gamma_bs": float(f"{r.gamma_bs:.3e}"), "gamma_cboe": float(f"{r.gamma_cboe:.3e}"),
                                    "gex_usd_mn": round(float(r.gex) / 1e6, 1)} for _, r in top.iterrows()]

        # 다음 월물 OPEX까지 만기 도래하는 |감마| 비중
        opex = next_monthly_opex(today)
        d["absg"] = d["gex"].abs()
        tot = d["absg"].sum()
        out["next_opex"] = opex.isoformat()
        out["gamma_expiring_by_opex_pct"] = round(float(d.loc[d.exp <= opex, "absg"].sum() / tot * 100), 1) if tot else None
    return out


def _interp_var(term, days):
    """분산(σ²T) 선형 보간으로 특정 만기 ATM IV."""
    if not term:
        return None
    xs = [t for t, _ in term]
    if days <= xs[0]:
        return term[0][1]
    if days >= xs[-1]:
        return term[-1][1]
    for (t0, v0), (t1, v1) in zip(term, term[1:]):
        if t0 <= days <= t1:
            w0, w1 = (v0 / 100) ** 2 * t0, (v1 / 100) ** 2 * t1
            w = w0 + (w1 - w0) * (days - t0) / (t1 - t0)
            return round(math.sqrt(w / days) * 100, 2)
    return None


def _skew25(df, days):
    """목표 만기에 가장 가까운 만기(10~60일)에서 25Δ 풋 IV − 25Δ 콜 IV (vol pt)."""
    c = df[(df.dte >= 10) & (df.dte <= 60) & (df.iv > 0) & (df.oi > 0)]
    if c.empty:
        return None
    exp = c.iloc[(c.dte - days).abs().argsort()].exp.iloc[0]
    e = c[c.exp == exp]
    p = e[e.cp == "P"]
    cl = e[e.cp == "C"]
    if p.empty or cl.empty:
        return None
    ivp = p.iloc[(p.delta + 0.25).abs().argsort()].iv.iloc[0]
    ivc = cl.iloc[(cl.delta - 0.25).abs().argsort()].iv.iloc[0]
    return round(float(ivp - ivc) * 100, 2)


def _zero_cross(grid, prof, spot):
    roots = []
    for i in range(len(grid) - 1):
        a, b = prof[i], prof[i + 1]
        if a == 0 or a * b < 0:
            roots.append(grid[i] - a * (grid[i + 1] - grid[i]) / (b - a) if b != a else grid[i])
    if not roots:
        return None
    return round(float(min(roots, key=lambda r: abs(r - spot))), 2)


def _nice_step(x):
    if x <= 0:
        return 1
    p = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 2.5, 5, 10):
        if x <= m * p:
            return m * p
    return 10 * p


def collect(today: date, keys: list[str] | None = None) -> dict:
    res, fails, stamps = {}, [], {}
    for k in keys or UNDERLYINGS:
        sym = UNDERLYINGS[k][0]
        try:
            df, spot, ts = parse_chain(_fetch(sym), today)
            if df.empty or not spot:
                raise ValueError("빈 체인 또는 기초자산 가격 없음")
            res[k] = analyze(k, df, spot, today)
            res[k]["cboe_timestamp"] = ts
            log.info("옵션 %-4s spot=%.2f P/C(OI)=%s GEX(BS)=%s$bn GEX(CBOE감마)=%s$bn zeroΓ=%s",
                     k, spot, res[k]["pc_oi"], res[k].get("gex_usd_bn"), res[k].get("gex_cboe_usd_bn"), res[k].get("zero_gamma"))
        except Exception as e:  # noqa: BLE001
            log.warning("옵션 %s 실패: %s: %s", k, type(e).__name__, e)
            fails.append(k)
        time.sleep(1)
    return {"underlyings": res, "failed": fails,
            "source": "CBOE delayed quotes (cdn.cboe.com/api/global/delayed_quotes/options), 15분 지연"}


# 일별 히스토리에 남길 스칼라 지표
SCALARS = ["spot", "pc_oi", "pc_vol", "call_vol", "put_vol", "gex_usd_bn", "gex_near_usd_bn", "zero_gamma",
           "call_gamma_wall", "put_gamma_wall", "atm_iv_30d", "skew_25d_30d"]


def daily_row(snapshot: dict) -> dict:
    return {k: {f: v.get(f) for f in SCALARS} for k, v in snapshot["underlyings"].items()}
