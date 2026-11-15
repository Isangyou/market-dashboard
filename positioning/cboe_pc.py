"""CBOE 일별 Put/Call Ratio (Index · Total · Equity) — CBOE 공표치, 키 불필요.

엔드포인트: https://cdn.cboe.com/data/us/options/market_statistics/daily/{YYYY-MM-DD}_daily_options
  (cboe.com/us/options/market_statistics/daily/ 화면이 읽는 JSON)
  응답: {"ratios": [{"name": "TOTAL PUT/CALL RATIO", "value": "0.95"}, ...], "INDEX OPTIONS": [...], ...}
  거래일이 아니거나 아직 공표 전이면 403(S3 AccessDenied) → 데이터 없음으로 처리. 그 외 오류는 중단
  2026-11-08 확인: 11/6 Total 0.95 · Index 1.26 · Equity 0.59, 2019-11-06도 200

저장: data/positioning/cboe_pc.json {"source", "rows": {날짜: {index, total, equity}}, "no_data": [날짜]}
  첫 실행 BACKFILL_DAYS 평일, 이후 마지막 행 다음 날 ~ 오늘(ET) + 최근 RECHECK_DAYS 평일 중 빠진 날만 요청
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from fetch.common import UA, log

URL = "https://cdn.cboe.com/data/us/options/market_statistics/daily/{d}_daily_options"
SOURCE = "CBOE (cboe.com/us/options/market_statistics/daily)"
NAMES = {"index": "INDEX PUT/CALL RATIO", "total": "TOTAL PUT/CALL RATIO", "equity": "EQUITY PUT/CALL RATIO"}
BACKFILL_DAYS = 370
RECHECK_DAYS = 10


def _weekdays(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def fetch_day(d: date) -> dict | None:
    """그날 세 비율. 403(거래일 아님·공표 전)이면 None, 그 외 HTTP 오류는 예외"""
    r = requests.get(URL.format(d=d.isoformat()), headers={"User-Agent": UA}, timeout=30)
    if r.status_code == 403:
        return None
    r.raise_for_status()
    rat = {x.get("name"): x.get("value") for x in r.json().get("ratios", [])}
    row = {k: float(rat[n]) for k, n in NAMES.items() if rat.get(n) not in (None, "")}
    return row or None


def update(path: Path, today: date | None = None) -> dict:
    """빠진 날만 요청해 파일 갱신. 실패해도 기존 파일 유지(반환값 = 현재 내용)"""
    try:
        db = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        db = {"rows": {}, "no_data": []}
    db["source"] = SOURCE
    rows, nod = db.setdefault("rows", {}), set(db.setdefault("no_data", []))
    today = today or datetime.now(ZoneInfo("America/New_York")).date()
    start = today - timedelta(days=BACKFILL_DAYS) if not rows else min(
        date.fromisoformat(max(rows)) + timedelta(days=1), today - timedelta(days=RECHECK_DAYS))
    todo = [d for d in _weekdays(start, today) if d.isoformat() not in rows and d.isoformat() not in nod]
    got = 0
    for d in todo:
        try:
            row = fetch_day(d)
        except Exception as e:  # noqa: BLE001
            log.warning("CBOE P/C %s 실패 → 중단: %s: %s", d, type(e).__name__, e)
            break
        if row:
            rows[d.isoformat()] = row
            got += 1
        elif (today - d).days > 3:   # 3일 넘게 없으면 휴장일로 보고 다시 묻지 않음
            nod.add(d.isoformat())
        time.sleep(1.1)
    db["rows"] = dict(sorted(rows.items()))
    db["no_data"] = sorted(nod)
    if got or todo:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(db, ensure_ascii=False) + "\n", encoding="utf-8")
    last = max(rows) if rows else None
    log.info("CBOE P/C: 요청 %d일 · 새 행 %d · 전체 %d행 · 마지막 %s %s", len(todo), got, len(rows), last, rows.get(last) if last else "")
    return db


# ── 주간 비교 (위클리 결론용) ──
PC_UNIT = 0.10          # 금 vs 전주 금, 주평균 vs 전주 평균 — 어느 한쪽이 |Δ| ≥ 이 값이면 '변화 있음'
UNWIND_PCTILE = 0.90    # 전주 금요일 값이 직전 1년(YEAR_DAYS 거래일) 상위 10% 안이고
UNWIND_DROP = 0.20      # 한 주 만에(금→금) 이만큼 이상 빠지면 '헤지 피크 후 되감기'
YEAR_DAYS = 252
LABEL = {"index": "Index", "total": "Total", "equity": "Equity"}


def week_stats(db: dict | None, fri: date | str) -> dict | None:
    """fri가 속한 주(월~금)와 그 전주의 금요일(=주 마지막 거래일) 종가·주평균 비교.
    반환 {"days", "prev_days", "series": {index|total|equity: {...}}} — 이번 주나 전주 행이 없으면 None"""
    rows = (db or {}).get("rows") or {}
    fri = date.fromisoformat(fri) if isinstance(fri, str) else fri
    mon, pfri = fri - timedelta(days=4), fri - timedelta(days=7)
    pmon = pfri - timedelta(days=4)
    ks = sorted(rows)
    cur = [k for k in ks if mon.isoformat() <= k <= fri.isoformat()]
    prv = [k for k in ks if pmon.isoformat() <= k <= pfri.isoformat()]
    if not cur or not prv:
        return None
    # 전주까지 금→금 주간 변화(1년) — 이번 주 하락폭 순위용
    by_wk = {}
    for k in ks:
        if k <= fri.isoformat():
            by_wk[date.fromisoformat(k).isocalendar()[:2]] = k
    wl = sorted(by_wk.values())[-53:]
    out = {"days": cur, "prev_days": prv, "series": {}}
    for f in NAMES:
        cv = [rows[k][f] for k in cur if f in rows[k]]
        pv = [rows[k][f] for k in prv if f in rows[k]]
        if not cv or not pv:
            continue
        last, plast = cv[-1], pv[-1]
        avg, pavg = round(sum(cv) / len(cv), 3), round(sum(pv) / len(pv), 3)
        d_fri, d_avg = round(last - plast, 2), round(avg - pavg, 3)
        year = [rows[k][f] for k in ks if k <= prv[-1] and f in rows[k]][-YEAR_DAYS:]
        pct = sum(x <= plast for x in year) / len(year)
        wchg = [round(rows[wl[i]][f] - rows[wl[i - 1]][f], 2) for i in range(1, len(wl)) if f in rows[wl[i]] and f in rows[wl[i - 1]]]
        out["series"][f] = {
            "label": LABEL[f], "fri": last, "fri_date": cur[-1], "prev_fri": plast, "prev_fri_date": prv[-1],
            "d_fri": d_fri, "avg": avg, "prev_avg": pavg, "d_avg": d_avg,
            "changed": abs(d_fri) >= PC_UNIT - 1e-9 or abs(round(d_avg, 2)) >= PC_UNIT - 1e-9,
            "prev_pctile_1y": round(pct, 3), "prev_is_1y_high": plast >= max(year), "year_days": len(year),
            "drop_rank_1y": (sorted(wchg).index(d_fri) + 1) if d_fri < 0 and d_fri in wchg else None, "weeks_1y": len(wchg),
            "unwind": pct >= UNWIND_PCTILE and d_fri <= -UNWIND_DROP + 1e-9,
        }
    return out if out["series"] else None
