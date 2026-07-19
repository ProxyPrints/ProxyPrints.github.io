# CORR-0005: `gh pr list`/`gh repo view` without `-R` resolve to the upstream parent, not this fork

- **Date**: 2026-07-19
- **Trigger / wrong premise**: assumed `gh pr list` and `gh repo view`,
  run with no explicit `-R` flag inside this repo's checkout, would
  resolve to this fork (`ProxyPrints/ProxyPrints.github.io`) via the
  `origin` remote, the same way `gh api repos/{owner}/{repo}/...`'s
  placeholder substitution correctly does.
- **How caught**: while building `session_context.sh`, the unqualified
  `gh pr list` call returned a set of PRs that were unmistakably
  `chilli-axe/mpc-autofill`'s own open PRs (dependabot bumps, unrelated
  third-party feature PRs), not this fork's actual two open PRs.
  Confirmed directly: `gh repo view --json nameWithOwner` also returns
  `chilli-axe/mpc-autofill` from this checkout. `git remote get-url origin` correctly returns this fork's own URL and was used instead.
- **Blast radius**: this is the same root cause CLAUDE.md already
  documents for `gh pr create`/`gh pr merge` defaulting their base repo
  to the parent — but it's broader than previously recorded: it also
  affects read-only listing/view commands, not just create/merge. A
  SessionStart hook using the unqualified form would have silently
  shown every session the wrong repo's open PRs, every session, with
  no error to notice.
- **Systemic fix**: `session_context.sh` derives the repo slug from
  `git remote get-url origin` (parsed) and passes it explicitly via
  `-R` to every `gh` call, rather than relying on any default
  resolution.
- **Disposition**: `gate` (fixed at the point of use in the hook) —
  worth a `docs/troubleshooting.md` or CLAUDE.md update broadening the
  existing create/merge-specific note to cover list/view too (not yet
  done as of this entry).
