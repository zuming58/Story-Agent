from __future__ import annotations

import tempfile
import json
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.responses import StreamingResponse

from .config import Settings
from .schemas import (
    AgentMessageCreate,
    AgentResponse,
    AgentSessionCreate,
    AgentSessionOut,
    AuditEventOut,
    AutomationPolicyOut,
    AutomationPolicyUpdate,
    AutomationDailyReportOut,
    AutomationRunCreate,
    AutomationRunOut,
    CanonAnalyzeRequest,
    CanonChangeRequestCreate,
    CanonChangeRequestDecision,
    CanonChangeRequestOut,
    CanonDocumentOut,
    CanonDraftUpdate,
    CanonEntityOut,
    CanonEntityTypeOut,
    CanonLockRequest,
    StoryBrief,
    ArchitectureProposalDecision,
    CanonGenerationProposalOut,
    CanonReadinessOut,
    CanonRelationOut,
    CanonRuleOut,
    BackupManifest,
    BackupRecord,
    ChangeProposalOut,
    ChapterApproveRequest,
    ChapterCommitOut,
    ChapterCommitRequest,
    ChapterContractDerive,
    ChapterContractLock,
    ChapterContractOut,
    ChapterContractUpdate,
    ChapterDraftActivateRequest,
    ChapterManualRevisionRequest,
    ChapterDraftOut,
    ChapterJobCreate,
    ChapterJobOut,
    ChapterQualityRevalidate,
    ChapterJobRetry,
    ChapterJobRun,
    ChapterRevisionRequest,
    ContextCompileRequest,
    ContextPackageOut,
    ContextTraceItemOut,
    ExportCreate,
    ExportJobOut,
    ExportProfileOut,
    ExportProfileUpdate,
    ExportReadinessOut,
    ExportReadinessRequest,
    EnduranceFindingOut,
    EnduranceReadinessOut,
    EnduranceReportOut,
    EnduranceRunCreate,
    EnduranceRunOut,
    EnduranceSuiteCreate,
    EnduranceSuiteOut,
    EnduranceSuiteUpdate,
    ForeshadowOut,
    KnowledgeBoundaryOut,
    ModelConfigCreate,
    ModelConfigOut,
    ModelConfigUpdate,
    ModelProviderCreate,
    ModelProviderOut,
    ModelProviderUpdate,
    ModelRunOut,
    ModelRoleBindingOut,
    ModelRoleBindingUpdate,
    PlanNodeCreate,
    PlanNodeOut,
    PlanNodeUpdate,
    PlanGenerationRequest,
    PlanGenerationProposalOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    ProposalApply,
    ProposalReject,
    ProviderConnectionTestOut,
    PublicationRecordCreate,
    PublicationRecordOut,
    QualityFindingAcceptRisk,
    QualityFindingOut,
    QualityReportOut,
    RetrievalHit,
    RetrievalQuery,
    RetrievalStatus,
    SourceVersionOut,
    SourceVersionSupersede,
    StateCandidateCommit,
    StateCandidateCreate,
    StateDeltaOut,
    StateFactOut,
    StateSnapshotOut,
    StoryEntityOut,
    StoryEventOut,
    StoryPlanOut,
    TrialReadinessOut,
)
from .secrets import SecretStore
from .services import StoryError, StoryService


MAX_BACKUP_UPLOAD_BYTES = 512 * 1024 * 1024


