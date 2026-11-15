#!/usr/bin/env bash
# options.yml guard 잡의 중복 실행 판정. 출력: dup=true|false (GITHUB_OUTPUT 형식으로 stdout 마지막 줄)
# scripts/intraday_guard.sh와 같은 방식. 그 파일은 장중 루프 전용이라 건드리지 않고 옵션용을 따로 둔다
# - 이 실행보다 먼저 시작해 아직 안 끝난 options 실행이 없으면 dup=false
# - 있으면 '마지막 활동'부터 IDLE_MAX초(기본 1200) 지났는지 본다
#     마지막 활동 = max(options-data 브랜치 마지막 커밋 시각, 그 실행의 시작 시각, 오늘 10:15 ET)
#     (09:30 시작 뒤에도 지연 시세가 개장분을 담기 전에는 푸시가 없을 수 있어 10:15 ET를 기준점에 넣음)
#   · 지났으면 죽은 것으로 보고 취소(응답 없으면 force-cancel) → dup=false (이 실행이 새로 시작)
#   · 아니면 살아 있음 → dup=true (이 실행은 건너뜀)
# - API 조회 실패 시 dup=false (루프가 안 도는 것보다 둘이 도는 편이 낫다: 둘 다 같은 브랜치를 덮어쓸 뿐)
# 필요 env: GH_TOKEN, REPO(owner/name), RUN_ID
set -uo pipefail
IDLE_MAX="${IDLE_MAX:-1200}"
log() { echo "[guard $(TZ=America/New_York date +%H:%M:%S) ET] $*" >&2; }
epoch() { date -d "$1" +%s; }

now="${NOW:-$(date +%s)}"   # NOW: 테스트용
open=$(gh api "repos/$REPO/actions/workflows/options.yml/runs?per_page=30" \
  --jq ".workflow_runs[] | select(.status != \"completed\" and .id < $RUN_ID) | \"\(.id) \(.run_started_at)\"") \
  || { log "실행 목록 조회 실패 → 진행"; echo "dup=false"; exit 0; }
if [[ -z "$open" ]]; then log "먼저 시작된 실행 없음 → 진행"; echo "dup=false"; exit 0; fi

# 브랜치가 아직 없으면(첫 실행 전) 커밋 시각 없이 판정
last=$(gh api "repos/$REPO/branches/options-data" --jq '.commit.commit.committer.date' 2>/dev/null) || last=""
if [[ -n "$last" ]]; then lc=$(epoch "$last"); log "마지막 스냅샷 푸시 $(TZ=America/New_York date -d "@$lc" '+%m-%d %H:%M:%S') ET"; else lc=0; log "options-data 브랜치 없음"; fi
open_at=$(TZ=America/New_York date -d "10:15" +%s)

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
