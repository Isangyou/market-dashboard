"""결론(수치 기반) — 데이터 성격 순 3블록 + 종합.

  blocks[0] cot      관측 포지션(CFTC COT): ES + 주간 σ ≥ UNIT 시장의 레버리지펀드·자산운용사(원자재는 운용역) 순포지션·주간 변화·σ
  blocks[1] options  관측 시장 상태(옵션): SPX ATM IV30 · 25Δ 스큐 · P/C · 최대 콜·풋 OI 행사가, 전주 대비 수치 + NDX·RUT·VIX 한 줄
  blocks[2] model    추정(모델): 딜러 감마 · zero-gamma · CTA 포지션 · CTA 전환가 — 항목마다 가정 한 줄, 방향·레벨 위주
                     + 가장 가까운 기계적 임계값(risk) 한 줄
  각 블록 easy      '쉽게 말하면'(easy.py). 관측 블록은 관측값만, 추정 블록은 '모델상으로는 ~'
  overall           '관측: …. 모델상으로는 ….'
  unchanged         블록별 전주 대비 기준 단위(UNIT) 미만이면 True → 화면에 '지난주와 변화 없음'

해석·전망 문장 없음. 숫자와 '넘으면 기계적으로 바뀌는 것'만. 기준 단위는 UNIT에서 조정.
"""
from __future__ import annotations

from . import easy
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


# ── 블록 ──
GROUP_SHOW = {"TFF": ("lev", "am"), "DIS": ("mm",)}
COT_MAX = 5  # ES 포함 표시 시장 수


def _cot_groups(m):
    gs = GROUP_SHOW["TFF"] if "lev" in m["groups"] else GROUP_SHOW["DIS"]
    return [(g, m["groups"][g]) for g in gs if g in m["groups"]]


def _cot_item(m):
    parts = []
    for g, x in _cot_groups(m):
        mv = easy._move(x["net"], x["chg_1w"])[0].split("(")[0]
        parts.append(f"{GROUP_KO.get(g, g)}: {mv}, 주간 {sg(x['chg_1w'] / 1000, 1)}k({sg(x.get('chg_1w_z'), 1)}σ) → 순 {sg(x['net'] / 1000, 1)}k")
    return f"{m['name']} — " + " · ".join(parts)


def cot_movers(cot, unit=UNIT["cot_z"]):
    """(|σ|, 시장키, 그룹키) — 표시 그룹 중 |주간 σ| ≥ unit, 큰 순"""
    out = []
    for k, m in (cot or {}).get("markets", {}).items():
        for g, x in _cot_groups(m):
            if x.get("chg_1w_z") is not None and abs(x["chg_1w_z"]) >= unit:
                out.append((abs(x["chg_1w_z"]), k, g))
    return sorted(out, key=lambda t: -t[0])


def block_cot(snap, prev):
    c, pc = snap.get("cot") or {}, (prev or {}).get("cot") or {}
    rd, prd = c.get("report_date"), pc.get("report_date")
    M = c.get("markets") or {}
    blk = {"key": "cot", "title": "관측 포지션 (CFTC COT)", "kind": "observed",
           "asof": f"{rd[5:].replace('-', '/')}(화) 포지션" if rd else None, "items": [], "note": None}
    if not M:
        blk.update(note="COT 데이터 없음", unchanged=None)
        return blk
    keys = ["ES"] if "ES" in M else []
    for _, k, _ in cot_movers(c):
        if k not in keys and len(keys) < COT_MAX:
            keys.append(k)
    blk["items"] = [{"text": _cot_item(M[k])} for k in keys]
    rest = {k for _, k, _ in cot_movers(c)} - set(keys)
    notes = []
    if rest:
        notes.append(f"그 외 주간 ≥{UNIT['cot_z']:.0f}σ {len(rest)}개 시장(아래 표)")
    if prd and rd == prd:
        notes.insert(0, f"새 공표 없음 — {rd} 기준 그대로")
        blk["unchanged"] = True
    else:
        blk["unchanged"] = not cot_movers(c) if prd else None
        if blk["unchanged"]:
            notes.insert(0, f"모든 시장 주간 변화 {UNIT['cot_z']:.0f}σ 미만")
    blk["note"] = " · ".join(notes) or None
    return blk


