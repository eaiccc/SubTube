#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  log_progress.sh --agent NAME --task TEXT --task-id ID --status STATUS [options]

This writes a local event under SUBTUBE_PROGRESS_DIR (default: progress/).
When --issue is supplied, it also synchronizes GitHub labels and posts the
standard progress comment through update_github_issue.sh.

Options:
  --agent NAME, --task TEXT, --task-id ID, --status STATUS
  --issue NUMBER --repo OWNER/REPO
  --role TEXT --owner NAME --reviewer NAME --qa NAME --points N
  --ac TEXT --evidence TEXT --test-result TEXT
  --branch TEXT --worktree TEXT --commit TEXT
  --tried-and-failed TEXT --exception TEXT --handoff-to NAME
  --next TEXT --notes TEXT
  --local-only       Do not call GitHub
  --close            Close the issue; only valid for completed
  --dry-run          Print the event without writing or calling GitHub
  -h, --help
EOF
}

AGENT=""
TASK=""
TASK_ID=""
STATUS=""
ISSUE=""
REPO="${SUBTUBE_GITHUB_REPO:-}"
ROLE=""
OWNER=""
REVIEWER=""
QA=""
POINTS=""
AC=""
EVIDENCE=""
TEST_RESULT=""
BRANCH=""
WORKTREE=""
COMMIT=""
TRIED=""
EXCEPTION=""
HANDOFF_TO=""
NEXT=""
NOTES=""
LOCAL_ONLY=0
CLOSE=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) AGENT="$2"; shift 2 ;;
    --task) TASK="$2"; shift 2 ;;
    --task-id) TASK_ID="$2"; shift 2 ;;
    --status) STATUS="$2"; shift 2 ;;
    --issue) ISSUE="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --role) ROLE="$2"; shift 2 ;;
    --owner) OWNER="$2"; shift 2 ;;
    --reviewer) REVIEWER="$2"; shift 2 ;;
    --qa) QA="$2"; shift 2 ;;
    --points) POINTS="$2"; shift 2 ;;
    --ac) AC="$2"; shift 2 ;;
    --evidence) EVIDENCE="$2"; shift 2 ;;
    --test-result) TEST_RESULT="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --worktree) WORKTREE="$2"; shift 2 ;;
    --commit) COMMIT="$2"; shift 2 ;;
    --tried-and-failed) TRIED="$2"; shift 2 ;;
    --exception) EXCEPTION="$2"; shift 2 ;;
    --handoff-to) HANDOFF_TO="$2"; shift 2 ;;
    --next) NEXT="$2"; shift 2 ;;
    --notes) NOTES="$2"; shift 2 ;;
    --local-only) LOCAL_ONLY=1; shift ;;
    --close) CLOSE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$AGENT" && -n "$TASK" && -n "$TASK_ID" && -n "$STATUS" ]] || {
  printf '%s\n' '--agent, --task, --task-id and --status are required' >&2
  exit 2
}
if [[ -n "$POINTS" && ! "$POINTS" =~ ^(1|2|3|5)$ ]]; then
  printf '%s\n' 'SP must be one of 1, 2, 3, or 5; split tickets over 5 SP' >&2
  exit 2
fi

timestamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
event_file="${SUBTUBE_PROGRESS_DIR:-progress}/${TASK_ID}.md"

event_body="$(cat <<EOF
## ${timestamp} — ${STATUS}

- Task: ${TASK}
- Agent: ${AGENT}
- Role: ${ROLE:-NOT PROVIDED}
- Issue: ${ISSUE:-NOT LINKED}
- SP: ${POINTS:-NOT PROVIDED}
- Owner: ${OWNER:-NOT PROVIDED}
- Reviewer: ${REVIEWER:-NOT PROVIDED}
- QA: ${QA:-NOT PROVIDED}
- AC: ${AC:-NOT PROVIDED}
- Evidence: ${EVIDENCE:-NOT VERIFIED}
- Test result: ${TEST_RESULT:-NOT RUN}
- Branch: ${BRANCH:-NOT PROVIDED}
- Worktree: ${WORKTREE:-NOT PROVIDED}
- Last commit: ${COMMIT:-NOT AVAILABLE}
- Tried and failed: ${TRIED:-NONE REPORTED}
- Exception: ${EXCEPTION:-NONE}
- Handoff to: ${HANDOFF_TO:-NONE}
- Next: ${NEXT:-NOT PROVIDED}
- Notes: ${NOTES:-NONE}
EOF
)"

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf '%s\n' "$event_body"
  exit 0
fi

mkdir -p "$(dirname "$event_file")"
printf '%s\n\n' "$event_body" >> "$event_file"
printf 'Local progress: %s\n' "$event_file"

if [[ -n "$ISSUE" && "$LOCAL_ONLY" -eq 0 ]]; then
  [[ -n "$REPO" ]] || { printf '%s\n' 'Issue updates require --repo or SUBTUBE_GITHUB_REPO' >&2; exit 2; }
  script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  update_args=(
    --repo "$REPO" --issue "$ISSUE" --status "$STATUS"
    --agent "$AGENT" --task "$TASK" --task-id "$TASK_ID"
  )
  [[ -n "$ROLE" ]] && update_args+=(--role "$ROLE")
  [[ -n "$OWNER" ]] && update_args+=(--owner "$OWNER")
  [[ -n "$REVIEWER" ]] && update_args+=(--reviewer "$REVIEWER")
  [[ -n "$QA" ]] && update_args+=(--qa "$QA")
  [[ -n "$POINTS" ]] && update_args+=(--points "$POINTS")
  [[ -n "$AC" ]] && update_args+=(--ac "$AC")
  [[ -n "$EVIDENCE" ]] && update_args+=(--evidence "$EVIDENCE")
  [[ -n "$TEST_RESULT" ]] && update_args+=(--test-result "$TEST_RESULT")
  [[ -n "$BRANCH" ]] && update_args+=(--branch "$BRANCH")
  [[ -n "$WORKTREE" ]] && update_args+=(--worktree "$WORKTREE")
  [[ -n "$COMMIT" ]] && update_args+=(--commit "$COMMIT")
  [[ -n "$TRIED" ]] && update_args+=(--tried-and-failed "$TRIED")
  [[ -n "$EXCEPTION" ]] && update_args+=(--exception "$EXCEPTION")
  [[ -n "$HANDOFF_TO" ]] && update_args+=(--handoff-to "$HANDOFF_TO")
  [[ -n "$NEXT" ]] && update_args+=(--next "$NEXT")
  [[ -n "$NOTES" ]] && update_args+=(--notes "$NOTES")
  [[ "$CLOSE" -eq 1 ]] && update_args+=(--close)
  bash "$script_dir/update_github_issue.sh" "${update_args[@]}"
fi
