#!/usr/bin/env python3
"""Fault-injection tests for guard_master.py.

Pipes sample PreToolUse JSON payloads at the hook and asserts the exit
code, per repo scope decision 2026-07-19: `gh pr merge` and `git merge`
into master are blocked everywhere; `git push` to master is blocked
only from a worker worktree checkout (cwd under .claude/worktrees/).

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
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard_master.py")


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
            ("non-Bash tool -> ALLOW regardless of content", "Edit", "gh pr merge", worker_task, False),
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
