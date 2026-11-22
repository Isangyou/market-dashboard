"""미국 옵션 스냅샷 — CBOE 지연 체인(15분 지연, 키 불필요) → data/options/{SYM}.json + index.json.

options.html이 읽는 데이터. CBOE는 브라우저의 직접 조회를 CORS로 막으므로(2026-11-15 확인,
Access-Control-Allow-Origin 없음) 화면은 이 스냅샷만 읽는다. 갱신은 scripts/options_loop.sh(Actions options.yml).

엔드포인트·응답 형식·시각 해석은 positioning/options.py와 같다 (_fetch, SYM_RE, chain_asof, chain_label 재사용).
  응답 `timestamp` = CBOE가 그 파일을 만든 시각(UTC, Last-Modified와 2초 이내). 요청 시각이 아니다 —
  휴장 중에는 몇 시간씩 그대로다(11-15 일 05:09 UTC 조회 시 SPY 11-14 23:57:55). `data.last_trade_time` = 기초자산 마지막 체결(ET).
  CDN 캐시는 5초(Cache-Control: max-age=0, s-maxage=5, stale-while-revalidate=5).

지표는 계산하지 않는다. 계산은 options.html 한 곳에서만 한다.
여기서는 화면이 쓰는 필드만 남겨 용량을 줄인다(11-13 종가 체인 14종목: 원본 36.5MB → 스냅샷 3.4MB).

저장:
  data/options/{SYM}.json
    {"sym", "cboe", "timestamp", "last_trade_time", "spot", "chg_pct", "iv30", "iv30_chg", "source",
     "roots": [...], "exps": [...], "cols": [...],
     "rows": [[root_i, exp_i, cp(1=콜·0=풋), 행사가, 거래량, OI, iv, delta, bid, ask], ...]}
    뺀 행: 심볼 루트에 숫자가 낀 계약(조정 계약, B1SPY… 같은 별도 상품군 — positioning과 같은 SYM_RE),
           거래량·OI가 0이면서 양쪽 호가도 없는 계약(어느 지표에도 안 쓰임)
  data/options/index.json
    {"generated_kst", "source", "tickers": [{"sym", "file", "timestamp", "last_trade_time", "label", "rows", "stale"}], "failed": [...]}
    실패한 종목은 이전 파일 유지 + stale: true. 이전 파일도 없으면 failed에만 기록

종목 목록: data/options_watchlist.json {"tickers": [...]} — 여기만 고치면 다음 회차부터 화면에 반영. 지수는 SPX처럼 적으면 _SPX로 요청.

실행: python -m fetch.options_live [--out DIR] [--tickers SPY,QQQ] [--sleep 1.0] [--exit-if-closed]
종료코드: 0 = 기록(변경 있음/없음 무관), 1 = 전 종목 실패,
          3 = 기록했지만 오늘(ET) 체결된 종목이 없음(휴장·개장 전) — --exit-if-closed 일 때만. 루프의 휴장 판정용
          4 = HTTP 403·429(차단·제한) → 그 자리에서 나머지 종목 요청 생략, 이전 값 stale로 index 기록. 루프는 종료
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "fetch"

from positioning.options import SYM_RE, _fetch, chain_asof, chain_label, fail_reason  # noqa: E402

from .common import log, now_kst  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WATCHLIST = ROOT / "data" / "options_watchlist.json"
DEFAULT_TICKERS = ["SPY", "QQQ", "IWM", "NVDA", "TSLA", "AAPL", "PLTR", "AMD", "AMZN", "GOOGL", "MU", "META", "MSFT", "AVGO"]
INDEX_ROOTS = {"SPX", "NDX", "RUT", "VIX", "XSP", "DJX", "OEX", "XEO"}   # CBOE 심볼이 '_' 접두인 지수
SOURCE = "CBOE delayed quotes (cdn.cboe.com/api/global/delayed_quotes/options), 15분 지연"
COLS = ["root_i", "exp_i", "cp", "strike", "vol", "oi", "iv", "delta", "bid", "ask"]


def cboe_symbol(sym: str) -> str:
    return f"_{sym}" if sym in INDEX_ROOTS else sym


def watchlist(path: Path = WATCHLIST) -> list[str]:
    try:
        tickers = json.loads(path.read_text(encoding="utf-8"))["tickers"]
        out = [str(t).strip().upper() for t in tickers if str(t).strip()]
        return list(dict.fromkeys(out)) or DEFAULT_TICKERS
    except Exception as e:  # noqa: BLE001
        log.warning("관심 종목 파일 %s 읽기 실패(%s) → 기본 목록", path, e)
        return DEFAULT_TICKERS


def _num(x) -> float | int:
    """정수면 정수로(용량 절약), 아니면 소수 4자리"""
    x = float(x or 0)
    return int(x) if x == int(x) else round(x, 4)


def _opt(x) -> float | None:
    try:
        return round(float(x), 4)
    except (TypeError, ValueError):
        return None


def compact(sym: str, js: dict) -> dict:
    """CBOE 응답 → 화면용 압축 형식. 기초자산 가격이 없으면 ValueError"""
    data = js.get("data") or {}
    spot = data.get("current_price") or data.get("close")
    if not spot:
        raise ValueError("기초자산 가격 없음")
    roots, exps, rows = {}, {}, []
    for o in data.get("options") or []:
        m = SYM_RE.match(o.get("option") or "")
        if not m:
            continue
        root, ymd, cp, k = m.groups()
        vol, oi = int(float(o.get("volume") or 0)), int(float(o.get("open_interest") or 0))
        bid, ask = float(o.get("bid") or 0), float(o.get("ask") or 0)
        if vol == 0 and oi == 0 and not (bid > 0 and ask > 0):
            continue
        exp = f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:]}"
        rows.append([roots.setdefault(root, len(roots)), exps.setdefault(exp, len(exps)), 1 if cp == "C" else 0,
                     _num(int(k) / 1000), vol, oi, round(float(o.get("iv") or 0), 4),
                     round(float(o.get("delta") or 0), 4), _num(bid), _num(ask)])
    if not rows:
        raise ValueError("빈 체인")
    return {"sym": sym, "cboe": cboe_symbol(sym), "timestamp": js.get("timestamp"),
            "last_trade_time": data.get("last_trade_time"), "spot": float(spot),
            "chg_pct": _opt(data.get("price_change_percent")), "iv30": _opt(data.get("iv30")),
            "iv30_chg": _opt(data.get("iv30_change")), "source": SOURCE,
            "roots": list(roots), "exps": list(exps), "cols": COLS, "rows": rows}


def _entry(doc: dict, stale: bool) -> dict:
    ca = chain_asof(doc.get("timestamp") or "", doc.get("last_trade_time"))
    return {"sym": doc["sym"], "file": f"{doc['sym']}.json", "timestamp": doc.get("timestamp"),
            "last_trade_time": doc.get("last_trade_time"), "label": chain_label(ca),
            "rows": len(doc.get("rows") or []), "stale": stale}


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _write(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def collect(tickers: list[str], out: Path, sleep: float = 1.0) -> dict:
    """종목별 수집·저장 → index 내용 반환. 수집 시각(timestamp)이 이전 파일과 같으면 다시 쓰지 않음"""
    out.mkdir(parents=True, exist_ok=True)
    entries, failed, changed, errors, blocked = [], [], 0, {}, None
    for i, sym in enumerate(tickers):
        path = out / f"{sym}.json"
        old = _read(path)
        if blocked:   # 403·429 뒤로는 요청하지 않음(CLAUDE.md: 즉시 중단) — 이전 값만 stale로
            failed.append(sym)
            errors[sym] = f"요청 생략({blocked})"
            if old:
                entries.append(_entry(old, stale=True))
            continue
        if i:
            time.sleep(sleep)
        try:
            doc = compact(sym, _fetch(cboe_symbol(sym)))
        except Exception as e:  # noqa: BLE001 — 한 종목 실패가 전체를 막지 않게
            errors[sym] = fail_reason(e)
            log.warning("옵션 %s 실패: %s (%s: %s)", sym, errors[sym], type(e).__name__, str(e)[:200])
            failed.append(sym)
            if old:
                entries.append(_entry(old, stale=True))
            if errors[sym].startswith(("HTTP 403", "HTTP 429")):
                blocked = errors[sym]
                log.warning("CBOE %s → 나머지 %d종목 요청 생략", blocked, len(tickers) - i - 1)
            continue
        if not old or old.get("timestamp") != doc["timestamp"]:
            _write(path, doc)
            changed += 1
        entries.append(_entry(doc, stale=False))
        log.info("옵션 %-5s spot=%.2f 계약 %d · %s", sym, doc["spot"], len(doc["rows"]), entries[-1]["label"])
    index = {"generated_kst": now_kst().isoformat(), "source": SOURCE, "tickers": entries, "failed": failed,
             "errors": errors, "blocked": blocked}
    old_index = _read(out / "index.json") or {}
    same = all(old_index.get(k) == index[k] for k in ("tickers", "failed", "blocked"))
    if changed or not same:
        _write(out / "index.json", index)
    log.info("옵션 스냅샷: 종목 %d · 갱신 %d · 실패 %d%s", len(tickers), changed, len(failed),
             "" if changed or not same else " · 변경 없음")
    return index


def traded_today(index: dict) -> bool:
    """방금 받은(stale 아님) 종목 중 last_trade_time 날짜가 오늘(ET)인 것이 있는가"""
    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    return any((t.get("last_trade_time") or "")[:10] == today for t in index["tickers"] if not t.get("stale"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "options"))
    ap.add_argument("--tickers", default="", help="쉼표 구분. 비우면 data/options_watchlist.json")
    ap.add_argument("--sleep", type=float, default=1.0, help="요청 간격(초)")
    ap.add_argument("--exit-if-closed", action="store_true", help="오늘(ET) 체결된 종목이 없으면 종료코드 3")
    args = ap.parse_args(argv)

    import logging
    if not log.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        log.addHandler(h)
    log.setLevel(logging.INFO)
    log.propagate = False

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] or watchlist()
    index = collect(tickers, Path(args.out), args.sleep)
    if index.get("blocked"):
        return 4
    if not index["tickers"]:
        return 1
    if args.exit_if_closed and not traded_today(index):
        log.info("오늘(ET) 체결된 종목 없음 → 휴장 또는 개장 전")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
