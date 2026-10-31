#!/usr/bin/env bash
# Managed by repo-kit. Shared helpers for spec.sh / build.sh (runs on the devbox runner).
# Needs: FJ_BOT_TOKEN, ISSUE, plus Forgejo Actions' GITHUB_REPOSITORY / GITHUB_SERVER_URL.
# The workflows copy .ci/kit to $RUNNER_TEMP before running it, so branch switches in the
# checkout can't change the scripts mid-run and nothing Claude edits is ever executed here.
set -euo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
. "$KIT_DIR/kit.env"
# shellcheck source=triggers.sh
. "$KIT_DIR/triggers.sh"

: "${FJ_BOT_TOKEN:?FJ_BOT_TOKEN secret missing (org secret, claude-bot PAT)}"
: "${ISSUE:?ISSUE not set}"
SERVER="${GITHUB_SERVER_URL:-$FORGEJO_URL}"
API="${SERVER%/}/api/v1"
REPO="${GITHUB_REPOSITORY:?}"
# shellcheck disable=SC2034  # used by spec.sh / build.sh
BRANCH="issue-$ISSUE"
# shellcheck disable=SC2034
SPEC="docs/specs/issue-$ISSUE.md"
# shellcheck disable=SC2034
TMPD="${RUNNER_TEMP:-$(mktemp -d)}"
# Files handed to Claude live here. It is the ONLY extra directory Claude gets (--add-dir);
# the trusted kit copy in $TMPD/kit stays outside its reach.
# shellcheck disable=SC2034
INPUT_DIR="$TMPD/claude-input"; mkdir -p "$INPUT_DIR"

fj() { # fj METHOD /path [curl args...]
  local m=$1 p=$2; shift 2
  curl -fsS -X "$m" -H "Authorization: token $FJ_BOT_TOKEN" -H 'Content-Type: application/json' "$API$p" "$@"
}
comment() { jq -n --arg b "$1" '{body:$b}' | fj POST "/repos/$REPO/issues/$ISSUE/comments" -d @- >/dev/null; }
label_id() { fj GET "/repos/$REPO/labels?limit=100" | jq -r --arg n "$1" '.[] | select(.name==$n) | .id' | head -n1; }
live_labels() { fj GET "/repos/$REPO/issues/$ISSUE" | jq -c '{issue:{labels:.labels}}'; }
add_label() {
  local id; id="$(label_id "$1")"
  [[ -n "$id" ]] && jq -n --argjson i "$id" '{labels:[$i]}' | fj POST "/repos/$REPO/issues/$ISSUE/labels" -d @- >/dev/null || true
}
remove_label() {
  local id; id="$(label_id "$1")"
  [[ -n "$id" ]] && fj DELETE "/repos/$REPO/issues/$ISSUE/labels/$id" >/dev/null 2>&1 || true
}
# Removes a label and reports whether this call was the one that removed it. Used to consume
# the one-shot `ready` approval so two concurrent runs can't both build.
take_label() {
  local id; id="$(label_id "$1")"
  [[ -n "$id" ]] || return 1
  fj DELETE "/repos/$REPO/issues/$ISSUE/labels/$id" >/dev/null 2>&1
}
git_auth() { git -c "http.extraHeader=Authorization: token $FJ_BOT_TOKEN" "$@"; }
fail() {
  comment "Automation stopped: $1"$'\n\n'"Run log: ${SERVER%/}/$REPO/actions"
  add_label needs-human; remove_label in-progress; exit 1
}

git config user.name  "${BOT_USER:-claude-bot}"
git config user.email "${BOT_USER:-claude-bot}@noreply.invalid"
# Never run repo-controlled git hooks on the runner (Claude can't write .git/, but be sure).
git config core.hooksPath /dev/null
