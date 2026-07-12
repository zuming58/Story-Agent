# Story Agent Phase 5 Handoff

Updated: 2026-07-13
Branch: `agent/chapter-pipeline-foundation`
Phase 5 baseline: `565d7b3`
Draft PR: https://github.com/zuming58/Story-Agent/pull/4
Latest implementation endpoint before final validation: `7f64f4f`
Final handoff/test update: pending commit after validation

## Scope Completed

Phase 5 backend is implemented. No `apps/web/**`, CSS, design tokens, Playwright tests, screenshots, `Story agent/`, or `openclaw skill/` files were modified.

Completed work packages:

1. `e85fbd9 feat: add chapter pipeline data model`
   - Added project migration `0006_chapter_pipeline`.
   - Added ORM models and Pydantic API contracts for chapter contracts, jobs, drafts, extractions, quality runs/findings, and commits.
   - Added `continuity_reviewer` and `story_editor` model roles.

2. `2db85e4 feat: add chapter contract job draft pipeline`
   - Added `Phase5Service`.
   - Added chapter contract derive/list/get/update/lock APIs.
   - Added chapter job create/list/get/run/cancel/retry APIs.
   - Added candidate draft creation through `chinese_writer`.
   - Added structured extraction through `fact_extractor`, with one JSON repair retry and Phase 4 state payload validation.
   - Candidate drafts and extractions do not modify official state.

3. `d236cd0 feat: add chapter quality review revision loop`
   - Added deterministic quality gate and finding fingerprint dedupe.
   - Added model review runs for `continuity_reviewer`, `story_editor`, and `style_reviewer`.
   - Missing reviewer roles create explicit `CHAPTER_MODEL_ROLE_NOT_CONFIGURED` findings and do not fake a pass.
   - Added accepted-risk flow.
   - Added revision flow using `reviser`, preserving parent draft links and enforcing max two rounds.

4. `7f64f4f feat: commit chapter drafts to story state`
   - Added manual/guarded approval.
   - Added official commit transaction for approved drafts.
   - Commits create `SourceVersion(source_kind=chapter)`, materialize extracted state via Phase 4 validation/materialization, create snapshots, rebuild retrieval, update `currentChapter`, and audit the commit.
   - Rewrites supersede prior current chapter commit/source and replay state inline.
   - Added manuscript mirror `manuscripts/chapter-XXXX.md`; mirror failure records audit and does not roll back SQLite truth.
   - Backup now includes `manuscripts/**`; restore remaps all Phase 5 project-scoped tables.

## Migration And Tables

Project migration:

- `0006_chapter_pipeline`

New tables:

- `chapter_contracts`
- `chapter_jobs`
- `chapter_drafts`
- `chapter_extractions`
- `quality_runs`
- `quality_findings`
- `chapter_commits`

Important constraints:

- One locked contract per project/chapter.
- One chapter job per project/contract/idempotency key.
- One draft version per job/version number.
- Quality finding dedupe by draft/fingerprint.
- One current commit per project/chapter.

## API Added

- `POST /api/v1/projects/{project_id}/chapter-contracts/derive`
- `GET /api/v1/projects/{project_id}/chapter-contracts`
- `GET|PUT /api/v1/projects/{project_id}/chapter-contracts/{contract_id}`
- `POST /api/v1/projects/{project_id}/chapter-contracts/{contract_id}/lock`
- `POST /api/v1/projects/{project_id}/chapter-jobs`
- `GET /api/v1/projects/{project_id}/chapter-jobs`
- `GET /api/v1/projects/{project_id}/chapter-jobs/{job_id}`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/run`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/cancel`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/retry`
- `GET /api/v1/projects/{project_id}/chapters/{chapter_number}/drafts`
- `GET /api/v1/projects/{project_id}/chapter-drafts/{draft_id}`
- `GET /api/v1/projects/{project_id}/chapter-jobs/{job_id}/quality`
- `POST /api/v1/projects/{project_id}/quality-findings/{finding_id}/accept-risk`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/revise`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/approve`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/commit`

## Job State Machine

Implemented statuses:

- `queued`
- `compiling_context`
- `drafting`
- `extracting`
- `validating`
- `reviewing`
- `revising`
- `human_review`
- `approved`
- `completed`
- `failed`
- `cancel_requested`
- `cancelled`
- `interrupted`

Startup recovery converts active jobs to `interrupted`, or `cancel_requested` jobs to `cancelled`.

## Known Limits

- Phase 5 has backend APIs and tests only; UI is intentionally untouched for GPT-5.6 ownership.
- The first runner is synchronous from the HTTP call, but it uses short SQLite write transactions around external model calls.
- Deterministic quality checks are intentionally conservative and cover empty drafts, placeholders, word budget, future-node keyword consumption, missing completion-condition evidence, and extraction validity. More domain-specific Canon rule checks can be extended in audit/follow-up without changing the core table/API contract.
- Manuscript Markdown is a rebuildable mirror. SQLite remains the truth source.

## Security Notes

- Tests use `MemorySecretStore` and local fake OpenAI-compatible HTTP servers.
- No real model call is required by automated tests.
- `model_runs` store role/provider/model/status/token/diagnostic metadata only; they do not store API keys.
- No API key, `.data`, database, log, backup ZIP, model raw response, or temporary file is intentionally tracked.

## Validation Results

Before updating this document:

- `uv run --project apps/api pytest apps/api/tests -q`: `59 passed`

Final validation:

- `npm run build`: passed. Existing Vite chunk-size warning remains.
- `npm run test`: passed. API `59 passed`; Web `3 files / 8 tests passed`.
- `npm run test:e2e`: passed. Playwright `6 passed`.

## Next Step For GPT-5.6 Audit

Audit from Phase 5 baseline `565d7b3` through the final pushed branch head. Recommended audit focus:

- Chapter commit transaction rollback and conflict behavior.
- Rewrite/supersede replay behavior for chapter source versions.
- Quality finding severity/accepted-risk policy.
- Model role failure behavior and absence of fake passes.
- Backup/restore remapping for all Phase 5 tables and manuscript mirrors.
- Confirmation that `apps/web/**` and visual baselines remain untouched.
