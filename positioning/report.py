"""주간 스냅샷 → 블록별 근거 수치 · CTA×COT 교차 · Notion 붙여넣기용 마크다운.

결론(요약·변화 포인트·리스크)은 brief.py. 여기 문장은 수치를 그대로 옮긴 근거 목록. 임계값은 THRESH에서 조정.
"""
from __future__ import annotations

THRESH = {
    "pctile_hi": 90, "pctile_lo": 10,     # COT 극단 백분위
    "z_hi": 2.0,                          # COT 3년 z-score 극단
    "chg_z": 2.0,                         # COT 주간 변화 이례(주간 변화 표준편차 배수)
    "cta_pctile_hi": 85, "cta_pctile_lo": 15,
    "flip_near_sigma": 1.0,               # 1주 σ 이내 flip → '근접'
}


def fmt_num(v, d=0, sign=False):
    if v is None:
        return "–"
    v = round(float(v), d) + 0.0  # −0 방지
    s = f"{v:+,.{d}f}" if sign else f"{v:,.{d}f}"
    return s


def sg(v, d=0):
    """부호 포함 숫자. 반올림 후 0이면 부호 없이 (−0.00 방지)"""
    if v is None:
        return "–"
    r = round(float(v), d) + 0.0
    return f"{r:,.{d}f}" if r == 0 else f"{r:+,.{d}f}"


def fmt_k(v, sign=True):
    """계약 수 → 'k' 표기"""
    if v is None:
        return "–"
    return (f"{sg(v / 1000, 1)}k" if sign else f"{v / 1000:,.1f}k")


def _px(v):
    if v is None:
        return "–"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 10:
        return f"{v:,.2f}"
    return f"{v:,.4f}"


def cta_bullets(cta: dict) -> list[dict]:
    A = cta.get("assets", {})
    C = cta.get("classes", {})
    out = []
    if "주식" in C:
        c = C["주식"]
        head = f"CTA 주식 {_dir(c['position_pct'])} {abs(c['position_pct']):.0f}% (전주 대비 {sg(c['chg_1w_pp'], 0)}%p)"
        subs = []
        es = A.get("ES")
        if es:
            down = next(s for s in es["scenarios"] if s["k"] == -2)
            up = next(s for s in es["scenarios"] if s["k"] == 2)
            subs.append(f"ES {sg(es['position_pct'], 0)}% · 3년 {es['position_pctile_3y']:.0f}백분위 · 실현변동성 {es['vol_ann_pct']:.1f}%(3년 중앙값 {es['vol_ref_pct']:.1f}%)")
            if es.get("composite_flip"):
                subs.append(f"ES 종합 신호 전환가 {_px(es['composite_flip'])} (현재 {_px(es['price'])} 대비 {sg(es['composite_flip_dist_pct'], 1)}%)")
            near = [f for f in es["flips"] if abs(f["dist_sigma"]) <= THRESH["flip_near_sigma"]]
            if near:
                subs.append("1주 σ 이내 전환 룩백: " + ", ".join(f"{f['lookback']}일 {_px(f['flip_level'])}({sg(f['dist_pct'], 1)}%)" for f in near))
            asym = "하방 비대칭(매도 여력 > 매수 여력)" if abs(down["chg_pp"]) > abs(up["chg_pp"]) * 1.5 else (
                "상방 비대칭(매수 여력 > 매도 여력)" if abs(up["chg_pp"]) > abs(down["chg_pp"]) * 1.5 else "대칭")
            subs.append(f"1주 −2σ({_px(down['price'])}) {sg(down['chg_pp'], 0)}%p / +2σ({_px(up['price'])}) {sg(up['chg_pp'], 0)}%p → {asym}")
        out.append({"kind": "cta_equity", "head": head, "subs": subs})
    others = []
    for cls in ("금리", "FX", "원자재"):
        if cls in C:
            others.append(f"{cls} {sg(C[cls]['position_pct'], 0)}%({sg(C[cls]['chg_1w_pp'], 0)}%p)")
    ext = [a for a in A.values() if a["position_pctile_3y"] >= THRESH["cta_pctile_hi"] or a["position_pctile_3y"] <= THRESH["cta_pctile_lo"]]
    subs = []
    if ext:
        subs.append("3년 극단 포지션: " + ", ".join(f"{a['name']} {sg(a['position_pct'], 0)}%({a['position_pctile_3y']:.0f}p)" for a in sorted(ext, key=lambda a: -abs(a['position_pct']))))
    big = sorted([a for a in A.values() if a["position_chg_1w_pp"] is not None], key=lambda a: -abs(a["position_chg_1w_pp"]))[:3]
    if big:
        subs.append("주간 변화 상위: " + ", ".join(f"{a['name']} {sg(a['position_chg_1w_pp'], 0)}%p" for a in big))
    if others:
        out.append({"kind": "cta_others", "head": "CTA 자산군: " + " · ".join(others), "subs": subs})
    return out


