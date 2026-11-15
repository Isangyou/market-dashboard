#!/usr/bin/env bash
# 미국 옵션 루프: INTERVAL(기본 300초) 경계마다 fetch.options_live 실행 → 바뀌었으면 options-data 브랜치에 덮어쓰기 → pages 배포 호출.
# 사용: scripts/options_loop.sh <종료 HH:MM ET> [inclusive]
#   시각은 전부 ET(America/New_York). 서머타임 때문에 KST·UTC로 고정하지 않는다
#   inclusive 를 주면 종료 시각 회차까지 실행 (16:35 포함용)
#   ONCE=1  → 시각과 무관하게 1회만 실행하고 종료 (수동 점검용, 휴장 판정 안 함)
#   WAIT_UNTIL=HH:MM → 루프 시작 전 그 시각(ET)까지 대기 (cron 09:20 → 09:30 시작)
#   INTERVAL=초 → 회차 간격 (기본 300. 15분 지연 데이터라 더 촘촘할 이유가 없음)
#   GH_TOKEN 이 있으면 푸시 후 pages.yml 배포 호출
# main에는 커밋하지 않는다. 스냅샷은 회차마다 약 3.4MB가 통째로 바뀌어 main 이력에 쌓으면 저장소가 빠르게 커진다
#   → options-data 브랜치를 항상 '부모 없는 커밋 1개'로 강제 푸시(이력 없음). pages.yml이 배포 때 그 브랜치의 data/options를 합친다
# 휴장: HOLIDAY_AFTER(기본 10:15 ET) 이후 회차에서 fetch.options_live 가 3(오늘 ET 체결 종목 없음)을 내면 루프 종료
set -uo pipefail
INTERVAL="${INTERVAL:-300}"
FETCH_TIMEOUT=240   # 초. 14종목 × (요청 + 1초 간격) ≈ 30~60초. 넘으면 종료코드 124로 끊고 다음 회차
HOLIDAY_AFTER="${HOLIDAY_AFTER:-10:15}"
END="${1:?종료 시각 HH:MM (ET)}"
INCLUSIVE="${2:-}"
ONCE="${ONCE:-}"
BRANCH=options-data
et() { TZ=America/New_York date "+$1"; }
step() { echo "[$(et %H:%M:%S) ET] #${n:-0} $*"; }
running() {
  local now; now="$(et %H:%M)"
  if [[ -n "$INCLUSIVE" ]]; then [[ ! "$now" > "$END" ]]; else [[ "$now" < "$END" ]]; fi
}

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
GIT_DIR_ABS="$(git rev-parse --absolute-git-dir)"
OPT="$(mktemp -d)"; OUT="$OPT/data/options"; mkdir -p "$OUT"
trap 'rm -rf "$OPT"' EXIT

# 이전 스냅샷을 이어받는다 (실패 종목의 '이전 값 유지'와 'timestamp 같으면 다시 안 씀'이 잡이 바뀌어도 동작하게)
last_tree=""
if git fetch -q --depth 1 origin "$BRANCH" 2>/dev/null; then
  if git archive FETCH_HEAD data/options | tar -x -C "$OPT"; then last_tree="$(git rev-parse 'FETCH_HEAD^{tree}')"; fi
  echo "이전 스냅샷 이어받음: 파일 $(find "$OUT" -type f | wc -l)개"
else
  echo "$BRANCH 브랜치 없음 → 이번 실행에서 새로 만듦"
fi

snap_tree() {   # $OPT 아래(data/options)만 담은 tree 해시를 출력. main의 인덱스·작업트리는 건드리지 않는다
  local idx="$GIT_DIR_ABS/options-index"
  rm -f "$idx"
  ( cd "$OPT" \
      && GIT_INDEX_FILE="$idx" git --git-dir="$GIT_DIR_ABS" --work-tree="$OPT" add -A . \
      && GIT_INDEX_FILE="$idx" git --git-dir="$GIT_DIR_ABS" write-tree )
}

if [[ -n "${WAIT_UNTIL:-}" ]]; then
  echo "$(et %H:%M:%S) ET → ${WAIT_UNTIL}까지 대기"
  while [[ "$(et %H:%M)" < "$WAIT_UNTIL" ]]; do sleep 15; done
  echo "$(et %H:%M:%S) ET 대기 종료, 루프 시작"
fi

n=0; pushed=0
while [[ -n "$ONCE" && $n -eq 0 ]] || { [[ -z "$ONCE" ]] && running; }; do
  n=$((n + 1))
  echo "::group::[$(et '%H:%M:%S') ET] #$n options"
  t0=$(date +%s); step "fetch 시작 (timeout ${FETCH_TIMEOUT}s)"
  timeout "$FETCH_TIMEOUT" python -m fetch.options_live --out "$OUT" --exit-if-closed
  rc=$?
  step "fetch 끝 rc=$rc $(( $(date +%s) - t0 ))s"
  echo "::endgroup::"
  if [[ $rc -eq 0 || $rc -eq 3 ]]; then
    if tree="$(snap_tree)" && [[ -n "$tree" ]]; then
      if [[ "$tree" != "$last_tree" ]]; then
        c="$(git commit-tree "$tree" -m "options: $(et '%Y-%m-%d %H:%M') ET")"
        for i in 1 2 3; do
          t1=$(date +%s)
          if git push -q -f origin "$c:refs/heads/$BRANCH"; then
            last_tree="$tree"; pushed=$((pushed + 1))
            step "push 성공 $BRANCH ${c:0:7} (시도 $i, $(( $(date +%s) - t1 ))s, 누적 ${pushed}회)"
            # 봇 푸시는 push 이벤트를 만들지 않고, 이 브랜치는 pages.yml 트리거 대상도 아니다 → 배포를 직접 호출
            if [[ -n "${GH_TOKEN:-}" ]]; then gh workflow run pages.yml --ref main || echo "::warning::pages 배포 호출 실패"; fi
            break
          fi
          echo "::warning::push 실패 (시도 $i/3, $(( $(date +%s) - t1 ))s), 5초 후 재시도"; sleep 5
        done
      else
        step "변경 없음 → 푸시 생략"
      fi
    else
      echo "::warning::스냅샷 tree 생성 실패"
    fi
    if [[ $rc -eq 3 && -z "$ONCE" && ! "$(et %H:%M)" < "$HOLIDAY_AFTER" ]]; then
      step "${HOLIDAY_AFTER} ET 이후인데 오늘(ET) 체결 없음 → 휴장으로 보고 루프 종료"
      break
    fi
  elif [[ $rc -eq 124 ]]; then
    echo "::warning::fetch.options_live ${FETCH_TIMEOUT}초 초과로 중단"
  else
    echo "::warning::fetch.options_live 종료코드 $rc"
  fi
  [[ -n "$ONCE" ]] && break
  # 다음 경계까지 대기 (경계 +5초)
  now_s=$(date +%s)
  next=$(( now_s - now_s % INTERVAL + INTERVAL + 5 ))
  # inclusive: 종료 시각이 경계 사이에 있으면 종료 시각에 한 번 더
  if [[ -n "$INCLUSIVE" ]]; then
    end_s=$(( $(TZ=America/New_York date -d "$END" +%s) + 5 ))
    (( now_s < end_s && end_s < next )) && next=$end_s
  fi
  step "대기 $(( next - now_s ))s → $(TZ=America/New_York date -d "@$next" +%H:%M:%S) ET"
  sleep $(( next - now_s ))
done
echo "루프 종료 $(et %H:%M) ET · 실행 ${n}회 · 푸시 ${pushed}회"
