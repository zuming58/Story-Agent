# Story Agent

本地优先的小说创作与短剧改编平台。当前版本已完成规划、模型、Canon/记忆、单章生产与质量复核闭环，并提供高保真章节写作工作台。

## 当前实现

- React + TypeScript + Vite 桌面 Web 前端；
- FastAPI、SQLite、SQLAlchemy 与 Alembic 本地服务；
- 作品目录库与每部作品独立数据库；
- 故事规划时间轴、里程碑契约、版本冲突和边界校验；
- OpenAI 兼容模型、Windows 安全密钥存储、角色模型绑定与流式故事 Agent；
- Canon、精确故事状态、全文/向量检索接口与可追溯上下文编译；
- 章节契约、候选正文、事实抽取、确定性质量门、三角色审稿与两轮修订；
- 章节写作和质量中心支持正文版本、人工编辑、AI 建议、批准与原子提交；
- 规划字段级差异、接受、拒绝、撤销与审计；
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
