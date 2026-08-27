#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  update_github_issue.sh --repo OWNER/REPO --issue NUMBER --status STATUS [options]

STATUS: planned | todo | in_progress | review_ready | qa | blocked | drifted | completed

Options:
  --repo REPO                 GitHub repository; falls back to SUBTUBE_GITHUB_REPO
  --issue NUMBER              Issue number
  --status STATUS             Progress event/status
  --agent NAME                Current Codex role, e.g. codex-uhura-pro
  --role ROLE                 Human-readable role
  --task TEXT                 Work item title
  --task-id ID                Local task identifier
  --owner NAME                Writer/owner
  --reviewer NAME             Independent reviewer
  --qa NAME                   QA owner
  --points N                  Estimate or reserved SP
  --ac TEXT                   Acceptance criteria covered
  --evidence TEXT             Test/fixture/build/readback evidence
  --test-result TEXT          Test result, or explicit NOT RUN
  --branch TEXT               Branch name
  --worktree TEXT             Worktree path
  --commit TEXT               Last commit or NOT AVAILABLE
  --tried-and-failed TEXT     Failure trace
  --exception TEXT            Approved exception
  --handoff-to NAME           Next agent
  --next TEXT                 Next action
  --notes TEXT                Additional report notes
  --close                     Required with completed; closes the issue
  --dry-run                   Print the comment and label plan only
  -h, --help                  Show this help
EOF
}

REPO="${SUBTUBE_GITHUB_REPO:-}"
ISSUE=""
STATUS=""
AGENT=""
ROLE=""
TASK=""
TASK_ID=""
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
CLOSE=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --issue) ISSUE="$2"; shift 2 ;;
    --status) STATUS="$2"; shift 2 ;;
    --agent) AGENT="$2"; shift 2 ;;
    --role) ROLE="$2"; shift 2 ;;
    --task) TASK="$2"; shift 2 ;;
    --task-id) TASK_ID="$2"; shift 2 ;;
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
    --close) CLOSE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$REPO" ]] || { printf '%s\n' 'Missing --repo or SUBTUBE_GITHUB_REPO' >&2; exit 2; }
[[ "$ISSUE" =~ ^[0-9]+$ ]] || { printf '%s\n' 'Issue must be a numeric value' >&2; exit 2; }
if [[ -n "$POINTS" && ! "$POINTS" =~ ^(1|2|3|5)$ ]]; then
  printf '%s\n' 'SP must be one of 1, 2, 3, or 5; split tickets over 5 SP' >&2
  exit 2
fi

case "$STATUS" in
  planned|todo) STATUS_LABEL="status:todo" ;;
  in_progress) STATUS_LABEL="status:in_progress" ;;
  review_ready) STATUS_LABEL="status:review_ready" ;;
  qa) STATUS_LABEL="status:qa" ;;
  blocked) STATUS_LABEL="status:blocked" ;;
  drifted) STATUS_LABEL="status:drifted" ;;
  completed)
    STATUS_LABEL=""
    [[ "$CLOSE" -eq 1 ]] || { printf '%s\n' 'completed requires --close so GitHub state cannot drift' >&2; exit 2; }
    ;;
  *) printf 'Unsupported status: %s\n' "$STATUS" >&2; exit 2 ;;
esac

if [[ -n "$AGENT" && "$STATUS" != planned && "$STATUS" != todo && "$STATUS" != completed ]]; then
  APP_LABEL="app:codex"
else
  APP_LABEL=""
fi

body_file="$(mktemp "${TMPDIR:-/tmp}/subtube-progress.XXXXXX")"
trap 'rm -f "$body_file"' EXIT

