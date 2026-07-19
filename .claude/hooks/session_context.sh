#!/usr/bin/env bash
# SessionStart hook: inject a fresh repo snapshot into every session's
# opening context, so premise-checking doesn't depend on the model
# remembering (or re-deriving) current git/PR/CI state.
#
# Repo-slug note: this repo is a GitHub fork, and both `gh repo view`
# and `gh pr list` (with no -R) default to the UPSTREAM PARENT repo,
# not this fork -- the same gotcha CLAUDE.md documents for `gh pr
# create`/`gh pr merge`. Derive the slug from `git remote get-url
# origin` instead, which is not affected.
#
# CI-state note: `gh api .../commits/<sha>/status` is the legacy
# Status API and stays empty/"pending" forever for GitHub-Actions-only
# repos (Actions posts to the newer Checks API). Use check-runs
# instead, or this hook silently hides real CI failures.
set -uo pipefail

INPUT="$(cat)"
CWD="$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get("cwd") or ".")
except Exception:
    print(".")
' 2>/dev/null)"
CWD="${CWD:-.}"

cd "$CWD" 2>/dev/null || cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || true

branch="$(git branch --show-current 2>/dev/null)"
branch="${branch:-(detached HEAD)}"
sha="$(git rev-parse --short HEAD 2>/dev/null)"
full_sha="$(git rev-parse HEAD 2>/dev/null)"
status="$(git status --short 2>/dev/null)"
log="$(git log -5 --oneline 2>/dev/null)"

origin_url="$(git remote get-url origin 2>/dev/null)"
slug="$(printf '%s' "$origin_url" | sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##')"

prs="(gh unavailable, unauthenticated, or no origin remote)"
ci_state="unknown (gh unavailable, unauthenticated, or no origin remote)"

if [ -n "$slug" ]; then
  fetched_prs="$(gh pr list -R "$slug" --state open --limit 10 2>/dev/null)"
  [ -n "$fetched_prs" ] && prs="$fetched_prs"
  [ -z "$fetched_prs" ] && prs="(none open)"

  if [ -n "$full_sha" ]; then
    runs_json="$(gh api "repos/${slug}/commits/${full_sha}/check-runs" -q '[.check_runs[] | {name,conclusion,status}]' 2>/dev/null)"
    if [ -n "$runs_json" ]; then
      ci_state="$(printf '%s' "$runs_json" | python3 -c '
import json, sys
runs = json.load(sys.stdin)
if not runs:
    print("no checks reported for HEAD")
else:
    failed = [r["name"] for r in runs if r.get("conclusion") not in ("success", "skipped", "neutral", None)]
    pending = [r["name"] for r in runs if r.get("status") != "completed"]
    if failed:
        print("FAILING -- " + ", ".join(failed))
    elif pending:
        print("pending -- " + ", ".join(pending))
    else:
        print("all green (" + str(len(runs)) + " checks)")
' 2>/dev/null)"
    fi
  fi
fi

cat <<EOF
## Repo snapshot (auto-injected at session start -- treat as authoritative)
- Branch: ${branch} @ ${sha:-unknown}
- CI state at HEAD: ${ci_state}
- Working tree: $( [ -z "$status" ] && echo "clean" || echo "dirty" )
$( [ -n "$status" ] && printf '%s\n' "$status" | sed 's/^/  /' )
- Last 5 commits:
$(printf '%s\n' "$log" | sed 's/^/  /')
- Open PRs (${slug:-unknown repo}):
$(printf '%s\n' "$prs" | sed 's/^/  /')
EOF
exit 0
