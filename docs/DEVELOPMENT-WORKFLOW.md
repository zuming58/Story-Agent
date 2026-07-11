# Development Workflow

This project uses GitHub as the coordination layer between machines and model sessions.

## Roles

- GPT-5.6 session: higher-level planning, architecture review, PR review, and final merge judgment.
- GPT-5.5 session: implementation, tests, local verification, documentation, and incremental commits.
- GitHub branch and draft PR: shared memory between both sessions.

## Branching

- Stable branch: `main`
- Current feature branch: `agent/local-data-foundation`
- Do not commit local data, generated databases, backups, secrets, or machine-specific files.
- Use focused commits that describe the product capability added.

## Handoff Rules

Before switching machines or model sessions:

1. Run the relevant tests.
2. Update `HANDOFF.md`.
3. Commit all intended source and documentation changes.
4. Push the feature branch.
5. Update the draft PR description or comment with any important caveats.

When resuming:

1. Pull the latest feature branch.
2. Read `HANDOFF.md`.
3. Read `docs/prd/PRD-001.md`.
4. Read `docs/ui/UI-DESIGN-BASELINE.md`.
5. Read `design-qa.md`.
6. Check `git status --short --branch`.
7. Continue from the listed next tasks.

## Verification Expectations

For backend/data changes:

- Run `npm run test:api`.
- Confirm revision conflicts return 409.
- Confirm failed transactional operations roll back.
- Confirm backup restore creates a new project and does not overwrite the source.

For frontend changes:

- Run `npm run test:web`.
- Run `npm run build`.
- Run Playwright at 1440x1024 and 1280x800 when UI behavior changes.
- Confirm business content survives clearing frontend `localStorage`.

For release or handoff:

- Run the broadest feasible verification set.
- Record exact pass/fail status in `HANDOFF.md`.

## GitHub Publishing

Preferred route with GitHub CLI:

```powershell
gh auth status
git remote -v
git push -u origin agent/local-data-foundation
gh pr create --draft --base main --head agent/local-data-foundation --title "Phase 2 local data foundation" --body-file HANDOFF.md
```

Fallback route without GitHub CLI:

```powershell
git remote -v
git push -u origin agent/local-data-foundation
```

Then create the draft PR manually on GitHub.

## Review Checklist For GPT-5.6

- Confirm the local-first data model matches the PRD.
- Review SQLite transaction boundaries and restore safety.
- Check API schema compatibility and error shapes.
- Check UI loading, disconnected, empty, conflict, and recovery states.
- Check that local data is ignored by Git.
- Decide whether the branch is ready to merge or needs another implementation pass.