{
  printf '## SubTube Progress — `%s`\n\n' "$STATUS"
  printf -- '- **Issue**: #%s\n' "$ISSUE"
  [[ -n "$TASK_ID" ]] && printf -- '- **Task ID**: `%s`\n' "$TASK_ID"
  [[ -n "$TASK" ]] && printf -- '- **Task**: %s\n' "$TASK"
  [[ -n "$AGENT" ]] && printf -- '- **Agent**: `%s`\n' "$AGENT"
  [[ -n "$ROLE" ]] && printf -- '- **Role**: %s\n' "$ROLE"
  [[ -n "$OWNER" ]] && printf -- '- **Owner**: `%s`\n' "$OWNER"
  [[ -n "$REVIEWER" ]] && printf -- '- **Reviewer**: `%s`\n' "$REVIEWER"
  [[ -n "$QA" ]] && printf -- '- **QA**: `%s`\n' "$QA"
  [[ -n "$POINTS" ]] && printf -- '- **SP**: %s\n' "$POINTS"
  [[ -n "$AC" ]] && printf -- '- **AC**: %s\n' "$AC"
  [[ -n "$BRANCH" ]] && printf -- '- **Branch**: `%s`\n' "$BRANCH"
  [[ -n "$WORKTREE" ]] && printf -- '- **Worktree**: `%s`\n' "$WORKTREE"
  [[ -n "$COMMIT" ]] && printf -- '- **Last commit**: `%s`\n' "$COMMIT"
  [[ -n "$EVIDENCE" ]] && printf -- '- **Evidence**: %s\n' "$EVIDENCE"
  [[ -n "$TEST_RESULT" ]] && printf -- '- **Test result**: %s\n' "$TEST_RESULT"
  [[ -n "$TRIED" ]] && printf -- '- **Tried and failed**: %s\n' "$TRIED"
  [[ -n "$EXCEPTION" ]] && printf -- '- **Exception**: %s\n' "$EXCEPTION"
  [[ -n "$HANDOFF_TO" ]] && printf -- '- **Handoff to**: `%s`\n' "$HANDOFF_TO"
  [[ -n "$NEXT" ]] && printf -- '- **Next**: %s\n' "$NEXT"
  [[ -n "$NOTES" ]] && printf -- '- **Report**: %s\n' "$NOTES"
  printf '\n> Issue comments are the source of truth. This event does not claim unverified runtime success.\n'
} > "$body_file"

if [[ "$DRY_RUN" -eq 1 ]]; then
  cat "$body_file"
  printf '\nLabel plan: remove status:* and app:*; add %s' "${STATUS_LABEL:-<none>}"
  [[ -n "$APP_LABEL" ]] && printf ' %s' "$APP_LABEL"
  printf '\n'
  [[ "$CLOSE" -eq 1 ]] && printf '%s\n' 'State plan: closed'
  exit 0
fi

command -v gh >/dev/null 2>&1 || { printf '%s\n' 'gh CLI is required' >&2; exit 127; }
command -v jq >/dev/null 2>&1 || { printf '%s\n' 'jq is required for safe label preservation' >&2; exit 127; }

existing_labels="$(gh api "repos/${REPO}/issues/${ISSUE}/labels?per_page=100" --paginate --jq '.[].name')"
label_json="$(printf '%s\n' "$existing_labels" | jq -Rsc \
  --arg status_label "$STATUS_LABEL" \
  --arg app_label "$APP_LABEL" \
  --arg status "$STATUS" \
  'split("\n")
   | map(select(length > 0) | select((startswith("status:") | not) and (startswith("app:") | not)))
   + (if $status_label != "" then [$status_label] else [] end)
   + (if $app_label != "" and $status != "completed" then [$app_label] else [] end)')"
gh api "repos/${REPO}/issues/${ISSUE}/labels" --method PUT --input - <<<"{\"labels\":${label_json}}" >/dev/null

if [[ "$CLOSE" -eq 1 ]]; then
  gh api "repos/${REPO}/issues/${ISSUE}" --method PATCH --raw-field state=closed >/dev/null
fi

gh api "repos/${REPO}/issues/${ISSUE}/comments" --method POST --raw-field "body=$(<"$body_file")" >/dev/null
printf 'Updated %s#%s: %s\n' "$REPO" "$ISSUE" "$STATUS"
