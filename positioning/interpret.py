"""결론 해석 문장 — 수치 상태(조건) → 의미 문장. 규칙 기반, 전망·목표가 없음.

원칙
- "무엇이 어떤 상태인지 / 그 상태에서 기계적으로 어떤 수급이 나오는지"만 서술
- 조건에 걸리지 않으면 문장을 만들지 않음 (억지 해석 금지)
- 임계값은 T에서 조정
"""
from __future__ import annotations

T = {
    "cta_long_hi": 60, "cta_short_hi": -60,      # CTA 포지션 '높음' 기준(%)
    "asym": 1.5,                                  # 시나리오 비대칭 배수
    "flip_near_pct": 1.5,                         # 전환가 '근접' 기준(%)
    "zg_near_pct": 1.5,                           # zero-gamma '근접' 기준(%)
    "skew_lo": 4.0, "skew_hi": 7.0,               # SPX 25Δ 스큐(vp)
    "iv_lo": 13.0, "iv_hi": 22.0,                 # SPX ATM IV30(%)
    "pc_hi": 1.5,                                 # 지수 P/C(OI) 높음
    "pct_hi": 85, "pct_lo": 15,                   # 3년 백분위 극단
}


def _p(v):
    return "–" if v is None else (f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}")


def _es_to_spx(snap):
    """ES 선물가격 → SPX 지수 환산용 베이시스(같은 금요일 종가 기준). 없으면 None."""
    es = snap.get("cta", {}).get("assets", {}).get("ES")
    spx = snap.get("options", {}).get("underlyings", {}).get("SPX")
    if not es or not spx:
        return None
    return es["price"] - spx["spot"]


def view_cta_equity(snap):
    A = snap.get("cta", {}).get("assets", {})
    es = A.get("ES")
    if not es:
        return None
    pos = es["position_pct"]
    down = next(s for s in es["scenarios"] if s["k"] == -2)["chg_pp"]
    up = next(s for s in es["scenarios"] if s["k"] == 2)["chg_pp"]
    out = []
    if pos >= T["cta_long_hi"]:
        out.append("주식 추세추종 자금은 이미 롱 비중이 높은 상태 → 추가로 살 여력보다 팔 여력이 큼")
    elif pos <= T["cta_short_hi"]:
        out.append("주식 추세추종 자금은 숏 비중이 높은 상태 → 반등 시 숏커버(매수) 여력이 큼")
    else:
        out.append("주식 추세추종 포지션은 중간 수준 → 방향이 정해지면 양쪽 모두 추가 매매 여력 있음")
    if abs(down) > abs(up) * T["asym"]:
        out.append(f"하락 시 매도(−2σ {down:+.0f}%p)가 상승 시 매수(+2σ {up:+.0f}%p)보다 커서, 하락이 나오면 CTA 매도가 낙폭을 키우는 구조")
    elif abs(up) > abs(down) * T["asym"]:
        out.append(f"상승 시 매수(+2σ {up:+.0f}%p)가 하락 시 매도보다 커서, 상승이 나오면 CTA 추격 매수가 붙는 구조")
    # 신호가 실제로 뒤집히는 방향만: 현재 +신호 & 전환가가 아래 → 매도 전환 / −신호 & 위 → 매수 전환
    near = [f for f in es["flips"] if abs(f["dist_pct"]) <= T["flip_near_pct"]
            and ((f["signal"] > 0 and f["dist_pct"] < 0) or (f["signal"] < 0 and f["dist_pct"] > 0))]
    if near:
        f = min(near, key=lambda x: abs(x["dist_pct"]))
        basis = _es_to_spx(snap)
        spx_lvl = f" (SPX 환산 약 {_p(f['flip_level'] - basis)})" if basis is not None else ""
        side = "하회" if f["dist_pct"] < 0 else "상회"
        out.append(f"{f['lookback']}일 신호 전환가 ES {_p(f['flip_level'])}{spx_lvl}가 {abs(f['dist_pct']):.1f}% 거리 → {side} 시 첫 기계적 {'매도' if side == '하회' else '매수'} 신호")
    if es["vol_ann_pct"] < es["vol_ref_pct"] * 0.9:
        out.append(f"실현변동성({es['vol_ann_pct']:.1f}%)이 평소({es['vol_ref_pct']:.1f}%)보다 낮아 레버리지가 높게 유지 중 → 변동성이 튀면 가격과 무관하게 포지션이 기계적으로 줄어듦")
    return out