def _dv(cur, old, d):
    return f"지난주 {old:.{d}f}, {sg(cur - old, d)}" if cur is not None and old is not None else "지난주 없음"


def block_options(snap, prev):
    u, pu = _spx(snap), _spx(prev) or {}
    wk = _get(snap, "options_week", "pc_vol_avg", "SPX")
    pwk = _get(prev, "options_week", "pc_vol_avg", "SPX")
    blk = {"key": "options", "title": "관측 시장 상태 (옵션 시장)", "kind": "observed",
           "asof": f"CBOE {_get(snap, 'asof', 'options') or '–'}", "items": [], "note": None}
    if not u:
        blk.update(note="옵션 데이터 없음", unchanged=None)
        return blk
    it = []
    if u.get("atm_iv_30d") is not None:
        old = pu.get("atm_iv_30d")
        it.append(f"SPX ATM IV30 {u['atm_iv_30d']:.1f}% (" + (f"지난주 {old:.1f}%, {sg(u['atm_iv_30d'] - old, 1)}%p" if old is not None else "지난주 없음") + ")")
    if u.get("skew_25d_30d") is not None:
        old = pu.get("skew_25d_30d")
        it.append(f"25Δ 스큐 {sg(u['skew_25d_30d'], 1)}vp (" + (f"지난주 {sg(old, 1)}vp, {sg(u['skew_25d_30d'] - old, 1)}vp" if old is not None else "지난주 없음") + ")")
    if u.get("pc_oi") is not None:
        t = f"P/C(OI) {u['pc_oi']:.2f} ({_dv(u['pc_oi'], pu.get('pc_oi'), 2)})"
        if wk is not None:
            t += f" · P/C(거래량, 주평균) {wk:.2f}" + (f" (지난주 {pwk:.2f})" if pwk is not None else "")
        it.append(t)
    cw, pw = u.get("call_oi_wall"), u.get("put_oi_wall")
    if cw or pw:
        dd = lambda k: f"{sg((k / u['spot'] - 1) * 100, 1)}%" if k else "–"
        t = (f"최대 OI 행사가(현재가 ±15%, 전 만기): 콜 {_px(cw)}({dd(cw)}) · 풋 {_px(pw)}({dd(pw)}) / 현재가 {_px(u['spot'])}")
        if pu.get("call_oi_wall") or pu.get("put_oi_wall"):
            t += f" (지난주 콜 {_px(pu.get('call_oi_wall'))} · 풋 {_px(pu.get('put_oi_wall'))})"
        it.append(t)
    U, PU = _get(snap, "options", "underlyings") or {}, _get(prev, "options", "underlyings") or {}
    oth = []
    for k in ("NDX", "RUT"):
        x, q = U.get(k), PU.get(k) or {}
        if x and x.get("atm_iv_30d") is not None:
            oth.append(f"{k} IV30 {x['atm_iv_30d']:.1f}%" + (f"({sg(x['atm_iv_30d'] - q['atm_iv_30d'], 1)})" if q.get("atm_iv_30d") is not None else ""))
    v, q = U.get("VIX"), PU.get("VIX") or {}
    if v and v.get("pc_oi") is not None:
        oth.append(f"VIX 옵션 P/C(OI) {v['pc_oi']:.2f}" + (f"({sg(v['pc_oi'] - q['pc_oi'], 2)})" if q.get("pc_oi") is not None else ""))
    if oth:
        it.append("그 외: " + " · ".join(oth))
    blk["items"] = [{"text": t} for t in it]
    if pu:
        small = all(a is None or b is None or abs(a - b) < unit for a, b, unit in (
            (u.get("atm_iv_30d"), pu.get("atm_iv_30d"), UNIT["iv"]), (u.get("skew_25d_30d"), pu.get("skew_25d_30d"), UNIT["skew"]),
            (u.get("pc_oi"), pu.get("pc_oi"), UNIT["pc"])))
        blk["unchanged"] = small and cw == pu.get("call_oi_wall") and pw == pu.get("put_oi_wall")
        if blk["unchanged"]:
            blk["note"] = f"IV·스큐 {UNIT['iv']:.0f}vp, P/C {UNIT['pc']:.2f} 미만 변화 · OI 집중 행사가 동일"
    else:
        blk["unchanged"] = None
    return blk


