#!/usr/bin/env bash
# Managed by repo-kit. Decides whether an issue event should start the spec or build step.
# Kept free of network calls so .ci/test.sh in the repo-kit repo can unit-test it with payloads.
#
# Forgejo reports label changes as action "label_updated" (not "labeled") and its payload has
# no top-level `label` object, so these predicates look only at the issue's CURRENT labels.
# Each step is made safe to re-trigger by labels the automation itself sets:
#   spec : idea|customer-request present, and none of spec-ready/ready/in-progress/needs-human
#   build: ready present, and none of in-progress/needs-human (build.sh then consumes `ready`)

# Usage: should_spec <event-json-file>   -> exit 0 if the spec step should run
should_spec() {
  jq -e '
    [.issue.labels[]?.name] as $l
    | (($l | index("idea")) or ($l | index("customer-request")))
      and ([$l[] | select(. == "spec-ready" or . == "ready" or . == "in-progress" or . == "needs-human")] | length == 0)
  ' "$1" >/dev/null
}

# Usage: should_build <event-json-file>  -> exit 0 if the build step should run
should_build() {
  jq -e '
    [.issue.labels[]?.name] as $l
    | ($l | index("ready"))
      and ([$l[] | select(. == "in-progress" or . == "needs-human")] | length == 0)
  ' "$1" >/dev/null
}
