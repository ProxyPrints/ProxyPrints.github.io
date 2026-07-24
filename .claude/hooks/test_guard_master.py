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
  - end-to-end `run_hook()` cases exercising the `cd <path> &&` chain
    through the actual `git merge`/`git push` rules.
  - direct unit cases against `effective_dir()` itself (via
    `load_hook_module()`), covering multi-step `&&` chains, quoted
    paths, and chain-boundary behavior (`;`/`&`/`|`/`||` correctly
    NOT carrying a `cd` across).

Same-day follow-up (still 2026-07-22): the first cut of this fix also
added `git -C <path>` support to `effective_dir()`, using an unanchored
scan over the whole command. That was flagged as a false-ALLOW risk --
an earlier, unrelated `git -C <other-path>` in a compound command could
hijack resolution for a later, unrelated `git merge`/`git push` in the
same line -- and confirmed by direct trace. Per the orchestrator's
tightening request, `git -C` support was dropped entirely rather than
anchored: `effective_dir()` now only follows a `cd <path>` chain
connected to the merge/push by `&&` (never `git -C`, and never a `cd`
behind a `;`/single-`&`/`|`/`||` boundary). This keeps the fix's
under-triggering gap (a bare `git -C <path> merge/push ...` command
isn't recognized as a merge/push attempt at all today, since the
calling rules' own detection regexes require "git" and "merge"/"push"
adjacent with no intervening flag) -- accepted as safe, since
under-triggering only ever produces an unnecessary DENY, never a wrong
ALLOW.

