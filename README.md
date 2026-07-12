# Story Agent

本地优先的小说创作与短剧改编平台。当前版本已完成高保真规划界面与本地数据闭环，重点验证作品隔离、故事规划、固定 AI 控制台、人工编辑与 AI 修改确认。

## 当前实现

- React + TypeScript + Vite 桌面 Web 前端；
- FastAPI、SQLite、SQLAlchemy 与 Alembic 本地服务；
- 作品目录库与每部作品独立数据库；
- 故事规划时间轴、里程碑契约、版本冲突和边界校验；
- 后端模拟故事 Agent、字段级差异、接受、拒绝、撤销与审计；
- 带 SHA-256 清单的项目 ZIP 备份和安全恢复；
- 1440×1024 与 1280×800 桌面适配；
- Vitest 单元测试与 Playwright 核心流程。

## 本地运行

项目运行时固定为 Node.js 24，并需要 Python 3.13 与 `uv`。

```powershell
npm --prefix apps/web install
uv sync --project apps/api --dev
npm run dev
```

常用验证命令：

```powershell
npm run build
npm run test
npm run test:e2e
```

## 目录

- `apps/web`：React 桌面 Web 前端；
- `apps/api`：FastAPI 本地数据服务；
- `docs/prd`：产品需求文档；
- `docs/ui`：选定 UI 基线和视觉稿。
- `.data`：本地作品数据（自动创建，禁止提交 Git）。

API 默认监听 `127.0.0.1:8765`；本机 `8000` 端口被 Incredibuild 占用，因此前端代理与测试统一使用 `8765`。
