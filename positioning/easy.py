"""'쉽게 말하면' 해설 — 결론(brief) 각 항목 아래 붙는 한 문단. 전부 수치 템플릿(고정 문장 없음).

  gamma    SPX 딜러 감마 부호·규모(35일 이내 GEX)와 전주 대비 배율 → '변동성 쿠션'
  cot      새 COT 공표 주: 주간 σ 상위 시장의 주체·방향·평소 대비 배율·시사점 + 순포지션 치우침
  flip     ES CTA 전환가를 '지수가 X% 빠지면 CTA 매도가 시작되는 선'으로, 전주 대비 안전/위험 + 감마와 합친 하방 쿠션 겹수
  overall  옵션·CTA·채권 포지션을 합친 한 줄

기준 단위는 brief.UNIT 공유. 전문용어는 처음 나올 때 괄호로 짧게 설명.
"""
from __future__ import annotations

from .report import _px, sg

TSY = {"ZT": "2년", "ZF": "5년", "ZN": "10년", "TN": "울트라10년", "ZB": "장기(본드)", "UB": "울트라본드"}
TSY_LONG_END = {"ZB", "UB"}
GROUP_EASY = {"lev": "레버리지펀드(헤지펀드 등 단기 투기 자금)", "mm": "운용역(원자재 추세·투기 자금)",
              "am": "자산운용사(연기금·장기 자금)", "dealer": "딜러(은행 등 중개)"}
RATIO_UP, RATIO_DOWN = 1.5, 1 / 1.5


def _get(d, *ks):
    for k in ks:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _gex(u):
    return u.get("gex_near_usd_bn") if u.get("gex_near_usd_bn") is not None else u.get("gex_usd_bn")


def _zg_dist(u):
    if not u or not u.get("zero_gamma") or not u.get("spot"):
        return None
    return (u["zero_gamma"] / u["spot"] - 1) * 100


def _ratio_phrase(cur, old):
    """지난주 대비 배율 문구. 부호가 다르거나 전주가 0에 가까우면 차이로"""
    if old is None:
        return None, None
    if (cur > 0) != (old > 0):
        return f"지난주 {'롱' if old > 0 else '숏'} 감마({sg(old, 1)}$bn)에서 부호가 바뀜", None
    if abs(old) < 0.5:
        return f"지난주 {sg(old, 1)}$bn에서 {sg(cur - old, 1)}$bn 변화", None
    r = cur / old
    return f"지난주({sg(old, 1)}$bn)의 {r:.1f}배", r


# ── 딜러 감마 ──
def gamma(u, pu):
    if not u or _gex(u) is None:
        return None
    g = _gex(u)
    pg = _gex(pu) if pu else None
    rp, r = _ratio_phrase(g, pg)
    long_g = g > 0
    zd = _zg_dist(u)
    if long_g:
        s = (f"딜러는 지금 롱 감마(가격이 오르면 팔고 내리면 사서 움직임을 되돌리는 헤지 위치)다. "
             f"35일 이내 만기 기준 지수 1% 변동당 약 {abs(g):.1f}$bn을 반대 방향으로 매매하는 규모" + (f"로 {rp}" if rp else "다."))
        if r is not None and r >= RATIO_UP:
            s += " — 변동성 쿠션이 두꺼워져 급등락은 억제되고 횡보에 유리한 쪽이다."
        elif r is not None and r <= RATIO_DOWN:
            s += " — 변동성 쿠션이 얇아져 지난주보다 움직임을 덜 흡수한다."
        else:
            s += " — 변동성 쿠션 두께는 지난주와 비슷하다." if r is not None else (" — 쿠션 역할을 한다." if rp else " 급등락을 억제하고 횡보에 유리한 쪽이다.")
    else:
        s = (f"딜러는 지금 숏 감마(가격이 내리면 팔고 오르면 사서 움직임을 키우는 헤지 위치)다. "
             f"35일 이내 만기 기준 지수 1% 변동당 약 {abs(g):.1f}$bn이 같은 방향으로 붙는 규모" + (f"로 {rp}" if rp else "다."))
        if r is not None and r >= RATIO_UP:
            s += " — 움직임 증폭 효과가 커졌다."
        elif r is not None and r <= RATIO_DOWN:
            s += " — 증폭 효과는 지난주보다 작다."
        else:
            s += (" — " if rp else " ") + "쿠션 없이 움직임이 증폭되는 구간이다."
    tail = []
    if u.get("gamma_expiring_by_opex_pct") is not None and u.get("next_opex"):
        tail.append(f"전체 감마의 {u['gamma_expiring_by_opex_pct']:.0f}%는 {u['next_opex'][5:].replace('-', '/')} 옵션 만기에 사라지고")
    if zd is not None:
        if long_g and zd < 0:
            tail.append(f"지수가 {abs(zd):.1f}% 내려 {_px(u['zero_gamma'])}(zero-gamma: 딜러 감마 부호가 바뀌는 선) 아래로 가면 "
                        f"숏 감마로 바뀌어 움직임을 증폭하는 쪽이 된다")
        elif not long_g and zd > 0:
            tail.append(f"지수가 {zd:.1f}% 올라 {_px(u['zero_gamma'])}(zero-gamma: 딜러 감마 부호가 바뀌는 선)을 넘으면 "
                        f"롱 감마로 돌아와 쿠션이 생긴다")
    if tail:
        s += " 다만 " + ", ".join(tail)
        s += " 쿠션이 그만큼 얇아진다." if s.endswith("사라지고") else "."
    return s


