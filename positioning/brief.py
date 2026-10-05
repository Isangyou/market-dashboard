"""결론(수치 기반) — 한 줄 요약 · 변화 포인트 · 리스크.

  line     CTA 주식(ES) 포지션 방향·규모·3년 백분위 + 전주 대비 변화
  changes  전주 스냅샷 대비 바뀐 항목만. 범주 3개(전환가 거리 · 옵션 · 선물 COT) 중
           변화 점수(|변화| / UNIT) ≥ 1인 범주를 점수 큰 순으로 최대 3개. 부호 전환은 +10점
  risk     현재가에서 가장 가까운 임계값(ES 신호 전환가 · SPX zero-gamma) 1개와 넘으면 생기는 일
  vs_prev  전주에 저장된 brief와 비교한 결과("변화 없음" 명시용)

해석·전망 문장 없음. 숫자와 '넘으면 기계적으로 바뀌는 것'만. 기준 단위는 UNIT에서 조정.
"""
from __future__ import annotations

from .report import _px, sg

UNIT = {
    "cta_pos": 5.0,    # ES CTA 포지션 %p
    "flip": 0.5,       # 전환가까지 거리 %p
    "gex": 5.0,        # SPX 35일 이내 GEX $bn/1%
    "skew": 1.0,       # SPX 25Δ 스큐 vp
    "iv": 1.0,         # SPX ATM IV30 %p
    "pc": 0.10,        # SPX P/C(OI)
    "zg": 0.5,         # SPX zero-gamma까지 거리 %p
    "cot_z": 1.0,      # COT 주간 변화 σ (cot.py chg_1w_z)
}
FLIP_BONUS = 10.0
GROUP_KO = {"lev": "레버리지펀드", "mm": "운용역(MM)", "am": "자산운용사", "dealer": "딜러"}


def _get(d, *ks):
    for k in ks:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _es(snap):
    return _get(snap, "cta", "assets", "ES")


def _spx(snap):
    return _get(snap, "options", "underlyings", "SPX")


def _dir(v):
    return "롱" if v > 0 else "숏" if v < 0 else "중립"


def _gex(u):
    return u.get("gex_near_usd_bn") if u.get("gex_near_usd_bn") is not None else u.get("gex_usd_bn")


def _zg_dist(u):
    if not u or not u.get("zero_gamma") or not u.get("spot"):
        return None
    return (u["zero_gamma"] / u["spot"] - 1) * 100


def _active_flips(es):
    """넘으면 신호 부호가 바뀌는 전환가만: +신호 & 아래 / −신호 & 위"""
    return [f for f in es.get("flips", []) if (f["signal"] > 0 and f["dist_pct"] < 0) or (f["signal"] < 0 and f["dist_pct"] > 0)]


# ── (1) 한 줄 요약 ──
def line(snap, prev):
    es = _es(snap)
    if not es:
        return {"text": "CTA 주식(ES) 데이터 없음", "changed": None}
    pos, pct = es["position_pct"], es["position_pctile_3y"]
    head = f"CTA 주식(ES) {_dir(pos)} {sg(pos, 0)}% · 3년 {pct:.0f}백분위"
    pes = _es(prev)
    if pes:
        d = pos - pes["position_pct"]
        tail = (f"전주 {sg(pes['position_pct'], 0)}% → {sg(d, 1)}%p, 백분위 {pes['position_pctile_3y']:.0f}→{pct:.0f}")
        changed = abs(d) >= UNIT["cta_pos"] or _dir(pos) != _dir(pes["position_pct"])
    else:
        d = es.get("position_chg_1w_pp")
        tail = f"모델 기준 1주 변화 {sg(d, 1)}%p, 전주 스냅샷 없음"
        changed = None
    if changed is False:
        tail += f" — 방향·규모 변화 없음(±{UNIT['cta_pos']:.0f}%p 미만)"
    return {"text": f"{head} ({tail})", "changed": changed, "pos": pos, "pctile": pct}


