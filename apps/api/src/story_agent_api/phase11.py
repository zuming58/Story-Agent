from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AdaptationFinding,
    AdaptationProposal,
    AdaptationWorkspace,
    CanonDocument,
    ChapterCommit,
    DramaEpisode,
    DramaScene,
    DramaScriptVersion,
    Plan,
    PlanNode,
    ProjectMeta,
    ShortStoryStrategy,
)
from .schemas import (
    AdaptationProposalAction,
    AdaptationWorkspaceCreate,
    AdaptationWorkspaceUpdate,
    DramaOutlineProposalCreate,
    ScriptProposalCreate,
    ScriptVersionApprove,
    ShortStoryProposalCreate,
)
from .services import StoryError, dumps, loads, remap_json_identifier, safe_json_loads, stable_digest


SHORT_STORY_RULES = {
    "DRAMA_APPROVAL_CONFLICT",
    "ADAPTATION_CANON_DEVIATION_UNDECLARED",
    "ADAPTATION_SOURCE_DRIFT",
    "SHORTFORM_EVENT_BUDGET_OVERFLOW",
    "SHORTFORM_FORESHADOW_DROPPED",
    "DRAMA_EPISODE_DURATION_OUT_OF_RANGE",
    "DRAMA_SCENE_DURATION_OVERFLOW",
    "DRAMA_CHARACTER_KNOWLEDGE_LEAK",
    "DRAMA_ABILITY_RULE_BREACH",
    "DRAMA_OPENING_HOOK_MISSING",
    "DRAMA_ENDING_CLIFFHANGER_MISSING",
    "DRAMA_DIALOGUE_WITHOUT_SOURCE_OR_PURPOSE",
}
OPEN_BLOCKING_SEVERITIES = {"error", "blocker"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model response is not a JSON object")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model response is not a JSON object")
    return value