def view_cta_others(snap):
    A = snap.get("cta", {}).get("assets", {})
    out = []
    bonds = [a for a in A.values() if a["class"] == "금리"]
    if bonds and all(a["position_pct"] <= T["cta_short_hi"] for a in bonds):
        pct = max(a["position_pctile_3y"] for a in bonds)
        out.append(f"미국채 선물 전 구간 숏이 3년 최대권(백분위 ≤{pct:.0f}) → 금리 상승 추세에 베팅한 포지션이 꽉 찬 상태. 금리가 꺾이면(채권 반등) 숏커버 매수가 한꺼번에 나올 수 있음")
    elif bonds and all(a["position_pct"] >= T["cta_long_hi"] for a in bonds):
        out.append("미국채 선물 롱이 높은 상태 → 금리 반등(채권 하락) 시 매도 물량 출회 가능")
    usd = A.get("DX")
    fx_short = [a["name"] for a in A.values() if a["class"] == "FX" and a["key"] != "DX" and a["position_pct"] < -30]
    if usd and usd["position_pct"] > 30 and fx_short:
        out.append(f"달러 롱 / {', '.join(fx_short)} 숏 → 달러 강세 추세 추종 중. 달러가 약해지면 이 통화들에서 숏커버가 나옴")
    ext_long = [a["name"] for a in A.values() if a["class"] == "원자재" and a["position_pctile_3y"] >= T["pct_hi"] and a["position_pct"] > 0]
    if ext_long:
        out.append(f"원자재 중 {', '.join(ext_long)}는 롱이 3년 상위권 → 추세가 꺾이면 차익실현 매도가 집중되기 쉬움")
    return out


def view_gamma(snap):
    spx = snap.get("options", {}).get("underlyings", {}).get("SPX")
    if not spx or spx.get("gex_usd_bn") is None:
        return None
    g = spx.get("gex_near_usd_bn") if spx.get("gex_near_usd_bn") is not None else spx["gex_usd_bn"]
    out = []
    if g > 0:
        out.append("딜러가 양(+)감마 → 오르면 팔고 내리면 사는 헤지를 하므로 지수 움직임이 눌리는(변동성 완충) 환경")
    else:
        out.append("딜러가 음(−)감마 → 오르면 사고 내리면 파는 헤지를 하므로 움직임이 커지는(변동성 증폭) 환경")
    zg = spx.get("zero_gamma")
    if zg:
        d = (zg / spx["spot"] - 1) * 100
        if abs(d) <= T["zg_near_pct"]:
            out.append(f"다만 zero-gamma {_p(zg)}가 현재가 대비 {d:+.1f}%로 가까움 → 이 아래로 내려가면 완충 효과가 사라지고 변동성이 커지는 구간으로 바뀜")
    cw, pw = spx.get("call_gamma_wall"), spx.get("put_gamma_wall")
    if cw and pw:
        out.append(f"콜 벽 {_p(cw)}은 상단에서 딜러 매도가 몰리는 가격(저항), 풋 벽 {_p(pw)}은 하단 지지로 작동하기 쉬운 가격")
    if spx.get("gamma_expiring_by_opex_pct") and spx["gamma_expiring_by_opex_pct"] >= 40:
        out.append(f"{spx['next_opex']} 월물 만기에 감마의 {spx['gamma_expiring_by_opex_pct']:.0f}%가 사라짐 → 만기 이후엔 완충력이 약해질 수 있음")
    return out


def view_options(snap):
    spx = snap.get("options", {}).get("underlyings", {}).get("SPX")
    if not spx:
        return None
    out = []
    sk, iv = spx.get("skew_25d_30d"), spx.get("atm_iv_30d")
    if sk is not None and sk < T["skew_lo"] and iv is not None and iv < T["iv_lo"]:
        out.append(f"SPX 변동성({iv:.1f}%)과 풋 프리미엄(스큐 {sk:+.1f}vp)이 모두 낮음 → 하락 대비 보험이 싸다 = 시장이 하락을 크게 걱정하지 않는 상태(안일함). 충격이 오면 풋 매수가 몰리며 변동성이 급등하기 쉬움")
    elif sk is not None and sk > T["skew_hi"]:
        out.append(f"풋 프리미엄(스큐 {sk:+.1f}vp)이 높음 → 하락 헤지 수요가 강함. 이미 보험을 많이 산 상태라 실제 하락 시 추가 패닉 매도는 덜할 수 있음")
    elif iv is not None and iv > T["iv_hi"]:
        out.append(f"SPX 변동성 {iv:.1f}%로 높음 → 불안 국면")
    vix = snap.get("options", {}).get("underlyings", {}).get("VIX")
    if vix and vix.get("pc_oi") is not None and vix["pc_oi"] < 0.5:
        out.append(f"VIX 옵션은 콜 우위(P/C {vix['pc_oi']:.2f}) → 변동성 급등에 대비한 콜 헤지가 쌓여 있음")
    return out