# ── (2) 변화 포인트 ──
def _chg_flip(es, pes):
    if not es or not pes:
        return None
    pf = {f["lookback"]: f for f in pes.get("flips", [])}
    score, bits = 0.0, []
    for f in es.get("flips", []):
        p = pf.get(f["lookback"])
        if p and (f["signal"] > 0) != (p["signal"] > 0):
            score += FLIP_BONUS
            bits.append(f"{f['lookback']}일 신호 {'매수' if p['signal'] > 0 else '매도'}→{'매수' if f['signal'] > 0 else '매도'} 전환")
    act = _active_flips(es)
    if act:
        f = min(act, key=lambda x: abs(x["dist_pct"]))
        p = pf.get(f["lookback"])
        if p:
            dd = abs(f["dist_pct"]) - abs(p["dist_pct"])
            s = abs(dd) / UNIT["flip"]
            if s >= 1:
                score += s
                bits.append(f"ES {f['lookback']}일 {sg(p['dist_pct'], 1)}% → {sg(f['dist_pct'], 1)}% "
                            f"({abs(dd):.1f}%p {'멀어짐' if dd > 0 else '가까워짐'}, 전환가 {_px(p['flip_level'])} → {_px(f['flip_level'])})")
    return {"key": "flip", "label": "전환가 거리", "score": round(score, 2), "text": " · ".join(bits)} if bits else None


def _chg_options(u, pu):
    if not u or not pu:
        return None
    cand = []

    def add(name, cur, old, unit, fmt, sign_flip=False):
        if cur is None or old is None:
            return
        s = abs(cur - old) / unit + (FLIP_BONUS if sign_flip and (cur > 0) != (old > 0) else 0)
        if s >= 1:
            cand.append((s, f"{name} {fmt(old)} → {fmt(cur)}"))

    g, pg = _gex(u), _gex(pu)
    add("SPX 딜러 감마(35일)", g, pg, UNIT["gex"], lambda v: f"{sg(v, 1)}$bn", sign_flip=True)
    add("zero-gamma 거리", _zg_dist(u), _zg_dist(pu), UNIT["zg"], lambda v: f"{sg(v, 1)}%")
    add("25Δ 스큐", u.get("skew_25d_30d"), pu.get("skew_25d_30d"), UNIT["skew"], lambda v: f"{sg(v, 1)}vp")
    add("ATM IV30", u.get("atm_iv_30d"), pu.get("atm_iv_30d"), UNIT["iv"], lambda v: f"{v:.1f}%")
    add("P/C(OI)", u.get("pc_oi"), pu.get("pc_oi"), UNIT["pc"], lambda v: f"{v:.2f}")
    if not cand:
        return None
    cand.sort(key=lambda x: -x[0])
    return {"key": "options", "label": "옵션 포지셔닝", "score": round(cand[0][0], 2), "text": " · ".join(t for _, t in cand)}


def _chg_cot(cot, pcot):
    """새 COT가 공표된 주만. 헤드라인 그룹 주간 변화 σ 상위 2개 시장"""
    rd, prd = (cot or {}).get("report_date"), (pcot or {}).get("report_date")
    if not rd or not prd or rd == prd:
        return None
    cand = []
    for m in cot.get("markets", {}).values():
        g = m["groups"][m["headline"]]
        z = g.get("chg_1w_z")
        if z is not None and abs(z) / UNIT["cot_z"] >= 1:
            cand.append((abs(z) / UNIT["cot_z"], f"{m['name']} {GROUP_KO.get(m['headline'], m['headline'])} 순 {sg(g['net'] / 1000, 1)}k"
                                                f"(주간 {sg(g['chg_1w'] / 1000, 1)}k, {sg(z, 1)}σ)"))
    if not cand:
        return None
    cand.sort(key=lambda x: -x[0])
    return {"key": "cot", "label": f"선물 포지션(COT {rd[5:]})", "score": round(cand[0][0], 2),
            "text": " · ".join(t for _, t in cand[:2]) + (f" 외 {len(cand) - 2}개 시장 ≥1σ" if len(cand) > 2 else "")}


def changes(snap, prev):
    if not prev:
        return [], "전주 스냅샷 없음 — 비교 생략"
    out = [c for c in (_chg_flip(_es(snap), _es(prev)),
                       _chg_options(_spx(snap), _spx(prev)),
                       _chg_cot(snap.get("cot"), prev.get("cot"))) if c]
    out.sort(key=lambda c: -c["score"])
    notes = []
    rd, prd = _get(snap, "cot", "report_date"), _get(prev, "cot", "report_date")
    if rd and rd == prd:
        notes.append(f"COT 새 공표 없음({rd} 기준 동일)")
    if not out:
        notes.insert(0, "변화 없음 — 전환가 거리·옵션·선물 모두 기준 단위 미만")
    return out[:3], " · ".join(notes) or None


