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
