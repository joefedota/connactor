# Connactor — Claude Code Guidelines

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

5. **Before pushing follow-up commits to an existing branch**, run `gh pr view <number> --json state,mergedAt` to confirm the PR is still open. If it has been merged, create a new branch off `main` and open a new PR instead.

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

## Brand colors

| Name     | Hex       | Usage |
|----------|-----------|-------|
| Yellow   | `#E4FF3C` | Primary accent — buttons, badges, favicon background |
| Charcoal | `#333333` | Primary text, icons, favicon letter |
| Cream    | `#FAF7F2` | App background |
| Purple   | `#C68DFE` | (reserved / unused in current UI) |

## Product copy rules

- **Never use the word "optimal"** in any user-facing text (UI labels, copy, tooltips, messages). Use **"best answer"** instead.
- **Sentence case everywhere** — all button labels, headings, tooltips, error messages, and any other user-facing text use sentence case. e.g. "New game" not "New Game", "How to play" not "How to Play", "Give up" not "Give Up".

## Query testing

**Always run new SQL and Cypher queries against a live database before committing.** Never rely solely on reading the query to verify correctness — syntax rules vary by DB version and errors only surface at runtime.

- **Cypher**: run via `docker exec connactor-neo4j-dev cypher-shell -u neo4j -p connactorpassword "<query>"` with realistic parameters (real IDs, non-empty exclusion lists, edge cases).
- **SQL**: run via `psql $DATABASE_URL -c "<query>"` or through the local Postgres container.

Test at minimum: the happy path returns expected results, exclusion/filter params work, and edge cases (empty lists, no results) don't error.

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
[CLAUDE]: <response>
```
If making a code change in response to a comment, make the change and include it in the reply. If disagreeing with a suggestion, explain why in the reply without making a change.
