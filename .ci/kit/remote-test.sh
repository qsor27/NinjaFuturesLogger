#!/usr/bin/env bash
# Managed by repo-kit. Runs this repo's test entrypoint in a disposable Proxmox sandbox.
#   linux   -> fresh LXC clone of template 9900, runs .ci/test.sh
#   windows -> Windows VM rolled back to its clean snapshot, runs .ci/test.ps1
# The working tree (tracked + untracked, minus .gitignore'd files) is streamed over SSH;
# the sandbox never needs Forgejo credentials. Exit code = test result.
# Works from: devbox runner, interactive Claude on devbox, Git Bash on Windows, macOS.
#
#   ./.ci/kit/remote-test.sh          attached run on fast local storage (CI, iteration)
#   ./.ci/kit/remote-test.sh --long   linux only: copy onto the NAS and run DETACHED for days/weeks;
#                                     prints a CT id - then: ssh pve-gate logs|result|stop <id>
#
# The sandbox node may be powered off outside working hours. If PVE_GATE_WAKE_MAC is set (the
# node's NIC MAC, in the caller's environment - not in the repo), an unreachable gate is woken
# with Wake-on-LAN and the run waits for it (PVE_GATE_WAKE_WAIT seconds, default 420).
set -euo pipefail
usage() {
  cat <<'EOF_USAGE'
Usage: remote-test.sh [--long] [-h|--help]

Runs this repo's test entrypoint in a disposable Proxmox sandbox. Exit code = test result.

  (no argument)   attached run on fast local storage (CI, iteration)
  --long          linux only: copy onto the NAS and run DETACHED for days/weeks;
                  prints a CT id for the gate commands below
  -h, --help      print this help and exit 0

Environment:
  PVE_GATE             ssh alias of the gate (default: pve-gate)
  PVE_GATE_WAKE_MAC    MAC of the sandbox node's NIC; if set, an unreachable gate is woken
                       with Wake-on-LAN (default: unset = no wake)
  PVE_GATE_WAKE_BCAST  broadcast address for the Wake-on-LAN packet (default: 255.255.255.255)
  PVE_GATE_WAKE_WAIT   seconds to wait for the woken gate (default: 420)

Exit codes:
  <test result>   the exit code of the sandbox test run
  64              usage error
  76              node was about to power off; handled internally by retrying

Follow-up gate commands for --long runs:
  ssh pve-gate logs <ct-id>     show the run's log
  ssh pve-gate result <ct-id>   show the result of the run
  ssh pve-gate stop <ct-id>     stop the run
EOF_USAGE
}
case "${1:-}" in
  -h|--help) usage; exit 0 ;;
esac
# kit.env next to this script, not the one in the tree: build.sh runs a trusted copy of the kit.
# shellcheck source=/dev/null
. "$(dirname "$0")/kit.env"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
GATE="${PVE_GATE:-pve-gate}"   # ssh alias from ~/.ssh/config (see repo-kit devbox setup)
MODE=""
case "${1:-}" in
  "") ;;
  --long) [[ "$PLATFORM" == linux ]] || { echo "--long is only available for linux repos" >&2; exit 64; }; MODE=long ;;
  *) echo "usage: $0 [--long] [-h|--help]">&2; exit 64 ;;
esac

gate_up() { ssh -o BatchMode=yes -o ConnectTimeout=5 "$GATE" ping >/dev/null 2>&1; }

send_wol() {
  local py; py="$(command -v python3 || command -v python)" || { echo ">> python is needed to send Wake-on-LAN" >&2; return 1; }
  "$py" - "$PVE_GATE_WAKE_MAC" "${PVE_GATE_WAKE_BCAST:-255.255.255.255}" <<'PY'
import socket, sys
mac = bytes.fromhex(sys.argv[1].replace(":", "").replace("-", ""))
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
for port in (9, 7):
    s.sendto(b"\xff" * 6 + mac * 16, (sys.argv[2], port))
PY
}

wake_gate() { # wake the node and wait until the gate answers; re-sends the packet every minute
  if [[ -z "${PVE_GATE_WAKE_MAC:-}" ]]; then
    echo ">> $GATE is unreachable and PVE_GATE_WAKE_MAC is not set - cannot wake it" >&2; return 1
  fi
  echo ">> $GATE is asleep - waking it (Wake-on-LAN $PVE_GATE_WAKE_MAC)"
  local deadline=$(( SECONDS + ${PVE_GATE_WAKE_WAIT:-420} )) next=0
  until gate_up; do
    (( SECONDS < deadline )) || { echo ">> $GATE did not come up in time" >&2; return 1; }
    (( SECONDS >= next )) && { send_wol; next=$(( SECONDS + 60 )); }
    sleep 10
  done
  echo ">> $GATE is up"
}

gate_up || wake_gate

echo ">> Testing $REPO_NAME ($PLATFORM${MODE:+, long-form on NAS}) in PVE sandbox via $GATE"
for attempt in 1 2 3; do
  rc=0
  git ls-files -z -c -o --exclude-standard \
    | tar --null --ignore-failed-read -T - -czf - \
    | ssh -o BatchMode=yes -o ConnectTimeout=10 "$GATE" test "$PLATFORM" "$REPO_NAME" ${MODE:+"$MODE"} || rc=$?
  # 76 = the node started draining for its idle power-off. A ping counts as activity and
  # cancels the drain; if it already powered off, wake it again.
  [[ $rc -eq 76 && $attempt -lt 3 ]] || exit "$rc"
  echo ">> sandbox node was about to power off - retrying"
  sleep 20
  gate_up || wake_gate
done
