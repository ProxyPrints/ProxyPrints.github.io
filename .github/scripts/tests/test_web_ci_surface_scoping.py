"""
web-ci surface-scoping regression guard (issue #773).

The defect: web-ci.yml gated its jobs on a `git diff --name-only` of the
push's own commit range (the `changes` job, PR #466). A deploy cut at a
merge whose own diff touched only one surface therefore shipped its
PARENT's other-surface change with no CI at the deployed SHA while every
check reported green — observed at 29b29601 (backend-only merge of #772)
whose parent fec94ee6 (#770) had just rewritten
frontend/src/features/questionFeed/QuestionFeed.tsx; the frontend jobs
ran SKIPPED at 29b29601.

The fix: the full matrix runs unconditionally on every push to master.
This guard fails if surface-scoping is reintroduced into web-ci.yml:

  - a `changes`-style detection job,
  - a job gated on `needs.changes.outputs.*`,
  - a `paths:` filter on the push trigger (a filtered push would again
    ship an ancestor's surface change with zero checks at the merge SHA).

It also replays the two real SHAs from the issue as a worked example:
the OLD detection logic computed frontend=false at 29b29601 (hence the
skipped jobs), and the NEW workflow runs frontend unconditionally, so a
deploy at 29b29601 now carries frontend CI covering fec94ee6's change.

Run: python3 .github/scripts/tests/test_web_ci_surface_scoping.py
"""

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "web-ci.yml"

# The two real SHAs from issue #773's write-up.
BACKEND_ONLY_MERGE = "29b29601b994852721462230ee0e784861a115ae"  # #772, parent of the frontend work
FRONTEND_PARENT = "fec94ee66c43a3796a033284d62c761a25d42286"  # #770, rewrote a frontend file


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def old_detection_logic(before: str, after: str) -> dict:
    """Replicates the PR #466 `changes` job: diff before..after, set
    backend/frontend flags from path prefixes."""
    out = subprocess.run(
        ["git", "diff", "--name-only", before, after],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    changed = out.stdout.splitlines()
    return {
        "backend": any(p.startswith("MPCAutofill/") for p in changed),
        "frontend": any(p.startswith("frontend/") for p in changed),
        "changed": changed,
    }


class TestNoSurfaceScoping(unittest.TestCase):
    def test_no_changes_detection_job(self):
        text = workflow_text()
        self.assertNotIn("Detect changed surfaces", text, "the surface-detection job must not exist")
        self.assertNotIn("name: Detect changed surfaces", text)

    def test_no_job_gated_on_changes_outputs(self):
        text = workflow_text()
        self.assertNotIn("needs.changes.outputs", text, "no job may gate on changes outputs")
        self.assertNotIn("needs: [changes]", text)
        self.assertNotIn("needs: [changes,", text)

    def test_push_trigger_has_no_paths_filter(self):
        text = workflow_text()
        self.assertNotIn('branches: ["master"]\n    paths:', text, "push trigger must not carry a paths filter")

    def test_full_matrix_jobs_all_present(self):
        text = workflow_text()
        for job in ("test-backend:", "test-frontend:", "merge-frontend-test-reports:", "build-frontend:"):
            self.assertIn(f"\n  {job}", text, f"{job} must exist")


@unittest.skipUnless(
    subprocess.run(
        ["git", "cat-file", "-e", f"{BACKEND_ONLY_MERGE}^{{commit}}"],
        capture_output=True,
        cwd=REPO_ROOT,
    ).returncode
    == 0,
    "29b29601 not present in this checkout (shallow clone) - worked example skipped",
)
class TestWorkedExampleRealSHAs(unittest.TestCase):
    """Replays issue #773's exact SHAs: proves the old logic skipped
    frontend at 29b29601 while the new workflow cannot."""

    def test_parent_actually_changed_a_frontend_file(self):
        # fec94ee6 is 29b29601's parent and must have touched frontend/,
        # else the issue's premise doesn't hold in this history.
        parents = subprocess.run(
            ["git", "rev-list", "--parents", "-n", "1", BACKEND_ONLY_MERGE],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
        ).stdout.split()
        self.assertIn(FRONTEND_PARENT, parents, "fec94ee6 must be 29b29601's parent")
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{BACKEND_ONLY_MERGE}^", BACKEND_ONLY_MERGE],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
        ).stdout
        # 29b29601's own diff is backend-only (that is the defect premise).
        self.assertTrue(any(p.startswith("MPCAutofill/") for p in out.splitlines()))
        self.assertFalse(any(p.startswith("frontend/") for p in out.splitlines()))

    def test_old_logic_skipped_frontend_at_29b29601(self):
        flags = old_detection_logic(FRONTEND_PARENT, BACKEND_ONLY_MERGE)
        # The OLD `changes` job computed frontend=false for this push -
        # this is why the frontend jobs reported SKIPPED at 29b29601.
        self.assertFalse(flags["frontend"], "old logic would have skipped frontend at 29b29601")
        self.assertTrue(flags["backend"])
        self.assertTrue(
            any("question_feed" in p for p in flags["changed"]),
            "29b29601's own diff should be the backend question-feed change",
        )

    def test_new_workflow_runs_frontend_unconditionally(self):
        # Under the new workflow there is no gate to trip: test-frontend
        # has no `if:` and no `needs:`-on-changes, so a deploy cut at
        # 29b29601 now carries frontend CI at the deployed SHA, covering
        # fec94ee6's frontend change.
        text = workflow_text()
        self.assertNotIn("needs.changes.outputs", text)
        self.assertNotIn("if: needs.changes", text)
        # Structural proof the frontend job cannot be skipped by a diff.
        self.assertIn("test-frontend:", text)
        self.assertNotIn("paths:", text.split("on:")[1].split("workflow_dispatch")[0])


if __name__ == "__main__":
    sys.exit(unittest.main(verbosity=2))
