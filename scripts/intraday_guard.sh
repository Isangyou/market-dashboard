#!/usr/bin/env bash
# intraday.yml calendar 잡의 중복 실행 판정. 출력: dup=true|false (GITHUB_OUTPUT 형식으로 stdout 마지막 줄)
# - 이 실행보다 먼저 시작해 아직 안 끝난 intraday 실행이 없으면 dup=false
# - 있으면 '마지막 활동'부터 IDLE_MAX초(기본 600) 지났는지 본다
#     마지막 활동 = max(data/intraday 마지막 커밋 시각, 그 실행의 시작 시각, 오늘 08:50 KST)
#     (08:35 시작 실행은 08:50까지 커밋 없이 대기하므로 08:50을 기준점에 넣음)
#   · 지났으면 죽은 것으로 보고 취소(응답 없으면 force-cancel) → dup=false (이 실행이 새로 시작)
#   · 아니면 살아 있음 → dup=true (이 실행은 건너뜀)
# - API 조회 실패 시 dup=false (루프가 안 도는 것보다 둘이 도는 편이 낫다: 스냅샷은 t 키로 병합됨)
# 필요 env: GH_TOKEN, REPO(owner/name), RUN_ID
set -uo pipefail
IDLE_MAX="${IDLE_MAX:-600}"
log() { echo "[guard $(TZ=Asia/Seoul date +%H:%M:%S)] $*" >&2; }
epoch() { date -d "$1" +%s; }

now="${NOW:-$(date +%s)}"   # NOW: 테스트용
open=$(gh api "repos/$REPO/actions/workflows/intraday.yml/runs?per_page=30" \
  --jq ".workflow_runs[] | select(.status != \"completed\" and .id < $RUN_ID) | \"\(.id) \(.run_started_at)\"") \
  || { log "실행 목록 조회 실패 → 진행"; echo "dup=false"; exit 0; }
if [[ -z "$open" ]]; then log "먼저 시작된 실행 없음 → 진행"; echo "dup=false"; exit 0; fi

last=$(gh api "repos/$REPO/commits?sha=main&path=data/intraday&per_page=1" --jq '.[0].commit.committer.date') \
  || { log "마지막 커밋 조회 실패 → 진행"; echo "dup=false"; exit 0; }
lc=$(epoch "$last"); open_at=$(TZ=Asia/Seoul date -d "08:50" +%s)
log "마지막 장중 커밋 $(TZ=Asia/Seoul date -d "@$lc" '+%m-%d %H:%M:%S') KST"

dup=false
while read -r id started; do
  st=$(epoch "$started")
  ref=$(( lc > st ? lc : st )); ref=$(( ref > open_at ? ref : open_at ))
  idle=$(( now - ref ))
  if (( idle < IDLE_MAX )); then
    log "실행 $id 진행 중, 마지막 활동 ${idle}s 전 → 살아 있음, 이번 실행은 건너뜀"
    dup=true
    continue
  fi
  log "실행 $id 마지막 활동 ${idle}s 전 (≥${IDLE_MAX}s) → 죽은 것으로 판단, 취소"
  gh run cancel "$id" -R "$REPO" || true
  for _ in $(seq 1 12); do
    [[ "$(gh api "repos/$REPO/actions/runs/$id" --jq .status)" == completed ]] && break
    sleep 5
  done
  if [[ "$(gh api "repos/$REPO/actions/runs/$id" --jq .status)" != completed ]]; then
    log "실행 $id 일반 취소 60초 무응답 → force-cancel"
    gh api -X POST "repos/$REPO/actions/runs/$id/force-cancel" >/dev/null || log "force-cancel 실패"
  fi
done <<< "$open"
echo "dup=$dup"