ASSUME = {
    "gamma": "딜러=고객 반대편(콜 롱·풋 숏) · 35일 이내 만기 · BS 감마 재계산",
    "zg": "같은 가정으로 가격대별 감마를 다시 계산해 부호가 바뀌는 가격 · 전 만기",
    "cta": "20·60·125·250일 추세추종 + 변동성 타기팅 복제 모델 (실제 CTA 포지션 아님)",
    "flip": "같은 모델에서 다음 주말 룩백 신호가 0이 되는 가격",
}


def block_model(snap, prev):
    es, pes = _es(snap), _es(prev)
    u, pu = _spx(snap), _spx(prev)
    blk = {"key": "model", "title": "추정 (모델 기반)", "kind": "model", "asof": None, "items": [], "note": None}
    it, same = [], []
    g = _gex(u) if u else None
    if g is not None:
        pg = _gex(pu) if pu else None
        side = "롱" if g > 0 else "숏"
        if pg is None:
            t = f"{side} 감마 · 규모 {sg(g, 0)}$bn/1%"
        elif (g > 0) != (pg > 0):
            t = f"{side} 감마 — 지난주 {'롱' if pg > 0 else '숏'} 감마에서 전환 · 규모 {sg(g, 0)}$bn/1% (지난주 {sg(pg, 0)})"
            same.append(False)
        else:
            t = f"{side} 감마 유지 · 규모 {sg(g, 0)}$bn/1% (지난주 {sg(pg, 0)})"
            same.append(abs(g - pg) < UNIT["gex"])
        it.append({"label": "딜러 감마", "assume": ASSUME["gamma"], "text": t})
    if u:
        zd, pzd = _zg_dist(u), _zg_dist(pu)
        if zd is not None:
            t = f"{_px(u['zero_gamma'])} — 지수({_px(u['spot'])})가 선 {'아래' if zd > 0 else '위'}, 선까지 {sg(zd, 1)}%"
            if pzd is not None:
                t += f" (지난주 {_px(pu['zero_gamma'])}, 지수가 선 {'아래' if pzd > 0 else '위'} {sg(pzd, 1)}%)"
                same.append(abs(zd - pzd) < UNIT["zg"])
        else:
            t = "현재가 ±12% 범위 안에 부호가 바뀌는 가격 없음"
        it.append({"label": "zero-gamma", "assume": ASSUME["zg"], "text": t})
    if es:
        pos, pct = es["position_pct"], es["position_pctile_3y"]
        t = f"ES {_dir(pos)} {abs(pos):.0f}% · 3년 {pct:.0f}백분위"
        if pes:
            d = pos - pes["position_pct"]
            word = "비슷" if abs(d) < UNIT["cta_pos"] else ("확대" if (d > 0) == (pos > 0) else "축소")
            if _dir(pos) != _dir(pes["position_pct"]):
                word = "방향 전환"
            t += f" (지난주 {sg(pes['position_pct'], 0)}%·{pes['position_pctile_3y']:.0f}백분위 → {word})"
            same.append(word == "비슷")
        it.append({"label": "CTA 포지션", "assume": ASSUME["cta"], "text": t})
        act = _active_flips(es)
        if act:
            act.sort(key=lambda x: abs(x["dist_pct"]))
            f = act[0]
            t = f"가장 가까운 {'매도' if f['dist_pct'] < 0 else '매수'} 전환선 {f['lookback']}일 {_px(f['flip_level'])}({sg(f['dist_pct'], 1)}%)"
            pf = {x["lookback"]: x for x in (pes or {}).get("flips", [])}.get(f["lookback"])
            if pf:
                t += f" (지난주 {sg(pf['dist_pct'], 1)}%)"
                same.append(abs(abs(f["dist_pct"]) - abs(pf["dist_pct"])) < UNIT["flip"])
            nxt = [x for x in act[1:] if (x["dist_pct"] < 0) == (f["dist_pct"] < 0)]
            if nxt:
                t += f" · 다음 {nxt[0]['lookback']}일 {_px(nxt[0]['flip_level'])}({sg(nxt[0]['dist_pct'], 1)}%)"
        else:
            t = "모든 룩백 신호가 이미 현재 방향 — 가까운 전환선 없음"
        it.append({"label": "CTA 전환가", "assume": ASSUME["flip"], "text": t})
    blk["items"] = it
    blk["unchanged"] = all(same) if same and prev else None
    return blk


