# Connactor — Agent Guidelines

## Workflow: one issue = one branch = one PR

For every GitHub issue you implement:

1. **Create a feature branch** off `main` before writing any code:
   ```
   git checkout -b feature/issue-{number}-{short-description}
   ```
   Example: `feature/issue-5-tmdb-person-enricher`

2. **Implement the issue** on that branch.

3. **Open a PR** against `main` when done — do not merge it yourself:
   ```
   gh pr create --title "..." --body "..."
   ```
   - Title should reference the issue: `feat: TMDB person enricher (#5)`
   - Body should summarize what changed and link `Closes #5`
   - Keep PRs focused — one issue per PR

4. **Never commit directly to `main`.**

## Branch naming
`feature/issue-{number}-{kebab-case-description}`

## PR body template
```
## What
Brief description of what was built.

## Why
Link to the issue: Closes #{number}

## Test plan
How to verify this works.
```

## Repo
https://github.com/joefedota/connactor

## Project board
https://github.com/joefedota/connactor/projects

## Code style rules

- **No imports in function scope** unless absolutely necessary (e.g. breaking a circular import). All imports go at the top of the file.
- **No print statements** in library/pipeline code — use `logging.getLogger(__name__)` and log at the appropriate level. Configure logging in entry points (`main()` functions) only.

## Documentation updates

After every PR, review and update all project documentation as needed:
- `SPEC.md` — product spec, API table, decision log
- `SYSTEM_DESIGN.md` — architecture, data model, endpoint mapping, infrastructure
- `ROADMAP.md` — tick completed items, add new issues discovered during implementation
- `README.md` — setup instructions, project structure

Update these files in the same PR as the code change, before opening the PR.

## Responding to PR comments

When responding to GitHub PR review comments, reply in the format:
```
[AGENT NAME]: <response>
```
Substitute your own model/agent name (e.g. `[CLAUDE]`, `[GEMINI]`). If making a code change in response to a comment, make the change and include it in the reply. If disagreeing with a suggestion, explain why in the reply without making a change.
