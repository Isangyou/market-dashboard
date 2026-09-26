"""공통 유틸: KST 시각, 로거, 실패 시 None 반환 데코레이터."""
import functools
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

log = logging.getLogger("fetch")


def now_kst() -> datetime:
    return datetime.now(KST).replace(microsecond=0)


def to_kst_iso(s: str) -> str:
    """오프셋 포함 ISO 문자열 → KST ISO8601. 오프셋이 없으면 KST로 간주."""
    if s.endswith("Z"):  # py3.9 fromisoformat은 'Z' 미지원
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST).replace(microsecond=0).isoformat()


def ymd_to_iso(s: str) -> str:
    """'20260923' → '2026-09-23'"""
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def safe(fn):
    """수집 함수용: 예외를 삼키고 로그 후 None 반환. 빈 DataFrame도 None으로 통일."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            df = fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — 수집 실패는 폴백으로 처리
            log.warning("%s%s 실패: %s: %s", fn.__name__, args, type(e).__name__, e)
            return None
        if df is None or len(df) == 0:
            log.warning("%s%s 결과 없음", fn.__name__, args)
            return None
        return df
    return wrapper
