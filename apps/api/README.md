# Story Agent API（预留）

下一轮在此目录建立 FastAPI、SQLAlchemy、Alembic 与 SQLite 服务。

前端已经预定义 `ProjectSummary`、`StoryPlan`、`PlanNode`、`PlanningValidation`、`AgentSession`、`AgentMessage` 和 `ChangeProposal`，后端应保持同一业务语义，并首先实现：

- `GET /api/v1/projects/{project_id}/plan`
- `PUT /api/v1/projects/{project_id}/plan/nodes/{node_id}`
- `POST /api/v1/agent/sessions`
- `POST /api/v1/agent/sessions/{session_id}/messages`
- `POST /api/v1/change-proposals/{proposal_id}/apply`
- `POST /api/v1/change-proposals/{proposal_id}/reject`
