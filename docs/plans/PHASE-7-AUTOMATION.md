# 第七阶段：每日自动托管与可恢复生产队列

状态：等待另一台电脑实施，完成后由当前 GPT-5.6 审计
建议分支：`agent/automation-foundation`
范围所有权：另一台电脑只开发后端、数据库、API 公共类型和 API 自动化测试；禁止修改 `apps/web/**`

## 1. 阶段目标

把单章流水线编排为本地可恢复的每日生产任务：

```text
托管策略到期
  -> 建立唯一运行与项目写作租约
  -> 按章顺序推导并锁定契约
  -> 调用 Phase 5 生成、抽取、质量与最多两轮修订
  -> guarded_auto 批准并原子提交
  -> 上一章正式提交后才允许下一章
  -> 生成运行报告；严重异常立即暂停后续章节
```

应用关闭时不安装 Windows 服务、不在后台偷偷运行。下次启动检测错过时段并记录 `missed`，等待用户明确补跑。

## 2. 数据库设计

新增 catalog 迁移，为 `model_configs` 增加：

- `input_price_per_million`、`output_price_per_million`，允许为空且不得为负。

新增项目迁移 `0008_automation_foundation`：

### `automation_policies`

- 每项目一条：`project_id`、`enabled`、`time_of_day`、`timezone`、`chapters_per_run`。
- `target_words_min/max`、`max_revision_rounds(0..2)`、`daily_cost_limit`。
- `stop_policy` 固定支持 `stop_on_blocking` 和 `stop_on_any_failure`。
- `approval_mode` 第一版只能是 `guarded_auto`；自动任务不得使用人工强制批准。
- `next_run_at`、`last_scheduled_local_date`、`revision` 和时间字段。

### `automation_runs`

- `id`、`project_id`、`policy_id`、`scheduled_local_date`、`trigger(scheduled|manual|catch_up)`。
- `status(queued|running|completed|partial|blocked|failed|cancel_requested|cancelled|missed|interrupted)`。
- 起止章节、计划/成功/隔离数量、Token、估算费用、停止原因、diagnostic、revision 和时间字段。
- 同一项目同一本地计划日期最多一个 scheduled run；幂等重试返回原运行。

### `automation_run_items`

- `automation_run_id`、`chapter_number`、`sequence_number`、`chapter_contract_id`、`chapter_job_id`、`chapter_commit_id`。
- `status(waiting|running|committed|isolated|blocked|failed|cancelled|skipped)`。
- Token、估算费用、错误码、diagnostic 和时间字段。
- 同一 run/chapter 唯一。

### `automation_leases`

- 每项目唯一租约：`project_id`、`owner_id`、`lease_expires_at`、`heartbeat_at`、`revision`。
- 任意时刻同一作品只能有一个会修改正式状态的自动运行。
- 租约过期后可以恢复；不得依赖进程内互斥锁作为唯一保护。

所有表纳入项目 ZIP 备份/恢复与跨作品 ID 重映射；模型定价属于 catalog 配置，不进入项目备份。

## 3. 调度与执行语义

- FastAPI lifespan 启动一个本地调度循环，每 30 秒检查一次到期策略；关闭时请求正在运行任务安全停止。
- 时间以策略 IANA timezone 计算，数据库统一保存 UTC ISO 时间；夏令时重复时段按本地日期幂等键只执行一次。
- 应用启动时：遗留 running 收敛为 interrupted；过去未执行的计划只创建一条 missed 记录，不自动补跑。
- 手动“立即运行”和“补跑 missed”使用同一执行器，不重复实现写作逻辑。
- 每个 run 从 `project.currentChapter + 1` 开始，严格串行。只有上一章产生 current ChapterCommit 后才进入下一章。
- 已存在正式提交的章节标记 skipped 并前进；存在未完成 Phase 5 job 时优先恢复该 job，不重新调用写作模型收费。
- Phase 5 返回 human_review 且存在 blocker/error、两轮后仍失败、Canon/状态/revision 冲突、正式提交失败或连续模型故障时，当前 item 隔离/阻断并停止后续章节。
- 取消在每个 Phase 5 阶段边界检查；已正式提交的章节不回滚，尚未提交的候选稿保留。

## 4. 费用与模型故障

- 每次 ModelRun 根据 prompt/completion token 和模型单价计算估算费用，写入 run item 与 run 汇总。
- 若策略配置费用上限但任一必需角色模型缺少定价，创建运行时返回 `AUTOMATION_MODEL_PRICE_REQUIRED`，不得按零费用继续。
- 启动下一次模型调用前预测最低剩余额度；已达到或预计超过日限额时停止新章节，保留当前候选状态并报告 `AUTOMATION_COST_LIMIT_REACHED`。
- 同一模型调用失败沿用 Provider 自身重试；自动编排层不得额外无限重试。
- 连续模型故障阈值默认 2 次，达到后整个 run blocked。

## 5. API

- `GET|PUT /api/v1/projects/{project_id}/automation/policy`
- `POST /api/v1/projects/{project_id}/automation/runs`：手动立即运行，支持 idempotencyKey
- `GET /api/v1/projects/{project_id}/automation/runs`
- `GET /api/v1/projects/{project_id}/automation/runs/{run_id}`
- `POST /api/v1/projects/{project_id}/automation/runs/{run_id}/cancel`
- `POST /api/v1/projects/{project_id}/automation/runs/{run_id}/resume`
- `POST /api/v1/projects/{project_id}/automation/runs/{run_id}/catch-up`：仅 missed 可调用

Policy 更新必须携带 `expectedRevision`。Run 输出包含 item 列表、费用/Token 汇总、停止原因、可恢复动作和下一计划时间。JSON 继续使用 camelCase，ID 为 UUID4，时间为 UTC ISO 8601。

## 6. 测试与验收

必须覆盖：

- 到期策略只创建一个 run；应用重启、重复 tick 和夏令时重复小时不重复执行。
- 应用关闭期间的任务变为 missed，必须人工 catch-up。
- 两章正常串行提交，第二章只能读取第一章提交后的新状态快照。
- 第一章 blocker/Canon 冲突/状态提交失败后，第二章保持 waiting/skipped 且不调用模型。
- 生成完成但 commit 失败时恢复复用候选稿，不重复 writer 调用。
- 费用汇总正确；缺少单价和超出日限额均阻止新模型调用。
- cancel、interrupted、lease 过期和服务重启均可恢复且不产生两个 current commit。
- 两部作品运行、租约、预算和报告完全隔离。
- 备份恢复包含 policy/run/item/lease，恢复为新项目且不覆盖原项目。
- 任意事务注入失败全部回滚；模型调用期间不持有 catalog/project 写事务。
- 全量 API 测试通过；不得修改或运行 UI 快照更新。

## 7. 交付规则

开始前从第六阶段合并后的 `main` 创建 `agent/automation-foundation`。完成后：

1. 更新 `HANDOFF.md`，记录迁移、表、接口、状态机、测试数字和已知问题；
2. 提交并推送功能分支，不合并 `main`；
3. 停止继续开发，不提前做自动托管 UI；
4. 等待当前 GPT-5.6 按租约、幂等、费用、恢复、事务和跨作品隔离做完整审计。
