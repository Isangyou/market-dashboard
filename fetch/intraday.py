"""장중 수집 → data/intraday/YYYY-MM-DD.json (+ data/intraday/index.json).

네이버가 장중 이력을 직접 주는 항목(E24~E27, E14)은 매 실행 이력 전체를 갱신하고,
실행 시각마다 주요 값 스냅샷을 snapshots[]에 누적한다(3분 간격 샘플 기록 겸 이력 API 실패 대비).
2026-09-28 오전까지는 5분 간격. 스냅샷은 t(HH:MM) 키로 병합·정렬만 하므로 간격이 섞여도 무방.

실행: python -m fetch.intraday [--force] [--data-dir DIR]
  - 거래일 + 08:50~15:40 KST 에만 동작. --force는 두 조건을 무시(검증용)
  - 섹션마다 데이터의 거래일이 대상일과 다르면 버림 (장 시작 전엔 API가 전 거래일 값을 줌)
  - 실패한 섹션은 이전 값 유지 + stale: true
종료코드: 0 = 기록(변경 있음/없음 무관), 3 = 장외·휴장이라 건너뜀, 1 = 전 섹션 실패
"""
import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "fetch"

from . import market_day, naver, yf  # noqa: E402
from .common import log, now_kst, ymd_to_iso  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WINDOW = ("08:50", "15:40")
# 이력 저장 기준 = 수집 종료 시각. 실시간 수집과 --force 백필이 같은 기준이 되도록 통일.
# 15:40이면 정규장 + 장 마감 동시호가(15:30 종가 단일가) 반영, 시간외(15:40~18:00)·NXT 미포함.
# 선물 정규장은 15:45 마감이라 마지막 5분은 빠짐.
KEEP_UNTIL = "15:40"
MARKETS = ["KOSPI", "KOSDAQ"]
SKIPPED = 3

FUT_INST = ["1000", "2000", "3000", "4000", "5000", "6000", "7000"]


def hm(t: str) -> str:
    """'090100' | '20260923090100' → '09:01'"""
    t = t[-6:]
    return f"{t[:2]}:{t[2:4]}"


def iso(date: str, t: str) -> str:
    return f"{date}T{t}:00+09:00"


# ── 섹션 수집 (각각 dict 또는 None) ─────────────────────────────

def index_chart(market: str):
    """E24. 1분 봉."""
    b = naver._get(f"/securityService/chart/domestic/index/{market}", {"periodType": "day"})
    if not b or not b.get("priceInfos"):
        return None
    date = ymd_to_iso(b["tradeBaseAt"])
    bars = [{"t": hm(p["localDateTime"]), "c": p["currentPrice"], "v": p.get("accumulatedTradingVolume")}
            for p in b["priceInfos"] if hm(p["localDateTime"]) <= KEEP_UNTIL]
    last = bars[-1]
    return {"date": date, "source": "naver:index_chart", "asof": iso(date, last["t"]),
            "status": b.get("marketStatus"), "last_close": b.get("lastClosePrice"),
            "open": b.get("openPrice"), "value": last["c"],
            "change": round(last["c"] - b["lastClosePrice"], 2) if b.get("lastClosePrice") else None,
            "change_pct": round((last["c"] / b["lastClosePrice"] - 1) * 100, 2) if b.get("lastClosePrice") else None,
            "bars": bars}


def _time_rows(market: str, date: str, have_until: str = ""):
    """E25/E26 페이지 순회. 최신순 → 오름차순으로 반환. have_until 이하 시각이 나오면 멈춤(증분)."""
    rows, page = [], 0
    while True:
        b = naver._get("/domestic/market/trend/time",
                       {"tradeType": "KRX", "marketType": market, "bizdate": date.replace("-", ""),
                        "startIdx": page, "pageSize": 100})
        if b is None:
            return None if not rows else rows[::-1]
        content = [c for c in b["content"] if ymd_to_iso(c["bizdate"]) == date]
        rows += content
        oldest = hm(content[-1]["time"]) if content else ""
        if b.get("last") in (True, "true") or not content or (have_until and oldest <= have_until):
            break
        page += 1
    return rows[::-1]


