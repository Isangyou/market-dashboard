"""adrinfo.kr ADR(20일 등락비율) — 엔드포인트 E37 (docs/endpoints.md).

별도 데이터 API가 없고, http://adrinfo.kr/chart HTML 안 인라인 스크립트에
`const kospi_adr=[[epoch_ms, 값], ...];` / `kosdaq_adr` 배열로 2019-10-07~ 전체 이력이 들어 있음.
epoch_ms = 해당 거래일 00:00 KST. 미래 날짜는 `null`, 배열 끝에 쉼표가 붙어 JSON이 아님 → 쌍 단위 정규식으로 파싱.
요청은 하루 1회(fetch/run.py adrinfo_due가 제한). 403 등 실패면 None → 그날은 네이버 계산값 폴백.
"""
import re
from datetime import datetime

import pandas as pd
import requests

from .common import KST, UA, log, safe

URL = "http://adrinfo.kr/chart"
SOURCE = "adrinfo"
_PAIR = re.compile(r"\[\s*(\d{12,13})\s*,\s*(-?\d+(?:\.\d+)?|null)\s*\]")


def _array(html: str, name: str):
    m = re.search(name + r"\s*=\s*\[(.*?)\]\s*;", html, re.S)
    return None if m is None else m.group(1)


def parse(html: str):
    """HTML → DataFrame[market(KOSPI/KOSDAQ), date, value, source, asof]. 배열을 못 찾으면 None."""
    rows = []
    for m in ("KOSPI", "KOSDAQ"):
        body = _array(html, f"{m.lower()}_adr")
        if body is None:
            return None
        for ms, v in _PAIR.findall(body):
            if v == "null":
                continue
            d = datetime.fromtimestamp(int(ms) / 1000, KST).strftime("%Y-%m-%d")
            # 일별 종가 기준 지표 → asof = 그날 15:30 KST (kospi.json과 같은 규칙)
            rows.append({"market": m, "date": d, "value": float(v), "source": SOURCE, "asof": f"{d}T15:30:00+09:00"})
    return pd.DataFrame(rows) if rows else None


@safe
def adr_history():
    """전체 이력 1회 요청. 403/429·구조 변경이면 None."""
    try:
        r = requests.get(URL, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"}, timeout=30)
    except requests.RequestException as e:
        log.warning("adrinfo 요청 실패: %s", e)
        return None
    if not r.ok:
        log.warning("adrinfo → HTTP %s (오늘은 건너뜀, 네이버 계산값 폴백)", r.status_code)
        return None
    df = parse(r.text)
    if df is None:
        log.warning("adrinfo: kospi_adr/kosdaq_adr 배열 없음 (페이지 구조 변경)")
    return df
