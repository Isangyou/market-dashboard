"""'쉽게 말하면' 해설 — 결론(brief) 각 항목 아래 붙는 한 문단. 전부 수치 템플릿(고정 문장 없음).

  gamma    SPX 딜러 감마: (a) zero-gamma 선 대비 위치 (b) 1%당 매매 규모 (c) 쿠션=자동 매수 흐름 정의 + 부호 전환 시
           원인 분해(지수 이동=복원됨 / 만기 소멸=복원 안 됨) (d) 되돌아가는 조건 + 다음 주요 만기 소멸 비중
  cot      새 COT 공표 주: 주간 σ 상위 시장의 주체·방향·평소 대비 배율·시사점 + 순포지션 치우침
  flip     ES CTA 전환가를 '지수가 X% 빠지면 CTA 매도가 시작되는 선'으로, 전주 대비 안전/위험 + 감마와 합친 하방 쿠션 겹수
  options  관측 옵션 시장(IV30·스큐·P/C·최대 OI 행사가)을 지난주와 비교한 평이한 설명 — 모델 가정 없음
  overall  '관측: COT·옵션 시장. 모델상으로는 딜러 감마·CTA.' 감마 부호가 바뀐 주는 '자동 매수 흐름 소멸/복원' + 하방 안전판 겹수

기준 단위는 brief.UNIT 공유. 전문용어는 처음 나올 때 괄호로 짧게 설명.
"""
from __future__ import annotations

from .report import _px, sg

TSY = {"ZT": "2년", "ZF": "5년", "ZN": "10년", "TN": "울트라10년", "ZB": "장기(본드)", "UB": "울트라본드"}
TSY_LONG_END = {"ZB", "UB"}
GROUP_EASY = {"lev": "레버리지펀드(헤지펀드 등 단기 투기 자금)", "mm": "운용역(원자재 추세·투기 자금)",
              "am": "자산운용사(연기금·장기 자금)", "dealer": "딜러(은행 등 중개)"}
RATIO_UP, RATIO_DOWN = 1.5, 1 / 1.5
SAFETY = {"딜러 롱 감마": "딜러 롱 감마", "CTA 롱 유지(매도 없음)": "CTA 매도선"}  # 종합 한 줄의 안전판 이름


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
CUSHION_DEF = ("여기서 '쿠션'은 지지선(가격이 멈추는 선)이 아니라 딜러의 자동 매수 흐름이다: 롱 감마에선 지수가 빠질 때 "
               "딜러가 기계적으로 사 주지만, 숏 감마에선 같이 팔아서 낙폭이 커진다.")


def opex(u, asof=None):
    """다음 주요 만기 (MM/DD, 종류, 소멸 비중%). 만기가 기준일 이전·당일이거나 비중이 0·없음이면 None"""
    e, pct = u.get("next_opex"), u.get("gamma_expiring_by_opex_pct")
    if not e or pct is None or round(pct) <= 0 or (asof and e <= asof):
        return None
    return e[5:].replace("-", "/"), u.get("next_opex_kind") or "월물", pct


def _near_at(u, s):
    """35일 이내 GEX 프로파일을 가격 s에서 선형 보간($bn). 프로파일 없거나 범위 밖이면 None"""
    pr = (u or {}).get("gex_profile") or {}
    xs, ys = pr.get("spot"), pr.get("near_usd_bn")
    if not xs or not ys or s is None or not xs[0] <= s <= xs[-1]:
        return None
    for i in range(len(xs) - 1):
        if xs[i] <= s <= xs[i + 1]:
            w = (s - xs[i]) / (xs[i + 1] - xs[i]) if xs[i + 1] != xs[i] else 0
            return ys[i] + (ys[i + 1] - ys[i]) * w
    return None