def investor_time(market: str, date: str, prev: dict = None):
    """E25. 현물 투자자별 장중 누적 (억원)."""
    prev_rows = (prev or {}).get("rows", [])
    prev_rows = [r for r in prev_rows if r["t"] <= KEEP_UNTIL]
    raw = _time_rows(market, date, prev_rows[-1]["t"] if prev_rows else "")
    if raw is None:
        return None
    by_t = {r["t"]: r for r in prev_rows if r["t"] <= KEEP_UNTIL}
    for it in raw:
        t = hm(it["time"])
        if t > KEEP_UNTIL:
            continue
        v = naver._investor_row(it)
        by_t[t] = {"t": t, "foreign": round(v["foreign"], 1), "individual": round(v["individual"], 1),
                   "institution": round(v["institution"], 1)}
    rows = [by_t[t] for t in sorted(by_t)]
    if not rows:
        return None
    return {"source": "naver:trend_time", "unit": "억원", "asof": iso(date, rows[-1]["t"]),
            "basis": f"KRX 장중 누적 잠정치 (~{KEEP_UNTIL}, 시간외·NXT 제외)", "rows": rows}


def futures_time(date: str, prev: dict = None):
    """E26. 선물 투자자별 장중 누적. 계약 수 + 외국인 금액(억)."""
    prev_rows = (prev or {}).get("rows", [])
    prev_rows = [r for r in prev_rows if r["t"] <= KEEP_UNTIL]
    raw = _time_rows("FUT", date, prev_rows[-1]["t"] if prev_rows else "")
    if raw is None:
        return None
    by_t = {r["t"]: r for r in prev_rows if r["t"] <= KEEP_UNTIL}
    for it in raw:
        t = hm(it["time"])
        if t > KEEP_UNTIL:
            continue
        m = {x["investorGubun"]: x for x in it["netAmounts"]}
        q = lambda c: int(m[c]["diffValue"]) if c in m else 0  # noqa: E731
        amt = lambda c: (int(m[c]["buyPrice"]) - int(m[c]["sellPrice"])) / 100 if c in m else 0  # 백만원 → 억  # noqa: E731
        by_t[t] = {"t": t, "foreign": q("9000"), "individual": q("8000"),
                   "institution": sum(q(c) for c in FUT_INST), "foreign_amt": round(amt("9000"), 1)}
    rows = [by_t[t] for t in sorted(by_t)]
    if not rows:
        return None
    return {"source": "naver:trend_time_fut", "unit": "계약", "asof": iso(date, rows[-1]["t"]), "rows": rows}


def futures_price(date: str):
    """E28. KOSPI200 선물 현재가 (20분 지연)."""
    b = naver._get("/securityService/integration/indicators", {"indicatorCodes": "FUT"})
    if not b:
        return None
    it = b[0]
    if not it["localTradedAt"].startswith(date):
        return None
    return {"source": "naver:indicators", "asof": it["localTradedAt"], "value": naver._num(it["currentPrice"]),
            "change": naver._num(it["fluctuations"]), "change_pct": naver._num(it["fluctuationsRatio"]),
            "delay": f'{it.get("delayTime")}분 지연'}


def program_chart(market: str, date: str):
    """E27. 프로그램 매매 누적 (억원). arb=차익, nonarb=비차익, total=전체."""
    d = date.replace("-", "")
    b = naver._get("/domestic/market/trendProgram/chart",
                   {"tradeType": "KRX", "krxMarketType": market, "bizdate": d,
                    "startDate": d, "endDate": d, "periodType": "TIME"})
    if not b:
        return None
    rows = sorted(({"t": hm(x["time"]), "arb": round(int(x["diffPureBuyAmt"]) / 1e8, 1),
                    "nonarb": round(int(x["biDiffPureBuyAmt"]) / 1e8, 1),
                    "total": round(int(x["totalDiffPureBuyAmt"]) / 1e8, 1)}
                   for x in b if ymd_to_iso(x["bizdate"]) == date and hm(x["time"]) <= KEEP_UNTIL),
                  key=lambda r: r["t"])
    if not rows:
        return None
    return {"source": "naver:program_chart", "unit": "억원", "asof": iso(date, rows[-1]["t"]), "rows": rows}


