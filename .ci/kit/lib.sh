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

# spec.sh / build.sh run `claude -p ... --output-format json > "$CLAUDE_OUT"`. Only the final
# result text is ever surfaced (log + failure comment) - never tool output or file contents.
CLAUDE_OUT="$TMPD/claude-out.json"; rm -f "$CLAUDE_OUT"
CLAUDE_MSG_MAX=6000
claude_summary() { # "subtype, N turns" or nothing
  [[ -s "$CLAUDE_OUT" ]] || return 0
  jq -r 'select(type=="object") | "\(.subtype // "unknown"), \(.num_turns // "?") turns"' "$CLAUDE_OUT" 2>/dev/null | head -n1 || true
}
claude_last_message() { # Claude's final text, truncated; empty if there is none
  [[ -s "$CLAUDE_OUT" ]] || return 0
  # </details> is escaped so Claude's text can't close the comment's <details> block early.
  jq -r --argjson n "$CLAUDE_MSG_MAX" 'select(type=="object") | (.result // "" | gsub("</details>"; "&lt;/details&gt;")) as $r
      | if ($r | length) > $n then $r[0:$n] + "\n\n[... truncated]" else $r end' "$CLAUDE_OUT" 2>/dev/null || true
}
log_claude() { # echo Claude's outcome into the run log (json output no longer streams there)
  local s m; s="$(claude_summary)"; m="$(claude_last_message)"
  [[ -n "$s$m" ]] || return 0
  echo "== Claude finished ($s)"; [[ -n "$m" ]] && printf '%s\n' "$m"; return 0
}
fail() {
  local body="Automation stopped: $1" s m
  s="$(claude_summary)"; m="$(claude_last_message)"
  if [[ -n "$s$m" ]]; then
    body+=$'\n\n'"<details><summary>Claude's last message (${s:-no result})</summary>"$'\n\n'"${m:-_(Claude returned no final message.)_}"$'\n\n'"</details>"
  fi
  comment "$body"$'\n\n'"Run log: ${SERVER%/}/$REPO/actions"
  add_label needs-human; remove_label in-progress; exit 1
}

git config user.name  "${BOT_USER:-claude-bot}"
git config user.email "${BOT_USER:-claude-bot}@noreply.invalid"
# Never run repo-controlled git hooks on the runner (Claude can't write .git/, but be sure).
git config core.hooksPath /dev/null
