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
    BackupManifest,
    BackupRecord,
    ChangeProposalOut,
    ModelConfigCreate,
    ModelConfigOut,
    ModelConfigUpdate,
    ModelProviderCreate,
    ModelProviderOut,
    ModelProviderUpdate,
    ModelRunOut,
    ModelRoleBindingOut,
    ModelRoleBindingUpdate,
    PlanNodeOut,
    PlanNodeUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    ProposalApply,
    ProposalReject,
    ProviderConnectionTestOut,
    StoryPlanOut,
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
        yield
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

    @app.patch("/api/v1/projects/{project_id}/plan/nodes/{node_id}", response_model=PlanNodeOut)
    def update_plan_node(project_id: str, node_id: str, payload: PlanNodeUpdate, request: Request) -> object:
        return service.update_plan_node(project_id, node_id, payload, request.state.request_id)

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