# ── COT ──
def _move(net, chg):
    """순포지션 변화 → (짧은 표현, 방향 부호: +1 롱 쪽, -1 숏 쪽)"""
    old = net - chg
    if old < 0 <= net:
        return "순숏→순롱 전환", 1
    if old > 0 >= net:
        return "순롱→순숏 전환", -1
    if net < 0:
        return ("순숏 축소(숏커버: 빌려 판 포지션 되사기)" if chg > 0 else "순숏 확대"), (1 if chg > 0 else -1)
    return ("순롱 확대" if chg > 0 else "순롱 축소"), (1 if chg > 0 else -1)


def _implication(key, m, d):
    """d = +1(롱 쪽으로 이동) / -1(숏 쪽으로 이동) → 무엇에 대한 베팅이 늘었/줄었는지"""
    cls = m.get("class") or ""
    if key in TSY:
        return "금리 상승 베팅 축소" if d > 0 else "금리 상승 베팅 확대"
    if key == "VX":
        return "변동성 상승 쪽으로 이동" if d > 0 else "변동성 하락 쪽으로 이동"
    if key == "DX":
        return "달러 강세 쪽으로 이동" if d > 0 else "달러 약세 쪽으로 이동"
    if key in ("6E", "6J", "6B", "6A"):
        return f"{m['name']} 강세(달러 대비) 쪽으로 이동" if d > 0 else f"{m['name']} 약세(달러 대비) 쪽으로 이동"
    if cls == "주식" or key in ("ES", "NQ", "RTY"):
        return "지수 상승 쪽으로 이동" if d > 0 else "지수 하락 쪽으로 이동"
    return "가격 상승 쪽으로 이동" if d > 0 else "가격 하락 쪽으로 이동"


def _iga(word):
    """주격 조사 이/가 — 괄호 앞 마지막 글자의 받침 기준"""
    c = word.split("(")[0].strip()[-1:]
    return "이" if c and "가" <= c <= "힣" and (ord(c) - 0xAC00) % 28 else "가"


def _lean(g):
    net, p = g["net"], g.get("pctile_3y")
    side = "숏" if net < 0 else "롱"
    ps = f", 3년 {p:.0f}백분위" if p is not None else ""
    return f"순{side} {abs(net) / 1000:.1f}k계약으로 여전히 {side} 쪽에 치우쳐 있다(미결제약정의 {abs(g.get('net_pct_oi') or 0):.0f}%{ps})"


def cot(c, pc, unit=1.0):
    rd, prd = (c or {}).get("report_date"), (pc or {}).get("report_date")
    if not rd:
        return None
    if prd and rd == prd:
        return None  # 새 공표 없음 — brief changes_note가 이미 표기
    rows = []
    for k, m in (c.get("markets") or {}).items():
        g = m["groups"][m["headline"]]
        z = g.get("chg_1w_z")
        if z is not None and abs(z) >= unit:
            rows.append((abs(z), k, m, g))
    if not rows:
        return f"{rd[5:].replace('-', '/')} COT에서는 평소 주간 변동폭(3년 표준편차) 이상 움직인 시장이 없다."
    rows.sort(key=lambda x: -x[0])
    parts = []
    seen = set()
    for _, k, m, g in rows[:2]:
        mv, d = _move(g["net"], g["chg_1w"])
        who = GROUP_EASY.get(m["headline"], m["headline"]) if m["headline"] not in seen else GROUP_EASY.get(m["headline"], m["headline"]).split("(")[0]
        mv = mv if "숏커버" not in mv or not seen else mv.split("(")[0]
        seen.add(m["headline"])
        parts.append(f"{who}{_iga(who)} {m['name']}에서 {mv} {abs(g['chg_1w']) / 1000:.1f}k계약 — 평소 주간 변동의 {abs(g['chg_1w_z']):.1f}배 → "
                     f"{_implication(k, m, d)}. 그래도 {_lean(g)}")
    s = f"{rd[5:].replace('-', '/')} COT 기준 " + ". ".join(parts) + "."
    if any(k in TSY for _, k, _, _ in rows[:2]):
        s += " (레버리지펀드 국채 숏은 현물-선물 차익거래(베이시스) 비중이 커서 방향성 베팅만은 아니다.)"
    rest = rows[2:]
    if rest:
        s += " 그 외 평소의 1배 이상: " + ", ".join(
            f"{m['name']} {_move(g['net'], g['chg_1w'])[0].split('(')[0]}({sg(g['chg_1w_z'], 1)}σ)" for _, k, m, g in rest) + "."
    return s


