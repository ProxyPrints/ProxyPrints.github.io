# Upstream wiki drift

<!-- last-seen-sha: 43a8eedcd21c2b16a48ef74ba5e7f9f5aba27f49 -->

Weekly, automated **detection only** comparison of
[chilli-axe/mpc-autofill's wiki](https://github.com/chilli-axe/mpc-autofill/wiki)
against the last time this doc was updated. This never copies upstream
wiki text into this repo, and never will — wiki content has no clear
license, so the only correct integration is a link to the upstream page,
plus (where genuinely worth it) a human-written adaptation with
attribution, decided on review. This table exists to surface _that a page
changed_, not to summarize or reproduce _what_ changed.

Generated and updated in place by
[`.github/workflows/docs-upstream-wiki-drift.yml`](../../.github/workflows/docs-upstream-wiki-drift.yml)
— edits here are overwritten on the next run; if a row looks wrong, fix
the workflow/script, not this file directly. The table below was seeded
by hand from a real clone of `chilli-axe/mpc-autofill.wiki.git` (rather
than left as an empty stub), since the workflow itself can't run — and
therefore can't populate its own seed — until this file and the workflow
are both on `master` (GitHub only schedules `cron` triggers from the
default branch). The first automated run will refresh every row and the
`last-seen-sha` marker above from real diffs, the same way every run
after it does.

| Page                                                                                                                     | Last changed upstream | Commit    |
| ------------------------------------------------------------------------------------------------------------------------ | --------------------- | --------- |
| [Backend](https://github.com/chilli-axe/mpc-autofill/wiki/Backend)                                                       | 2025-05-29            | `27ea820` |
| [Desktop-Tool](https://github.com/chilli-axe/mpc-autofill/wiki/Desktop-Tool)                                             | 2026-01-24            | `098da5f` |
| [Frontend](https://github.com/chilli-axe/mpc-autofill/wiki/Frontend)                                                     | 2025-08-23            | `e6f2c03` |
| [GitHub Repo Configuration](https://github.com/chilli-axe/mpc-autofill/wiki/GitHub%20Repo%20Configuration)               | 2026-04-06            | `62f7a36` |
| [Google-Scripts](https://github.com/chilli-axe/mpc-autofill/wiki/Google-Scripts)                                         | 2026-06-16            | `43a8eed` |
| [Home](https://github.com/chilli-axe/mpc-autofill/wiki/Home)                                                             | 2026-01-24            | `098da5f` |
| [Image-CDN-Google-Drive-Credentials](https://github.com/chilli-axe/mpc-autofill/wiki/Image-CDN-Google-Drive-Credentials) | 2026-06-13            | `ad90993` |
| [Overview](https://github.com/chilli-axe/mpc-autofill/wiki/Overview)                                                     | 2025-03-30            | `fd24c69` |
| [XML-Schema-Specification](https://github.com/chilli-axe/mpc-autofill/wiki/XML-Schema-Specification)                     | 2026-01-24            | `af06fe2` |
| [\_Footer](https://github.com/chilli-axe/mpc-autofill/wiki/_Footer)                                                      | 2023-05-31            | `03a205a` |

Last checked: 2026-07-18
