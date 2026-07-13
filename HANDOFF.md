# Story Agent 第七阶段交接

更新时间：2026-07-13
分支：`agent/automation-foundation`
阶段基线：`86c849c`
最新提交：待最终提交后填写
当前状态：第七阶段“每日自动托管与可恢复生产队列”后端开发已完成本地实现与 API 全量测试，等待提交、推送后交由 GPT-5.6 完整审计。

## 本阶段完成内容

- 新增每部作品的自动托管策略：启用开关、每日时间、时区、每次章节数、目标字数、最多修订轮次、日费用上限、停止策略和 guarded_auto 审批模式。
- 新增本地 FastAPI 生命周期调度器：启动恢复 interrupted/cancel_requested 自动化运行；每 30 秒检查 due policy；应用关闭时停止调度器。
- 支持 missed 任务：应用启动/检查时发现过去未执行日程只创建单条 `missed` 记录，不自动补跑；用户可通过 catch-up API 创建补跑运行。
- 支持手动立即运行、幂等键、取消、恢复和 missed catch-up。
- 自动化执行严格串行：从 `project.currentChapter + 1` 开始，下一章只在上一章产生 current `ChapterCommit` 后继续；已有 current commit 的章节会跳过为 committed。
- 新增项目级 SQLite 租约 `automation_leases`，同一作品同一时间只允许一个自动写作运行。
- 自动化编排只调用 Phase 5 公开接口：derive/lock contract、create/retry/run job、revise、guarded_auto approve、commit；不绕过章节契约、候选状态、质量门、revision 和正式提交事务。
- 模型调用仍由 Phase 5 在写事务外完成；自动化服务只在短事务中更新 run/item/lease。
- 新增 token 与估算费用汇总：按新增 `ModelRun` 的 prompt/completion tokens 和 catalog 模型价格计算 run/item 成本。
- 日费用上限：设置 `dailyCostLimit` 后，自动化要求相关角色模型均配置 input/output 百万 token 价格；缺失时返回 `AUTOMATION_MODEL_PRICE_REQUIRED`；预算耗尽时停止后续章节并标记 `AUTOMATION_COST_LIMIT_REACHED`。
- 严重问题停止后续章节：guarded_auto 审批失败、修订轮次耗尽、Phase 5 状态冲突/提交失败/模型错误会隔离当前 item 并跳过后续 item。
- 备份恢复已纳入自动化表 remap，恢复项目会把 policy/run/item/lease 的 `project_id` 映射到新项目 ID，保持跨作品隔离。

## 迁移与数据库表

Catalog 迁移：

- `apps/api/migrations/catalog/versions/0003_model_pricing.py`
- `model_configs.input_price_per_million`
- `model_configs.output_price_per_million`

Project 迁移：

- `apps/api/migrations/project/versions/0008_automation_foundation.py`
- `automation_policies`
- `automation_runs`
- `automation_run_items`
- `automation_leases`

关键唯一约束：

- scheduled run：同一 project + local date 只允许一条 `trigger = scheduled` 记录。
- run idempotency：同一 project + 非空 `idempotency_key` 唯一。
- run item：同一 run + chapter 唯一。
- lease：每个 project 一条。

## 新增 API

- `GET /api/v1/projects/{project_id}/automation/policy`
- `PUT /api/v1/projects/{project_id}/automation/policy`
- `POST /api/v1/projects/{project_id}/automation/runs`
- `GET /api/v1/projects/{project_id}/automation/runs`
- `GET /api/v1/projects/{project_id}/automation/runs/{run_id}`
- `POST /api/v1/projects/{project_id}/automation/runs/{run_id}/cancel`
- `POST /api/v1/projects/{project_id}/automation/runs/{run_id}/resume`
- `POST /api/v1/projects/{project_id}/automation/runs/{run_id}/catch-up`

## 状态机

Run status：

- `queued`
- `running`
- `completed`
- `partial`
- `blocked`
- `failed`
- `cancel_requested`
- `cancelled`
- `missed`
- `interrupted`

Run item status：

- `waiting`
- `running`
- `committed`
- `blocked`
- `failed`
- `cancelled`
- `skipped`
- `interrupted`

## 测试结果

- `uv run --project apps/api pytest apps/api/tests/test_model_config.py -q`：`7 passed`
- `uv run --project apps/api pytest apps/api/tests/test_phase7_automation.py -q`：`6 passed`
- `uv run --project apps/api pytest apps/api/tests -q`：`82 passed`
- `npm run build`：通过；保留既有 Vite chunk-size warning
- `npm run test`：通过；API `82 passed`，Web `3 files / 9 tests passed`
- `npm run test:e2e`：Playwright `10 passed`

备注：测试均使用内存 SecretStore 和本地假 OpenAI 兼容服务，没有调用真实付费模型。

## 已知限制与未完成

- 本阶段只实现后端；未修改 `apps/web/**`，未开发自动托管 UI。
- 本地调度器只在 FastAPI 应用运行期间工作，不提供 Windows 服务或应用关闭后的后台生产。
- 常用 IANA 时区在系统缺少 tzdata 时有固定偏移 fallback；完整 DST 精确性依赖运行环境提供 IANA tzdata。
- 未开发短篇策略、短剧、外部平台发布、Windows 打包或第八阶段功能。

## 审计建议

请以 `86c849c` 为基线审计：