def usdkrw_round(date: str):
    """E14. 하나은행 고시 회차 → 1분 단위 마지막 값."""
    b = naver._get("/stockSecurity/exchange-rates/v2/USD/charts/round", {"bankType": "hana"})
    if not b or not b.get("priceInfos"):
        return None
    d = date.replace("-", "")
    by_min = {}
    for p in b["priceInfos"]:
        ts = p["tradeBaseAt"]
        if ts[:8] == d and hm(ts) <= KEEP_UNTIL:
            by_min[hm(ts)] = naver._num(p["currentPrice"])
    if not by_min:
        return None
    rows = [{"t": t, "v": by_min[t]} for t in sorted(by_min)]
    last_close = naver._num(b.get("lastClosingPrice"))
    return {"source": "naver:hana_round", "label": "하나은행 고시", "asof": iso(date, rows[-1]["t"]),
            "last_close": last_close, "rows": rows}


# ── 저장 ─────────────────────────────────────────────────────────

def us_futures(now, date, old: dict):
    """NQ=F·CL=F 1분봉 (yfinance, 지연). 같은 시각(t)은 새 값으로 덮어쓰고 이전 행은 유지.
    실시간 수집일(date == 오늘)에만 받는다 — --force로 지난 날을 채울 땐 이전 값 그대로."""
    out = {}
    for sym in yf.US_FUT:
        o = (old or {}).get(sym)
        new = yf.us_future_1m(sym, now) if date == now.date().isoformat() else None
        if new and o and o.get("since") == new["since"]:
            by_t = {r["t"]: r for r in o.get("rows", [])}
            by_t.update({r["t"]: r for r in new["rows"]})
            new["rows"] = [by_t[t] for t in sorted(by_t)]
        out[sym] = keep_or_stale(new, o, f"us_futures {sym}")
    return out


def keep_or_stale(new, old, name):
    if new is not None:
        return {**new, "stale": False}
    if old:
        log.warning("%s 실패 → 이전 값 유지(stale)", name)
        return {**old, "stale": True}
    log.warning("%s 실패, 이전 값 없음", name)
    return None