def flip_cause(u, pu, asof, pasof):
    """전주 대비 GEX 변화 분해($bn): 지수 이동(같은 포지션, 가격만 전주→이번 주) · 만기 소멸(전주에 있던 만기 중
    (전주 기준일, 이번 기준일]에 끝난 것) · 나머지(신규·청산 포지션, 35일 창 이동). 이번 주 단기 프로파일 없으면 None"""
    if not u or not pu or not asof or not pasof:
        return None
    g, pg = _gex(u), _gex(pu)
    at_prev = _near_at(u, pu.get("spot"))
    if g is None or pg is None or at_prev is None:
        return None
    lst = pu.get("gex_near_by_expiry")
    full = lst is not None
    gone = [x for x in (lst if full else pu.get("diag_gex_by_expiry") or []) if pasof < x["exp"] <= asof]
    spot_eff = g - at_prev
    exp_eff = -sum(x["gex_usd_bn"] for x in gone)
    return {"spot": spot_eff, "expiry": exp_eff, "rest": (g - pg) - spot_eff - exp_eff, "total": g - pg,
            "gone": sorted(x["exp"] for x in gone), "full": full}


def _cause_text(u, pu, fc):
    s0, s1 = pu["spot"], u["spot"]
    days = "·".join(e[5:].replace("-", "/") for e in fc["gone"])
    t = (f"부호가 바뀐 원인(지난주 {'롱' if _gex(pu) > 0 else '숏'} 감마 {sg(_gex(pu), 1)}$bn → {sg(_gex(u), 1)}$bn, "
         f"합계 {sg(fc['total'], 1)}$bn): ① 지수가 {_px(s0)}→{_px(s1)}({sg((s1 / s0 - 1) * 100, 1)}%)로 "
         f"{'내려와 zero-gamma 선 아래로 간' if s1 < s0 else '올라와 zero-gamma 선 위로 간'} 효과 {sg(fc['spot'], 1)}$bn "
         f"— 포지션은 그대로고 지수 위치 때문에 생긴 부분이라 지수가 {'다시 오르면' if s1 < s0 else '다시 빠지면'} 되돌아간다.")
    if fc["gone"]:
        t += (f" ② {days} 옵션 만기로 포지션 자체가 소멸한 효과 {sg(fc['expiry'], 1)}$bn"
              + ("" if fc["full"] else "(지난주 상위 8개 만기만 집계, 최소치)") + " — 지수가 돌아와도 복원되지 않는다.")
    if abs(fc["rest"]) >= 0.5:
        t += f" 나머지 {sg(fc['rest'], 1)}$bn은 새로 쌓이거나 정리된 포지션."
    return t


