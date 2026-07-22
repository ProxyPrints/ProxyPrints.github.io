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
differ from where a `cd <path> &&`-chained command actually runs git, e.g.
`cd /path/to/feature-worktree && git merge origin/master` from a session
whose cwd is a master checkout. Judging that by session cwd alone misjudges
the branch and wrongly denies legitimate feature-branch work (see the
2026-07-22 incident in docs/troubleshooting.md). `effective_dir()` only
follows a `cd <path>` chain joined to the merge/push by `&&` (real shell
`&&` semantics: the cd must have actually succeeded for the rest of the
chain to run) -- a `cd` behind a `;`, single `&`, `|`, or `||` boundary is a
different statement and is deliberately not followed. It does NOT support
`git -C <path>` (considered and dropped 2026-07-22: an unanchored `-C` scan
over the whole command could get hijacked by an unrelated, earlier `-C` in
the same line and wrongly ALLOW a real merge-into-master -- see
docs/troubleshooting.md for the full trace). `effective_dir()` fails
closed: any resolution failure (no leading `cd` chain, or a `cd` in the
chain whose target path doesn't exist) falls back to session cwd exactly as
before the fix.

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
_CD_RE = re.compile(r"^\s*cd\s+(" + _PATH_TOKEN + r")\s*$")

# Longer operators first ("&&"/"||" before the single-char class) so a "&&"
# chain is recognized as one AND-join, not mistaken for two separate
# single-"&" (background) separators.
_SEG_SPLIT_RE = re.compile(r"\|\||&&|[;&|]")

# (\s|$), not \b -- a word boundary alone would wrongly match "git
# merge-base ..." (the "e"->"-" transition IS a \b), same false-positive
# the calling rules' own detection regexes already guard against.
MERGE_LEAD_RE = re.compile(r"^\s*git\s+merge(\s|$)")
PUSH_LEAD_RE = re.compile(r"^\s*git\s+push(\s|$)")


def _segments(command):
    """Split a shell command into (segment, delimiter_after) pairs.

    `delimiter_after` is the operator token immediately following that
    segment (one of "&&", "||", ";", "&", "|"), or None for the last
    segment. Only used internally by effective_dir() to walk a `cd`
    chain -- not a real shell parser (no quoting/subshell awareness beyond
    what _PATH_TOKEN already handles for a single `cd` argument).
    """
    parts = []
    pos = 0
    for m in _SEG_SPLIT_RE.finditer(command):
        parts.append((command[pos : m.start()], m.group(0)))
        pos = m.end()
    parts.append((command[pos:], None))
    return parts


def effective_dir(command, session_cwd, target_re):
    """Resolve the directory the merge/push `target_re` matched actually runs in.

    The hook's session cwd is a single value for the whole session, but a
    command can redirect where git runs via a leading `cd <path> &&` chain
    -- e.g. `cd /path/to/feature-worktree && git merge origin/master` run
    from a session whose registered cwd is a different (e.g. master)
    checkout. Judging branch state from the session cwd alone misattributes
    that command to the wrong checkout.

    Splits the command into simple-command segments on `;`, `&`, `|`, `&&`,
    and `||`, locates the (first, leftmost) segment matching `target_re`
    (the same "git merge"/"git push" the calling rule already detected),
    then walks backward from it collecting only the segments connected by
    an unbroken chain of `&&` -- a `cd` behind a `;`, single `&`, `|`, or
    `||` boundary is a different shell statement and must not apply here
    (real `&&` semantics: each step only runs if the previous one
    succeeded, so a `cd` genuinely chained by `&&` did actually take effect
    before the merge/push ran). Processes that chain left to right,
    applying each whole-segment `cd <path>` in turn.

    No `git -C <path>` support: considered and rejected (2026-07-22) after
    confirming an unanchored scan for it can get hijacked by an earlier,
    unrelated `git -C` elsewhere in the same compound command and wrongly
    ALLOW a real merge-into-master -- see docs/troubleshooting.md. A bare
    `git -C <path> merge/push ...` is therefore not resolved specially, and
    in practice isn't even detected as a merge/push attempt at all today,
    since the calling rules' own detection regexes require "git" and
    "merge"/"push" adjacent with no intervening flag -- an accepted,
    safely-under-triggering gap, not something this function needs to
    close.

    Falls back to session_cwd (today's pre-fix behavior) whenever there's
    no leading `cd` chain, or any `cd` in the chain targets a path that
    isn't a real directory on disk -- this fail-closed default means a
    resolution failure never produces a result more permissive than
    session-cwd-only judging.
    """
    segments = _segments(command)

    target_index = None
    for i, (seg, _delim) in enumerate(segments):
        if target_re.match(seg.strip()):
            target_index = i
            break
    if target_index is None:
        return session_cwd

    chain_start = target_index
    i = target_index - 1
    while i >= 0 and segments[i][1] == "&&":
        chain_start = i
        i -= 1

    current = session_cwd
    for i in range(chain_start, target_index):
        seg, _delim = segments[i]
        m = _CD_RE.match(seg)
        if not m:
            continue
        path = m.group(1).strip("'\"")
        if not os.path.isabs(path):
            path = os.path.join(current, path)
        if not os.path.isdir(path):
            return session_cwd  # fail-closed: a broken cd invalidates the chain
        current = path

    return current


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
        if (
            not re.search(r"--ff-only\b", command)
            and current_branch(effective_dir(command, cwd, MERGE_LEAD_RE)) == "master"
        ):
            log_stub("git-merge-into-master-unconditional", command, cwd)
            deny(
                "[guard_master] `git merge` into master is owner-only, always. "
                "Push your branch and open a PR instead."
            )

    if in_worker_worktree and re.search(r"(^|[;&|])\s*git\s+push(\s|$)", command):
        pushes_master = targets_master(command)
        if not pushes_master and current_branch(effective_dir(command, cwd, PUSH_LEAD_RE)) == "master":
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