# ── 조립 + 전주 결론과 비교 ──
def build(snap, prev):
    blocks = [block_cot(snap, prev), block_options(snap, prev), block_model(snap, prev)]
    rk = risk(snap)
    pb = (prev or {}).get("brief")
    vs = {}
    if rk:
        rk["label"] = rk["text"].split(" (")[0]
    if pb:
        prk = pb.get("risk") or {}
        if rk and prk.get("key") == rk["key"]:
            vs["risk"] = f"지난주와 같은 임계값 (거리 {sg(prk['dist_pct'], 1)}% → {sg(rk['dist_pct'], 1)}%)"
        elif rk:
            vs["risk"] = f"지난주 가장 가까운 임계값은 {prk.get('label') or prk.get('key', '–')} ({sg(prk.get('dist_pct'), 1)}%)"
        vs["unchanged"] = all(b.get("unchanged") for b in blocks) and bool(rk) and prk.get("key") == rk["key"]
    blocks[2]["note"] = (f"가장 가까운 기계적 임계값: {rk['text']}" + (f" — {vs['risk']}" if vs.get("risk") else "")) if rk else None
    ez = easy.build(snap, prev, UNIT)
    blocks[0]["easy"] = [ez["cot"]] if ez.get("cot") else []
    blocks[1]["easy"] = [ez["options"]] if ez.get("options") else []
    blocks[2]["easy"] = [f"모델상으로는 {t}" for t in (ez.get("gamma"), ez.get("flip")) if t]
    return {"blocks": blocks, "risk": rk, "vs_prev": vs, "overall": ez.get("overall"),
            "prev_week": (prev or {}).get("week"), "prev_brief": _compact(pb)}


def _item_text(i):
    return f"{i['label']}: {i['text']}" if i.get("label") else i["text"]


def _compact(b):
    """전주 결론 원문만 보관(화면 '지난주 결론' 비교용). 재귀 저장 방지로 prev_brief는 빼고"""
    if not b:
        return None
    if "blocks" not in b:  # 2026-10-18 이전 구조
        return {"blocks": [{"title": "결론(이전 구조)", "items": [b["line"]["text"]] + [c["text"] for c in b.get("changes", [])]
                            + [x for x in (b.get("changes_note"), (b.get("risk") or {}).get("text")) if x]}]}
    return {"blocks": [{"title": x["title"], "items": [_item_text(i) for i in x["items"]] + ([x["note"]] if x.get("note") else [])}
                       for x in b["blocks"]], "overall": b.get("overall")}


def to_lines(b):
    """마크다운·로그용: [(블록 제목, [항목 문자열 또는 (본문, [하위])])] + 종합"""
    out = []
    for x in b["blocks"]:
        title = x["title"] + (f" · {x['asof']}" if x.get("asof") else "") + (" · 지난주와 변화 없음" if x.get("unchanged") else "")
        items = [(_item_text(i), [f"가정: {i['assume']}"]) if i.get("assume") else _item_text(i) for i in x["items"]]
        if x.get("note"):
            items.append(x["note"])
        items += [f"쉽게 말하면: {e}" for e in x.get("easy") or []]
        out.append((title, items))
    if b.get("overall"):
        out.append(("종합", [b["overall"]]))
    return out
