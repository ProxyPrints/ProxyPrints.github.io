#!/usr/bin/env python3
"""Fault-injection tests for guard_master.py.

Pipes sample PreToolUse JSON payloads at the hook and asserts the exit
code, per repo scope decision 2026-07-19: `gh pr merge` and `git merge`
into master are blocked everywhere; `git push` to master is blocked
only from a worker worktree checkout (cwd under .claude/worktrees/).

2026-07-22: added coverage for `effective_dir()`, the fix for a
production incident where a `cd <feature-worktree> && git merge
origin/master` run from a session whose registered cwd was a master
checkout got wrongly denied (see docs/troubleshooting.md). Two layers:
  - end-to-end `run_hook()` cases exercising the `cd <path> &&` form
    through the actual `git merge`/`git push` rules (the form those
    rules' own outer detection regexes can actually match).
  - direct unit cases against `effective_dir()` itself (via
    `load_hook_module()`), covering the `git -C <path>` form too --
    note that form is *not* separately exercised end-to-end here,
    because the outer `git\\s+merge`/`git\\s+push` detection regexes
    (unchanged by this fix) require "git" and "merge"/"push" adjacent
    with no intervening flag, so a bare `git -C <path> merge ...`
    command isn't recognized as a merge/push attempt at all today --
    a pre-existing scope boundary of those regexes, not something this
    fix introduces or resolves.

On the "does this survive bypassPermissions / --dangerously-skip-permissions"
requirement: Claude Code's own hook contract guarantees a PreToolUse
hook's exit-2 decision applies in every permission mode, including
bypass (confirmed against code.claude.com/docs/en/hooks -- the hook
process itself never receives or branches on permission_mode). This
suite verifies the hook's decision logic, which is the only part that
could actually be wrong; it does not re-run a live Claude Code session
to reconfirm Claude Code's own enforcement of that contract.

Run: python3 .claude/hooks/test_guard_master.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard_master.py")


def load_hook_module():
    spec = importlib.util.spec_from_file_location("guard_master", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_repo(root, name, branch, under_worktree=False):
    path = os.path.join(root, ".claude", "worktrees", name) if under_worktree else os.path.join(root, name)
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)
    open(os.path.join(path, "f.txt"), "w").write("x")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    subprocess.run(["git", "branch", "-m", branch], cwd=path, check=True)
    return path


def run_hook(tool_name, command, cwd):
    payload = json.dumps({"tool_name": tool_name, "tool_input": {"command": command}, "cwd": cwd})
    result = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, timeout=10)
    return result.returncode, result.stderr.strip()


def main():
    root = tempfile.mkdtemp(prefix="guard_master_test_")
    try:
        main_master = make_repo(root, "main_master", "master", under_worktree=False)
        worker_task = make_repo(root, "worker-task", "task-123", under_worktree=True)
        worker_master = make_repo(root, "worker-master", "master", under_worktree=True)
        # A second worker worktree, on a feature branch, standing in for
        # "the feature worktree a `cd <path> &&`-prefixed command redirects
        # into" in the effective_dir() cases below.
        worker_feature = make_repo(root, "worker-feature", "feature-x", under_worktree=True)

        cases = [
            # (label, tool_name, command, cwd, expect_deny)
            ("gh pr merge bare, main checkout -> DENY (unconditional)", "Bash", "gh pr merge", main_master, True),
            (
                "gh pr merge w/ flags, worker -> DENY (unconditional)",
                "Bash",
                "gh pr merge 123 --squash",
                worker_task,
                True,
            ),
            ("git merge into master, main checkout -> DENY", "Bash", "git merge feature-x", main_master, True),
            ("git merge on a non-master branch, worker -> ALLOW", "Bash", "git merge feature-x", worker_task, False),
            ("git push origin master, worker -> DENY", "Bash", "git push origin master", worker_task, True),
            (
                "git push origin master, main checkout -> ALLOW (interactive convention)",
                "Bash",
                "git push origin master",
                main_master,
                False,
            ),
            ("git push own feature branch, worker -> ALLOW", "Bash", "git push origin task-123", worker_task, False),
            ("bare git push while on master, worker -> DENY (fallback)", "Bash", "git push", worker_master, True),
            (
                "push a branch merely named master-experimental, worker -> ALLOW (no false positive)",
                "Bash",
                "git push origin master-experimental",
                worker_task,
                False,
            ),
            ("benign command, worker -> ALLOW", "Bash", "git status", worker_task, False),
            (
                "git merge-base (subcommand prefix collision), main checkout -> ALLOW",
                "Bash",
                "git merge-base master origin/worktree-x",
                main_master,
                False,
            ),
            (
                "git merge-base, worker on master -> ALLOW (not a real merge)",
                "Bash",
                "git merge-base HEAD origin/master",
                worker_master,
                False,
            ),
            (
                "git merge --ff-only origin/master, main checkout -> ALLOW (sync, not a merge decision)",
                "Bash",
                "git merge --ff-only origin/master",
                main_master,
                False,
            ),
            (
                "git merge --ff-only origin/master, worker on master -> ALLOW",
                "Bash",
                "git merge --ff-only origin/master",
                worker_master,
                False,
            ),
            (
                "git merge (no --ff-only) into master, worker on master -> DENY (still unconditional)",
                "Bash",
                "git merge origin/feature-x",
                worker_master,
                True,
            ),
            ("non-Bash tool -> ALLOW regardless of content", "Edit", "gh pr merge", worker_task, False),
            # effective_dir(): a `cd <path> &&`-prefixed command redirects
            # git to a different checkout than the session's registered cwd
            # -- the 2026-07-22 incident (docs/troubleshooting.md).
            (
                "cd <feature worktree> && git merge origin/master, session cwd on master -> ALLOW "
                "(effective_dir resolves to the feature branch, not master)",
                "Bash",
                f"cd {worker_feature} && git merge origin/master",
                main_master,
                False,
            ),
            (
                "plain git merge, session cwd on master -> DENY (unchanged baseline)",
                "Bash",
                "git merge origin/master",
                main_master,
                True,
            ),
            (
                "cd /nonexistent && git merge x, session cwd on master -> DENY (fail-closed: "
                "bad path falls back to session cwd, same as today)",
                "Bash",
                "cd /nonexistent/path/does/not/exist && git merge origin/master",
                main_master,
                True,
            ),
            (
                "gh pr merge, any cwd -> DENY (unconditional, unaffected by effective_dir)",
                "Bash",
                "gh pr merge 5",
                main_master,
                True,
            ),
            (
                "git merge --ff-only origin/master, session cwd on master -> ALLOW (exemption still applies)",
                "Bash",
                "git merge --ff-only origin/master",
                main_master,
                False,
            ),
            (
                "cd <feature worktree> && git push (bare), session cwd is a worker on master -> ALLOW "
                "(effective_dir resolves to the feature branch, so the master-fallback push rule doesn't trigger)",
                "Bash",
                f"cd {worker_feature} && git push",
                worker_master,
                False,
            ),
            (
                "cd /nonexistent && git push (bare), session cwd is a worker on master -> DENY (fail-closed)",
                "Bash",
                "cd /nonexistent/path/does/not/exist && git push",
                worker_master,
                True,
            ),
            (
                "cd <feature worktree> && git push, session cwd is the MAIN checkout on master -> ALLOW "
                "(in_worker_worktree gate is still session-cwd-based, not effective_dir -- main checkout "
                "pushes stay exempt per the interactive convention regardless of any cd)",
                "Bash",
                f"cd {worker_feature} && git push origin master",
                main_master,
                False,
            ),
        ]

        failures = 0
        for label, tool_name, command, cwd, expect_deny in cases:
            code, stderr = run_hook(tool_name, command, cwd)
            denied = code == 2
            ok = denied == expect_deny
            status = "PASS" if ok else "FAIL"
            print(f"[{status}] {label} (exit={code})")
            if not ok:
                failures += 1
                print(f"         expected deny={expect_deny}, got deny={denied}, stderr={stderr!r}")

        # Direct unit coverage for effective_dir(), including the `git -C
        # <path>` form the end-to-end cases above can't reach through the
        # outer merge/push detection regexes (see module docstring).
        gm = load_hook_module()
        effective_dir_cases = [
            # (label, command, session_cwd, expected_resolved_dir)
            (
                "cd <path> && ... resolves to <path> when it's a real dir",
                f"cd {worker_feature} && git merge origin/master",
                main_master,
                worker_feature,
            ),
            (
                "quoted cd path resolves the same as bare",
                f'cd "{worker_feature}" && git merge origin/master',
                main_master,
                worker_feature,
            ),
            (
                "no cd/-C redirect falls back to session_cwd",
                "git merge origin/master",
                main_master,
                main_master,
            ),
            (
                "cd to a nonexistent path fails closed to session_cwd",
                "cd /nonexistent/path/does/not/exist && git merge origin/master",
                main_master,
                main_master,
            ),
            (
                "git -C <path> resolves to <path> when it's a real dir",
                f"git -C {worker_feature} merge origin/master",
                main_master,
                worker_feature,
            ),
            (
                "git -C <nonexistent path> fails closed to session_cwd",
                "git -C /nonexistent/path/does/not/exist merge origin/master",
                main_master,
                main_master,
            ),
            (
                "git -C takes precedence over a preceding cd",
                f"cd {main_master} && git -C {worker_feature} merge origin/master",
                worker_master,
                worker_feature,
            ),
        ]
        for label, command, session_cwd, expected in effective_dir_cases:
            got = gm.effective_dir(command, session_cwd)
            ok = os.path.realpath(got) == os.path.realpath(expected)
            status = "PASS" if ok else "FAIL"
            print(f"[{status}] effective_dir: {label}")
            if not ok:
                failures += 1
                print(f"         expected {expected!r}, got {got!r}")

        # KNOWN GAP -- documents current (undesired) behavior, does not
        # count toward pass/fail. See effective_dir()'s docstring and the
        # PR body: an unrelated, earlier `git -C <path>` in a compound
        # command can hijack branch resolution for a later, unrelated
        # `git merge`/`git push` in the same command. Flagged for an
        # explicit owner decision, not fixed here (would need to scope the
        # regex to the specific triggering invocation -- broader than this
        # fix's remit).
        unrelated_repo = make_repo(root, "unrelated-repo", "some-other-branch")
        gap_command = f"git -C {unrelated_repo} status && git merge origin/master"
        gap_resolved = gm.effective_dir(gap_command, main_master)
        print(
            f"[KNOWN GAP] effective_dir() resolves an unrelated earlier `git -C` over the "
            f"actual merge's own context: resolved to {gap_resolved!r} (unrelated-repo), not "
            f"{main_master!r} (session cwd, main_master's real branch) -- not counted pass/fail"
        )

        # Malformed input: fail open, never block on a parse error.
        result = subprocess.run([sys.executable, HOOK], input="not json", capture_output=True, text=True, timeout=10)
        ok = result.returncode == 0
        print(f"[{'PASS' if ok else 'FAIL'}] malformed JSON input -> ALLOW (fail open) (exit={result.returncode})")
        if not ok:
            failures += 1

        print()
        if failures:
            print(f"{failures} test(s) FAILED")
            sys.exit(1)
        print("All tests passed.")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