def create_app(settings: Settings | None = None, secret_store: SecretStore | None = None) -> FastAPI:
    settings = settings or Settings()
    service = StoryService(settings, secret_store=secret_store)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        service.initialize()
        service.phase7.start_scheduler()
        yield
        await service.phase7.stop_scheduler()
        service.close()

    app = FastAPI(title="Story Agent API", version="0.1.0", lifespan=lifespan)
    app.state.story_service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = request.headers.get("X-Request-ID") or str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(StoryError)
    async def story_error_handler(request: Request, exc: StoryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message, "details": exc.details, "requestId": request.state.request_id})

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "storage": "sqlite"}

    @app.get("/api/v1/model-providers", response_model=list[ModelProviderOut])
    def list_model_providers() -> object:
        return service.list_model_providers()

    @app.post("/api/v1/model-providers", response_model=ModelProviderOut, status_code=201)
    def create_model_provider(payload: ModelProviderCreate) -> object:
        return service.create_model_provider(payload)

    @app.post("/api/v1/model-providers/deepseek-preset", response_model=ModelProviderOut, status_code=201)
    def create_deepseek_preset() -> object:
        return service.create_deepseek_preset()

    @app.get("/api/v1/model-providers/{provider_id}", response_model=ModelProviderOut)
    def get_model_provider(provider_id: str) -> object:
        return service.get_model_provider(provider_id)

    @app.patch("/api/v1/model-providers/{provider_id}", response_model=ModelProviderOut)
    def update_model_provider(provider_id: str, payload: ModelProviderUpdate) -> object:
        return service.update_model_provider(provider_id, payload)

    @app.delete("/api/v1/model-providers/{provider_id}", status_code=204)
    def delete_model_provider(provider_id: str) -> None:
        service.delete_model_provider(provider_id)

    @app.post("/api/v1/model-providers/{provider_id}/test", response_model=ProviderConnectionTestOut)
    def test_model_provider(provider_id: str) -> object:
        return service.test_model_provider(provider_id)

    @app.get("/api/v1/model-providers/{provider_id}/models", response_model=list[ModelConfigOut])
    def list_model_configs(provider_id: str) -> object:
        return service.list_model_configs(provider_id)

    @app.post("/api/v1/model-providers/{provider_id}/models", response_model=ModelConfigOut, status_code=201)
    def create_model_config(provider_id: str, payload: ModelConfigCreate) -> object:
        return service.create_model_config(provider_id, payload)

    @app.patch("/api/v1/models/{model_id}", response_model=ModelConfigOut)
    def update_model_config(model_id: str, payload: ModelConfigUpdate) -> object:
        return service.update_model_config(model_id, payload)

    @app.delete("/api/v1/models/{model_id}", status_code=204)
    def delete_model_config(model_id: str) -> None:
        service.delete_model_config(model_id)

    @app.get("/api/v1/model-role-bindings", response_model=list[ModelRoleBindingOut])
    def list_model_role_bindings() -> object:
        return service.list_model_role_bindings()

    @app.put("/api/v1/model-role-bindings/{role}", response_model=ModelRoleBindingOut)
    def update_model_role_binding(role: str, payload: ModelRoleBindingUpdate) -> object:
        return service.update_model_role_binding(role, payload)

    @app.get("/api/v1/projects", response_model=list[ProjectOut])
    def list_projects() -> list[object]:
        return service.list_projects()

    @app.post("/api/v1/projects", response_model=ProjectOut, status_code=201)
    def create_project(payload: ProjectCreate) -> object:
        return service.create_project(payload)

    @app.get("/api/v1/projects/{project_id}", response_model=ProjectOut)
    def get_project(project_id: str) -> object:
        return service.get_project(project_id, touch=True)

    @app.patch("/api/v1/projects/{project_id}", response_model=ProjectOut)
    def update_project(project_id: str, payload: ProjectUpdate) -> object:
        return service.update_project(project_id, payload)

    @app.get("/api/v1/projects/{project_id}/plan", response_model=StoryPlanOut)
    def get_plan(project_id: str) -> object:
        return service.get_plan(project_id)

    @app.get("/api/v1/projects/{project_id}/canon")
    def get_canon(project_id: str) -> object:
        return service.phase4.get_canon(project_id)

    @app.post("/api/v1/projects/{project_id}/canon/analyze")
    def analyze_canon(project_id: str, payload: CanonAnalyzeRequest, request: Request) -> object:
        return service.phase4.analyze_canon(project_id, payload, request.state.request_id)

    @app.put("/api/v1/projects/{project_id}/canon/draft")
    def update_canon_draft(project_id: str, payload: CanonDraftUpdate) -> object:
        return service.phase4.update_canon_draft(project_id, payload)

    @app.post("/api/v1/projects/{project_id}/canon/lock")
    def lock_canon(project_id: str, payload: CanonLockRequest, request: Request) -> object:
        return service.phase4.lock_canon(project_id, payload, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/canon/generation-proposals", response_model=CanonGenerationProposalOut, status_code=201)
    def create_canon_generation_proposal(project_id: str, payload: StoryBrief, request: Request) -> object:
        return service.phase8.create_canon_proposal(project_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/canon/generation-proposals", response_model=list[CanonGenerationProposalOut])
    def list_canon_generation_proposals(project_id: str) -> object:
        return service.phase8.list_canon_proposals(project_id)

    @app.post("/api/v1/canon/generation-proposals/{proposal_id}/apply")
    def apply_canon_generation_proposal(proposal_id: str, payload: ArchitectureProposalDecision, request: Request) -> object:
        return service.phase8.apply_canon_proposal(proposal_id, payload, request.state.request_id)

    @app.post("/api/v1/canon/generation-proposals/{proposal_id}/reject", response_model=CanonGenerationProposalOut)
    def reject_canon_generation_proposal(proposal_id: str, payload: ArchitectureProposalDecision, request: Request) -> object:
        return service.phase8.reject_canon_proposal(proposal_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/canon/readiness", response_model=CanonReadinessOut)
    def get_canon_readiness(project_id: str) -> object:
        return service.phase8.canon_readiness(project_id)

    @app.post("/api/v1/projects/{project_id}/canon/change-requests")
    def create_canon_change_request(project_id: str, payload: CanonChangeRequestCreate, request: Request) -> object:
        return service.phase4.create_canon_change_request(project_id, payload, request.state.request_id)

    @app.post("/api/v1/canon/change-requests/{change_request_id}/apply")
    def apply_canon_change_request(change_request_id: str, payload: CanonChangeRequestDecision, request: Request) -> object:
        return service.phase4.apply_canon_change_request(change_request_id, payload, request.state.request_id)

    @app.post("/api/v1/canon/change-requests/{change_request_id}/reject")
    def reject_canon_change_request(change_request_id: str, payload: CanonChangeRequestDecision, request: Request) -> object:
        return service.phase4.reject_canon_change_request(change_request_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/state/entities")
    def list_state_entities(project_id: str) -> object:
        return service.phase4.list_state_entities(project_id)

    @app.get("/api/v1/projects/{project_id}/state/entities/{entity_id}")
    def get_state_entity(project_id: str, entity_id: str) -> object:
        return service.phase4.get_state_entity(project_id, entity_id)

    @app.get("/api/v1/projects/{project_id}/state/foreshadows")
    def list_foreshadows(project_id: str) -> object:
        return service.phase4.list_foreshadows(project_id)

    @app.get("/api/v1/projects/{project_id}/state/timeline")
    def list_state_timeline(project_id: str) -> object:
        return service.phase4.list_timeline(project_id)

    @app.post("/api/v1/projects/{project_id}/state/candidates")
    def create_state_candidate(project_id: str, payload: StateCandidateCreate, request: Request) -> object:
        return service.phase4.create_state_candidate(project_id, payload, request.state.request_id)

    @app.post("/api/v1/state/candidates/{candidate_id}/commit")
    def commit_state_candidate(candidate_id: str, payload: StateCandidateCommit, request: Request) -> object:
        return service.phase4.commit_state_candidate(candidate_id, payload, request.state.request_id)

    @app.post("/api/v1/source-versions/{source_version_id}/supersede")
    def supersede_source_version(source_version_id: str, payload: SourceVersionSupersede, request: Request) -> object:
        return service.phase4.supersede_source_version(source_version_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/state/snapshots")
    def list_state_snapshots(project_id: str) -> object:
        return service.phase4.list_snapshots(project_id)

    @app.post("/api/v1/projects/{project_id}/retrieval/search")
    def retrieval_search(project_id: str, payload: RetrievalQuery) -> object:
        return service.phase4.search_retrieval(project_id, payload)

    @app.post("/api/v1/projects/{project_id}/retrieval/rebuild")
    def retrieval_rebuild(project_id: str) -> object:
        return service.phase4.rebuild_retrieval(project_id)

    @app.get("/api/v1/projects/{project_id}/retrieval/status")
    def retrieval_status(project_id: str) -> object:
        return service.phase4.retrieval_status(project_id)

    @app.post("/api/v1/projects/{project_id}/context/compile")
    def compile_context(project_id: str, payload: ContextCompileRequest, request: Request) -> object:
        return service.phase4.compile_context(project_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/context/traces/{trace_id}")
    def get_context_trace(project_id: str, trace_id: str) -> object:
        return service.phase4.get_context_trace(project_id, trace_id)

    @app.post("/api/v1/projects/{project_id}/chapter-contracts/derive", response_model=ChapterContractOut)
    def derive_chapter_contract(project_id: str, payload: ChapterContractDerive, request: Request) -> object:
        return service.phase5.derive_chapter_contract(project_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/chapter-contracts", response_model=list[ChapterContractOut])
    def list_chapter_contracts(project_id: str) -> object:
        return service.phase5.list_chapter_contracts(project_id)

    @app.get("/api/v1/projects/{project_id}/chapter-contracts/{contract_id}", response_model=ChapterContractOut)
    def get_chapter_contract(project_id: str, contract_id: str) -> object:
        return service.phase5.get_chapter_contract(project_id, contract_id)

    @app.put("/api/v1/projects/{project_id}/chapter-contracts/{contract_id}", response_model=ChapterContractOut)
    def update_chapter_contract(project_id: str, contract_id: str, payload: ChapterContractUpdate, request: Request) -> object:
        return service.phase5.update_chapter_contract(project_id, contract_id, payload, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/chapter-contracts/{contract_id}/lock", response_model=ChapterContractOut)
    def lock_chapter_contract(project_id: str, contract_id: str, payload: ChapterContractLock, request: Request) -> object:
        return service.phase5.lock_chapter_contract(project_id, contract_id, payload, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/chapter-jobs", response_model=ChapterJobOut, status_code=201)
    def create_chapter_job(project_id: str, payload: ChapterJobCreate, request: Request) -> object:
        return service.phase5.create_chapter_job(project_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/chapter-jobs", response_model=list[ChapterJobOut])
    def list_chapter_jobs(project_id: str) -> object:
        return service.phase5.list_chapter_jobs(project_id)

    @app.get("/api/v1/projects/{project_id}/chapter-jobs/{job_id}", response_model=ChapterJobOut)
    def get_chapter_job(project_id: str, job_id: str) -> object:
        return service.phase5.get_chapter_job(project_id, job_id)

    @app.post("/api/v1/projects/{project_id}/chapter-jobs/{job_id}/run", response_model=ChapterJobOut)
    def run_chapter_job(project_id: str, job_id: str, payload: ChapterJobRun, request: Request) -> object:
        return service.phase5.run_chapter_job(project_id, job_id, payload, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/chapter-jobs/{job_id}/cancel", response_model=ChapterJobOut)
    def cancel_chapter_job(project_id: str, job_id: str, request: Request) -> object:
        return service.phase5.cancel_chapter_job(project_id, job_id, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/chapter-jobs/{job_id}/retry", response_model=ChapterJobOut)
    def retry_chapter_job(project_id: str, job_id: str, payload: ChapterJobRetry, request: Request) -> object:
        return service.phase5.retry_chapter_job(project_id, job_id, payload, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/chapter-jobs/{job_id}/resume", response_model=ChapterJobOut)
    def resume_chapter_job(project_id: str, job_id: str, request: Request) -> object:
        return service.phase5.resume_chapter_job(project_id, job_id, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/chapters/{chapter_number}/drafts", response_model=list[ChapterDraftOut])
    def list_chapter_drafts(project_id: str, chapter_number: int) -> object:
        return service.phase5.list_chapter_drafts(project_id, chapter_number)

    @app.get("/api/v1/projects/{project_id}/chapter-drafts/{draft_id}")
    def get_chapter_draft(project_id: str, draft_id: str) -> object:
        return service.phase5.get_chapter_draft(project_id, draft_id)

    @app.get("/api/v1/projects/{project_id}/chapters/{chapter_number}/commits", response_model=list[ChapterCommitOut])
    def list_chapter_commits(project_id: str, chapter_number: int) -> object:
        return service.phase5.list_chapter_commits(project_id, chapter_number)

    @app.get("/api/v1/projects/{project_id}/chapter-jobs/{job_id}/quality", response_model=QualityReportOut)
    def get_chapter_quality(project_id: str, job_id: str) -> object:
        return service.phase5.get_quality_report(project_id, job_id)

    @app.post("/api/v1/projects/{project_id}/chapter-jobs/{job_id}/quality/revalidate", response_model=ChapterJobOut)
    def revalidate_chapter_quality(project_id: str, job_id: str, payload: ChapterQualityRevalidate, request: Request) -> object:
        return service.phase5.revalidate_deterministic_quality(project_id, job_id, payload, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/quality-findings/{finding_id}/accept-risk", response_model=QualityFindingOut)
    def accept_quality_risk(project_id: str, finding_id: str, payload: QualityFindingAcceptRisk, request: Request) -> object:
        return service.phase5.accept_quality_risk(project_id, finding_id, payload, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/chapter-jobs/{job_id}/revise", response_model=ChapterJobOut)
    def revise_chapter_job(project_id: str, job_id: str, payload: ChapterRevisionRequest, request: Request) -> object:
        return service.phase5.revise_chapter_job(project_id, job_id, payload, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/chapter-jobs/{job_id}/manual-revisions", response_model=ChapterJobOut)
    def create_manual_chapter_revision(project_id: str, job_id: str, payload: ChapterManualRevisionRequest, request: Request) -> object:
        return service.phase5.create_manual_revision(project_id, job_id, payload, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/chapter-jobs/{job_id}/drafts/{draft_id}/activate", response_model=ChapterJobOut)
    def activate_chapter_draft(project_id: str, job_id: str, draft_id: str, payload: ChapterDraftActivateRequest, request: Request) -> object:
        return service.phase5.activate_chapter_draft(project_id, job_id, draft_id, payload, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/chapter-jobs/{job_id}/approve", response_model=ChapterJobOut)
    def approve_chapter_job(project_id: str, job_id: str, payload: ChapterApproveRequest, request: Request) -> object:
        return service.phase5.approve_chapter_job(project_id, job_id, payload, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/chapter-jobs/{job_id}/commit", response_model=ChapterCommitOut)
    def commit_chapter_job(project_id: str, job_id: str, payload: ChapterCommitRequest, request: Request) -> object:
        return service.phase5.commit_chapter_job(project_id, job_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/automation/policy", response_model=AutomationPolicyOut)
    def get_automation_policy(project_id: str) -> object:
        return service.phase7.get_policy(project_id)

    @app.get("/api/v1/projects/{project_id}/trial-readiness", response_model=TrialReadinessOut)
    def get_trial_readiness(project_id: str, chapter_count: int = Query(default=1, alias="chapterCount")) -> object:
        return service.phase7.get_trial_readiness(project_id, chapter_count)

    @app.put("/api/v1/projects/{project_id}/automation/policy", response_model=AutomationPolicyOut)
    def update_automation_policy(project_id: str, payload: AutomationPolicyUpdate) -> object:
        return service.phase7.update_policy(project_id, payload)

    @app.post("/api/v1/projects/{project_id}/automation/runs", response_model=AutomationRunOut, status_code=201)
    def create_automation_run(project_id: str, payload: AutomationRunCreate, request: Request) -> object:
        return service.phase7.create_manual_run(project_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/automation/runs", response_model=list[AutomationRunOut])
    def list_automation_runs(project_id: str) -> object:
        return service.phase7.list_runs(project_id)

    @app.get("/api/v1/projects/{project_id}/automation/reports", response_model=list[AutomationDailyReportOut])
    def list_automation_reports(project_id: str) -> object:
        return service.phase7.get_daily_reports(project_id)

    @app.get("/api/v1/projects/{project_id}/automation/runs/{run_id}", response_model=AutomationRunOut)
    def get_automation_run(project_id: str, run_id: str) -> object:
        return service.phase7.get_run(project_id, run_id)

    @app.post("/api/v1/projects/{project_id}/automation/runs/{run_id}/cancel", response_model=AutomationRunOut)
    def cancel_automation_run(project_id: str, run_id: str, request: Request) -> object:
        return service.phase7.cancel_run(project_id, run_id, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/automation/runs/{run_id}/resume", response_model=AutomationRunOut)
    def resume_automation_run(project_id: str, run_id: str, request: Request) -> object:
        return service.phase7.resume_run(project_id, run_id, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/automation/runs/{run_id}/catch-up", response_model=AutomationRunOut)
    def catch_up_automation_run(project_id: str, run_id: str, request: Request) -> object:
        return service.phase7.catch_up_run(project_id, run_id, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/exports/profile", response_model=ExportProfileOut)
    def get_export_profile(project_id: str) -> object:
        return service.phase9.get_profile(project_id)

    @app.put("/api/v1/projects/{project_id}/exports/profile", response_model=ExportProfileOut)
    def update_export_profile(project_id: str, payload: ExportProfileUpdate) -> object:
        return service.phase9.update_profile(project_id, payload)

    @app.post("/api/v1/projects/{project_id}/exports/readiness", response_model=ExportReadinessOut)
    def check_export_readiness(project_id: str, payload: ExportReadinessRequest) -> object:
        return service.phase9.readiness(project_id, payload)

    @app.post("/api/v1/projects/{project_id}/exports", response_model=ExportJobOut, status_code=201)
    def create_export(project_id: str, payload: ExportCreate, request: Request) -> object:
        return service.phase9.create_export(project_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/exports", response_model=list[ExportJobOut])
    def list_exports(project_id: str) -> object:
        return service.phase9.list_exports(project_id)

    @app.get("/api/v1/projects/{project_id}/exports/{export_id}", response_model=ExportJobOut)
    def get_export(project_id: str, export_id: str) -> object:
        return service.phase9.get_export(project_id, export_id)

    @app.post("/api/v1/projects/{project_id}/exports/{export_id}/cancel", response_model=ExportJobOut)
    def cancel_export(project_id: str, export_id: str, request: Request) -> object:
        return service.phase9.cancel_export(project_id, export_id, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/exports/{export_id}/resume", response_model=ExportJobOut)
    def resume_export(project_id: str, export_id: str, request: Request) -> object:
        return service.phase9.resume_export(project_id, export_id, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/exports/{export_id}/artifacts/{artifact_id}/download")
    def download_export_artifact(project_id: str, export_id: str, artifact_id: str) -> FileResponse:
        path = service.phase9.artifact_path(project_id, export_id, artifact_id)
        return FileResponse(path, filename=path.name)

    @app.post("/api/v1/projects/{project_id}/exports/{export_id}/publication-records", response_model=PublicationRecordOut, status_code=201)
    def create_publication_record(project_id: str, export_id: str, payload: PublicationRecordCreate, request: Request) -> object:
        return service.phase9.create_publication_record(project_id, export_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/publication-records", response_model=list[PublicationRecordOut])
    def list_publication_records(project_id: str) -> object:
        return service.phase9.list_publication_records(project_id)

    @app.get("/api/v1/projects/{project_id}/endurance/readiness", response_model=EnduranceReadinessOut)
    def get_endurance_readiness(project_id: str, chapter_count: int = Query(default=5, alias="chapterCount")) -> object:
        return service.phase10.readiness(project_id, chapter_count)

    @app.post("/api/v1/projects/{project_id}/endurance/suites", response_model=EnduranceSuiteOut, status_code=201)
    def create_endurance_suite(project_id: str, payload: EnduranceSuiteCreate) -> object:
        return service.phase10.create_suite(project_id, payload)

    @app.get("/api/v1/projects/{project_id}/endurance/suites", response_model=list[EnduranceSuiteOut])
    def list_endurance_suites(project_id: str) -> object:
        return service.phase10.list_suites(project_id)

    @app.put("/api/v1/projects/{project_id}/endurance/suites/{suite_id}", response_model=EnduranceSuiteOut)
    def update_endurance_suite(project_id: str, suite_id: str, payload: EnduranceSuiteUpdate) -> object:
        return service.phase10.update_suite(project_id, suite_id, payload)

    @app.post("/api/v1/projects/{project_id}/endurance/runs", response_model=EnduranceRunOut, status_code=201)
    def create_endurance_run(project_id: str, payload: EnduranceRunCreate, request: Request) -> object:
        return service.phase10.create_run(project_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/endurance/runs", response_model=list[EnduranceRunOut])
    def list_endurance_runs(project_id: str) -> object:
        return service.phase10.list_runs(project_id)

    @app.get("/api/v1/projects/{project_id}/endurance/runs/{run_id}", response_model=EnduranceRunOut)
    def get_endurance_run(project_id: str, run_id: str) -> object:
        return service.phase10.get_run(project_id, run_id)

    @app.post("/api/v1/projects/{project_id}/endurance/runs/{run_id}/cancel", response_model=EnduranceRunOut)
    def cancel_endurance_run(project_id: str, run_id: str, request: Request) -> object:
        return service.phase10.cancel_run(project_id, run_id, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/endurance/runs/{run_id}/resume", response_model=EnduranceRunOut)
    def resume_endurance_run(project_id: str, run_id: str, request: Request) -> object:
        return service.phase10.resume_run(project_id, run_id, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/endurance/runs/{run_id}/evaluate", response_model=EnduranceRunOut)
    def evaluate_endurance_run(project_id: str, run_id: str, request: Request) -> object:
        return service.phase10.evaluate_run(project_id, run_id, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/endurance/runs/{run_id}/findings", response_model=list[EnduranceFindingOut])
    def list_endurance_findings(project_id: str, run_id: str) -> object:
        return service.phase10.list_findings(project_id, run_id)

    @app.get("/api/v1/projects/{project_id}/endurance/runs/{run_id}/report", response_model=EnduranceReportOut)
    def get_endurance_report(project_id: str, run_id: str) -> object:
        return service.phase10.get_report(project_id, run_id)

    @app.patch("/api/v1/projects/{project_id}/plan/nodes/{node_id}", response_model=PlanNodeOut)
    def update_plan_node(project_id: str, node_id: str, payload: PlanNodeUpdate, request: Request) -> object:
        return service.update_plan_node(project_id, node_id, payload, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/plan/nodes", response_model=PlanNodeOut, status_code=201)
    def create_plan_node(project_id: str, payload: PlanNodeCreate, request: Request) -> object:
        return service.create_plan_node(project_id, payload, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/plan/generation-proposals", response_model=PlanGenerationProposalOut, status_code=201)
    def create_plan_generation_proposal(project_id: str, payload: PlanGenerationRequest, request: Request) -> object:
        return service.phase8.create_plan_proposal(project_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/plan/generation-proposals", response_model=list[PlanGenerationProposalOut])
    def list_plan_generation_proposals(project_id: str) -> object:
        return service.phase8.list_plan_proposals(project_id)

    @app.post("/api/v1/plan/generation-proposals/{proposal_id}/apply")
    def apply_plan_generation_proposal(proposal_id: str, payload: ArchitectureProposalDecision, request: Request) -> object:
        return service.phase8.apply_plan_proposal(proposal_id, payload, request.state.request_id)

    @app.post("/api/v1/plan/generation-proposals/{proposal_id}/reject", response_model=PlanGenerationProposalOut)
    def reject_plan_generation_proposal(proposal_id: str, payload: ArchitectureProposalDecision, request: Request) -> object:
        return service.phase8.reject_plan_proposal(proposal_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/agent/sessions", response_model=list[AgentSessionOut])
    def list_sessions(project_id: str) -> object:
        return service.list_sessions(project_id)

    @app.post("/api/v1/projects/{project_id}/agent/sessions", response_model=AgentSessionOut, status_code=201)
    def create_session(project_id: str, payload: AgentSessionCreate) -> object:
        return service.create_session(project_id, payload.scope)

    @app.post("/api/v1/agent/sessions/{session_id}/messages", response_model=AgentResponse)
    def send_message(session_id: str, payload: AgentMessageCreate) -> object:
        return service.send_message(session_id, payload)

    @app.post("/api/v1/agent/sessions/{session_id}/messages/stream")
    async def stream_message(session_id: str, payload: AgentMessageCreate, request: Request) -> StreamingResponse:
        async def events():
            active_run_id: str | None = None
            try:
                async for event in service.stream_agent_message(session_id, payload, request.state.request_id):
                    active_run_id = event.get("runId") or active_run_id
                    yield f"event: {event['event']}\n"
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                    if await request.is_disconnected():
                        if active_run_id:
                            service.cancel_model_run(payload.project_id, active_run_id)
                        break
            except StoryError as exc:
                error = {"event": "failed", "errorCode": exc.code, "message": exc.message, "details": exc.details, "requestId": request.state.request_id}
                yield "event: failed\n"
                yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/v1/projects/{project_id}/model-runs/{run_id}/cancel", response_model=ModelRunOut)
    def cancel_model_run(project_id: str, run_id: str) -> object:
        return service.cancel_model_run(project_id, run_id)

    @app.get("/api/v1/projects/{project_id}/model-runs", response_model=list[ModelRunOut])
    def list_model_runs(project_id: str, limit: int = Query(default=100, ge=1, le=500), status: str | None = Query(default=None), role: str | None = Query(default=None)) -> object:
        return service.list_model_runs(project_id, limit, status=status, role=role)

    @app.get("/api/v1/projects/{project_id}/change-proposals", response_model=list[ChangeProposalOut])
    def list_proposals(project_id: str, status: str | None = Query(default=None)) -> object:
        return service.list_proposals(project_id, status)

    @app.post("/api/v1/change-proposals/{proposal_id}/apply", response_model=ChangeProposalOut)
    def apply_proposal(proposal_id: str, payload: ProposalApply, request: Request) -> object:
        return service.apply_proposal(proposal_id, payload, request.state.request_id)

    @app.post("/api/v1/change-proposals/{proposal_id}/reject", response_model=ChangeProposalOut)
    def reject_proposal(proposal_id: str, payload: ProposalReject, request: Request) -> object:
        return service.reject_proposal(proposal_id, payload, request.state.request_id)

    @app.get("/api/v1/projects/{project_id}/audit-events", response_model=list[AuditEventOut])
    def audit_events(project_id: str, limit: int = Query(default=100, ge=1, le=500), event_type: str | None = Query(default=None), entity_type: str | None = Query(default=None)) -> object:
        return service.list_audit_events(project_id, limit, event_type=event_type, entity_type=entity_type)

    @app.post("/api/v1/projects/{project_id}/audit-events/{event_id}/undo", response_model=AuditEventOut)
    def undo_event(project_id: str, event_id: str, request: Request) -> object:
        return service.undo_event(project_id, event_id, request.state.request_id)

    @app.post("/api/v1/projects/{project_id}/backups", response_model=BackupManifest, status_code=201)
    def create_backup(project_id: str) -> object:
        return service.create_backup(project_id)

    @app.get("/api/v1/projects/{project_id}/backups", response_model=list[BackupRecord])
    def list_backups(project_id: str) -> object:
        return service.list_backups(project_id)

    @app.get("/api/v1/projects/{project_id}/backups/{backup_id}/download")
    def download_backup(project_id: str, backup_id: str) -> FileResponse:
        path = service.backup_archive_path(project_id, backup_id)
        return FileResponse(path, media_type="application/zip", filename=path.name)

    @app.post("/api/v1/projects/restore", response_model=ProjectOut, status_code=201)
    async def restore_project(backup: UploadFile = File(...)) -> object:
        suffix = Path(backup.filename or "backup.zip").suffix or ".zip"
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=settings.data_dir, suffix=suffix, delete=False) as handle:
                temp_path = Path(handle.name)
                written = 0
                while chunk := backup.file.read(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_BACKUP_UPLOAD_BYTES:
                        raise StoryError(413, "BACKUP_UPLOAD_TOO_LARGE", "备份文件超过 512 MB 上传限制。")
                    handle.write(chunk)
            return service.restore_backup(temp_path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    return app


app = create_app()
