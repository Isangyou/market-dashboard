"""주간 포지셔닝 리포트 생성 (진입점).

  python -m positioning.run                  # 전체 수집 → 이번 주 파일 갱신
  python -m positioning.run --only cot       # 일부만 (나머지는 이번 주 기존 값 유지)
  python -m positioning.run --data-dir /tmp/x
  python -m positioning.run --rebuild-conclusion   # 수집 없이 저장된 전 주차의 결론만 오래된 주부터 다시 생성

저장 (data/positioning/):
  options_daily.json      옵션 스칼라 지표 일별 누적 {날짜: {SPX: {...}}}  ← 매 실행 누적
  weeks/YYYY-MM-DD.json   주간 스냅샷(키 = 해당 주 금요일, 미국 기준). 주중엔 '진행 중'으로 덮어쓰고
                          금요일 종가 + 그 주 화요일 COT가 모두 반영되면 '확정'
  index.json              주차 목록 (weekly.html 드롭다운)

한 소스가 실패해도 나머지로 파일을 만들고, 실패 섹션은 이번 주 기존 값 → 없으면 전주 값을 stale로 유지.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, timedelta
from pathlib import Path

from fetch.common import log, now_kst

from . import cot as cot_mod
from . import cta as cta_mod
from . import options as opt_mod
from . import brief, report

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = ("cta", "options", "cot")


def week_friday(d: date) -> date:
    return d + timedelta(days=(4 - d.weekday()) % 7) if d.weekday() <= 4 else d - timedelta(days=d.weekday() - 4)


def us_market_date(now) -> date:
    """KST 실행 시각 → 가장 최근 완료된 미국 거래일(대략). 주말·월요일 오전은 직전 금요일."""
    d = (now - timedelta(hours=14)).date()  # KST 06:00 ≈ ET 17:00(서머타임) 이후면 당일 종가 완료
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _dump(p: Path, obj, indent=None):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=indent, allow_nan=False, default=_nan_none) + "\n", encoding="utf-8")


def _nan_none(o):
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=",".join(SECTIONS))
    ap.add_argument("--data-dir", default=str(ROOT / "data" / "positioning"))
    ap.add_argument("--rebuild-conclusion", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.rebuild_conclusion:
        return rebuild_conclusion(Path(a.data_dir))
    only = [s.strip() for s in a.only.split(",") if s.strip()]
    ddir = Path(a.data_dir)

    now = now_kst()
    mdate = us_market_date(now)
    fri = week_friday(mdate)
    wk_path = ddir / "weeks" / f"{fri.isoformat()}.json"
    idx = _load(ddir / "index.json", {"weeks": []})
    existing = _load(wk_path, {})
    prev_weeks = sorted([w["week"] for w in idx["weeks"] if w["week"] < fri.isoformat()])
    prev = _load(ddir / "weeks" / f"{prev_weeks[-1]}.json") if prev_weeks else None

    snap = {"week": fri.isoformat(), "generated": now.isoformat(), "stale": []}
    if "cta" in only:
        snap["cta"] = cta_mod.collect()
    if "options" in only:
        snap["options"] = opt_mod.collect(mdate)
    if "cot" in only:
        snap["cot"] = cot_mod.collect()

    # 실패·미실행 섹션 보충
    for s in SECTIONS:
        empty = s not in snap or not (snap[s].get("assets") or snap[s].get("underlyings") or snap[s].get("markets"))
        if empty:
            fb = existing.get(s) or (prev or {}).get(s)
            if fb:
                snap[s] = fb
                if s in only:
                    snap["stale"].append(s)
                    log.warning("%s 수집 실패 → %s 값 유지", s, "이번 주 기존" if existing.get(s) else "전주")
            else:
                snap[s] = {}

    # 옵션 일별 누적 + 주간 평균 P/C(거래량)
    od_path = ddir / "options_daily.json"
    od = _load(od_path, {"rows": {}})
    if snap["options"].get("underlyings") and "options" in only and "options" not in snap["stale"]:
        od["rows"][mdate.isoformat()] = opt_mod.daily_row(snap["options"])
        od["rows"] = dict(sorted(od["rows"].items())[-800:])
        _dump(od_path, od)
    mon = fri - timedelta(days=4)
    wk_rows = {d: r for d, r in od["rows"].items() if mon.isoformat() <= d <= fri.isoformat()}
    wavg = {}
    for d, r in wk_rows.items():
        for k, v in r.items():
            if v.get("pc_vol") is not None:
                wavg.setdefault(k, []).append(v["pc_vol"])
    snap["options_week"] = {"days": sorted(wk_rows), "pc_vol_avg": {k: round(sum(v) / len(v), 3) for k, v in wavg.items()}}
    # 일별 히스토리(차트용): SPX·VIX 주요 스칼라 최근 1년
    hist_days = sorted(od["rows"])[-260:]
    snap["options_hist"] = {
        "date": hist_days,
        **{f"{k}_{f}": [od["rows"][d].get(k, {}).get(f) for d in hist_days]
           for k in ("SPX", "VIX", "NDX") for f in ("pc_oi", "pc_vol", "gex_usd_bn", "skew_25d_30d", "atm_iv_30d", "spot", "zero_gamma")},
    }

    # 기준일·확정 여부
    cta_asof = max((v["asof"] for v in snap["cta"].get("assets", {}).values()), default=None)
    cot_date = snap["cot"].get("report_date")
    opt_ts = next((v.get("cboe_timestamp") for v in snap["options"].get("underlyings", {}).values()), None)
    snap["asof"] = {"cta": cta_asof, "options": opt_ts, "cot": cot_date, "us_market_date": mdate.isoformat()}
    tue = (fri - timedelta(days=3)).isoformat()
    final = cta_asof == fri.isoformat() and cot_date == tue and not snap["stale"]
    snap["status"] = "확정" if final else "진행 중"
    y, w, _ = fri.isocalendar()
    snap["week_label"] = f"{fri.year}년 {fri.month}월 {(fri.day - 1) // 7 + 1}주차 ({mon.strftime('%m/%d')}–{fri.strftime('%m/%d')}, ISO {y}-W{w:02d})"

    snap["crowding"] = report.crowding(snap["cta"], snap["cot"])
    snap["conclusion"] = report.build_conclusion(snap, prev)
    snap["brief"] = brief.build(snap, prev)
    snap["markdown"] = report.to_markdown(snap)

    _dump(wk_path, snap)
    weeks = {w["week"]: w for w in idx["weeks"]}

    # 휴일로 COT 공표가 다음 주 월요일로 밀린 경우: 전주 파일에 COT만 반영해 확정 처리
    if prev and cot_date and snap["cot"].get("markets"):
        pfri = date.fromisoformat(prev["week"])
        if cot_date == (pfri - timedelta(days=3)).isoformat() and prev.get("status") != "확정":
            prev["cot"] = snap["cot"]
            prev["asof"]["cot"] = cot_date
            prev["stale"] = [s for s in prev.get("stale", []) if s != "cot"]
            pp = sorted(w for w in weeks if w < prev["week"])
            pprev = _load(ddir / "weeks" / f"{pp[-1]}.json") if pp else None
            prev["crowding"] = report.crowding(prev["cta"], prev["cot"])
            prev["conclusion"] = report.build_conclusion(prev, pprev)
            prev["brief"] = brief.build(prev, pprev)
            prev["markdown"] = report.to_markdown(prev)
            prev["status"] = "확정" if prev["asof"].get("cta") == prev["week"] and not prev["stale"] else prev["status"]
            _dump(ddir / "weeks" / f"{prev['week']}.json", prev)
            weeks[prev["week"]]["status"] = prev["status"]
            log.info("전주(%s) 파일에 지연 공표 COT(%s) 반영 → %s", prev["week"], cot_date, prev["status"])
    weeks[fri.isoformat()] = {"week": fri.isoformat(), "label": snap["week_label"], "status": snap["status"],
                              "generated": snap["generated"]}
    _dump(ddir / "index.json", {"weeks": sorted(weeks.values(), key=lambda w: w["week"], reverse=True)}, indent=1)
    log.info("저장: %s (%s) stale=%s", wk_path, snap["status"], snap["stale"])
    print(snap["markdown"])


def rebuild_conclusion(ddir: Path):
    """규칙 변경 후 기존 주차 결론 재생성. 전주 brief를 쓰므로 오래된 주부터 순서대로"""
    idx = _load(ddir / "index.json", {"weeks": []})
    prev = None
    for w in sorted(x["week"] for x in idx["weeks"]):
        p = ddir / "weeks" / f"{w}.json"
        snap = _load(p)
        if not snap:
            continue
        snap.pop("summary", None)
        snap["conclusion"] = report.build_conclusion(snap, prev)
        snap["brief"] = brief.build(snap, prev)
        snap["markdown"] = report.to_markdown(snap)
        _dump(p, snap)
        log.info("결론 재생성: %s", w)
        print(snap["markdown"] + "\n")
        prev = snap


if __name__ == "__main__":
    main()
