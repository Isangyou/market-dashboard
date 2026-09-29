"""전체 수집 → data/latest.json, data/series/*.json 갱신.

실행: python -m fetch.run  (또는 python fetch/run.py)
옵션: --disable naver,yfinance   특정 소스 강제 비활성 (폴백·stale 검증용)
      --backfill                 시계열을 길게(약 1년) 다시 받음

규칙
- 소스 우선순위 naver > pykrx/fred > yfinance. 시계열의 같은 날짜는 우선순위가 같거나
  높은 소스만 덮어씀(폴백 값이 1차 값을 덮지 않음). 각 레코드에 source·asof 보존
- 항목이 모든 소스에서 실패하면 latest.json의 이전 값 유지 + stale: true
- 내용이 바뀐 파일만 씀 (generated_at만 다른 경우는 쓰지 않음)
"""
import argparse
import json
import logging
import math
import sys
from datetime import timedelta
from pathlib import Path

if __package__ in (None, ""):  # python fetch/run.py 로 직접 실행한 경우
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "fetch"

import pandas as pd  # noqa: E402

from . import fred, krx, kred, naver, yf  # noqa: E402
from .common import log, now_kst  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SERIES_DIR = DATA / "series"
PRIORITY = {"naver": 0, "kred": 0, "pykrx": 1, "fred": 1, "yfinance": 2}
MARKETS = ["KOSPI", "KOSDAQ"]
UST_TENORS = ["1M", "2M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]

# key → (라벨, 단위)
VALUE_SERIES = {
    **{f"ust_{t.lower()}": (f"미국채 {t}", "%") for t in UST_TENORS},
    "ktb_3y": ("국고 3Y", "%"), "ktb_10y": ("국고 10Y", "%"),
    "usdkrw": ("USD/KRW", "KRW"), "usdjpy": ("USD/JPY", "JPY"), "usdcnh": ("USD/CNH", "CNH"),
    "eurusd": ("EUR/USD", "USD"), "dxy": ("DXY", "pt"),
    "wti": ("WTI", "USD/bbl"), "brent": ("Brent", "USD/bbl"), "vix": ("VIX", "pt"),
    "kospi": ("코스피", "pt"), "kosdaq": ("코스닥", "pt"),
}

# pykrx는 KRX 로그인 요구로 현재 동작하지 않아 기본 비활성 (코드는 유지, --enable pykrx 로 켬)
DEFAULT_DISABLED = {"pykrx"}
disabled: set = set()


def call(source: str, fn, *args, **kwargs):
    if source in disabled:
        return None
    return fn(*args, **kwargs)


def prio(src: str) -> int:
    return PRIORITY.get(src.split(":")[0], 9)


def clean(v):
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):  # numpy 스칼라
        return v.item()
    return v


def records(df) -> list:
    return [{k: clean(v) for k, v in r.items()} for r in df.to_dict("records")]


def write_if_changed(path: Path, obj: dict, ignore=("generated_at",)) -> bool:
    old = json.loads(path.read_text()) if path.exists() else None
    strip = lambda o: {k: v for k, v in (o or {}).items() if k not in ignore}  # noqa: E731
    if old is not None and strip(old) == strip(obj):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")
    return True


class Series:
    """data/series/{key}.json — {"key","label","unit","records":[{date,...,source,asof}]}"""

    def __init__(self, key, label, unit):
        self.key, self.label, self.unit = key, label, unit
        self.path = SERIES_DIR / f"{key}.json"
        old = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.by_date = {r["date"]: r for r in old.get("records", [])}

    def __len__(self):
        return len(self.by_date)

    def merge(self, df) -> int:
        if df is None:
            return 0
        n = 0
        for r in records(df):
            cur = self.by_date.get(r["date"])
            if cur is None or prio(r["source"]) <= prio(cur["source"]):
                if cur != r:
                    n += 1
                self.by_date[r["date"]] = r
        return n

    def last(self, k=1):
        return [self.by_date[d] for d in sorted(self.by_date)[-k:]]

    def save(self) -> bool:
        recs = [self.by_date[d] for d in sorted(self.by_date)]
        return write_if_changed(self.path, {"key": self.key, "label": self.label,
                                            "unit": self.unit, "records": recs}, ignore=())


def latest_from_history(df):
    """시계열 마지막 2행으로 현재값 카드 구성 (1차 현재값 API 실패 시)."""
    if df is None or len(df) == 0:
        return None
    df = df.sort_values("date")
    last = df.iloc[-1]
    prev = df.iloc[-2]["value"] if len(df) > 1 else None
    chg = None if prev is None else round(last["value"] - prev, 4)
    pct = None if not prev else round(chg / prev * 100, 2)
    return {"value": clean(last["value"]), "change": clean(chg), "change_pct": clean(pct),
            "source": last["source"], "asof": last["asof"]}