def options_bullets(opt: dict, prev: dict | None) -> list[dict]:
    U = opt.get("underlyings", {})
    P = (prev or {}).get("underlyings", {})
    out = []
    spx = U.get("SPX")
    if spx and spx.get("gex_usd_bn") is not None:
        g = spx["gex_usd_bn"]
        regime = "양(+)감마 — 딜러 역추세 헤지로 변동성 억제 구간" if g > 0 else "음(−)감마 — 딜러 순추세 헤지로 변동성 확대 구간"
        near = spx.get("gex_near_usd_bn")
        head = f"SPX 딜러 감마 {sg(g, 1)}$bn/1%(전 만기)" + (f" · 35일 이내 {sg(near, 1)}$bn" if near is not None else "") + f" → {regime}"
        subs = []
        zg = spx.get("zero_gamma")
        if zg:
            subs.append(f"zero-gamma {_px(zg)} (현재 {_px(spx['spot'])} 대비 {sg((zg / spx['spot'] - 1) * 100, 1)}%)")
        walls = []
        if spx.get("call_gamma_wall"):
            walls.append(f"콜 벽 {_px(spx['call_gamma_wall'])}")
        if spx.get("put_gamma_wall"):
            walls.append(f"풋 벽 {_px(spx['put_gamma_wall'])}")
        if walls:
            subs.append(" · ".join(walls) + " (행사가별 순GEX 최대·최소)")
        if spx.get("gamma_expiring_by_opex_pct") is not None:
            subs.append(f"{spx['next_opex']} 월물 만기까지 |감마| {spx['gamma_expiring_by_opex_pct']:.0f}% 소멸")
        p = P.get("SPX")
        if p and p.get("gex_usd_bn") is not None:
            subs.append(f"전주 GEX {sg(p['gex_usd_bn'], 1)}$bn → {sg(g, 1)}$bn")
        out.append({"kind": "gamma", "head": head, "subs": subs})
    rows = []
    for k in ("SPX", "NDX", "RUT", "VIX", "TLT", "GLD", "USO"):
        u = U.get(k)
        if not u:
            continue
        p = P.get(k, {})
        bits = [f"P/C(OI) {fmt_num(u.get('pc_oi'), 2)}"]
        if p.get("pc_oi") is not None and u.get("pc_oi") is not None:
            bits[-1] += f"({sg(u['pc_oi'] - p['pc_oi'], 2)})"
        if u.get("skew_25d_30d") is not None:
            s = f"25Δ스큐 {sg(u['skew_25d_30d'], 1)}vp"
            if p.get("skew_25d_30d") is not None:
                s += f"({sg(u['skew_25d_30d'] - p['skew_25d_30d'], 1)})"
            bits.append(s)
        if u.get("atm_iv_30d") is not None:
            bits.append(f"ATM IV30 {u['atm_iv_30d']:.1f}%")
        rows.append(f"{k}: " + " · ".join(bits))
    if rows:
        out.append({"kind": "options", "head": "콜/풋 포지셔닝 (괄호: 전주 대비)", "subs": rows})
    return out


def cot_bullets(cot: dict) -> list[dict]:
    M = cot.get("markets", {})
    out = []
    es = M.get("ES")
    if es:
        lev, am = es["groups"]["lev"], es["groups"]["am"]
        out.append({
            "kind": "cot",
            "head": f"ES 레버리지펀드 순 {fmt_k(lev['net'])}(주간 {fmt_k(lev['chg_1w'])}) · 자산운용사 순 {fmt_k(am['net'])}(주간 {fmt_k(am['chg_1w'])})",
            "subs": [f"레버리지펀드 3년 {lev['pctile_3y']:.0f}백분위(z {fmt_num(lev['z_3y'], 1, True)}), 자산운용사 {am['pctile_3y']:.0f}백분위(z {fmt_num(am['z_3y'], 1, True)})",
                     f"기준일 {es['report_date']}(화) · OI {fmt_k(es['oi'], False)}({fmt_k(es['oi_chg_1w'])})"],
        })
    ext, jumps = [], []
    for m in M.values():
        g = m["groups"][m["headline"]]
        if g["pctile_3y"] is not None and (g["pctile_3y"] >= THRESH["pctile_hi"] or g["pctile_3y"] <= THRESH["pctile_lo"] or abs(g["z_3y"] or 0) >= THRESH["z_hi"]):
            ext.append(f"{m['name']} {fmt_k(g['net'])}({g['pctile_3y']:.0f}p, z {fmt_num(g['z_3y'], 1, True)})")
        if g.get("chg_1w_z") is not None and abs(g["chg_1w_z"]) >= THRESH["chg_z"]:
            jumps.append(f"{m['name']} {fmt_k(g['chg_1w'])}({sg(g['chg_1w_z'], 1)}σ)")
    subs = []
    if ext:
        subs.append("3년 극단(투기 순포지션): " + ", ".join(ext))
    if jumps:
        subs.append("주간 변화 이례(≥2σ): " + ", ".join(jumps))
    if subs:
        out.append({"head": "선물 투기 포지션(Lev Funds·Managed Money) 극단·급변", "subs": subs})
    return out