2026-07-24: added coverage for the `Edit`/`Write`/`NotebookEdit`
worktree-path-trap guard (see the module docstring's "Scope added
2026-07-24" section) -- both end-to-end `run_hook_payload()` cases
against the actual tool_input shapes those three tools send, and direct
unit cases against `worktree_main_checkout_root()` / `resolve_write_target()`
/ `targets_main_checkout()`.

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


def run_hook_payload(payload):
    result = subprocess.run(
        [sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True, timeout=10
    )
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
            # Orchestrator-requested regression cases (2026-07-22 tightening,
            # closing the git -C false-ALLOW gap):
            (
                "git -C <unrelated> status && git merge x, session cwd on master -> DENY "
                "(git -C support dropped entirely -- an unrelated earlier `-C` must NOT hijack "
                "resolution for the real merge that follows)",
                "Bash",
                f"git -C {worker_feature} status && git merge origin/master",
                main_master,
                True,
            ),
            (
                "cd <feature worktree> && git fetch && git merge origin/master, session cwd on master -> "
                "ALLOW (a cd earlier in the SAME && chain, even with an intervening non-cd step, still "
                "carries forward to the merge)",
                "Bash",
                f"cd {worker_feature} && git fetch && git merge origin/master",
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

        # End-to-end coverage for the 2026-07-24 Edit/Write/NotebookEdit
        # worktree-path-trap guard, against the actual tool_input shapes
        # those three tools send (file_path for Edit/Write, notebook_path
        # for NotebookEdit).
        worker_task_subdir = os.path.join(worker_task, "sub", "dir")
        os.makedirs(worker_task_subdir, exist_ok=True)
        other_worktree_target = os.path.join(worker_feature, "f.txt")
        main_checkout_target = os.path.join(main_master, "f.txt")
        own_worktree_target = os.path.join(worker_task, "f.txt")
        # Deliberately a sibling of `root`, not under it -- stands in for
        # /tmp, the orchestration repo, or the memory dir: genuinely
        # outside the repo entirely, not just outside the main checkout.
        outside_repo_target = os.path.join(tempfile.gettempdir(), "guard_master_test_outside_repo_notes.txt")

        write_guard_cases = [
            # (label, payload, expect_deny)
            (
                "Edit targets main checkout, worker cwd -> DENY",
                {"tool_name": "Edit", "cwd": worker_task, "tool_input": {"file_path": main_checkout_target}},
                True,
            ),
            (
                "Write targets main checkout, worker cwd -> DENY",
                {
                    "tool_name": "Write",
                    "cwd": worker_task,
                    "tool_input": {"file_path": main_checkout_target, "content": "x"},
                },
                True,
            ),
            (
                "NotebookEdit targets main checkout via notebook_path, worker cwd -> DENY",
                {
                    "tool_name": "NotebookEdit",
                    "cwd": worker_task,
                    "tool_input": {"notebook_path": main_checkout_target.replace(".txt", ".ipynb")},
                },
                True,
            ),
            (
                "Edit targets main checkout, cwd nested deep inside the worker worktree -> DENY "
                "(main-root resolution isn't sensitive to how deep cwd is under .claude/worktrees/)",
                {"tool_name": "Edit", "cwd": worker_task_subdir, "tool_input": {"file_path": main_checkout_target}},
                True,
            ),
            (
                "Edit targets the session's OWN worktree copy -> ALLOW",
                {"tool_name": "Edit", "cwd": worker_task, "tool_input": {"file_path": own_worktree_target}},
                False,
            ),
            (
                "Edit targets a DIFFERENT worker worktree's copy -> ALLOW "
                "(only main-checkout-outside-any-worktree is gated)",
                {"tool_name": "Edit", "cwd": worker_task, "tool_input": {"file_path": other_worktree_target}},
                False,
            ),
            (
                "Edit targets a path entirely outside the repo (e.g. /tmp) -> ALLOW",
                {"tool_name": "Edit", "cwd": worker_task, "tool_input": {"file_path": outside_repo_target}},
                False,
            ),
            (
                "Edit targets the main checkout, but session cwd IS the main checkout (not a worktree) -> ALLOW "
                "(rule only applies to worker worktree sessions)",
                {"tool_name": "Edit", "cwd": main_master, "tool_input": {"file_path": main_checkout_target}},
                False,
            ),
            (
                "Edit with a relative file_path from a worker cwd -> ALLOW (resolves under cwd, inside the worktree)",
                {"tool_name": "Edit", "cwd": worker_task, "tool_input": {"file_path": "f.txt"}},
                False,
            ),
            (
                "Read targets the main checkout, worker cwd -> ALLOW (read-only calls are never gated)",
                {"tool_name": "Read", "cwd": worker_task, "tool_input": {"file_path": main_checkout_target}},
                False,
            ),
            (
                # NOTE: relative to `root` (this fixture's `main_root`, since
                # `worker_task` = root/.claude/worktrees/worker-task), not
                # `main_master` (which is just an unrelated sibling repo used
                # by the other cases above) -- see worktree_main_checkout_root().
                "Edit targets main-root WORKERS.md, worker cwd -> ALLOW "
                "(documented multi-worker coordination exception)",
                {
                    "tool_name": "Edit",
                    "cwd": worker_task,
                    "tool_input": {"file_path": os.path.join(root, "WORKERS.md")},
                },
                False,
            ),
            (
                "Edit targets a file under main-root journal/, worker cwd -> ALLOW " "(documented journal/ exception)",
                {
                    "tool_name": "Edit",
                    "cwd": worker_task,
                    "tool_input": {"file_path": os.path.join(root, "journal", "2026-07-24-notes.md")},
                },
                False,
            ),
            (
                "Edit targets a file merely NAMED like the journal/ exception "
                "(journal-archive/notes.md) -> DENY (no false-negative prefix match)",
                {
                    "tool_name": "Edit",
                    "cwd": worker_task,
                    "tool_input": {"file_path": os.path.join(root, "journal-archive", "notes.md")},
                },
                True,
            ),
        ]

        for label, payload, expect_deny in write_guard_cases:
            code, stderr = run_hook_payload(payload)
            denied = code == 2
            ok = denied == expect_deny
            status = "PASS" if ok else "FAIL"
            print(f"[{status}] {label} (exit={code})")
            if not ok:
                failures += 1
                print(f"         expected deny={expect_deny}, got deny={denied}, stderr={stderr!r}")

        # Direct unit coverage for effective_dir(), covering the cd-chain
        # walk and its boundaries (see module docstring / effective_dir()'s
        # own docstring for what changed 2026-07-22 and why).
        gm = load_hook_module()
        unrelated_repo = make_repo(root, "unrelated-repo", "some-other-branch")
        effective_dir_cases = [
            # (label, command, session_cwd, target_re, expected_resolved_dir)
            (
                "cd <path> && git merge ... resolves to <path> when it's a real dir",
                f"cd {worker_feature} && git merge origin/master",
                main_master,
                gm.MERGE_LEAD_RE,
                worker_feature,
            ),
            (
                "quoted cd path resolves the same as bare",
                f'cd "{worker_feature}" && git merge origin/master',
                main_master,
                gm.MERGE_LEAD_RE,
                worker_feature,
            ),
            (
                "no cd redirect falls back to session_cwd",
                "git merge origin/master",
                main_master,
                gm.MERGE_LEAD_RE,
                main_master,
            ),
            (
                "cd to a nonexistent path fails closed to session_cwd",
                "cd /nonexistent/path/does/not/exist && git merge origin/master",
                main_master,
                gm.MERGE_LEAD_RE,
                main_master,
            ),
            (
                "cd && <non-cd step> && git merge -- the cd still carries through an "
                "intervening non-cd step in the same && chain",
                f"cd {worker_feature} && git fetch && git merge origin/master",
                main_master,
                gm.MERGE_LEAD_RE,
                worker_feature,
            ),
            (
                "cd <path>; git merge -- a cd behind a ';' is a different statement, " "must NOT carry forward",
                f"cd {worker_feature}; git merge origin/master",
                main_master,
                gm.MERGE_LEAD_RE,
                main_master,
            ),
            (
                "cd <path> & git merge -- a cd behind a single '&' (backgrounding) is a "
                "different statement, must NOT carry forward",
                f"cd {worker_feature} & git merge origin/master",
                main_master,
                gm.MERGE_LEAD_RE,
                main_master,
            ),
            (
                "cd <path> || git merge -- a cd behind '||' is a different statement, " "must NOT carry forward",
                f"cd {worker_feature} || git merge origin/master",
                main_master,
                gm.MERGE_LEAD_RE,
                main_master,
            ),
            (
                "git -C <path> is no longer resolved at all -- falls back to session_cwd",
                f"git -C {worker_feature} merge origin/master",
                main_master,
                gm.MERGE_LEAD_RE,
                main_master,
            ),
            (
                "the false-ALLOW gap this tightening closes: an unrelated earlier `git -C` "
                "must NOT hijack resolution for a real, later merge in the same line",
                f"git -C {unrelated_repo} status && git merge origin/master",
                main_master,
                gm.MERGE_LEAD_RE,
                main_master,
            ),
            (
                "same cd-chain resolution for the push rule's target_re",
                f"cd {worker_feature} && git push",
                worker_master,
                gm.PUSH_LEAD_RE,
                worker_feature,
            ),
        ]
        for label, command, session_cwd, target_re, expected in effective_dir_cases:
            got = gm.effective_dir(command, session_cwd, target_re)
            ok = os.path.realpath(got) == os.path.realpath(expected)
            status = "PASS" if ok else "FAIL"
            print(f"[{status}] effective_dir: {label}")
            if not ok:
                failures += 1
                print(f"         expected {expected!r}, got {got!r}")

        # Direct unit coverage for the worktree-write-guard helpers
        # (worktree_main_checkout_root / resolve_write_target /
        # targets_main_checkout), independent of the end-to-end cases above.
        norm = lambda p: p.replace(os.sep, "/")  # noqa: E731
        worktree_helper_cases = [
            (
                "worktree_main_checkout_root: worker cwd -> the dir before .claude/worktrees/",
                gm.worktree_main_checkout_root(worker_task),
                norm(root),
            ),
            (
                "worktree_main_checkout_root: main checkout cwd (no .claude/worktrees/ in path) -> None",
                gm.worktree_main_checkout_root(main_master),
                None,
            ),
            (
                "resolve_write_target: absolute file_path passes through normalized",
                gm.resolve_write_target({"file_path": main_checkout_target}, worker_task),
                norm(os.path.normpath(main_checkout_target)),
            ),
            (
                "resolve_write_target: notebook_path key is also recognized",
                gm.resolve_write_target({"notebook_path": "/a/b.ipynb"}, worker_task),
                "/a/b.ipynb",
            ),
            (
                "resolve_write_target: relative file_path resolves against cwd",
                gm.resolve_write_target({"file_path": "f.txt"}, worker_task),
                norm(os.path.normpath(os.path.join(worker_task, "f.txt"))),
            ),
            (
                "resolve_write_target: neither key present -> None",
                gm.resolve_write_target({"content": "x"}, worker_task),
                None,
            ),
        ]
        for label, got, expected in worktree_helper_cases:
            ok = got == expected
            status = "PASS" if ok else "FAIL"
            print(f"[{status}] {label}")
            if not ok:
                failures += 1
                print(f"         expected {expected!r}, got {got!r}")

        targets_main_checkout_cases = [
            (
                "targets_main_checkout: path under main root, not under .claude/worktrees/ -> True",
                gm.targets_main_checkout(norm(main_checkout_target), norm(root)),
                True,
            ),
            (
                "targets_main_checkout: path under main root's .claude/worktrees/ subtree -> False",
                gm.targets_main_checkout(norm(own_worktree_target), norm(root)),
                False,
            ),
            (
                "targets_main_checkout: path outside main root entirely -> False",
                gm.targets_main_checkout(norm(outside_repo_target), norm(root)),
                False,
            ),
        ]
        for label, got, expected in targets_main_checkout_cases:
            ok = got == expected
            status = "PASS" if ok else "FAIL"
            print(f"[{status}] {label}")
            if not ok:
                failures += 1
                print(f"         expected {expected!r}, got {got!r}")

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
