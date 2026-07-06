# southern_company_api — Claude Code Context

## Project Summary

Python package for the Southern Company utility API (Alabama Power, Georgia Power, Mississippi Power). A fork/local copy of `Lash-L/southern_company_api`. Provides async Python access to account data, usage, and billing. Used as a dependency or reference for the `southern-company-hacs` Home Assistant integration.

## Environment

- **Language**: Python (Poetry-managed)
- **Source**: `src/`
- **Tests**: `tests/`
- **GitHub**: https://github.com/tempeduck/southern_company_api (public)

## Rules

- Use Poetry for dependency management (`poetry install`, `poetry run pytest`)
- Pre-commit hooks enabled — run `pre-commit run --all-files` before pushing
- Credentials never hardcoded — passed at runtime by callers
- Black code style enforced

## Agent Collaboration Rules

- **Read History First**: At the start of every session, the agent MUST run `git status` and `git log -n 5` to understand recent changes, and read the `## Active Handoff` section in this file.
- **Commit with Context**: Every commit message must explain the _why_ behind a change, not just the _what_.
- **The Handoff Journal**: Before concluding a session or completing a major task, the active agent MUST update the `## Active Handoff` section at the bottom of this file.
- **Interactive Dry Runs**: The agent must always perform a dry run and list planned changes for user approval before modifying code, databases, or configuration files.
- **Explicit Task Tracking**: Maintain a shared checklist of tasks in `task.md` or `CLAUDE.md`. Mark tasks as `[x]` for complete, `[/]` for in-progress, and `[ ]` for pending.

## Active Handoff

- [2026-07-06 (Claude Code)]: PR #18 (upstream Nicor Gas support) cleanup complete. All Copilot/Lash-L review items were already fixed in a284080; the 14 reply comments that had been posted as raw file paths were deleted and reposted with real content, a summary comment pings Lash-L for re-review (can't use the re-request API without upstream write access). Awaiting Lash-L's re-review.
- [2026-06-06 (Claude Code)]: Added agent collaboration rules and initialized handoff log.
