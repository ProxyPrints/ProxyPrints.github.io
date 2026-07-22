#!/usr/bin/env python3
"""PreToolUse gate: no automated session merges or pushes master directly.

Scope (owner decision 2026-07-19):
  - `gh pr merge` and `git merge` into master: blocked everywhere,
    unconditionally. No legitimate solo-workflow case exists for a
    session to merge on its own — that's an owner-only action.
    Exception: `git merge --ff-only` is a fast-forward sync, not a
    merge decision (git refuses it unless the result is a pure
    fast-forward), so it's exempt regardless of cwd.
  - `git push` to master: blocked only when running from a worker
    worktree checkout (cwd under .claude/worktrees/). The main
    checkout's interactive pushes to master stay untouched, per this
    repo's standing convention (see CLAUDE.md, Push policy).

Both `current_branch(...) == "master"` checks above resolve branch state via
`effective_dir()`, not the raw session cwd -- a session's registered cwd can
differ from where a `cd <path> &&`-prefixed (or `git -C <path>`-scoped)
command actually runs git, e.g. `cd /path/to/feature-worktree && git merge
origin/master` from a session whose cwd is a master checkout. Judging that
by session cwd alone misjudges the branch and wrongly denies legitimate
feature-branch work (see the 2026-07-22 incident in
docs/troubleshooting.md). `effective_dir()` fails closed: any resolution
failure (no such redirect, or the target path doesn't exist) falls back to
session cwd exactly as before the fix.

This is a best-effort text/state heuristic, not a security boundary —
GitHub branch protection is the backstop that survives a bug here.

Every deny also appends a one-line stub to corrections/.pending-stubs.jsonl
(repo root) -- this is the one reliable "a gate fired" signal Claude Code's
hook system currently offers (confirmed 2026-07-19: there's no hook event
for "a human clicked deny on an interactive permission prompt", only for a
hook's own decision or an auto-mode-classifier denial). A stub here means
"guard_master.py blocked something", not "a human overruled the agent" --
see corrections/README.md. Logging failure never blocks the deny itself.
"""
import json
import os
import re
import subprocess
import sys
import time

MASTER_TOKENS = {"master", "origin/master", "HEAD:master", "refs/heads/master"}


def log_stub(rule, command, cwd):
    try:
        # Derive from cwd (the repo/worktree that actually triggered the deny),
        # not this script's own on-disk location -- a worktree session's stub
        # belongs with its own branch, and this also keeps test fixtures (which
        # have no corrections/ dir) from writing into the real ledger.
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return
        repo_root = result.stdout.strip()
        stub_path = os.path.join(repo_root, "corrections", ".pending-stubs.jsonl")
        if not os.path.isdir(os.path.dirname(stub_path)):
            return
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "rule": rule,
            "command": command,
            "cwd": cwd,
        }
        with open(stub_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # never let stub logging interfere with the actual deny


def current_branch(cwd):
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


_PATH_TOKEN = r'"[^"]*"|\'[^\']*\'|\S+'


def effective_dir(command, session_cwd):
    """Resolve the directory a git command actually runs in.

    The hook's session cwd is a single value for the whole session, but a
    command can redirect where git runs via a leading `cd <path> &&` or a
    `git -C <path>` flag -- e.g. `cd /path/to/feature-worktree && git merge
    origin/master` run from a session whose registered cwd is a different
    (e.g. master) checkout. Judging branch state from the session cwd alone
    misattributes that command to the wrong checkout.

    `git -C <path>` takes precedence when present, since it overrides the
    directory the git subcommand itself operates in regardless of any
    preceding `cd`. Falls back to session_cwd whenever no such redirect is
    found, or the redirect's path isn't a real directory on disk -- this
    fail-closed default means a resolution failure never produces a result
    more permissive than today's cwd-only behavior.

    KNOWN GAP (2026-07-22, flagged not fixed -- see PR body): the `git -C`
    match is an unanchored re.search over the whole command string, so in a
    compound command with an earlier, unrelated `git -C <other-path> ...`
    before the `git merge`/`git push` that actually triggered this rule
    (e.g. `git -C /some/unrelated/repo status && git merge origin/master`),
    that earlier path wins the resolution even though it has nothing to do
    with the merge/push being judged. Unlike the `cd` branch below (anchored
    to the start of the command via re.match, so it can only ever capture a
    genuinely leading `cd`), this can make effective_dir() return the wrong
    directory in the more dangerous direction: a real merge-into-master from
    this session's actual branch could read as non-master and get wrongly
    ALLOWED, not just wrongly denied. Left as-is because tightening the
    regex to scope it to the specific triggering git invocation is a bigger
    change than this fix's "minimal change, no broader process modification"
    remit covers -- needs an explicit owner decision, not a unilateral fix.
    """
    m = re.search(r"git\s+-C\s+(" + _PATH_TOKEN + r")", command)
    if m:
        path = m.group(1).strip("'\"")
        if os.path.isdir(path):
            return path
        return session_cwd

    m = re.match(r"\s*cd\s+(" + _PATH_TOKEN + r")\s*&&", command)
    if m:
        path = m.group(1).strip("'\"")
        if not os.path.isabs(path):
            path = os.path.join(session_cwd, path)
        if os.path.isdir(path):
            return path

    return session_cwd


def targets_master(command):
    for tok in re.split(r"\s+", command.strip()):
        tok = tok.strip("'\"")
        if tok in MASTER_TOKENS or tok.endswith("/master") or tok.endswith(":master"):
            return True
    return False


def deny(reason):
    print(reason, file=sys.stderr)
    sys.exit(2)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # malformed input: fail open, never block on a parse error

    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    command = (payload.get("tool_input") or {}).get("command") or ""
    cwd = payload.get("cwd") or os.getcwd()
    in_worker_worktree = "/.claude/worktrees/" in cwd.replace(os.sep, "/")

    if re.search(r"(^|[;&|])\s*gh\s+pr\s+merge(\s|$)", command):
        log_stub("gh-pr-merge-unconditional", command, cwd)
        deny(
            "[guard_master] `gh pr merge` is owner-only, always. Open/leave the PR "
            "for the owner to merge themselves."
        )

    if re.search(r"(^|[;&|])\s*git\s+merge(\s|$)", command):
        # --ff-only is synchronization, not an authorization-bearing merge
        # decision: git itself refuses to run it unless the result is a pure
        # fast-forward, so there's no new, unreviewed content it can land.
        if not re.search(r"--ff-only\b", command) and current_branch(effective_dir(command, cwd)) == "master":
            log_stub("git-merge-into-master-unconditional", command, cwd)
            deny(
                "[guard_master] `git merge` into master is owner-only, always. "
                "Push your branch and open a PR instead."
            )

    if in_worker_worktree and re.search(r"(^|[;&|])\s*git\s+push(\s|$)", command):
        pushes_master = targets_master(command)
        if not pushes_master and current_branch(effective_dir(command, cwd)) == "master":
            # bare `git push` / `git push <remote>` with no explicit ref relies
            # on the current branch's upstream -- being on master is enough.
            if re.search(r"(^|[;&|])\s*git\s+push(\s+\S+)?\s*($|[;&|])", command):
                pushes_master = True
        if pushes_master:
            log_stub("git-push-master-from-worktree", command, cwd)
            deny(
                "[guard_master] this is a worker worktree (.claude/worktrees/) -- "
                "push your own branch and let the owner land it. Never push "
                "master directly from a worker."
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