def gamma(u, pu, asof=None, pasof=None):
    if not u or _gex(u) is None:
        return None
    g = _gex(u)
    pg = _gex(pu) if pu else None
    switched = pg is not None and (g > 0) != (pg > 0)
    rp, r = _ratio_phrase(g, pg)
    long_g = g > 0
    zg, zd = u.get("zero_gamma"), _zg_dist(u)
    zline = f"zero-gamma 선({_px(zg)}: 딜러 감마 부호가 바뀌는 가격)" if zg else None
    pos = "롱 감마(지수가 내리면 사고 오르면 파는 헤지 위치)" if long_g else "숏 감마(지수가 내리면 팔고 오르면 사는 헤지 위치)"
    # (a) 위치
    on_side = zd is not None and ((long_g and zd < 0) or (not long_g and zd > 0))
    if on_side:
        s = (f"지수가 {zline} {'위로 올라와' if long_g else '아래로 내려와'} 딜러가 {pos}로 전환됐다." if switched else
             f"지수가 {zline} {'위' if long_g else '아래'}에 있어 딜러가 {pos} 상태다.")
    else:
        s = f"딜러가 {pos}로 전환됐다." if switched else f"딜러는 {pos} 상태다."
    # (b) 규모
    s += (f" 이 상태에선 지수가 1% 움직일 때 딜러가 {'반대' if long_g else '같은'} 방향으로 약 {abs(g):.1f}$bn 매매해서 "
          f"움직임이 {'줄어든다' if long_g else '커진다'}(35일 이내 만기 기준)")
    if not switched and rp:
        s += f" — {rp}"
        if r is not None and r >= RATIO_UP:
            s += f", {'자동 매수 흐름이 두꺼워졌다' if long_g else '증폭 효과가 커졌다'}."
        elif r is not None and r <= RATIO_DOWN:
            s += f", {'자동 매수 흐름이 얇아졌다' if long_g else '증폭 효과는 작아졌다'}."
        else:
            s += ", 규모는 비슷하다." if r is not None else "."
    else:
        s += "."
    # (c) 쿠션 정의 + 부호 전환 원인
    s += " " + CUSHION_DEF
    if switched:
        fc = flip_cause(u, pu, asof, pasof)
        s += " " + (_cause_text(u, pu, fc) if fc else
                    f"지난주 {'롱' if pg > 0 else '숏'} 감마 {sg(pg, 1)}$bn에서 부호가 바뀌었다(원인 분해용 가격대별 데이터 없음).")
    # (d) 되돌아가는 조건
    if on_side:
        s += (f" 지수가 {abs(zd):.1f}% 빠져 zero-gamma 선({_px(zg)}) 아래로 내려가면 이 흐름이 매도로 바뀐다." if long_g else
              f" 지수가 {zd:.1f}% 올라 zero-gamma 선({_px(zg)})을 다시 넘으면 자동 매수 흐름이 복원된다.")
    ox = opex(u, asof)
    if ox:
        s += f" 전체 감마(절댓값)의 {ox[2]:.0f}%는 {ox[0]} {ox[1]} 옵션 만기에 사라져 그만큼 흐름 규모가 줄어든다."
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


# ── 관측 옵션 시장 ──
def _cmp(cur, old, unit, up, down, same="지난주와 비슷하다"):
    if cur is None or old is None:
        return None
    return up if cur - old >= unit else down if old - cur >= unit else same


def options(u, pu, wk=None, unit=None):
    """관측값만: 옵션 가격(IV)·풋/콜 가격 차(스큐)·미결제 비율(P/C)·미결제 집중 행사가"""
    if not u:
        return None
    unit = unit or {"iv": 1.0, "skew": 1.0, "pc": 0.10}
    pu = pu or {}
    out = []
    iv, piv = u.get("atm_iv_30d"), pu.get("atm_iv_30d")
    if iv is not None:
        t = f"옵션 가격에 담긴 SPX 앞으로 30일 예상 변동폭(ATM IV30)은 연 {iv:.1f}%(하루 약 {iv / 252 ** 0.5:.2f}%)"
        c = _cmp(iv, piv, unit["iv"], f"로 지난주 {piv:.1f}%보다 올랐다(옵션이 비싸짐)", f"로 지난주 {piv:.1f}%보다 내렸다(옵션이 싸짐)",
                 f"로 지난주 {piv:.1f}%와 비슷하다") if piv is not None else None
        out.append(t + (c or "다") + ".")
    sk, psk = u.get("skew_25d_30d"), pu.get("skew_25d_30d")
    if sk is not None:
        t = f"하락 보험인 풋이 같은 거리의 콜보다 {abs(sk):.1f}vp {'비싸' if sk > 0 else '싸'}"
        c = _cmp(sk, psk, unit["skew"], f" 지난주({sg(psk, 1)}vp)보다 하락 대비 수요가 커졌다", f" 지난주({sg(psk, 1)}vp)보다 하락 대비 수요가 줄었다",
                 f" 지난주({sg(psk, 1)}vp)와 비슷하다") if psk is not None else None
        out.append(t + (c or "다") + ".")
    pc, ppc = u.get("pc_oi"), pu.get("pc_oi")
    if pc is not None:
        t = f"남아 있는 풋 계약은 콜의 {pc:.2f}배(P/C, 미결제 기준)"
        c = _cmp(pc, ppc, unit["pc"], f"로 지난주 {ppc:.2f}배보다 풋 쪽 비중이 늘었다", f"로 지난주 {ppc:.2f}배보다 풋 쪽 비중이 줄었다",
                 f"로 지난주 {ppc:.2f}배와 비슷하다") if ppc is not None else None
        out.append(t + (c or "다") + "." + (f" 이번 주 거래량 기준으로는 {wk:.2f}배." if wk is not None else ""))
    cw, pw = u.get("call_oi_wall"), u.get("put_oi_wall")
    if cw and pw:
        dd = lambda k: sg((k / u["spot"] - 1) * 100, 1)
        if cw == pw:
            t = f"미결제가 가장 많이 쌓인 행사가는 콜·풋 모두 {_px(cw)}(현재가 대비 {dd(cw)}%)"
        else:
            t = f"미결제가 가장 많이 쌓인 행사가는 콜 {_px(cw)}({dd(cw)}%) · 풋 {_px(pw)}({dd(pw)}%)"
        moved = pu.get("call_oi_wall") and (pu.get("call_oi_wall"), pu.get("put_oi_wall")) != (cw, pw)
        out.append(t + (f"로, 지난주(콜 {_px(pu['call_oi_wall'])} · 풋 {_px(pu.get('put_oi_wall'))})에서 옮겨 왔다." if moved else
                        ("로 지난주와 같다." if pu.get("call_oi_wall") else "다.")))
    return " ".join(out) or None


