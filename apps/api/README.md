# Story Agent API

本地优先的 FastAPI 服务。负责作品目录、每部作品独立 SQLite、规划版本、对话、修改提案、审计和备份恢复。

```powershell
uv sync --dev
uv run uvicorn story_agent_api.main:app --reload --host 127.0.0.1 --port 8765
```

测试：

```powershell
uv run pytest
```