- 自动化执行是否始终通过 Phase 5 公开接口，没有绕过质量门或正式提交事务。
- 模型调用期间是否未持有 SQLite 写事务。
- 费用统计和 `AUTOMATION_MODEL_PRICE_REQUIRED` 是否覆盖所有 required roles。
- missed/catch-up、cancel/resume、startup recovery 是否符合 PHASE-7-AUTOMATION.md。
- 备份恢复 remap 是否覆盖新增自动化表且不跨项目泄漏。

# Story Agent 第六阶段交接

更新时间：2026-07-13
分支：`agent/chapter-workbench`
阶段基线：`bbc366d`（PR #4 合并提交）
第六阶段实现提交：`452d744`
第七阶段交接文档提交：`f7b3b4b`
草稿 PR：https://github.com/zuming58/Story-Agent/pull/5
当前状态：第六阶段代码、视觉验收、全量验证、远端推送和草稿 PR 均已完成；等待 GPT-5.6 合并 PR #5 后创建第七阶段分支。

## 1. 本阶段完成内容

第六阶段把第五阶段章节流水线接入正式桌面 UI：

- `/writing`：章节状态轨道、契约生成/编辑/锁定、任务创建/运行/取消/恢复、上下文追踪、候选正文编辑、版本历史与差异。
- `/quality`：确定性规则、连续性审稿、故事编辑、文风审稿、问题证据、风险接受、自动修订、人工批准与 guarded_auto 正式提交。
- `/settings`：增加“模型配置 / 安全审计”分栏，原备份与调用诊断页面不再占用质量中心路由。
- 右侧故事 Agent 在写作/质量页面显示章节、契约、正文版本和选区作用域；AI 选区建议必须由用户应用到编辑缓冲区并保存为新候选版本。
- 页面使用真实第五阶段 API，不依赖静态业务模拟。

UI 仍沿用“墨曜指挥舱”：深墨蓝、暖金操作、紧凑章节轨道和固定右侧 Agent。1440×1024 与 1280×800 均无横向溢出；1280 下生产流水线自动下沉，不压缩正文编辑区。

## 2. 数据库与后端扩展

新增项目迁移：

- `0007_chapter_draft_current`

`chapter_drafts` 新增 `is_current`：

- 每个 chapter job 只允许一份当前候选稿；
- 迁移时将每个任务版本号最高的旧稿标记为 current；
- 新生成、自动修订和人工编辑均创建新版本，不覆盖旧稿；
- 用户可恢复历史候选版本；正式正文和 current state 不受候选版本切换影响。

新增接口：

- `GET /api/v1/projects/{project_id}/chapters/{chapter_number}/commits`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/manual-revisions`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/drafts/{draft_id}/activate`

人工正文保存要求 parent draft revision 与 job revision；保存后重新运行事实抽取和完整质量门。外部模型调用仍位于短事务之外。

## 3. 前端数据权威

- React Query：章节契约、任务、候选稿、抽取、质量报告、上下文追踪和提交历史。
- Zustand：当前章节、当前任务、Agent 面板和选区等 UI 状态。
- 业务正文、质量报告和提交状态不写入 `localStorage`。
- 刷新页面后从 SQLite 恢复契约、任务、当前候选版本、质量结果和正式提交。
- 409 revision 冲突会刷新服务端最新数据，不覆盖其他操作。

## 4. 验证结果

- 第五/六阶段专项 API：`23 passed`
- `npm run test`：API `76 passed`；Web `3 files / 9 tests passed`
- `npm run build`：通过，仅保留既有 Vite chunk-size warning
- `npm run test:e2e`：Playwright `10 passed`；覆盖契约锁定、任务刷新恢复、质量中心与两个桌面分辨率
- 浏览器人工视觉检查：1440×1024、1280×800 无横向溢出，Agent 不遮挡编辑区
- Python compileall 与敏感文件检查：推送前最终执行

## 5. 已知限制

- 本阶段没有实现后台定时器、每日多章队列、费用日限额和自动日报；这些属于第七阶段。
- 当前章节 run/revise 接口是同步请求驱动，但状态写入采用可恢复阶段机，模型调用期间不持有项目写事务。
- Playwright 不调用真实付费模型；模型生成、抽取、三 reviewer 和 reviser 由 API 测试中的本地 OpenAI 兼容假服务覆盖。
- 当前构建单 chunk 仍大于 500 kB，后续前端阶段可做路由级 lazy loading。

## 6. 下一台电脑当前任务

只实施 [docs/plans/PHASE-7-AUTOMATION.md](docs/plans/PHASE-7-AUTOMATION.md) 中定义的第七阶段自动托管后端。

禁止事项：

- 不修改 `apps/web/**`、CSS、设计令牌、Playwright 视觉与 UI 文案；UI 仍由当前电脑独占维护。
- 不提前开发短篇策略、短剧改编、外部平台自动发布或 Windows 打包。
- 不提交 API Key、`.data`、SQLite、日志、备份 ZIP、测试临时文件、`Story agent/` 和 `openclaw skill/`。
- 不绕过 Phase 5 的契约、revision、质量门、候选状态和原子提交规则。

完成第七阶段后必须运行 API 全量测试、更新本文件、提交并推送指定分支，然后停止等待 GPT-5.6 审计。

## 7. 常用命令

```powershell
npm --prefix apps/web install
uv sync --project apps/api --dev
npm run dev
npm run build
npm run test
npm run test:e2e
```
