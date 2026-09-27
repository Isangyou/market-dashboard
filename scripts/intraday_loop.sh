#!/usr/bin/env bash
# 장중 루프: 5분 경계마다 fetch.intraday 실행 → data/intraday 변경 시 커밋·푸시.
# 사용: scripts/intraday_loop.sh <종료 HH:MM KST> [inclusive]
#   inclusive 를 주면 종료 시각 당일 회차까지 실행 (오후 잡 15:40 포함용)
#   ONCE=1  → 시각과 무관하게 1회만 실행하고 종료 (수동 점검용)
#   FORCE=1 → intraday.py --force (거래일·시간 조건 무시, 최근 거래일 기록)
set -uo pipefail
END="${1:?종료 시각 HH:MM}"
INCLUSIVE="${2:-}"
ONCE="${ONCE:-}"
ARGS=()
[[ -n "${FORCE:-}" ]] && ARGS+=(--force)
kst() { TZ=Asia/Seoul date "+$1"; }
running() {
  local now; now="$(kst %H:%M)"
  if [[ -n "$INCLUSIVE" ]]; then [[ ! "$now" > "$END" ]]; else [[ "$now" < "$END" ]]; fi
}

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

n=0; pushed=0
while [[ -n "$ONCE" && $n -eq 0 ]] || { [[ -z "$ONCE" ]] && running; }; do
  n=$((n + 1))
  echo "::group::[$(kst '%H:%M:%S')] #$n intraday"
  python -m fetch.intraday ${ARGS[@]+"${ARGS[@]}"}
  rc=$?
  echo "::endgroup::"
  if [[ $rc -eq 0 ]]; then
    git add data/intraday
    if ! git diff --cached --quiet; then
      git commit -q -m "intraday: $(kst '%Y-%m-%d %H:%M') KST"
      for i in 1 2 3; do
        if git pull -q --rebase --autostash && git push -q; then pushed=$((pushed + 1)); break; fi
        echo "::warning::push 실패 (시도 $i/3), 5초 후 재시도"; sleep 5
      done
    else
      echo "변경 없음 → 커밋 생략"
    fi
  elif [[ $rc -ne 3 ]]; then
    echo "::warning::fetch.intraday 종료코드 $rc"
  fi
  [[ -n "$ONCE" ]] && break
  # 다음 5분 경계까지 대기 (경계 +5초: API 반영 여유)
  sleep $(( 300 - $(date +%s) % 300 + 5 ))
done
echo "루프 종료 $(kst %H:%M) KST · 실행 ${n}회 · 푸시 ${pushed}회"