# ── (3) 리스크 ──
def risk(snap):
    es, u = _es(snap), _spx(snap)
    cand = []
    if es:
        sc = sorted(es.get("scenarios", []), key=lambda s: s["k"])
        basis = es["price"] - u["spot"] if u and u.get("spot") else None
        for f in _active_flips(es):
            down = f["dist_pct"] < 0
            spx = f" · SPX 약 {_px(f['flip_level'] - basis)}" if basis is not None else ""
            # 전환가를 넘어서는 첫 1주 시나리오의 포지션 변화
            beyond = [s for s in sc if s["k"] != 0 and (s["price"] <= f["flip_level"] if down else s["price"] >= f["flip_level"])]
            beyond = max(beyond, key=lambda s: s["k"]) if down and beyond else (min(beyond, key=lambda s: s["k"]) if beyond else None)
            scen = f", 1주 {sg(beyond['k'], 0)}σ({_px(beyond['price'])})면 포지션 {sg(beyond['chg_pp'], 0)}%p" if beyond else ""
            cand.append({"key": f"flip{f['lookback']}", "dist_pct": f["dist_pct"],
                         "text": f"ES {f['lookback']}일 전환가 {_px(f['flip_level'])} ({sg(f['dist_pct'], 1)}%{spx}) → "
                                 f"{'하회' if down else '상회'} 시 {f['lookback']}일 신호 {'매도' if down else '매수'} 전환, "
                                 f"CTA 주식 {'롱 축소' if down else '숏 축소'} 시작{scen}"})
    zd = _zg_dist(u)
    if zd is not None:
        below = zd < 0
        cand.append({"key": "zero_gamma", "dist_pct": zd,
                     "text": f"SPX zero-gamma {_px(u['zero_gamma'])} ({sg(zd, 1)}%) → "
                             + ("하회 시 딜러 음(−)감마: 하락에 매도 헤지가 붙어 변동성 확대 구간" if below
                                else "상회 시 딜러 양(+)감마 복귀: 헤지가 움직임을 줄이는 구간")})
    if not cand:
        return None
    return min(cand, key=lambda c: abs(c["dist_pct"]))


# ── 조립 + 전주 결론과 비교 ──
def build(snap, prev):
    ln = line(snap, prev)
    ch, note = changes(snap, prev)
    rk = risk(snap)
    pb = (prev or {}).get("brief")
    vs = {}
    if pb:
        prk = pb.get("risk") or {}
        if rk and prk.get("key") == rk["key"]:
            vs["risk"] = f"지난주와 같은 임계값 (거리 {sg(prk['dist_pct'], 1)}% → {sg(rk['dist_pct'], 1)}%)"
        elif rk:
            vs["risk"] = f"지난주 가장 가까운 임계값은 {prk.get('label') or prk.get('key', '–')} ({sg(prk.get('dist_pct'), 1)}%)"
        vs["unchanged"] = ln.get("changed") is False and not ch and bool(rk) and prk.get("key") == rk["key"]
    if rk:
        rk["label"] = rk["text"].split(" (")[0]
    return {"line": ln, "changes": ch, "changes_note": note, "risk": rk, "vs_prev": vs,
            "prev_week": (prev or {}).get("week"), "prev_brief": _compact(pb)}


def _compact(b):
    """전주 결론 원문만 보관(화면 '지난주 결론' 비교용). 재귀 저장 방지로 prev_brief는 빼고"""
    if not b:
        return None
    return {"line": b["line"]["text"], "changes": [c["text"] for c in b.get("changes", [])],
            "changes_note": b.get("changes_note"), "risk": (b.get("risk") or {}).get("text")}


def to_lines(b):
    """마크다운·로그용 평문 3블록"""
    out = [("요약", [b["line"]["text"] + (" · **지난주 결론과 변화 없음**" if b["vs_prev"].get("unchanged") else "")])]
    ch = [f"{c['label']}: {c['text']}" for c in b["changes"]]
    if b.get("changes_note"):
        ch.append(b["changes_note"])
    out.append(("변화 포인트", ch))
    rk = [b["risk"]["text"]] if b.get("risk") else ["임계값 데이터 없음"]
    if b["vs_prev"].get("risk"):
        rk.append(b["vs_prev"]["risk"])
    out.append(("리스크", rk))
    return out
