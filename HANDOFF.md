# Story Agent Handoff

Updated: 2026-07-11
Branch: `agent/local-data-foundation`
Base commit before this phase: `702d1ef`
Latest local commit: see `git log -1 --oneline`

## Current Phase

Phase 2 is the local data foundation. The goal is to replace prototype-only business state with a local-first backend while keeping the current planning UI and simulated Agent workflow.

Current status: implementation is committed and pushed to GitHub on `agent/local-data-foundation`. It passes API unit tests, web unit tests, and production build. Draft PR creation is still pending because GitHub CLI installation stalled on the package source/network path.

## Architecture

Data authority now belongs to the FastAPI service and local SQLite files:

- `.data/catalog.db` stores the project catalog and recent-open state.
- `.data/projects/{project-id}-{slug}/story.db` stores each project's plan, Agent sessions, proposals, and audit events.
- `.data/projects/{project-id}-{slug}/project.json` is a readable project manifest.
- `.data/projects/{project-id}-{slug}/canon/story-core.md` is the author-readable canon seed file.
- `.data/projects/{project-id}-{slug}/backups/` stores generated ZIP backups.

Frontend authority:

- React Query owns business data loaded from `/api/v1`.
- Zustand only stores UI state such as active project id, selected milestone id, Agent panel collapsed state, panel width, and notices.
- Business content should not be restored from `localStorage`.

Backend rules:

- API JSON is camelCase.
- IDs use UUID4 for persistent project/session/proposal/audit records.
- Datetimes are UTC ISO 8601 values.
- SQLite enables WAL, foreign keys, and a write timeout.
- Plan node writes use `revision` for optimistic concurrency.
- Proposal apply, node update, and audit logging are committed transactionally.
- Alembic has separate migration scopes for catalog and project databases.

## Completed

- Added FastAPI app under `apps/api`.
- Added SQLAlchemy models, Pydantic schemas, database manager, and service layer.
- Added Alembic migrations for catalog and project databases.
- Added project create/list/open/update endpoints.
- Added plan read and plan node edit endpoints.
- Added Agent sessions, messages, and simulated change proposal generation.
- Added proposal apply/reject with revision checks.
- Added audit event listing and undo for reversible changes.
- Added project backup and restore with SHA-256 manifest verification.
- Seeded "夜巡人" as the first local demo project.
- Added frontend API client and `StoryWorkspaceContext`.
- Added project overview page.
- Moved business data from Zustand/localStorage into React Query plus backend API.
- Updated Vite dev proxy for `/api`.
- Updated package scripts for combined API and web dev/test.

## Not Complete

- GitHub remote has been configured as `https://github.com/zuming58/Story-Agent.git`.
- Feature branch `agent/local-data-foundation` has been pushed.
- GitHub CLI is not installed yet on this computer. `winget install --id GitHub.cli --source winget` stalled and was stopped.
- Draft PR has not yet been created.
- `npm run test:e2e` still needs a fresh run after Playwright Chromium is installed. API startup reached `/api/v1/health`, but Playwright could not launch Chromium.
- The UI should still be visually checked at 1440x1024 and 1280x800 after the backend is running.
- The next stronger model should review transactional edges, restore safety, and frontend error states before merge.

## Known Issues And Risks

- The Playwright config starts the web dev server but not the API server. Run the root `npm run dev` or otherwise start the API before E2E tests.
- Playwright Chromium is missing in this environment, and `npm --prefix apps/web exec playwright install chromium` failed with `ECONNRESET`.
- Existing `.data` is intentionally ignored and should not be committed.
- `apps/api/.venv`, SQLite files, logs, backups, temp files, and local reference folders must stay out of Git.
- This folder was copied between machines, so verify remotes and credentials before pushing.

## Database Tables

Catalog database:

- `projects`
- `app_settings`

Project database:

- `project_meta`
- `plans`
- `plan_nodes`
- `story_markers`
- `agent_sessions`
- `agent_messages`
- `change_proposals`
- `change_operations`
- `proposal_impacts`
- `audit_events`

## API Surface

- `GET /api/v1/health`
- `GET /api/v1/projects`
- `POST /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `PATCH /api/v1/projects/{project_id}`
- `GET /api/v1/projects/{project_id}/plan`
- `PATCH /api/v1/projects/{project_id}/plan/nodes/{node_id}`
- `GET /api/v1/projects/{project_id}/agent/sessions`
- `POST /api/v1/projects/{project_id}/agent/sessions`
- `POST /api/v1/agent/sessions/{session_id}/messages`
- `GET /api/v1/projects/{project_id}/change-proposals`
- `POST /api/v1/change-proposals/{proposal_id}/apply`
- `POST /api/v1/change-proposals/{proposal_id}/reject`
- `GET /api/v1/projects/{project_id}/audit-events`
- `POST /api/v1/projects/{project_id}/audit-events/{event_id}/undo`
- `POST /api/v1/projects/{project_id}/backups`
- `POST /api/v1/projects/restore`

## Commands

Install:

```powershell
npm install
uv sync --project apps/api --dev
```

Run:

```powershell
npm run dev
```

Verify:

```powershell
npm run test:api
npm run test:web
npm run build
npm run test:e2e
```

Publish:

```powershell
git remote add origin https://github.com/zuming58/Story-Agent.git
git push -u origin agent/local-data-foundation
```

If GitHub CLI is installed and authenticated:

```powershell
gh pr create --draft --base main --head agent/local-data-foundation --title "Phase 2 local data foundation" --body-file HANDOFF.md
```

## Latest Test Results

Last verified in this workspace on 2026-07-11:

- `npm run test:api`: passed, 7 tests.
- `npm run test:web`: passed, 5 tests.
- `npm run build`: passed.
- `npm run test:e2e`: blocked before assertions because Playwright Chromium is not installed. Browser install attempt failed with `ECONNRESET`.

## Next Agent Tasks

1. Create a draft PR from `agent/local-data-foundation` to `main`.
2. Install or verify GitHub CLI only if PR automation is desired.
3. Install Playwright Chromium and rerun E2E with API available.
4. Ask GPT-5.6 to review the PR against `docs/prd/PRD-001.md`, `docs/ui/UI-DESIGN-BASELINE.md`, `design-qa.md`, and this handoff.

## Do Not Commit

- `.data/`
- `.agents/`
- `.codex/`
- `apps/api/.venv/`
- `node_modules/`
- `*.db`, `*.sqlite*`, `*.zip`, logs, and temp files
- Local reference directories `Story agent/` and `openclaw skill/`