# ── 종합 ──
GROUP_SHORT = {"lev": "레버리지펀드", "am": "자산운용사", "mm": "운용역"}


def _cot_obs(c, pc, unit):
    rd, prd = (c or {}).get("report_date"), (pc or {}).get("report_date")
    if not rd:
        return None
    if prd and rd == prd:
        return f"COT 새 공표 없음({rd[5:].replace('-', '/')} 기준)"
    rows = []
    for k, m in (c.get("markets") or {}).items():
        for g in (("lev", "am") if "lev" in m["groups"] else ("mm",)):
            x = m["groups"].get(g)
            if x and x.get("chg_1w_z") is not None and abs(x["chg_1w_z"]) >= unit:
                rows.append((abs(x["chg_1w_z"]), k, m, g, x))
    if not rows:
        return f"COT({rd[5:].replace('-', '/')})는 모든 시장 주간 변화가 평소 범위(1σ 미만)"
    rows.sort(key=lambda r: -r[0])
    return f"COT({rd[5:].replace('-', '/')})는 " + " · ".join(
        f"{GROUP_SHORT[g]} {m['name']} {_move(x['net'], x['chg_1w'])[0].split('(')[0]}({sg(x['chg_1w_z'], 1)}σ)" for _, k, m, g, x in rows[:2]) + (
        f" 외 {len(rows) - 2}건 ≥1σ" if len(rows) > 2 else "")


def _opt_obs(u, pu, unit):
    if not u or u.get("atm_iv_30d") is None:
        return None
    pu = pu or {}
    iv, sk, pc = u.get("atm_iv_30d"), u.get("skew_25d_30d"), u.get("pc_oi")
    piv, psk, ppc = pu.get("atm_iv_30d"), pu.get("skew_25d_30d"), pu.get("pc_oi")
    bits = [f"IV30 {iv:.1f}%" + (f"({sg(iv - piv, 1)}%p)" if piv is not None else "")]
    if sk is not None:
        bits.append(f"스큐 {sg(sk, 1)}vp" + (f"({sg(sk - psk, 1)})" if psk is not None else ""))
    if pc is not None:
        bits.append(f"P/C {pc:.2f}" + (f"({sg(pc - ppc, 2)})" if ppc is not None else ""))
    tag = ""
    if piv is not None and psk is not None and sk is not None:
        div, dsk = iv - piv, sk - psk
        if div >= unit["iv"] and dsk >= unit["skew"]:
            tag = "로 옵션이 비싸지고 하락 대비 수요 증가"
        elif div <= -unit["iv"] and dsk <= -unit["skew"]:
            tag = "로 옵션이 싸지고 하락 대비 수요 감소"
        elif abs(div) < unit["iv"] and abs(dsk) < unit["skew"] and (ppc is None or abs(pc - ppc) < unit["pc"]):
            tag = "로 지난주와 비슷"
    return "SPX 옵션은 " + "·".join(bits) + tag


