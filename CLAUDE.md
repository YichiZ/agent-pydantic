# agent-pydantic

## Browser eval (`agents/browser/evals/`)

- An eval measures three things per trial: accuracy, time and cost. Record all three in
  `agents/browser/evals/runs/README.md`; if one is missing, say so there.
- A live trial costs real money (agent plus judge). Ask before running one.
- Publish only scores and met or violated per rubric item. Never commit the benchmark's task text, its rubric or the
  judge's full reports.

### Local-only folders

`agents/browser/evals/.benchmark/` (the benchmark clone, pinned commit in the browser README) and
`agents/browser/evals/.reports/` (the judge's full reports) are gitignored. Their one home is the main checkout, not
a worktree. `.env` is also only in the main checkout: pass it with `uv run --env-file <main checkout>/.env`.

When working in a worktree:

- Do not clone the benchmark again. Symlink the main checkout's `.benchmark` into the worktree and add the path to
  the worktree's git `info/exclude` (the `.gitignore` pattern does not match a symlink).
- Save every full report straight into the main checkout's `.reports/`.
- Before merging the PR or removing the worktree, check the worktree for a real `.benchmark/` or `.reports/` and
  move anything in them to the main checkout. A merge does not carry gitignored files, and removing the worktree
  deletes them.