# CTA 자산 ↔ COT 시장 매핑 (크라우딩 교차 확인)
CROSS = {"ES": "ES", "NQ": "NQ", "RTY": "RTY", "ZT": "ZT", "ZF": "ZF", "ZN": "ZN", "ZB": "ZB",
         "DX": "DX", "6E": "6E", "6J": "6J", "6B": "6B", "6A": "6A",
         "CL": "CL", "NG": "NG", "GC": "GC", "SI": "SI", "HG": "HG"}


def crowding(cta: dict, cot: dict) -> list[dict]:
    rows = []
    A, M = cta.get("assets", {}), cot.get("markets", {})
    for a, m in CROSS.items():
        if a not in A or m not in M:
            continue
        ca, cm = A[a], M[m]
        g = cm["groups"][cm["headline"]]
        flag = None
        if ca["class"] == "금리":
            # 국채 선물 Lev Funds 숏은 현·선 베이시스 트레이드가 대부분 → 방향성 비교 무의미
            rows.append({"key": a, "name": ca["name"], "class": ca["class"],
                         "cta_pos": ca["position_pct"], "cta_pctile": ca["position_pctile_3y"],
                         "cot_group": g["name"], "cot_pctile": g["pctile_3y"], "cot_z": g["z_3y"],
                         "flag": None, "note": "베이시스 트레이드 영향 — 판정 제외"})
            continue
        if ca["position_pct"] > 0 and ca["position_pctile_3y"] >= 80 and (g["pctile_3y"] or 0) >= 80:
            flag = "롱 크라우딩"
        elif ca["position_pct"] < 0 and ca["position_pctile_3y"] <= 20 and (g["pctile_3y"] or 100) <= 20:
            flag = "숏 크라우딩"
        elif (ca["position_pct"] > 0) != ((g["z_3y"] or 0) > 0) and abs(g["z_3y"] or 0) >= 1:
            flag = "CTA·COT 방향 괴리"
        rows.append({"key": a, "name": ca["name"], "class": ca["class"],
                     "cta_pos": ca["position_pct"], "cta_pctile": ca["position_pctile_3y"],
                     "cot_group": g["name"], "cot_pctile": g["pctile_3y"], "cot_z": g["z_3y"],
                     "flag": flag})
    return rows


def build_conclusion(snap: dict, prev: dict | None) -> list[dict]:
    cb = []
    cb += cta_bullets(snap.get("cta", {}))
    cb += options_bullets(snap.get("options", {}), (prev or {}).get("options"))
    cb += cot_bullets(snap.get("cot", {}))
    flags = [r for r in snap.get("crowding", []) if r["flag"]]
    if flags:
        cb.append({"kind": "cross", "head": "교차 확인(CTA 모델 × COT)",
                   "subs": [f"{r['name']}: {r['flag']} (CTA {sg(r['cta_pos'], 0)}%/{r['cta_pctile']:.0f}p · COT {r['cot_pctile']:.0f}p)" for r in flags]})
    return cb


def _dir(v):
    return "롱" if v >= 0 else "숏"


def to_markdown(snap: dict) -> str:
    """Notion 위클리 노트 [매크로] 섹션에 붙여넣는 형식: 굵은 헤드 + 중첩 불릿."""
    from .brief import to_lines
    lines = [f"**[포지셔닝] {snap['week_label']}**"]
    if snap.get("brief"):
        for title, items in to_lines(snap["brief"]):
            lines.append(f"- **{title}**")
            for s in items:
                lines.append(f"    - {s}")
    lines.append("- **근거 수치**")
    for b in snap.get("conclusion", []):
        lines.append(f"    - {b['head']}")
        for s in b["subs"]:
            lines.append(f"        - {s}")
    src = snap.get("asof", {})
    lines.append(f"- 기준: CTA 모델 {src.get('cta', '–')} 종가 · 옵션 CBOE {src.get('options', '–')} · COT {src.get('cot', '–')}(화)")
    return "\n".join(lines)
