"""KRED (kred.dev) 재공표 V-KOSPI 200 — CC BY-NC-ND 4.0. 엔드포인트 E33 (docs/endpoints.md).

별도 데이터 API가 없고, 시리즈 페이지 HTML의 Next.js RSC 페이로드에 전체 이력(initialData)이 들어 있음.
한 번 받으면 2010-01-04~ 전체가 오므로 증분 요청이 따로 없다. 요청은 하루 최대 2회(fetch/run.py가 제한).
"""
import json
import re

import pandas as pd
import requests

from .common import UA, log, safe

URL = "https://kred.dev/ko/series/KRVKOSPI"
SOURCE = "kred:KRVKOSPI"
_RE = re.compile(r'\\"initialData\\":(\[.*?\])')


def parse(html: str):
    m = _RE.search(html)
    if not m:
        return None
    arr = json.loads(m.group(1).replace('\\"', '"'))
    return pd.DataFrame([{"date": r["date"], "value": r["value"], "source": SOURCE, "asof": r["date"]}
                         for r in arr if r.get("value") is not None])


@safe
def vkospi_history():
    """전체 이력 1회 요청. 403/429·챌린지 페이지면 None."""
    try:
        r = requests.get(URL, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"}, timeout=30)
    except requests.RequestException as e:
        log.warning("kred 요청 실패: %s", e)
        return None
    if not r.ok:
        log.warning("kred → HTTP %s", r.status_code)
        return None
    df = parse(r.text)
    if df is None:
        log.warning("kred: initialData 없음 (페이지 구조 변경 또는 챌린지 페이지)")
    return df