def _model_shape(es, u, pu):
    g = _gex(u) if u else None
    cs = cushions(es, u) if es and es["position_pct"] > 0 else []
    pg = _gex(pu) if pu else None
    if g is not None and pg is not None and (g > 0) != (pg > 0):
        zd, zg = _zg_dist(u), u.get("zero_gamma")
        flow = (f"딜러 자동 매수 흐름 {'소멸' if g < 0 else '복원'}({'롱' if pg > 0 else '숏'} 감마 → {'숏' if g < 0 else '롱'} 감마"
                + (f", 지수가 {zd:.1f}% 올라 {_px(zg)} 선을 넘으면 복원" if g < 0 and zd is not None and zd > 0 else "") + ")")
        if not cs:
            return flow + "으로 하방 안전판 없음"
        if len(cs) == 1:
            return flow + f"으로 하방 안전판은 {SAFETY.get(cs[0][1], cs[0][1])}(-{abs(cs[0][0]):.1f}%) 1겹만 남음"
        return flow + f"으로 하방 안전판 {len(cs)}겹: " + " · ".join(f"{SAFETY.get(n, n)} -{abs(d):.1f}%까지" for d, n in cs)
    if g is not None and g > 0:
        s = f"딜러 롱 감마로 하방 안전판 {len(cs)}겹(" + " · ".join(f"{SAFETY.get(n, n)} -{abs(d):.1f}%까지" for d, n in cs) + ")" if cs else "딜러 롱 감마로 변동 흡수 쪽"
        return s
    if g is not None:
        return "딜러 숏 감마로 움직임이 커지기 쉬운 쪽" + (f", 하방 안전판은 CTA 매도선(-{abs(cs[0][0]):.1f}%) 1겹" if cs else ", 하방 안전판 없음")
    return None


def overall(snap, prev, unit):
    es, pes = _get(snap, "cta", "assets", "ES"), _get(prev, "cta", "assets", "ES")
    u, pu = _get(snap, "options", "underlyings", "SPX"), _get(prev, "options", "underlyings", "SPX")
    obs = [x for x in (_cot_obs(snap.get("cot"), (prev or {}).get("cot"), unit["cot_z"]), _opt_obs(u, pu, unit)) if x]
    rd, prd = _get(snap, "cot", "report_date"), _get(prev, "cot", "report_date")
    if rd and rd != prd:
        obs.append(bonds(snap["cot"], unit["cot_z"]))
    mdl = [x for x in (_model_shape(es, u, pu),) if x]
    if es:
        side = "롱" if es["position_pct"] > 0 else "숏"
        mdl.append(f"CTA {side} {abs(es['position_pct']):.0f}%(3년 {es['position_pctile_3y']:.0f}백분위)")
    if not obs and not mdl:
        return None
    return ("관측: " + " · ".join(obs) + "." if obs else "") + (" 모델상으로는 " + " · ".join(mdl) + "." if mdl else "")


def build(snap, prev, unit):
    es, pes = _get(snap, "cta", "assets", "ES"), _get(prev, "cta", "assets", "ES")
    u, pu = _get(snap, "options", "underlyings", "SPX"), _get(prev, "options", "underlyings", "SPX")
    c, pc = snap.get("cot"), (prev or {}).get("cot")
    asof, pasof = _get(snap, "asof", "us_market_date") or snap.get("week"), _get(prev, "asof", "us_market_date") or (prev or {}).get("week")
    return {"cot": cot(c, pc, unit["cot_z"]), "options": options(u, pu, _get(snap, "options_week", "pc_vol_avg", "SPX"), unit),
            "gamma": gamma(u, pu, asof, pasof), "flip": flip(es, pes, u, unit["flip"]), "overall": overall(snap, prev, unit)}