def bonds(c, unit=1.0):
    """국채 레버리지펀드 주간 변화 요약 → (문구, 상태키). 새 공표 아닌 주는 호출 안 함"""
    ups, downs = [], []
    for k in TSY:
        m = (c.get("markets") or {}).get(k)
        if not m:
            continue
        g = m["groups"][m["headline"]]
        if g.get("chg_1w_z") is None or abs(g["chg_1w_z"]) < unit:
            continue
        (ups if g["chg_1w"] > 0 else downs).append(k)
    if not ups and not downs:
        return "국채 선물 포지션은 평소 범위 안"
    if ups and downs:
        lu = [TSY[k] for k in ups]
        ld = [TSY[k] for k in downs]
        return f"국채는 {'·'.join(lu)} 숏 축소 vs {'·'.join(ld)} 숏 확대로 만기별 엇갈림"
    ks = ups or downs
    return f"국채 {'·'.join(TSY[k] for k in ks)} {'숏 축소(금리 상승 베팅 축소)' if ups else '숏 확대(금리 상승 베팅 확대)'}"


# ── 전환가 거리 ──
def _active(es):
    return [f for f in es.get("flips", []) if (f["signal"] > 0 and f["dist_pct"] < 0) or (f["signal"] < 0 and f["dist_pct"] > 0)]


def cushions(es, u):
    """현재가 아래(롱일 때) 쿠션 목록 [(거리%, 이름)] — 딜러 롱 감마 구간 끝 · CTA 첫 매도선"""
    out = []
    zd = _zg_dist(u)
    g = _gex(u) if u else None
    if g is not None and g > 0 and zd is not None and zd < 0:
        out.append((zd, "딜러 롱 감마"))
    act = [f for f in _active(es or {}) if f["dist_pct"] < 0]
    if act:
        f = max(act, key=lambda x: x["dist_pct"])
        out.append((f["dist_pct"], "CTA 롱 유지(매도 없음)"))
    return sorted(out, key=lambda x: -x[0])