ADR_N = 20
KRED_MAX_PER_DAY = 2


def kred_due(now, fetches: list, last_date: str) -> bool:
    """KRED 요청 여부. 하루 최대 2회: 16:30 이후 첫 1회, 그게 당일 값을 못 받았으면 20:00 이후 1회 더.
    fetches = 오늘(KST) 요청 시각 목록(ISO)."""
    today, hm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    mine = [t for t in fetches if t.startswith(today)]
    if len(mine) >= KRED_MAX_PER_DAY or hm < "16:30":
        return False
    return not mine or (hm >= "20:00" and max(mine)[11:16] < "20:00" and (last_date or "") < today)


def adr_from_breadth(recs):
    """ADR = 최근 20거래일 상승 종목 수 합 ÷ 하락 종목 수 합 × 100. 누적 20일 미만이면 None.
    누락된 날(마감 후 실행이 한 번도 안 돈 날)이 있으면 창이 20거래일보다 길어짐 — 미보정."""
    out = []
    for i in range(ADR_N - 1, len(recs)):
        w = recs[i - ADR_N + 1:i + 1]
        fall = sum(r["fall"] for r in w)
        if fall:
            out.append({"date": w[-1]["date"], "value": round(sum(r["rise"] for r in w) / fall * 100, 2),
                        "source": "naver:indicators_breadth", "asof": w[-1]["asof"]})
    return pd.DataFrame(out) if out else None