def snapshot(now, doc) -> dict:
    last = lambda sec, k: (sec or {}).get("rows", [{}])[-1].get(k) if (sec or {}).get("rows") else None  # noqa: E731
    k = (doc["index"] or {}).get("KOSPI") or {}
    return {"t": now.strftime("%H:%M"), "sampled_at": now.isoformat(),
            "kospi": k.get("value"), "kospi_chg_pct": k.get("change_pct"),
            "foreign_kospi": last(doc["investor"].get("KOSPI"), "foreign"),
            "foreign_kosdaq": last(doc["investor"].get("KOSDAQ"), "foreign"),
            "fut_foreign": last(doc["futures"], "foreign"),
            "program_kospi": last(doc["program"].get("KOSPI"), "total"),
            "usdkrw": last(doc["usdkrw"], "v")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="거래일·시간 조건 무시 (검증용)")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    args = ap.parse_args()

    import logging
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    log.propagate = False

    now = now_kst()
    day = market_day.status()
    hhmm = now.strftime("%H:%M")
    if not args.force:
        if not day["trading"]:
            print(f"휴장일 ({day['date']}, {day['holiday'] or '비거래일'}) → 건너뜀. 다음 거래일 {day['next']}")
            return SKIPPED
        if not (WINDOW[0] <= hhmm <= WINDOW[1]):
            print(f"장외 시각 {hhmm} (수집 {WINDOW[0]}~{WINDOW[1]}) → 건너뜀")
            return SKIPPED

    # 대상 거래일: 강제 실행이면 지수 차트의 거래일(=직전 거래일일 수 있음), 아니면 오늘
    kospi = index_chart("KOSPI")
    date = (kospi or {}).get("date") if args.force else day["date"]
    if not date:
        print("대상 거래일을 정할 수 없음")
        return 1

    out_dir = Path(args.data_dir) / "intraday"
    path = out_dir / f"{date}.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    o_idx, o_inv, o_prg = old.get("index", {}), old.get("investor", {}), old.get("program", {})

    same_day = lambda sec: sec if sec and sec.get("date", date) == date else None  # noqa: E731
    kosdaq = index_chart("KOSDAQ")
    doc = {
        "date": date,
        "index": {"KOSPI": keep_or_stale(same_day(kospi), o_idx.get("KOSPI"), "index KOSPI"),
                  "KOSDAQ": keep_or_stale(same_day(kosdaq), o_idx.get("KOSDAQ"), "index KOSDAQ")},
        "investor": {m: keep_or_stale(investor_time(m, date, o_inv.get(m)), o_inv.get(m), f"investor {m}")
                     for m in MARKETS},
        "futures": keep_or_stale(futures_time(date, old.get("futures")), old.get("futures"), "futures"),
        "futures_price": keep_or_stale(futures_price(date), old.get("futures_price"), "futures_price"),
        "program": {m: keep_or_stale(program_chart(m, date), o_prg.get(m), f"program {m}") for m in MARKETS},
        "usdkrw": keep_or_stale(usdkrw_round(date), old.get("usdkrw"), "usdkrw"),
        "us_futures": us_futures(now, date, old.get("us_futures")),
    }
    ok = [doc["index"]["KOSPI"], doc["investor"]["KOSPI"], doc["futures"], doc["program"]["KOSPI"], doc["usdkrw"]]
    if not any(x and not x.get("stale") for x in ok):
        print("모든 섹션 실패 (또는 대상일 데이터 없음) → 기록 안 함")
        return 1 if not args.force else SKIPPED

    snaps = {s["t"]: s for s in old.get("snapshots", [])}
    # 실시간 샘플만 기록: 오늘 + 수집 창 안 (--force로 지난 거래일을 채우거나 장 마감 후 보충할 땐 생략)
    if date == now.date().isoformat() and WINDOW[0] <= hhmm <= WINDOW[1]:
        snap = snapshot(now, doc)
        snaps[snap["t"]] = snap
    doc["snapshots"] = [snaps[t] for t in sorted(snaps)]
    doc["updated_at"] = now.isoformat()
    doc["market_day"] = day

    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    idx_path = out_dir / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else {"dates": []}
    dates = sorted(set(idx["dates"]) | {date})
    idx_new = {"dates": dates, "latest": dates[-1]}
    if idx_new != idx:
        idx_path.write_text(json.dumps(idx_new, ensure_ascii=False, indent=1) + "\n")

    # 요약
    k = doc["index"]["KOSPI"] or {}
    inv = (doc["investor"]["KOSPI"] or {}).get("rows", [{}])[-1]
    fut = (doc["futures"] or {}).get("rows", [{}])[-1]
    prg = (doc["program"]["KOSPI"] or {}).get("rows", [{}])[-1]
    fx = (doc["usdkrw"] or {}).get("rows", [{}])[-1]
    print(f"[{now.isoformat()}] {path.relative_to(Path(args.data_dir).parent)}  대상일 {date}")
    print(f"  KOSPI {k.get('value')} ({k.get('change_pct')}%) 분봉 {len(k.get('bars', []))}개")
    for sym, u in (doc["us_futures"] or {}).items():
        if u:
            print(f"  {u['symbol']} {u['rows'][-1]['c'] if u['rows'] else '-'} (기준 {u['prev_close']}) 1분봉 {len(u['rows'])}개 "
                  f"마지막 {u['asof'][11:16]} 지연 {u.get('delay_min')}분 stale={u.get('stale')}")
    print(f"  외국인 현물 KOSPI {inv.get('foreign')}억 @{inv.get('t')}  행 {len((doc['investor']['KOSPI'] or {}).get('rows', []))}")
    print(f"  외국인 선물 {fut.get('foreign')}계약 ({fut.get('foreign_amt')}억) @{fut.get('t')}")
    print(f"  프로그램 KOSPI 전체 {prg.get('total')}억 (차익 {prg.get('arb')} / 비차익 {prg.get('nonarb')}) @{prg.get('t')}")
    print(f"  USD/KRW 하나은행 고시 {fx.get('v')} @{fx.get('t')}  행 {len((doc['usdkrw'] or {}).get('rows', []))}")
    print(f"  stale: {[n for n, v in [('kospi', doc['index']['KOSPI']), ('inv', doc['investor']['KOSPI']), ('fut', doc['futures']), ('prg', doc['program']['KOSPI']), ('fx', doc['usdkrw'])] if not v or v.get('stale')] or '없음'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