def flip(es, pes, u, flip_unit=0.5):
    if not es:
        return None
    act = _active(es)
    if not act:
        return "CTA 모델의 모든 룩백 신호가 이미 현재 방향과 같은 쪽으로 넘어가 있어, 기계적으로 매매가 바뀌는 전환가가 가까이에 없다."
    f = min(act, key=lambda x: abs(x["dist_pct"]))
    down = f["dist_pct"] < 0
    pf = {x["lookback"]: x for x in (pes or {}).get("flips", [])}.get(f["lookback"])
    s = (f"지수(ES 선물)가 {abs(f['dist_pct']):.1f}% {'빠지면' if down else '오르면'}({_px(f['flip_level'])} {'아래' if down else '위'}) "
         f"CTA(추세추종 펀드) {f['lookback']}일 신호가 {'매도' if down else '매수'}로 뒤집혀 "
         f"{'매도' if down else '매수(숏커버)'}가 시작되는 선이다.")
    if pf:
        dd = abs(f["dist_pct"]) - abs(pf["dist_pct"])
        if abs(dd) < flip_unit:
            s += f" 지난주 {abs(pf['dist_pct']):.1f}%와 비슷해 안전도 변화는 거의 없다."
        else:
            s += f" 지난주 {abs(pf['dist_pct']):.1f}%에서 {abs(dd):.1f}%p {'멀어져 안전해졌다' if dd > 0 else '가까워져 위험해졌다'}."
    sc = sorted(es.get("scenarios", []), key=lambda x: x["k"])
    one = next((x for x in sc if x["k"] == (-1 if down else 1)), None)
    if one and abs(one["chg_pp"]) >= 1:
        mv = (one["price"] / es["price"] - 1) * 100
        side = "롱" if es["position_pct"] > 0 else "숏"
        shrink = (one["chg_pp"] < 0) == (es["position_pct"] > 0)
        s += (f" 선에 닿기 전에도 1주 {sg(one['k'], 0)}σ({sg(mv, 1)}%)면 모델 {side} 포지션이 {abs(one['chg_pp']):.0f}%p "
              f"{'줄어든다' if shrink else '늘어난다'}.")
    others = sorted([x for x in act if x is not f and (x["dist_pct"] < 0) == down], key=lambda x: abs(x["dist_pct"]))
    if others:
        s += f" 다음 선은 {others[0]['lookback']}일 {sg(others[0]['dist_pct'], 1)}%({_px(others[0]['flip_level'])})."
    if down:
        cs = cushions(es, u)
        if cs:
            s += f" 감마와 합치면 하방 쿠션은 {len(cs)}겹: " + " ".join(
                f"{'①②'[i]} -{abs(d):.1f}%까지 {n}" for i, (d, n) in enumerate(cs)) + "."
            if len(cs) == 2 and cs[0][1] == "딜러 롱 감마":
                s += (f" {abs(cs[0][0]):.1f}~{abs(cs[1][0]):.1f}% 구간은 딜러가 숏 감마로 바뀌어 하락을 키울 수 있어 "
                      f"CTA 선까지 빨리 닿을 수 있다.")
            elif len(cs) == 2:
                s += f" CTA 매도가 먼저 시작돼도 {abs(cs[1][0]):.1f}%까지는 딜러 롱 감마가 일부를 흡수한다."
        else:
            s += " 딜러 감마도 숏이라 하방 쿠션이 없다."
    return s


# ── 종합 ──
def overall(es, u, pu, c, pc, unit=1.0):
    bits = []
    g = _gex(u) if u else None
    if g is not None:
        _, r = _ratio_phrase(g, _gex(pu) if pu else None)
        rr = f"(지난주의 {r:.1f}배)" if r is not None else ""
        bits.append(f"옵션은 딜러 {'롱 감마' + rr + '로 변동을 흡수' if g > 0 else '숏 감마' + rr + '로 변동을 증폭'}")
    if es:
        act = _active(es)
        f = min(act, key=lambda x: abs(x["dist_pct"])) if act else None
        side = "롱" if es["position_pct"] > 0 else "숏"
        bits.append(f"CTA는 {side} {abs(es['position_pct']):.0f}%(3년 {es['position_pctile_3y']:.0f}백분위)"
                    + (f"에 {'매도' if f['dist_pct'] < 0 else '매수'}선까지 {abs(f['dist_pct']):.1f}%" if f else ""))
    rd, prd = (c or {}).get("report_date"), (pc or {}).get("report_date")
    if rd and rd != prd:
        bits.append(bonds(c, unit))
    if not bits:
        return None
    cs = cushions(es, u) if es and es["position_pct"] > 0 else []
    if g is not None and g > 0:
        shape = f"하방 쿠션 {len(cs)}겹의 롱 감마 횡보 구조" if cs else "롱 감마 횡보 구조"
        if cs and cs[0][1] == "딜러 롱 감마":
            shape += f", 다만 {abs(cs[0][0]):.1f}% 아래부터는 쿠션이 얇아진다"
    elif g is not None:
        shape = "숏 감마로 움직임이 커지기 쉬운 구조" + (f", CTA 매도선 {abs(cs[0][0]):.1f}% 한 겹만 남음" if cs else "")
    else:
        shape = "옵션 데이터 없이 CTA 기준만 판단 가능한 구조"
    return "지금 시장 구조는 " + shape + " — " + " · ".join(bits) + "."


def build(snap, prev, unit_cot=1.0, unit_flip=0.5):
    es, pes = _get(snap, "cta", "assets", "ES"), _get(prev, "cta", "assets", "ES")
    u, pu = _get(snap, "options", "underlyings", "SPX"), _get(prev, "options", "underlyings", "SPX")
    c, pc = snap.get("cot"), (prev or {}).get("cot")
    return {"gamma": gamma(u, pu), "cot": cot(c, pc, unit_cot), "flip": flip(es, pes, u, unit_flip),
            "overall": overall(es, u, pu, c, pc, unit_cot)}