def view_cot(snap):
    M = snap.get("cot", {}).get("markets", {})
    es = M.get("ES")
    out = []
    if es:
        lev, am = es["groups"]["lev"], es["groups"]["am"]
        if T["pct_lo"] < (lev["pctile_3y"] or 50) < T["pct_hi"] and T["pct_lo"] < (am["pctile_3y"] or 50) < T["pct_hi"]:
            out.append("S&P 선물은 헤지펀드(순숏)·자산운용사(순롱) 모두 3년 평균권 → 선물 포지션 쏠림은 크지 않음")
        oi_chg = es.get("oi_chg_1w") or 0
        rd = es["report_date"]
        if oi_chg < -0.15 * (es["oi"] - oi_chg) and rd[5:7] in ("03", "06", "09", "12"):
            out.append(f"OI 급감({oi_chg / 1000:+,.0f}k)은 분기 만기 롤오버로 인한 것 → 포지션 청산 신호로 보지 않음")
    bonds = [m for k, m in M.items() if m["class"] == "금리"]
    if bonds and any(m["groups"]["lev"]["net"] < 0 for m in bonds):
        out.append("국채 선물 레버리지펀드 대규모 숏은 대부분 현·선 베이시스 트레이드(현물 롱+선물 숏) → 금리 방향 베팅으로 읽지 않음")
    return out


def view_cross(snap):
    rows = [r for r in snap.get("crowding", []) if r.get("flag")]
    out = []
    lc = [r["name"] for r in rows if r["flag"] == "롱 크라우딩"]
    sc = [r["name"] for r in rows if r["flag"] == "숏 크라우딩"]
    if lc:
        out.append(f"{', '.join(lc)}: CTA·투기세력이 같은 방향(롱)으로 몰림 → 새로 살 사람이 적고, 되돌림 시 매도가 겹침")
    if sc:
        out.append(f"{', '.join(sc)}: 숏이 한쪽으로 몰림 → 반등 시 숏커버 랠리 위험")
    return out


VIEWS = {"cta_equity": view_cta_equity, "cta_others": view_cta_others, "gamma": view_gamma,
         "options": view_options, "cot": view_cot, "cross": view_cross}


def summary(snap) -> list[str]:
    """맨 위 한눈 요약 (최대 4줄)."""
    out = []
    A = snap.get("cta", {}).get("assets", {})
    spx = snap.get("options", {}).get("underlyings", {}).get("SPX") or {}
    es = A.get("ES")
    # 1) 핵심 가격대: CTA 단기 전환가(SPX 환산)와 zero-gamma가 겹치는지
    if es and spx.get("zero_gamma"):
        basis = _es_to_spx(snap)
        cand = [f for f in es["flips"] if f["signal"] > 0 and f["dist_pct"] < 0]
        f20 = min(cand, key=lambda x: abs(x["dist_pct"])) if cand else None
        g = spx.get("gex_near_usd_bn") if spx.get("gex_near_usd_bn") is not None else spx.get("gex_usd_bn")
        if basis is not None and f20 and (g or 0) > 0 and spx["zero_gamma"] < spx["spot"]:
            flip_spx = f20["flip_level"] - basis
            zg = spx["zero_gamma"]
            if abs(flip_spx / zg - 1) * 100 <= 0.5:
                lo, hi = sorted([flip_spx, zg])
                out.append(f"SPX {_p(lo)}~{_p(hi)}가 이번 주 핵심 가격대: CTA {f20['lookback']}일 매도 전환과 딜러 감마 음전환이 겹침 → 이 아래로 밀리면 기계적 매도와 변동성 확대가 동시에 붙을 수 있음")
    # 2) 주식 포지셔닝 상태
    v = view_cta_equity(snap) or []
    if v:
        out.append(v[0] + (" · " + v[1] if len(v) > 1 and "구조" in v[1] else ""))
    # 3) 옵션 심리
    vo = view_options(snap) or []
    if vo:
        out.append(vo[0].split(" 충격이")[0].rstrip("."))
    # 4) 채권·크로스에셋 쏠림
    vc = view_cta_others(snap) or []
    if vc:
        out.append(vc[0].split(". ")[0])
    return out[:4]