class Phase11Service:
    def __init__(self, service: Any):
        self.service = service

    def recover_interrupted_adaptations(self) -> None:
        now = _now()
        for project in self.service.list_projects():
            with self.service.db.project_write(project.id, project.folder_path) as session:
                for workspace in session.scalars(select(AdaptationWorkspace).where(AdaptationWorkspace.status == "analyzing")).all():
                    workspace.status = "ready"
                    workspace.diagnostic_json = dumps({"recovered": "startup_recovery"})
                    workspace.revision += 1
                    workspace.updated_at = now
                for proposal in session.scalars(select(AdaptationProposal).where(AdaptationProposal.status == "generating")).all():
                    proposal.status = "interrupted"
                    proposal.error_code = "startup_recovery"
                    proposal.error_message = "Generation was interrupted by service startup recovery."
                    proposal.revision += 1
                    proposal.updated_at = now

    # ------------------------------------------------------------------
    # Workspaces
    # ------------------------------------------------------------------
    def create_workspace(self, project_id: str, payload: AdaptationWorkspaceCreate) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        if project.project_kind != "standard":
            raise StoryError(409, "DEMO_PROJECT_WRITE_BLOCKED", "Adaptation workspaces require a standard project.")
        now = _now()
        with self.service.db.project_write(project.id, project.folder_path) as session:
            existing = session.scalar(select(AdaptationWorkspace).where(
                AdaptationWorkspace.project_id == project.id,
                AdaptationWorkspace.name == payload.name,
                AdaptationWorkspace.status != "archived",
            ))
            if existing:
                return self._workspace_dict(session, existing)
            manifest = self._freeze_source_manifest(session, project.id, payload)
            workspace = AdaptationWorkspace(
                id=str(uuid4()),
                project_id=project.id,
                name=payload.name,
                kind=payload.kind,
                source_type=payload.source_type,
                source_id=payload.source_id,
                source_manifest_json=dumps(manifest),
                canon_revision=manifest["canon"]["revision"],
                canon_checksum=manifest["canon"]["checksum"],
                plan_revision=manifest.get("plan", {}).get("revision"),
                plan_checksum=manifest.get("plan", {}).get("checksum"),
                commit_manifest_json=dumps(manifest.get("commits", [])),
                target_word_count=payload.target_word_count,
                target_chapter_count=payload.target_chapter_count,
                target_episode_count=payload.target_episode_count,
                unit_duration_seconds=payload.unit_duration_seconds,
                audience=payload.audience,
                platform_constraints_json=dumps(payload.platform_constraints),
                status="draft",
                revision=1,
                created_at=now,
                updated_at=now,
            )
            session.add(workspace)
            session.add(self.service._audit("adaptation_workspace.created", "adaptation_workspace", workspace.id, {"kind": workspace.kind}, "system"))
            session.flush()
            return self._workspace_dict(session, workspace)

    def list_workspaces(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            rows = session.scalars(select(AdaptationWorkspace).where(AdaptationWorkspace.project_id == project.id).order_by(AdaptationWorkspace.created_at.desc())).all()
            return [self._workspace_dict(session, row) for row in rows]

    def get_workspace(self, project_id: str, workspace_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            workspace = self._get_workspace(session, project.id, workspace_id)
            return self._workspace_dict(session, workspace)

    def update_workspace(self, project_id: str, workspace_id: str, payload: AdaptationWorkspaceUpdate) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            workspace = self._get_workspace(session, project.id, workspace_id)
            self._check_workspace_revision(workspace, payload.expected_revision)
            changes = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
            if "platform_constraints" in changes:
                workspace.platform_constraints_json = dumps(changes.pop("platform_constraints") or {})
            for key, value in changes.items():
                setattr(workspace, key, value)
            if payload.status == "locked":
                blocking = self._open_blocking_findings(session, workspace.id)
                if blocking:
                    raise StoryError(409, "ADAPTATION_FINDINGS_BLOCKING", "Open adaptation findings block locking.", {"findingCount": len(blocking)})
                workspace.locked_at = workspace.locked_at or _now()
            workspace.revision += 1
            workspace.updated_at = _now()
            session.flush()
            return self._workspace_dict(session, workspace)

    def readiness(self, project_id: str, workspace_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        checks: list[dict[str, Any]] = []
        with self.service.db.project(project.id, project.folder_path) as session:
            workspace = self._get_workspace(session, project.id, workspace_id)
            current = self._current_manifest_for_workspace(session, workspace)
            drift = stable_digest(current) != stable_digest(loads(workspace.source_manifest_json) or {})
            canon_locked = current["canon"].get("status") == "locked"
            strategy_ready = True
            if workspace.kind == "short_drama" and workspace.source_type == "short_story_strategy":
                strategy = session.get(ShortStoryStrategy, workspace.source_id)
                strategy_ready = bool(strategy and strategy.project_id == project.id and strategy.status == "active")
            blocking = self._open_blocking_findings(session, workspace.id)
        checks.append({"code": "ADAPTATION_STANDARD_PROJECT_REQUIRED", "status": "ready" if project.project_kind == "standard" else "blocked", "title": "Standard project", "detail": "Workspace belongs to a standard project."})
        checks.append({"code": "ADAPTATION_CANON_LOCKED", "status": "ready" if canon_locked else "blocked", "title": "Canon locked", "detail": "Canon is locked." if canon_locked else "Lock Canon before adaptation."})
        checks.append({"code": "ADAPTATION_SOURCE_DRIFT", "status": "blocked" if drift else "ready", "title": "Source manifest", "detail": "Source has drifted." if drift else "Source manifest is unchanged."})
        checks.append({"code": "ADAPTATION_STRATEGY_READY", "status": "ready" if strategy_ready else "blocked", "title": "Source strategy", "detail": "Strategy source is usable." if strategy_ready else "Short drama source strategy is unavailable."})
        checks.append({"code": "ADAPTATION_FINDINGS_CLEAR", "status": "ready" if not blocking else "blocked", "title": "Blocking findings", "detail": "No blocking findings." if not blocking else f"{len(blocking)} blocking findings are open."})
        return {
            "projectId": project.id,
            "workspaceId": workspace_id,
            "ready": not any(item["status"] == "blocked" for item in checks),
            "checks": checks,
            "sourceManifest": current,
            "updatedAt": _now(),
        }

    # ------------------------------------------------------------------
    # Proposals
    # ------------------------------------------------------------------
    def create_short_story_proposal(self, project_id: str, workspace_id: str, payload: ShortStoryProposalCreate, request_id: str) -> dict[str, Any]:
        return self._create_model_proposal(
            project_id,
            workspace_id,
            payload.expected_workspace_revision,
            payload.idempotency_key,
            "short_story_strategy",
            "short_story_architect",
            request_id,
            {"instructions": payload.instructions},
        )

    def create_drama_outline_proposal(self, project_id: str, workspace_id: str, payload: DramaOutlineProposalCreate, request_id: str) -> dict[str, Any]:
        extra = {"instructions": payload.instructions, "targetEpisodeCount": payload.target_episode_count}
        return self._create_model_proposal(
            project_id,
            workspace_id,
            payload.expected_workspace_revision,
            payload.idempotency_key,
            "drama_outline",
            "drama_adapter",
            request_id,
            extra,
        )

    def create_script_proposal(self, project_id: str, workspace_id: str, episode_id: str, payload: ScriptProposalCreate, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            workspace = self._get_workspace(session, project.id, workspace_id)
            self._check_workspace_revision(workspace, payload.expected_workspace_revision)
            episode = self._get_episode(session, project.id, workspace.id, episode_id)
            snapshot = self._proposal_snapshot(session, workspace, {"episode": self._episode_dict(session, episode, include_details=True), "instructions": payload.instructions})
        proposal = self._create_model_proposal(
            project_id,
            workspace_id,
            payload.expected_workspace_revision,
            payload.idempotency_key,
            "script",
            "script_writer",
            request_id,
            {"episodeId": episode_id, "instructions": payload.instructions, "snapshot": snapshot},
            materialize=False,
        )
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = self._get_proposal(session, proposal["id"])
            workspace = self._get_workspace(session, project.id, row.workspace_id)
            episode = self._get_episode(session, project.id, workspace.id, episode_id)
            output = loads(row.structured_output_json) or {}
            self._validate_script_output(session, workspace, row, episode, output)
            version = self._create_script_version(session, workspace, episode, row, output)
            row.status = "applied"
            row.applied_at = _now()
            row.revision += 1
            row.updated_at = _now()
            session.flush()
            result = self._proposal_dict(row)
            result["scriptVersionId"] = version.id
            return result

    def apply_proposal(self, proposal_id: str, payload: AdaptationProposalAction, request_id: str) -> dict[str, Any]:
        with self._project_for_proposal(proposal_id) as context:
            project, session = context
            proposal = self._get_proposal(session, proposal_id)
            self._check_proposal_revision(proposal, payload.expected_revision)
            if proposal.status != "pending":
                raise StoryError(409, "ADAPTATION_PROPOSAL_NOT_PENDING", "Only pending adaptation proposals can be applied.")
            workspace = self._get_workspace(session, project.id, proposal.workspace_id)
            self._ensure_workspace_source_not_drifted(session, workspace)
            blocking = self._open_blocking_findings(session, workspace.id, proposal_id=proposal.id)
            if blocking:
                raise StoryError(409, "ADAPTATION_FINDINGS_BLOCKING", "Open findings block proposal application.", {"findingCount": len(blocking)})
            output = loads(proposal.structured_output_json) or {}
            if proposal.proposal_kind == "short_story_strategy":
                self._apply_short_story_strategy(session, workspace, output)
                workspace.status = "ready"
            elif proposal.proposal_kind == "drama_outline":
                self._apply_drama_outline(session, workspace, proposal, output)
                workspace.status = "ready"
            else:
                raise StoryError(422, "ADAPTATION_PROPOSAL_KIND_UNSUPPORTED", "Unsupported adaptation proposal kind.")
            proposal.status = "applied"
            proposal.applied_at = _now()
            proposal.revision += 1
            proposal.updated_at = _now()
            workspace.revision += 1
            workspace.updated_at = _now()
            session.add(self.service._audit("adaptation_proposal.applied", "adaptation_proposal", proposal.id, {"requestId": request_id}, request_id))
            session.flush()
            return self._proposal_dict(proposal)

    def reject_proposal(self, proposal_id: str, payload: AdaptationProposalAction, request_id: str) -> dict[str, Any]:
        with self._project_for_proposal(proposal_id) as context:
            _project, session = context
            proposal = self._get_proposal(session, proposal_id)
            self._check_proposal_revision(proposal, payload.expected_revision)
            if proposal.status not in {"pending", "failed", "interrupted"}:
                raise StoryError(409, "ADAPTATION_PROPOSAL_CLOSED", "Proposal is already closed.")
            proposal.status = "rejected"
            proposal.rejected_at = _now()
            proposal.revision += 1
            proposal.updated_at = _now()
            session.add(self.service._audit("adaptation_proposal.rejected", "adaptation_proposal", proposal.id, {"requestId": request_id}, request_id))
            session.flush()
            return self._proposal_dict(proposal)

    # ------------------------------------------------------------------
    # Episodes, scripts, findings
    # ------------------------------------------------------------------
    def list_episodes(self, project_id: str, workspace_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            workspace = self._get_workspace(session, project.id, workspace_id)
            episodes = session.scalars(select(DramaEpisode).where(DramaEpisode.workspace_id == workspace.id).order_by(DramaEpisode.episode_number)).all()
            return [self._episode_dict(session, episode, include_details=True) for episode in episodes]

    def approve_script_version(self, project_id: str, workspace_id: str, version_id: str, payload: ScriptVersionApprove, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            workspace = self._get_workspace(session, project.id, workspace_id)
            version = session.get(DramaScriptVersion, version_id)
            if not version or version.project_id != project.id or version.workspace_id != workspace.id:
                raise StoryError(404, "DRAMA_SCRIPT_VERSION_NOT_FOUND", "Drama script version not found.")
            if version.revision != payload.expected_revision:
                raise StoryError(409, "DRAMA_SCRIPT_REVISION_CONFLICT", "Script version revision conflict.", {"currentRevision": version.revision})
            blocking = self._open_blocking_findings(session, workspace.id, episode_id=version.episode_id)
            if blocking:
                raise StoryError(409, "ADAPTATION_FINDINGS_BLOCKING", "Open findings block script approval.", {"findingCount": len(blocking)})
            current = session.scalar(select(DramaScriptVersion).where(
                DramaScriptVersion.episode_id == version.episode_id,
                DramaScriptVersion.status == "approved",
                DramaScriptVersion.is_current.is_(True),
            ))
            if current and current.id != version.id:
                self._add_finding(session, workspace, "DRAMA_APPROVAL_CONFLICT", "blocker", {"currentVersionId": current.id, "candidateVersionId": version.id}, "Resolve the current approved script before approving another version.", episode_id=version.episode_id)
                raise StoryError(409, "DRAMA_APPROVAL_CONFLICT", "Episode already has a current approved script.", {"currentVersionId": current.id})
            version.status = "approved"
            version.kind = "approved"
            version.is_current = True
            version.approved_at = _now()
            version.revision += 1
            version.updated_at = _now()
            episode = session.get(DramaEpisode, version.episode_id)
            if episode:
                episode.status = "approved"
                episode.revision += 1
                episode.updated_at = _now()
            session.add(self.service._audit("drama_script_version.approved", "drama_script_version", version.id, {"requestId": request_id}, request_id))
            session.flush()
            return self._script_dict(version)

    def list_findings(self, project_id: str, workspace_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            workspace = self._get_workspace(session, project.id, workspace_id)
            rows = session.scalars(select(AdaptationFinding).where(AdaptationFinding.workspace_id == workspace.id).order_by(AdaptationFinding.created_at.asc())).all()
            return [self._finding_dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Restore repair
    # ------------------------------------------------------------------
    def repair_restored_metadata(self, project_id: str, folder_path: str, source_project_id: str) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            for workspace in session.scalars(select(AdaptationWorkspace)).all():
                workspace.project_id = project_id
                workspace.source_manifest_json = dumps(remap_json_identifier(safe_json_loads(workspace.source_manifest_json, {}), source_project_id, project_id))
                workspace.commit_manifest_json = dumps(remap_json_identifier(safe_json_loads(workspace.commit_manifest_json, []), source_project_id, project_id))
                if workspace.status == "analyzing":
                    workspace.status = "ready"
                    workspace.diagnostic_json = dumps({"recovered": "backup_restore"})
                    workspace.revision += 1
            for strategy in session.scalars(select(ShortStoryStrategy)).all():
                strategy.project_id = project_id
                strategy.chapter_budget_json = dumps(remap_json_identifier(safe_json_loads(strategy.chapter_budget_json, []), source_project_id, project_id))
                strategy.foreshadow_plan_json = dumps(remap_json_identifier(safe_json_loads(strategy.foreshadow_plan_json, {}), source_project_id, project_id))
                strategy.checksum = self._strategy_checksum(strategy)
            for proposal in session.scalars(select(AdaptationProposal)).all():
                proposal.project_id = project_id
                proposal.input_snapshot_json = dumps(remap_json_identifier(safe_json_loads(proposal.input_snapshot_json, {}), source_project_id, project_id))
                proposal.structured_output_json = dumps(remap_json_identifier(safe_json_loads(proposal.structured_output_json, {}), source_project_id, project_id))
                proposal.diff_json = dumps(remap_json_identifier(safe_json_loads(proposal.diff_json, {}), source_project_id, project_id))
                proposal.impact_scope_json = dumps(remap_json_identifier(safe_json_loads(proposal.impact_scope_json, []), source_project_id, project_id))
                proposal.canon_deviations_json = dumps(remap_json_identifier(safe_json_loads(proposal.canon_deviations_json, []), source_project_id, project_id))
                if proposal.status == "generating":
                    proposal.status = "interrupted"
                    proposal.error_code = "backup_restore"
            for episode in session.scalars(select(DramaEpisode)).all():
                episode.project_id = project_id
                episode.source_refs_json = dumps(remap_json_identifier(safe_json_loads(episode.source_refs_json, []), source_project_id, project_id))
                episode.checksum = self._episode_checksum(episode)
            for scene in session.scalars(select(DramaScene)).all():
                scene.project_id = project_id
                scene.source_evidence_json = dumps(remap_json_identifier(safe_json_loads(scene.source_evidence_json, []), source_project_id, project_id))
                scene.canon_refs_json = dumps(remap_json_identifier(safe_json_loads(scene.canon_refs_json, []), source_project_id, project_id))
                scene.checksum = self._scene_checksum(scene)
            for version in session.scalars(select(DramaScriptVersion)).all():
                version.project_id = project_id
                version.structured_dialogue_json = dumps(remap_json_identifier(safe_json_loads(version.structured_dialogue_json, []), source_project_id, project_id))
                version.checksum = self._script_checksum(version)
            for finding in session.scalars(select(AdaptationFinding)).all():
                finding.project_id = project_id
                evidence = remap_json_identifier(safe_json_loads(finding.evidence_json, {}), source_project_id, project_id)
                finding.evidence_json = dumps(evidence)
                finding.fingerprint = stable_digest({"workspaceId": finding.workspace_id, "rule": finding.rule_code, "evidence": evidence, "episodeId": finding.episode_id, "sceneId": finding.scene_id})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _create_model_proposal(
        self,
        project_id: str,
        workspace_id: str,
        expected_workspace_revision: int,
        idempotency_key: str | None,
        proposal_kind: str,
        role: str,
        request_id: str,
        extra: dict[str, Any],
        *,
        materialize: bool = True,
    ) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        now = _now()
        with self.service.db.project_write(project.id, project.folder_path) as session:
            workspace = self._get_workspace(session, project.id, workspace_id)
            if idempotency_key:
                existing = session.scalar(select(AdaptationProposal).where(AdaptationProposal.workspace_id == workspace.id, AdaptationProposal.idempotency_key == idempotency_key))
                if existing:
                    return self._proposal_dict(existing)
            self._check_workspace_revision(workspace, expected_workspace_revision)
            self._ensure_workspace_source_not_drifted(session, workspace)
            snapshot = self._proposal_snapshot(session, workspace, extra)
            proposal = AdaptationProposal(
                id=str(uuid4()),
                project_id=project.id,
                workspace_id=workspace.id,
                proposal_kind=proposal_kind,
                idempotency_key=idempotency_key,
                input_snapshot_json=dumps(snapshot),
                status="generating",
                revision=1,
                created_at=now,
                updated_at=now,
            )
            session.add(proposal)
            workspace.status = "analyzing"
            workspace.revision += 1
            workspace.updated_at = now
            session.flush()
            proposal_id = proposal.id
        try:
            output, model_run_id = self._model_json_with_repair(project, role, proposal_kind, snapshot, request_id)
        except StoryError as exc:
            with self.service.db.project_write(project.id, project.folder_path) as session:
                proposal = self._get_proposal(session, proposal_id)
                proposal.status = "failed"
                proposal.error_code = exc.code
                proposal.error_message = exc.message
                proposal.revision += 1
                proposal.updated_at = _now()
                workspace = self._get_workspace(session, project.id, proposal.workspace_id)
                workspace.status = "ready"
                workspace.revision += 1
                workspace.updated_at = _now()
                return self._proposal_dict(proposal)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            proposal = self._get_proposal(session, proposal_id)
            workspace = self._get_workspace(session, project.id, proposal.workspace_id)
            self._ensure_workspace_source_not_drifted(session, workspace)
            normalized = self._normalize_proposal_output(proposal_kind, output)
            proposal.structured_output_json = dumps(normalized)
            proposal.diff_json = dumps(self._proposal_diff(proposal_kind, normalized))
            proposal.impact_scope_json = dumps(normalized.get("impactScope", []))
            proposal.canon_deviations_json = dumps(normalized.get("canonDeviations", []))
            proposal.model_run_id = model_run_id
            proposal.status = "pending"
            proposal.revision += 1
            proposal.updated_at = _now()
            workspace.status = "ready"
            workspace.revision += 1
            workspace.updated_at = _now()
            self._validate_proposal(session, workspace, proposal, normalized)
            session.flush()
            result = self._proposal_dict(proposal)
        return result if materialize else result

    def _model_json_with_repair(self, project: Any, role: str, proposal_kind: str, snapshot: dict[str, Any], request_id: str) -> tuple[dict[str, Any], str | None]:
        messages = [
            {"role": "system", "content": f"You are {role}. Return exactly one JSON object for {proposal_kind}; no markdown."},
            {"role": "user", "content": dumps(snapshot)},
        ]
        try:
            text, run_id = self._complete_role(project, role, messages, request_id, response_json=True, run_role=f"{role}:{proposal_kind}")
            return _json_object(text), run_id
        except (ValueError, json.JSONDecodeError):
            repair_messages = [
                {"role": "system", "content": "Repair the previous output into one valid JSON object only."},
                {"role": "user", "content": dumps({"proposalKind": proposal_kind, "snapshot": snapshot})},
            ]
            text, run_id = self._complete_role(project, role, repair_messages, request_id, response_json=True, run_role=f"{role}:{proposal_kind}:repair")
            try:
                return _json_object(text), run_id
            except (ValueError, json.JSONDecodeError) as exc:
                raise StoryError(422, "ADAPTATION_MODEL_JSON_INVALID", "Model response was not valid JSON after one repair attempt.") from exc

    def _complete_role(self, project: Any, role: str, messages: list[dict[str, str]], request_id: str, *, response_json: bool = False, run_role: str | None = None) -> tuple[str, str | None]:
        return self.service.phase8._complete_role(project, role, messages, request_id, response_json=response_json, run_role=run_role)

    def _validate_proposal(self, session: Session, workspace: AdaptationWorkspace, proposal: AdaptationProposal, output: dict[str, Any]) -> None:
        if proposal.proposal_kind == "short_story_strategy":
            self._validate_short_story_strategy(session, workspace, proposal, output)
        elif proposal.proposal_kind == "drama_outline":
            self._validate_drama_outline(session, workspace, proposal, output)
        elif proposal.proposal_kind == "script":
            episode_id = output.get("episodeId")
            episode = self._get_episode(session, workspace.project_id, workspace.id, episode_id) if isinstance(episode_id, str) else None
            if episode:
                self._validate_script_output(session, workspace, proposal, episode, output)

    def _validate_short_story_strategy(self, session: Session, workspace: AdaptationWorkspace, proposal: AdaptationProposal, output: dict[str, Any]) -> None:
        if not output.get("openingHook"):
            self._add_finding(session, workspace, "DRAMA_OPENING_HOOK_MISSING", "error", {"field": "openingHook"}, "Add an opening hook in chapter 1 or 2.", proposal_id=proposal.id)
        chapters = output.get("chapterBudget", [])
        if not isinstance(chapters, list) or not chapters:
            self._add_finding(session, workspace, "SHORTFORM_EVENT_BUDGET_OVERFLOW", "error", {"field": "chapterBudget"}, "Provide a chapter budget for the short story.", proposal_id=proposal.id)
            return
        target_chapters = workspace.target_chapter_count or output.get("targetChapterCount") or len(chapters)
        if int(target_chapters) > 30:
            self._add_finding(session, workspace, "SHORTFORM_EVENT_BUDGET_OVERFLOW", "blocker", {"targetChapterCount": target_chapters}, "Short story strategy must stay within 30 chapters.", proposal_id=proposal.id)
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            events = chapter.get("majorEvents", chapter.get("events", []))
            max_events = int(chapter.get("maxMajorEvents", 3) or 3)
            if isinstance(events, list) and len(events) > max_events:
                self._add_finding(session, workspace, "SHORTFORM_EVENT_BUDGET_OVERFLOW", "error", {"chapter": chapter.get("chapterNumber"), "eventCount": len(events), "maxEvents": max_events}, "Reduce or split major events in this chapter.", proposal_id=proposal.id)
        foreshadow = output.get("foreshadowPlan", {})
        if isinstance(foreshadow, dict):
            retained = set(foreshadow.get("retain", []) or [])
            resolved = set(foreshadow.get("resolved", []) or [])
            missing = sorted(retained - resolved)
            if missing:
                self._add_finding(session, workspace, "SHORTFORM_FORESHADOW_DROPPED", "error", {"missing": missing}, "Resolve retained foreshadows in the ending plan.", proposal_id=proposal.id)
        for merge in output.get("characterMergePlan", []) or []:
            if isinstance(merge, dict) and (not merge.get("from") or not merge.get("to") or not merge.get("reason")):
                self._add_finding(session, workspace, "ADAPTATION_CANON_DEVIATION_UNDECLARED", "warning", {"merge": merge}, "Character merges need source, target, and causal responsibility.", proposal_id=proposal.id)
        forbidden = output.get("forbiddenReveals", []) or []
        ending = str(output.get("ending", ""))
        early = [item for item in forbidden if isinstance(item, str) and item and item in ending]
        if early:
            self._add_finding(session, workspace, "ADAPTATION_CANON_DEVIATION_UNDECLARED", "error", {"forbiddenRevealsInEnding": early}, "Move forbidden reveals outside this short story strategy.", proposal_id=proposal.id)

    def _validate_drama_outline(self, session: Session, workspace: AdaptationWorkspace, proposal: AdaptationProposal, output: dict[str, Any]) -> None:
        episodes = output.get("episodes", [])
        if len(episodes) not in {6, 12, 24}:
            self._add_finding(session, workspace, "DRAMA_EPISODE_DURATION_OUT_OF_RANGE", "blocker", {"episodeCount": len(episodes)}, "Drama outline must contain 6, 12, or 24 episodes.", proposal_id=proposal.id)
        expected = list(range(1, len(episodes) + 1))
        actual = [item.get("episodeNumber") for item in episodes if isinstance(item, dict)]
        if actual != expected:
            self._add_finding(session, workspace, "DRAMA_EPISODE_DURATION_OUT_OF_RANGE", "error", {"episodeNumbers": actual}, "Episode numbers must be continuous and ordered.", proposal_id=proposal.id)
        for item in episodes:
            if not isinstance(item, dict):
                continue
            duration = int(item.get("targetDurationSeconds", workspace.unit_duration_seconds or 90) or 0)
            if duration < 30 or duration > 1800:
                self._add_finding(session, workspace, "DRAMA_EPISODE_DURATION_OUT_OF_RANGE", "error", {"episode": item.get("episodeNumber"), "duration": duration}, "Episode duration is outside allowed range.", proposal_id=proposal.id)
            if not item.get("openingHook"):
                self._add_finding(session, workspace, "DRAMA_OPENING_HOOK_MISSING", "error", {"episode": item.get("episodeNumber")}, "Each episode needs an opening hook.", proposal_id=proposal.id)
            if not item.get("cliffhanger"):
                self._add_finding(session, workspace, "DRAMA_ENDING_CLIFFHANGER_MISSING", "error", {"episode": item.get("episodeNumber")}, "Each episode needs an ending cliffhanger.", proposal_id=proposal.id)
            total_scene_duration = sum(int(scene.get("estimatedDurationSeconds", 0) or 0) for scene in item.get("scenes", []) if isinstance(scene, dict))
            if total_scene_duration > duration:
                self._add_finding(session, workspace, "DRAMA_SCENE_DURATION_OVERFLOW", "error", {"episode": item.get("episodeNumber"), "sceneDuration": total_scene_duration, "episodeDuration": duration}, "Scene durations exceed episode duration.", proposal_id=proposal.id)

    def _validate_script_output(self, session: Session, workspace: AdaptationWorkspace, proposal: AdaptationProposal, episode: DramaEpisode, output: dict[str, Any]) -> None:
        dialogue = output.get("structuredDialogue", [])
        if not isinstance(dialogue, list) or not dialogue:
            self._add_finding(session, workspace, "DRAMA_DIALOGUE_WITHOUT_SOURCE_OR_PURPOSE", "error", {"episodeId": episode.id}, "Script needs structured dialogue with source and purpose.", proposal_id=proposal.id, episode_id=episode.id)
            return
        for line in dialogue:
            if isinstance(line, dict) and (not line.get("source") or not line.get("purpose")):
                self._add_finding(session, workspace, "DRAMA_DIALOGUE_WITHOUT_SOURCE_OR_PURPOSE", "error", {"line": line}, "Each dialogue line needs source evidence and dramatic purpose.", proposal_id=proposal.id, episode_id=episode.id)
        duration = int(output.get("estimatedDurationSeconds", episode.target_duration_seconds) or 0)
        if duration > episode.target_duration_seconds:
            self._add_finding(session, workspace, "DRAMA_EPISODE_DURATION_OUT_OF_RANGE", "error", {"episodeId": episode.id, "scriptDuration": duration, "episodeDuration": episode.target_duration_seconds}, "Script duration exceeds episode target.", proposal_id=proposal.id, episode_id=episode.id)

    def _apply_short_story_strategy(self, session: Session, workspace: AdaptationWorkspace, output: dict[str, Any]) -> ShortStoryStrategy:
        for old in session.scalars(select(ShortStoryStrategy).where(ShortStoryStrategy.workspace_id == workspace.id, ShortStoryStrategy.status == "active")).all():
            old.status = "superseded"
            old.revision += 1
            old.updated_at = _now()
        strategy = ShortStoryStrategy(
            id=str(uuid4()),
            project_id=workspace.project_id,
            workspace_id=workspace.id,
            core_hook=str(output.get("coreHook", "")),
            opening_hook=str(output.get("openingHook", "")),
            main_conflict=str(output.get("mainConflict", "")),
            emotional_curve_json=dumps(output.get("emotionalCurve", [])),
            ending=str(output.get("ending", "")),
            point_of_view=str(output.get("pointOfView", "")),
            target_word_count=int(output.get("targetWordCount", workspace.target_word_count or 10000)),
            chapter_budget_json=dumps(output.get("chapterBudget", [])),
            character_merge_plan_json=dumps(output.get("characterMergePlan", [])),
            foreshadow_plan_json=dumps(output.get("foreshadowPlan", {})),
            compression_rules_json=dumps(output.get("compressionRules", {})),
            forbidden_reveals_json=dumps(output.get("forbiddenReveals", [])),
            status="active",
            revision=1,
            created_at=_now(),
            updated_at=_now(),
        )
        strategy.checksum = self._strategy_checksum(strategy)
        session.add(strategy)
        return strategy

    def _apply_drama_outline(self, session: Session, workspace: AdaptationWorkspace, proposal: AdaptationProposal, output: dict[str, Any]) -> None:
        for episode_data in output.get("episodes", []) or []:
            if not isinstance(episode_data, dict):
                continue
            episode = DramaEpisode(
                id=str(uuid4()),
                project_id=workspace.project_id,
                workspace_id=workspace.id,
                episode_number=int(episode_data.get("episodeNumber")),
                title=str(episode_data.get("title", "")),
                logline=str(episode_data.get("logline", "")),
                target_duration_seconds=int(episode_data.get("targetDurationSeconds", workspace.unit_duration_seconds or 90)),
                opening_hook=str(episode_data.get("openingHook", "")),
                cliffhanger=str(episode_data.get("cliffhanger", "")),
                source_refs_json=dumps(episode_data.get("sourceRefs", [])),
                status="draft",
                revision=1,
                created_at=_now(),
                updated_at=_now(),
            )
            episode.checksum = self._episode_checksum(episode)
            session.add(episode)
            session.flush()
            for scene_data in episode_data.get("scenes", []) or []:
                if not isinstance(scene_data, dict):
                    continue
                scene = DramaScene(
                    id=str(uuid4()),
                    project_id=workspace.project_id,
                    workspace_id=workspace.id,
                    episode_id=episode.id,
                    scene_number=int(scene_data.get("sceneNumber", 1)),
                    setting_type=str(scene_data.get("settingType", "")),
                    location=str(scene_data.get("location", "")),
                    time_of_day=str(scene_data.get("timeOfDay", "")),
                    characters_json=dumps(scene_data.get("characters", [])),
                    objective=str(scene_data.get("objective", "")),
                    conflict=str(scene_data.get("conflict", "")),
                    turn=str(scene_data.get("turn", "")),
                    visual_action=str(scene_data.get("visualAction", "")),
                    estimated_duration_seconds=int(scene_data.get("estimatedDurationSeconds", 30)),
                    source_evidence_json=dumps(scene_data.get("sourceEvidence", [])),
                    canon_refs_json=dumps(scene_data.get("canonRefs", [])),
                    revision=1,
                    created_at=_now(),
                    updated_at=_now(),
                )
                scene.checksum = self._scene_checksum(scene)
                session.add(scene)

    def _create_script_version(self, session: Session, workspace: AdaptationWorkspace, episode: DramaEpisode, proposal: AdaptationProposal, output: dict[str, Any]) -> DramaScriptVersion:
        current_max = session.scalar(select(DramaScriptVersion.version_number).where(DramaScriptVersion.episode_id == episode.id).order_by(DramaScriptVersion.version_number.desc()).limit(1)) or 0
        version = DramaScriptVersion(
            id=str(uuid4()),
            project_id=workspace.project_id,
            workspace_id=workspace.id,
            episode_id=episode.id,
            version_number=current_max + 1,
            kind="candidate",
            fountain_text=str(output.get("fountainText", "")),
            markdown_text=str(output.get("markdownText", "")),
            structured_dialogue_json=dumps(output.get("structuredDialogue", [])),
            word_count=int(output.get("wordCount", len(str(output.get("markdownText", "")).split()))),
            estimated_duration_seconds=int(output.get("estimatedDurationSeconds", episode.target_duration_seconds)),
            model_run_id=proposal.model_run_id,
            status="candidate",
            is_current=False,
            revision=1,
            created_at=_now(),
            updated_at=_now(),
        )
        version.checksum = self._script_checksum(version)
        session.add(version)
        return version

    def _freeze_source_manifest(self, session: Session, project_id: str, payload: AdaptationWorkspaceCreate) -> dict[str, Any]:
        canon = self._locked_canon(session)
        plan = session.scalar(select(Plan))
        manifest = {
            "projectId": project_id,
            "sourceType": payload.source_type,
            "sourceId": payload.source_id,
            "canon": self._canon_manifest(canon),
            "plan": self._plan_manifest(session, plan) if plan else None,
            "commits": [],
        }
        if payload.source_type == "chapter_range":
            if payload.chapter_start is None or payload.chapter_end is None or payload.chapter_start > payload.chapter_end:
                raise StoryError(422, "ADAPTATION_SOURCE_RANGE_INVALID", "chapterStart and chapterEnd are required for chapter range sources.")
            commits = self._freeze_commit_range(session, project_id, payload.chapter_start, payload.chapter_end)
            manifest["commits"] = commits
        elif payload.source_type == "short_story_strategy":
            if not payload.source_id:
                raise StoryError(422, "ADAPTATION_SOURCE_REQUIRED", "sourceId is required for short story strategy sources.")
            strategy = session.get(ShortStoryStrategy, payload.source_id)
            if not strategy or strategy.project_id != project_id or strategy.status != "active":
                raise StoryError(404, "SHORT_STORY_STRATEGY_NOT_FOUND", "Short story strategy source not found.")
            manifest["strategy"] = {"id": strategy.id, "revision": strategy.revision, "checksum": strategy.checksum, "workspaceId": strategy.workspace_id}
        return manifest

    def _current_manifest_for_workspace(self, session: Session, workspace: AdaptationWorkspace) -> dict[str, Any]:
        payload = AdaptationWorkspaceCreate(
            name=workspace.name,
            kind=workspace.kind,  # type: ignore[arg-type]
            source_type=workspace.source_type,  # type: ignore[arg-type]
            source_id=workspace.source_id,
            target_word_count=workspace.target_word_count,
            target_chapter_count=workspace.target_chapter_count,
            target_episode_count=workspace.target_episode_count if workspace.target_episode_count in {6, 12, 24} else None,  # type: ignore[arg-type]
            unit_duration_seconds=workspace.unit_duration_seconds,
            audience=workspace.audience,
            platform_constraints=loads(workspace.platform_constraints_json) or {},
        )
        frozen = loads(workspace.source_manifest_json) or {}
        commits = frozen.get("commits", [])
        if workspace.source_type == "chapter_range" and commits:
            payload.chapter_start = min(item["chapterNumber"] for item in commits)
            payload.chapter_end = max(item["chapterNumber"] for item in commits)
        return self._freeze_source_manifest(session, workspace.project_id, payload)

    def _proposal_snapshot(self, session: Session, workspace: AdaptationWorkspace, extra: dict[str, Any]) -> dict[str, Any]:
        return {
            "projectId": workspace.project_id,
            "workspaceId": workspace.id,
            "workspaceRevision": workspace.revision,
            "kind": workspace.kind,
            "targetWordCount": workspace.target_word_count,
            "targetChapterCount": workspace.target_chapter_count,
            "targetEpisodeCount": workspace.target_episode_count,
            "unitDurationSeconds": workspace.unit_duration_seconds,
            "sourceManifest": loads(workspace.source_manifest_json) or {},
            **extra,
        }

    def _ensure_workspace_source_not_drifted(self, session: Session, workspace: AdaptationWorkspace) -> None:
        current = self._current_manifest_for_workspace(session, workspace)
        frozen = loads(workspace.source_manifest_json) or {}
        if stable_digest(current) != stable_digest(frozen):
            self._add_finding(session, workspace, "ADAPTATION_SOURCE_DRIFT", "blocker", {"frozen": frozen, "current": current}, "Create a new workspace or regenerate the proposal from the current source.")
            raise StoryError(409, "ADAPTATION_SOURCE_DRIFT", "Adaptation source manifest has drifted.")

    @staticmethod
    def _canon_manifest(canon: CanonDocument) -> dict[str, Any]:
        return {"id": canon.id, "revision": canon.revision, "status": canon.status, "checksum": stable_digest({"revision": canon.revision, "content": canon.content_markdown})}

    def _locked_canon(self, session: Session) -> CanonDocument:
        canon = session.get(CanonDocument, "story-core")
        if not canon or canon.status != "locked":
            raise StoryError(409, "ADAPTATION_CANON_NOT_LOCKED", "Lock Canon before creating an adaptation workspace.")
        return canon

    def _plan_manifest(self, session: Session, plan: Plan) -> dict[str, Any]:
        nodes = session.scalars(select(PlanNode).where(PlanNode.plan_id == plan.id).order_by(PlanNode.target_chapter)).all()
        payload = {
            "id": plan.id,
            "revision": plan.revision,
            "chapterStart": plan.chapter_start,
            "chapterEnd": plan.chapter_end,
            "nodes": [{"id": node.id, "revision": node.revision, "targetChapter": node.target_chapter, "rangeMin": node.range_min, "rangeMax": node.range_max} for node in nodes],
        }
        return {**payload, "checksum": stable_digest(payload)}

    def _freeze_commit_range(self, session: Session, project_id: str, start: int, end: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for chapter in range(start, end + 1):
            commit = session.scalar(select(ChapterCommit).where(
                ChapterCommit.project_id == project_id,
                ChapterCommit.chapter_number == chapter,
                ChapterCommit.is_current.is_(True),
                ChapterCommit.status == "official",
            ))
            if not commit:
                raise StoryError(409, "ADAPTATION_SOURCE_COMMIT_MISSING", "Chapter range must use continuous current official commits.", {"chapterNumber": chapter})
            rows.append({"projectId": project_id, "chapterNumber": chapter, "commitId": commit.id, "revision": commit.revision, "checksum": commit.checksum, "sourceVersionId": commit.source_version_id, "stateSnapshotId": commit.state_snapshot_id})
        return rows

    @staticmethod
    def _normalize_proposal_output(kind: str, output: dict[str, Any]) -> dict[str, Any]:
        if kind == "script":
            return {**output, "episodeId": output.get("episodeId")}
        return output

    @staticmethod
    def _proposal_diff(kind: str, output: dict[str, Any]) -> dict[str, Any]:
        return {"kind": kind, "keys": sorted(output.keys())}

    def _add_finding(
        self,
        session: Session,
        workspace: AdaptationWorkspace,
        rule_code: str,
        severity: str,
        evidence: dict[str, Any],
        suggestion: str,
        *,
        proposal_id: str | None = None,
        episode_id: str | None = None,
        scene_id: str | None = None,
    ) -> None:
        fingerprint = stable_digest({"workspaceId": workspace.id, "rule": rule_code, "evidence": evidence, "episodeId": episode_id, "sceneId": scene_id})
        existing = session.scalar(select(AdaptationFinding).where(AdaptationFinding.workspace_id == workspace.id, AdaptationFinding.fingerprint == fingerprint))
        if existing:
            existing.status = "open"
            existing.updated_at = _now()
            existing.revision += 1
            return
        session.add(AdaptationFinding(
            id=str(uuid4()),
            project_id=workspace.project_id,
            workspace_id=workspace.id,
            proposal_id=proposal_id,
            episode_id=episode_id,
            scene_id=scene_id,
            rule_code=rule_code,
            severity=severity,
            evidence_json=dumps(evidence),
            suggestion=suggestion,
            fingerprint=fingerprint,
            status="open",
            revision=1,
            created_at=_now(),
            updated_at=_now(),
        ))

    def _open_blocking_findings(self, session: Session, workspace_id: str, *, proposal_id: str | None = None, episode_id: str | None = None) -> list[AdaptationFinding]:
        query = select(AdaptationFinding).where(
            AdaptationFinding.workspace_id == workspace_id,
            AdaptationFinding.status == "open",
            AdaptationFinding.severity.in_(OPEN_BLOCKING_SEVERITIES),
        )
        if proposal_id is not None:
            query = query.where(AdaptationFinding.proposal_id == proposal_id)
        if episode_id is not None:
            query = query.where(AdaptationFinding.episode_id == episode_id)
        return list(session.scalars(query).all())

    def _get_workspace(self, session: Session, project_id: str, workspace_id: str) -> AdaptationWorkspace:
        workspace = session.get(AdaptationWorkspace, workspace_id)
        if not workspace or workspace.project_id != project_id:
            raise StoryError(404, "ADAPTATION_WORKSPACE_NOT_FOUND", "Adaptation workspace not found.")
        return workspace

    def _get_proposal(self, session: Session, proposal_id: str) -> AdaptationProposal:
        proposal = session.get(AdaptationProposal, proposal_id)
        if not proposal:
            raise StoryError(404, "ADAPTATION_PROPOSAL_NOT_FOUND", "Adaptation proposal not found.")
        return proposal

    def _get_episode(self, session: Session, project_id: str, workspace_id: str, episode_id: str) -> DramaEpisode:
        episode = session.get(DramaEpisode, episode_id)
        if not episode or episode.project_id != project_id or episode.workspace_id != workspace_id:
            raise StoryError(404, "DRAMA_EPISODE_NOT_FOUND", "Drama episode not found.")
        return episode

    @staticmethod
    def _check_workspace_revision(workspace: AdaptationWorkspace, expected_revision: int) -> None:
        if workspace.revision != expected_revision:
            raise StoryError(409, "ADAPTATION_WORKSPACE_REVISION_CONFLICT", "Workspace revision conflict.", {"currentRevision": workspace.revision})

    @staticmethod
    def _check_proposal_revision(proposal: AdaptationProposal, expected_revision: int) -> None:
        if proposal.revision != expected_revision:
            raise StoryError(409, "ADAPTATION_PROPOSAL_REVISION_CONFLICT", "Proposal revision conflict.", {"currentRevision": proposal.revision})

    def _project_for_proposal(self, proposal_id: str):
        service = self.service

        class _Context:
            def __enter__(inner_self):
                for project in service.list_projects():
                    session = service.db.project_write(project.id, project.folder_path)
                    active = session.__enter__()
                    proposal = active.get(AdaptationProposal, proposal_id)
                    if proposal:
                        if proposal.project_id != project.id:
                            session.__exit__(None, None, None)
                            continue
                        inner_self.session = session
                        inner_self.project = project
                        return project, active
                    session.__exit__(None, None, None)
                raise StoryError(404, "ADAPTATION_PROPOSAL_NOT_FOUND", "Adaptation proposal not found.")

            def __exit__(inner_self, exc_type, exc, tb):
                return inner_self.session.__exit__(exc_type, exc, tb)

        return _Context()

    @staticmethod
    def _strategy_checksum(strategy: ShortStoryStrategy) -> str:
        return stable_digest({
            "workspaceId": strategy.workspace_id,
            "coreHook": strategy.core_hook,
            "openingHook": strategy.opening_hook,
            "mainConflict": strategy.main_conflict,
            "ending": strategy.ending,
            "chapterBudget": safe_json_loads(strategy.chapter_budget_json, []),
            "foreshadowPlan": safe_json_loads(strategy.foreshadow_plan_json, {}),
        })

    @staticmethod
    def _episode_checksum(episode: DramaEpisode) -> str:
        return stable_digest({"workspaceId": episode.workspace_id, "episodeNumber": episode.episode_number, "title": episode.title, "logline": episode.logline, "duration": episode.target_duration_seconds, "openingHook": episode.opening_hook, "cliffhanger": episode.cliffhanger, "sourceRefs": safe_json_loads(episode.source_refs_json, [])})

    @staticmethod
    def _scene_checksum(scene: DramaScene) -> str:
        return stable_digest({"episodeId": scene.episode_id, "sceneNumber": scene.scene_number, "location": scene.location, "characters": safe_json_loads(scene.characters_json, []), "objective": scene.objective, "duration": scene.estimated_duration_seconds})

    @staticmethod
    def _script_checksum(version: DramaScriptVersion) -> str:
        return stable_digest({"episodeId": version.episode_id, "versionNumber": version.version_number, "markdown": version.markdown_text, "dialogue": safe_json_loads(version.structured_dialogue_json, []), "duration": version.estimated_duration_seconds})

    def _workspace_dict(self, session: Session, item: AdaptationWorkspace) -> dict[str, Any]:
        strategy = session.scalar(select(ShortStoryStrategy).where(ShortStoryStrategy.workspace_id == item.id, ShortStoryStrategy.status == "active"))
        return {
            "id": item.id,
            "projectId": item.project_id,
            "name": item.name,
            "kind": item.kind,
            "sourceType": item.source_type,
            "sourceId": item.source_id,
            "sourceManifest": loads(item.source_manifest_json) or {},
            "canonRevision": item.canon_revision,
            "canonChecksum": item.canon_checksum,
            "planRevision": item.plan_revision,
            "planChecksum": item.plan_checksum,
            "commitManifest": loads(item.commit_manifest_json) or [],
            "targetWordCount": item.target_word_count,
            "targetChapterCount": item.target_chapter_count,
            "targetEpisodeCount": item.target_episode_count,
            "unitDurationSeconds": item.unit_duration_seconds,
            "audience": item.audience,
            "platformConstraints": loads(item.platform_constraints_json) or {},
            "status": item.status,
            "diagnostic": loads(item.diagnostic_json) if item.diagnostic_json else None,
            "revision": item.revision,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
            "lockedAt": item.locked_at,
            "strategy": self._strategy_dict(strategy) if strategy else None,
        }

    @staticmethod
    def _strategy_dict(item: ShortStoryStrategy) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "workspaceId": item.workspace_id,
            "coreHook": item.core_hook,
            "openingHook": item.opening_hook,
            "mainConflict": item.main_conflict,
            "emotionalCurve": loads(item.emotional_curve_json) or [],
            "ending": item.ending,
            "pointOfView": item.point_of_view,
            "targetWordCount": item.target_word_count,
            "chapterBudget": loads(item.chapter_budget_json) or [],
            "characterMergePlan": loads(item.character_merge_plan_json) or [],
            "foreshadowPlan": loads(item.foreshadow_plan_json) or {},
            "compressionRules": loads(item.compression_rules_json) or {},
            "forbiddenReveals": loads(item.forbidden_reveals_json) or [],
            "checksum": item.checksum,
            "status": item.status,
            "revision": item.revision,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
        }

    @staticmethod
    def _proposal_dict(item: AdaptationProposal) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "workspaceId": item.workspace_id,
            "proposalKind": item.proposal_kind,
            "idempotencyKey": item.idempotency_key,
            "inputSnapshot": loads(item.input_snapshot_json) or {},
            "structuredOutput": loads(item.structured_output_json) or {},
            "diff": loads(item.diff_json) or {},
            "impactScope": loads(item.impact_scope_json) or [],
            "canonDeviations": loads(item.canon_deviations_json) or [],
            "modelRunId": item.model_run_id,
            "status": item.status,
            "errorCode": item.error_code,
            "errorMessage": item.error_message,
            "revision": item.revision,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
            "appliedAt": item.applied_at,
            "rejectedAt": item.rejected_at,
        }

    def _episode_dict(self, session: Session, item: DramaEpisode, *, include_details: bool) -> dict[str, Any]:
        result = {
            "id": item.id,
            "projectId": item.project_id,
            "workspaceId": item.workspace_id,
            "episodeNumber": item.episode_number,
            "title": item.title,
            "logline": item.logline,
            "targetDurationSeconds": item.target_duration_seconds,
            "openingHook": item.opening_hook,
            "cliffhanger": item.cliffhanger,
            "sourceRefs": loads(item.source_refs_json) or [],
            "status": item.status,
            "checksum": item.checksum,
            "revision": item.revision,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
            "scenes": [],
            "scriptVersions": [],
        }
        if include_details:
            result["scenes"] = [self._scene_dict(row) for row in session.scalars(select(DramaScene).where(DramaScene.episode_id == item.id).order_by(DramaScene.scene_number)).all()]
            result["scriptVersions"] = [self._script_dict(row) for row in session.scalars(select(DramaScriptVersion).where(DramaScriptVersion.episode_id == item.id).order_by(DramaScriptVersion.version_number)).all()]
        return result

    @staticmethod
    def _scene_dict(item: DramaScene) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "workspaceId": item.workspace_id,
            "episodeId": item.episode_id,
            "sceneNumber": item.scene_number,
            "settingType": item.setting_type,
            "location": item.location,
            "timeOfDay": item.time_of_day,
            "characters": loads(item.characters_json) or [],
            "objective": item.objective,
            "conflict": item.conflict,
            "turn": item.turn,
            "visualAction": item.visual_action,
            "estimatedDurationSeconds": item.estimated_duration_seconds,
            "sourceEvidence": loads(item.source_evidence_json) or [],
            "canonRefs": loads(item.canon_refs_json) or [],
            "checksum": item.checksum,
            "revision": item.revision,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
        }

    @staticmethod
    def _script_dict(item: DramaScriptVersion) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "workspaceId": item.workspace_id,
            "episodeId": item.episode_id,
            "versionNumber": item.version_number,
            "parentVersionId": item.parent_version_id,
            "kind": item.kind,
            "fountainText": item.fountain_text,
            "markdownText": item.markdown_text,
            "structuredDialogue": loads(item.structured_dialogue_json) or [],
            "wordCount": item.word_count,
            "estimatedDurationSeconds": item.estimated_duration_seconds,
            "modelRunId": item.model_run_id,
            "checksum": item.checksum,
            "status": item.status,
            "isCurrent": item.is_current,
            "revision": item.revision,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
            "approvedAt": item.approved_at,
        }

    @staticmethod
    def _finding_dict(item: AdaptationFinding) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "workspaceId": item.workspace_id,
            "proposalId": item.proposal_id,
            "episodeId": item.episode_id,
            "sceneId": item.scene_id,
            "ruleCode": item.rule_code,
            "severity": item.severity,
            "evidence": loads(item.evidence_json) or {},
            "suggestion": item.suggestion,
            "fingerprint": item.fingerprint,
            "status": item.status,
            "revision": item.revision,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
        }