def row_of(df, col, code):
    if df is None:
        return None
    hit = df[df[col] == code]
    if hit.empty:
        return None
    r = {k: clean(v) for k, v in hit.iloc[0].to_dict().items()}
    out = {k: r.get(k) for k in ("value", "change", "change_pct", "source", "asof")}
    out.update({k: r[k] for k in ("high", "low") if r.get(k) is not None})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--disable", default="", help="쉼표 구분: naver,yfinance,fred,pykrx")
    ap.add_argument("--enable", default="", help="기본 비활성 소스 켜기 (쉼표 구분: pykrx)")
    ap.add_argument("--backfill", action="store_true")
    args = ap.parse_args()
    disabled.update(DEFAULT_DISABLED - {s for s in args.enable.split(",") if s})
    disabled.update(s for s in args.disable.split(",") if s)

    # 루트 로거는 건드리지 않음 (pykrx가 루트에 잘못된 포맷으로 logging.info를 호출함)
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    log.propagate = False
    now = now_kst()
    prev_latest = json.loads((DATA / "latest.json").read_text()) if (DATA / "latest.json").exists() else {}
    prev_items = prev_latest.get("items", {})
    changed = []

    # ── 현재값 목록 (한 번씩만 호출) ──
    curve = {n: call("naver", naver.bond_curve, n) for n in ("USA", "KOR")}
    world = call("naver", naver.marketindex_list, "exchangeWorld")
    majors = call("naver", naver.marketindex_list, "majors/exchange")
    energy = call("naver", naver.marketindex_list, "energy")
    naver_latest = {
        **{k: row_of(curve["USA"], "key", k) for k in VALUE_SERIES if k.startswith("ust_")},
        "ktb_3y": row_of(curve["KOR"], "key", "ktb_3y"),
        "ktb_10y": row_of(curve["KOR"], "key", "ktb_10y"),
        "usdkrw": row_of(call("naver", naver.usdkrw_latest), "code", "FX_USDKRW"),
        "usdjpy": row_of(world, "code", "USDJPY"),
        "eurusd": row_of(world, "code", "EURUSD"),
        "dxy": row_of(majors, "code", ".DXY"),
        "wti": row_of(energy, "code", "CLcv1"),
        "brent": row_of(energy, "code", "LCOcv1"),
        "vix": row_of(call("naver", naver.vix_latest), "code", ".VIX"),
    }

    # ── 값 시계열 ──
    items = {}
    for key, (label, unit) in VALUE_SERIES.items():
        s = Series(key, label, unit)
        long = args.backfill or len(s) < 60
        months, pages = (12, 5) if long else (1, 1)
        start = (now - timedelta(days=370 if long else 40)).strftime("%Y-%m-%d")
        period = "1y" if long else "1mo"

        cands = []  # (source, 호출) — 앞에서부터 첫 성공 사용
        if key.startswith("ust_") or key.startswith("ktb_"):
            code = ("US" if key.startswith("ust_") else "KR") + key.split("_")[1].upper() + "T=RR"
            cands.append(("naver", lambda: naver.bond_history(code, months)))
            cands.append(("fred", lambda: fred.history(key, start)))
        elif key == "usdkrw":
            cands.append(("naver", lambda: naver.usdkrw_history(months)))
        elif key in naver.PRICE_PATHS:
            cands.append(("naver", lambda: naver.prices_history(key, pages)))
        if key in yf.TICKERS:
            cands.append(("yfinance", lambda: yf.history(key, period)))

        hist = None
        for src, fn in cands:
            hist = call(src, fn)
            if hist is not None:
                break
        n_new = s.merge(hist)
        if s.save():
            changed.append(f"series/{key}.json (+{n_new})")

        cur = naver_latest.get(key) if "naver" not in disabled else None
        if not cur and hist is not None:
            # 소스가 1행만 줄 때(CNH=X 등)는 같은 소스의 누적 시계열로 전일대비 계산
            same = [r for r in s.last(len(s)) if r["source"] == hist.iloc[-1]["source"]]
            cur = latest_from_history(hist if len(hist) > 1 else pd.DataFrame(same))
        if cur:
            items[key] = {"label": label, "unit": unit, **cur, "stale": False}
        elif key in prev_items:
            items[key] = {**prev_items[key], "stale": True}
            log.warning("%s: 모든 소스 실패 → 이전 값 유지(stale)", key)
        else:
            log.warning("%s: 모든 소스 실패, 이전 값도 없음", key)

    # ── 지수 일별 거래대금 (E36, 억원) ── 네이버가 최근 약 6거래일만 보관 → 과거분 없음, 09-17부터 누적.
    # 날짜당 요청 1회라 kospi.json 최근 10거래일 중 빠진 날만 받음(보통 장 마감 후 1건). 6거래일 넘게 못 받으면 그날은 영구 결측
    kdates = [r["date"] for r in Series("kospi", "코스피", "pt").last(10)]
    for m in MARKETS:
        s = Series(f"tv_{m.lower()}", f"{m} 거래대금", "억원")
        todo = [d for d in kdates if d not in s.by_date]
        if todo:
            n_new = s.merge(call("naver", naver.index_trading_value, m, todo))
            if s.save():
                changed.append(f"series/tv_{m.lower()}.json (+{n_new})")

    # ── VKOSPI (KRED 재공표) ── 요청 1회에 전체 이력. 요청 시각은 latest.json meta.kred_fetches에 기록해 하루 2회 제한
    s = Series("vkospi", "VKOSPI", "pt")
    fetches = [t for t in prev_latest.get("meta", {}).get("kred_fetches", []) if t[:10] == now.strftime("%Y-%m-%d")]
    kred_ok = None   # None = 이번엔 안 부름
    if "kred" not in disabled and kred_due(now, fetches, s.last()[0]["date"] if len(s) else ""):
        fetches.append(now.isoformat(timespec="seconds"))
        df = kred.vkospi_history()
        kred_ok = df is not None
        n_new = s.merge(df)
        if s.save():
            changed.append(f"series/vkospi.json (+{n_new})")
    if kred_ok is False and "vkospi" in prev_items:
        items["vkospi"] = {**prev_items["vkospi"], "stale": True}
        log.warning("vkospi: kred 실패 → 이전 값 유지(stale)")
    elif len(s):
        items["vkospi"] = {"label": "VKOSPI", "unit": "pt",
                           **latest_from_history(pd.DataFrame(s.last(2))), "stale": False}

    # ── 투자자별 순매수 ──
    investor, prev_inv = {}, prev_latest.get("investor", {})
    for m in MARKETS:
        s = Series(f"investor_{m.lower()}", f"{m} 투자자별 순매수", "억원")
        long = args.backfill or len(s) < 200
        df = call("naver", naver.investor_daily, m, 3 if long else 1, 100 if long else 30)
        if df is None:
            end = now.strftime("%Y%m%d")
            start = (now - timedelta(days=400 if long else 45)).strftime("%Y%m%d")
            df = call("pykrx", krx.investor_daily, m, start, end)
        n_new = s.merge(df)
        today = call("naver", naver.investor_today, m)
        if today is not None and (df is None or today.iloc[0]["date"] not in set(df["date"])):
            n_new += s.merge(today)  # 장중 잠정치: 다음 실행에 E3 확정치로 대체됨
        if s.save():
            changed.append(f"series/investor_{m.lower()}.json (+{n_new})")
        if df is not None or today is not None:
            investor[m] = {**s.last()[0], "stale": False}
        elif m in prev_inv:
            investor[m] = {**prev_inv[m], "stale": True}
            log.warning("investor %s: 실패 → stale", m)

    # ── 개별 종목 일별 종가 (이격도 차트용) ── 첫 실행 3페이지(약 300거래일), 이후 1페이지
    for code, name in naver.STOCKS.items():
        s = Series(f"stock_{code}", name, "원")
        n_new = s.merge(call("naver", naver.stock_daily, code, 3 if args.backfill or len(s) < 250 else 1))
        if s.save():
            changed.append(f"series/stock_{code}.json (+{n_new})")

    # ── 등락 종목 수 → ADR ── 네이버에 이력이 없어 장 마감 후 스냅샷을 날짜별로 직접 누적하고
    # 20일 ADR을 계산해 adr_*.json에 source=naver로 이어 붙임. 장중엔 breadth()가 None → 아무것도 안 함
    bdf, breadth = call("naver", naver.breadth), {}
    for m in MARKETS:
        s = breadth[m] = Series(f"breadth_{m.lower()}", f"{m} 상승·하락 종목 수", "종목")
        rows = None if bdf is None else bdf[bdf["market"] == m].drop(columns="market")
        n_new = s.merge(rows if rows is not None and len(rows) else None)
        if s.save():
            changed.append(f"series/breadth_{m.lower()}.json (+{n_new})")
        a = Series(f"adr_{m.lower()}", f"{m} ADR 20일", "%")
        n_new = a.merge(adr_from_breadth(s.last(len(s))))
        if a.save():
            changed.append(f"series/adr_{m.lower()}.json (+{n_new})")

    # ── 증시자금동향 (하루 1회 갱신, 2거래일 지연) ── 첫 실행·--backfill은 전체 이력(약 61페이지),
    # 이후엔 최신 100행만. asof=기준일이라 값이 같으면 write_if_changed가 파일을 안 씀
    s = Series("deposit", "증시자금동향 (고객예탁금·신용잔고·펀드)", "억원")
    df = call("naver", naver.deposit_trend, 70 if args.backfill or len(s) < 1000 else 1)
    n_new = s.merge(df)
    if s.save():
        changed.append(f"series/deposit.json (+{n_new})")
    deposit_last = s.last()[0] if len(s) else None

    # ── 외국인 상위 10 ──
    top, prev_top = {}, prev_latest.get("foreign_top", {})
    for m in MARKETS:
        df = call("naver", naver.foreign_top, m, "DAY", 10)
        if df is None and m in investor:
            df = call("pykrx", krx.foreign_top, m, investor[m]["date"].replace("-", ""), 10)
        if df is not None:
            r = records(df)
            top[m] = {"period": "DAY", "source": r[0]["source"], "asof": r[0]["asof"],
                      "date_from": r[0]["date_from"], "date_to": r[0]["date_to"],
                      "buy": [x for x in r if x["side"] == "buy"],
                      "sell": [x for x in r if x["side"] == "sell"], "stale": False}
        elif m in prev_top:
            top[m] = {**prev_top[m], "stale": True}
            log.warning("foreign_top %s: 실패 → stale", m)

    inv_sources = ["naver"] + ([] if "pykrx" in disabled else ["pykrx"])
    latest = {"generated_at": now.isoformat(), "items": items,
              "investor": investor, "foreign_top": top,
              "meta": {"investor_sources": inv_sources, "pykrx_enabled": "pykrx" not in disabled,
                       "kred_fetches": fetches}}
    if write_if_changed(DATA / "latest.json", latest):
        changed.append("latest.json")

    # ── 요약 출력 ──
    print(f"\n[{now.isoformat()}] naver blocked={naver.is_blocked()} disabled={sorted(disabled) or '-'}")
    print(f"{'key':10} {'value':>10} {'chg':>9}  {'source':24} {'asof':26} stale")
    for k, v in items.items():
        print(f"{k:10} {v['value']!s:>10} {v.get('change')!s:>9}  {v['source']:24} {v['asof']:26} {v['stale']}")
    for m, v in investor.items():
        print(f"investor {m:7} {v['date']} 외국인 {v['foreign']:,.0f}억 개인 {v['individual']:,.0f}억 "
              f"기관계 {v['institution']:,.0f}억  [{v['source']} {v['asof']}] stale={v['stale']}")
    if deposit_last:
        r = deposit_last
        print(f"deposit {r['date']} 고객예탁금 {r['deposit']:,.0f}억 신용잔고 {r['credit']:,.0f}억 "
              f"주식형 {r['fund_stock']:,.0f}억 [{r['source']}]")
    for m, bs in breadth.items():
        if len(bs):
            r = bs.last()[0]
            print(f"breadth {m:7} {r['date']} 상승 {r['rise']} 하락 {r['fall']} 보합 {r['steady']} "
                  f"[{r['source']} {r['asof']}] 누적 {len(bs)}일")
    for m, v in top.items():
        b, s_ = v["buy"][0], v["sell"][0]
        print(f"top {m:7} 매수1 {b['name']} {b['net_amount']:,}억 / 매도1 {s_['name']} {s_['net_amount']:,}억 "
              f"[{v['source']} {v['date_to']}] stale={v['stale']}")
    print(f"\n변경 파일 {len(changed)}개: " + (", ".join(changed) if changed else "없음"))


if __name__ == "__main__":
    main()
