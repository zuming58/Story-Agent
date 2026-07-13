# Story Agent 第八阶段验收交接

更新时间：2026-07-13
当前分支：`agent/trial-ready-workbench`
开发基线：`7a808b4`
状态：当前电脑实施与自审计完成，等待用户 UI 和单章流程确认；未合并 `main`

## 1. 本阶段已完成

- Canon 设定库正式页面：Markdown 核心、AI 结构化、实体/别名/属性/关系/规则、缺口诊断、二次锁定和差异变更申请。
- 统一试写就绪检查：模型角色、密钥、连接测试、价格、Canon、规划范围、章节和托管冲突。
- 自动托管正式页面：默认关闭的每日策略、1/3/5 章手动试写、运行队列、Token/费用、诊断、取消、恢复、补跑和日报。
- 作品首页六步试写引导；Canon 和自动托管页继续使用固定 AI 控制台。
- Provider 连接测试状态持久化；手动 run 冻结 1/3/5 章范围，保持幂等和原 Phase 5/7 事务边界。

详细实施与验收节奏见 [PHASE-8-TRIAL-READY-WORKBENCH.md](docs/plans/PHASE-8-TRIAL-READY-WORKBENCH.md)，审计修复见 [PHASE-8-AUDIT.md](docs/plans/PHASE-8-AUDIT.md)。

## 2. 迁移、公共类型与 API

- Catalog migration：`0005_provider_connection_status`
- Project migration：`0010_trial_ready_workbench`
- 新类型：`TrialReadiness`、`TrialReadinessCheck`、`TrialReadinessStatus`、`TrialRunSize`
- `GET /api/v1/projects/{project_id}/trial-readiness?chapterCount=1|3|5`
- `POST /api/v1/projects/{project_id}/automation/runs` 可选 `chapterCount: 1|3|5`
- 现有 Canon/automation/model API 被 UI 正式接入，业务内容不依赖 `localStorage`。

## 3. 不可破坏的权威关系

- Catalog SQLite 是作品目录、Provider、模型与角色绑定权威；API Key 只在 Windows Credential Manager。
- 每个作品的 `story.db` 是 Canon、规划、候选稿、质量、正式提交和自动化运行权威。
- `ChapterCommit.is_current = true` 才是正式正文；候选稿不能直接修改正式 Canon 或故事状态。
- 模型调用期间不得持有 SQLite 长写事务；自动化正式提交仍必须通过租约 fencing、质量门和 Phase 5 原子 commit。

## 4. 当前验收任务

1. 在本地页面检查 `/canon`、`/overview` 和 `/automation` 的质感、信息层级和 1280/1440 操作性。
2. 在“模型与费用设置”配置真实 Provider、API Key、价格和六个自动写作角色，点击连接测试。
3. 新建独立试验作品，完成 Canon 并锁定，确认规划覆盖第 1 章。
4. 先写 1 章，核对契约、候选正文、质量报告和正式提交；再扩展 3—5 章。
5. 用户确认 UI 与单章流程后才合并 `main`。

## 5. 已知限制

- 真实模型单章冒烟不在自动测试中运行；需用户本地密钥配置完成后手动触发，不提交密钥、数据库或正文。
- 构建仅保留既有 Vite chunk-size warning。
- 第九阶段导出方案已顺延到 [PHASE-9-EXPORT-PUBLISHING.md](docs/plans/PHASE-9-EXPORT-PUBLISHING.md)。
- 本阶段未实施外部发布、短篇、短剧或 EXE。

## 6. 最终验证结果

- `npm run test`：API `101 passed`；Web `3 files / 11 tests passed`。
- `npm run build`：通过，仅保留既有 Vite chunk-size warning。
- `npm run test:e2e`：Playwright `14 passed`，覆盖 1440×1024 与 1280×800。
- Phase 8 专项：`6 passed`，覆盖就绪阻断、Provider 状态、1/3/5 章、幂等、DB 约束与跨作品隔离。
- Python `compileall`：通过。
- 自动测试未调用真实 DeepSeek API，未消耗用户额度。

## 7. 开发与测试命令

```powershell
npm --prefix apps/web install
uv sync --project apps/api --dev
npm run dev
npm run build
npm run test
npm run test:e2e
```

## 8. Git 与敏感数据

- GitHub 是代码权威；`.data`、`.e2e-data`、API Key、SQLite、日志、备份 ZIP 和生成正文不进入 Git。
- 不修改或提交 `Story agent/` 与 `openclaw skill/` 两个参考目录。
- 本分支只在用户确认后合并 `main`；没有交给另一台电脑的开发任务。
