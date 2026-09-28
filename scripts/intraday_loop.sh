#!/usr/bin/env bash
# 장중 루프: 3분 경계마다 fetch.intraday 실행 → data/intraday 변경 시 커밋·푸시.
# 사용: scripts/intraday_loop.sh <종료 HH:MM KST> [inclusive]
#   inclusive 를 주면 종료 시각 회차까지 실행 (오후 잡 15:40 포함용).
#   종료 시각이 3분 경계가 아니어도(15:40) 그 시각에 마지막 1회를 돈다
#   ONCE=1  → 시각과 무관하게 1회만 실행하고 종료 (수동 점검용)
#   FORCE=1 → intraday.py --force (거래일·시간 조건 무시, 최근 거래일 기록)
#   WAIT_UNTIL=HH:MM → 루프 시작 전 그 시각(KST)까지 대기 (cron 08:35 → 08:50 시작)
#   GH_TOKEN 이 있으면 푸시 후 pages.yml 배포 호출
set -uo pipefail
INTERVAL=180   # 초. 3분 경계(:00,:03,…)마다 실행
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

if [[ -n "${WAIT_UNTIL:-}" ]]; then
  echo "$(kst %H:%M:%S) KST → ${WAIT_UNTIL}까지 대기"
  while [[ "$(kst %H:%M)" < "$WAIT_UNTIL" ]]; do sleep 15; done
  echo "$(kst %H:%M:%S) KST 대기 종료, 루프 시작"
fi

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
        if git pull -q --rebase --autostash && git push -q; then
          pushed=$((pushed + 1))
          # 봇 푸시는 push 이벤트를 만들지 않으므로 Pages 배포를 직접 호출
          if [[ -n "${GH_TOKEN:-}" ]]; then gh workflow run pages.yml --ref main || echo "::warning::pages 배포 호출 실패"; fi
          break
        fi
        echo "::warning::push 실패 (시도 $i/3), 5초 후 재시도"; sleep 5
      done
    else
      echo "변경 없음 → 커밋 생략"
    fi
  elif [[ $rc -ne 3 ]]; then
    echo "::warning::fetch.intraday 종료코드 $rc"
  fi
  [[ -n "$ONCE" ]] && break
  # 다음 3분 경계까지 대기 (경계 +5초: API 반영 여유)
  now_s=$(date +%s)
  next=$(( now_s - now_s % INTERVAL + INTERVAL + 5 ))
  # inclusive: 종료 시각이 경계 사이에 있으면(15:39 → 15:40 → 15:42) 종료 시각에 한 번 더
  if [[ -n "$INCLUSIVE" ]]; then
    end_s=$(( $(TZ=Asia/Seoul date -d "$END" +%s) + 5 ))
    (( now_s < end_s && end_s < next )) && next=$end_s
  fi
  sleep $(( next - now_s ))
done
echo "루프 종료 $(kst %H:%M) KST · 실행 ${n}회 · 푸시 ${pushed}회"
