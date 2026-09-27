"""거래일(휴장일) 판정 — update.yml·intraday.yml 공용.

1차: 네이버 market-status (`today.isTradingDay`, 공휴일·임시휴장 반영)
실패 시: 평일=거래일로 간주 (보수적으로 수집은 돌게 함)

CLI: python -m fetch.market_day [--github-output]
  → 상태 출력, --github-output이면 $GITHUB_OUTPUT에 trading=true|false, next=YYYY-MM-DD 기록. 종료코드는 항상 0
"""
import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "fetch"

from . import naver  # noqa: E402
from .common import log, now_kst  # noqa: E402


def status() -> dict:
    """{"date","trading","holiday","next","latest","source"}"""
    today = now_kst().date().isoformat()
    b = naver._get("/stockSecurity/exchanges/market-status", {"exchanges": "krx"})
    try:
        st = next(s for s in b["exchanges"][0]["statuses"] if s["marketType"] == "KOSPI")
        return {"date": st["today"]["date"], "trading": bool(st["today"]["isTradingDay"]),
                "holiday": st["today"].get("holidayDescription"),
                "next": st.get("next", {}).get("tradeBaseAt"),
                "latest": st.get("latest", {}).get("tradeBaseAt"),
                "source": "naver:market_status"}
    except Exception as e:  # noqa: BLE001
        log.warning("market-status 실패(%s) → 요일로 판정", e)
        return {"date": today, "trading": now_kst().weekday() < 5, "holiday": None,
                "next": None, "latest": None, "source": "weekday-fallback"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--github-output", action="store_true")
    args = ap.parse_args()
    s = status()
    print(json.dumps(s, ensure_ascii=False))
    if args.github_output and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"trading={'true' if s['trading'] else 'false'}\nnext={s['next'] or ''}\n")


if __name__ == "__main__":
    main()
