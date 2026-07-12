# Story Agent 第五阶段：章节生产、自动质检与修订闭环

状态：待另一台电脑实施，完成后由当前 GPT-5.6 审计
前置条件：第四阶段 PR #3 经 GPT-5.6 审计修复后合入 `main`
建议工作分支：`agent/chapter-pipeline-foundation`
范围所有权：另一台电脑只实现后端、数据库、公共类型和自动化测试；`apps/web/**`、UI、CSS、设计令牌和视觉基线仍由当前 GPT-5.6 电脑独占维护

## 1. 阶段目标

本阶段把第四阶段的 Canon、精确状态和上下文编译器接入“单章生产闭环”，目标不是一次生成很多正文，而是让每一章都经过可恢复、可审计、可阻断的生产流水线：

```text
章节契约
  → 编译上下文
  → 生成候选正文
  → 抽取候选事实/事件/伏笔变化
  → 确定性规则检查
  → 多角色模型质检
  → 最多两轮定向修订
  → 人工确认或自动批准
  → 正文版本与状态台账原子提交
```

完成后，系统至少能稳定生产并保存一章候选正文，自动回答：

- 本章是否提前消费了后续 10—20 章的内容？
- 是否违反锁定 Canon、人物能力、法宝、等级、知识边界和时间线？
- 计划要求的钩子、伏笔、人物出场和完成条件是否落实？
- 哪些问题已自动修订，哪些仍需人工确认？
- 最终正文对应哪一版上下文、模型调用、质量报告和状态来源？

本阶段不做无人值守日程、不自动发布到小说平台、不做短剧改编、不开发 UI。

## 2. 核心权威与提交边界

1. `chapter_contract` 是单章任务边界，必须来自锁定 Canon、规划节点和作者明确要求；模型不得擅自扩大章节目标。
2. 模型生成的正文、事实抽取和修订结果全部先进入 candidate；任何模型调用不得直接修改 current state、locked Canon 或正式正文。
3. 模型调用期间不得持有 SQLite 写事务；每次调用前后只使用短事务记录状态。
4. 正式批准时，正文版本、来源版本、状态事实/事件/伏笔变化、快照、索引和审计必须在同一项目写锁下提交；任一步失败全部回滚。
5. 状态提交继续遵守 `expectedCurrentValue` 与 `revision`；发生事实冲突时章节不得自动批准。
6. 自动修订最多两轮。两轮后仍有 blocker/critical 问题时转 `human_review`，不得无限循环消耗模型额度。
7. Markdown 正文是可重建镜像，SQLite 是版本、状态与审批真相源。

## 3. 数据库迁移 `0006_chapter_pipeline`

至少新增：

### `chapter_contracts`

- `id`、`project_id`、`chapter_number`、`title`
- `plan_node_id`、`plan_node_revision`、`canon_revision_digest`、`state_snapshot_id`
- `objective_json`、`allowed_scope_json`、`forbidden_scope_json`
- `required_characters_json`、`required_foreshadows_json`、`required_hooks_json`
- `completion_conditions_json`、`pov`、`target_words_min/max`、`pace`
- `status(draft|locked|superseded)`、`revision`、时间字段

约束：同一作品同一章只能有一个 locked contract；锁定后只能复制新 revision，不原地静默改写。

### `chapter_jobs`

- `id`、`project_id`、`chapter_contract_id`、`status`
- 状态：`queued|compiling_context|drafting|extracting|validating|reviewing|revising|human_review|approved|committing|completed|failed|cancel_requested|cancelled|interrupted`
- `attempt_number`、`current_revision_round`、`context_trace_id`
- `idempotency_key`、`lease_owner`、`lease_expires_at`
- `error_code`、`diagnostic_json`、`created_at/started_at/finished_at/updated_at`

约束：同一 contract 同一 idempotency key 只能创建一个 job；服务启动时将遗留 running 状态收敛为 `interrupted` 或安全恢复。

### `chapter_drafts`

- `id`、`project_id`、`chapter_job_id`、`chapter_contract_id`
- `version_number`、`parent_draft_id`、`kind(generated|revised|approved)`
- `content_markdown`、`word_count`、`checksum`
- `model_run_id`、`context_trace_id`、`status(candidate|approved|superseded)`
- `revision`、时间字段

正文必须保留版本链；禁止覆盖旧稿。

### `chapter_extractions`

- `id`、`chapter_draft_id`、`model_run_id`
- `payload_json`、`schema_version`、`status(candidate|validated|rejected)`
- `validation_errors_json`、`checksum`、时间字段

抽取结构映射到第四阶段 `StateCandidateCreate`：entities、facts、events、foreshadows、boundaries，并必须携带事实变更的 `expectedCurrentValue`。

### `quality_runs` 与 `quality_findings`

- run：`id`、`chapter_job_id`、`chapter_draft_id`、`gate_type(deterministic|model)`、`reviewer_role`、`model_run_id`、`status`、摘要与时间。
- finding：`id`、`quality_run_id`、`rule_code`、`severity(info|warning|error|blocker)`、`category`、`message`、`evidence_json`、`location_json`、`suggested_fix`、`fingerprint`、`status(open|fixed|accepted_risk|superseded)`。

相同草稿、规则和证据的 finding 必须用 fingerprint 去重。

### `chapter_commits`

- `id`、`project_id`、`chapter_number`、`chapter_contract_id`
- `approved_draft_id`、`source_version_id`、`state_snapshot_id`
- `quality_summary_json`、`checksum`、`revision`、`committed_at`

同一作品同一章节只能有一个 current commit；重写章节必须创建新 revision，并使旧来源版本走第四阶段 supersede/replay。

## 4. 章节契约生成与“防止 100 章写成 20 章”

章节契约必须显式区分：

- `mustAdvance`：本章必须推进的最小目标。
- `mayAdvance`：允许轻微推进但不可完成的目标。
- `mustNotAdvance`：后续章目标、禁止提前揭示的真相、禁止提前出场的人物/能力/道具。
- `knowledgeAtStart/knowledgeAtEnd`：各人物本章前后允许知道的信息。
- `stateAtStart/expectedStateDelta`：允许变化的精确字段。
- `requiredSetup/requiredPayoff`：本章需埋设或回收的钩子/伏笔。
- `paceBudget`：场景数、重大事件数、信息揭示数、能力升级数上限。

确定性规则至少包含：

- `SCOPE_FUTURE_NODE_CONSUMED`：正文完成了不在当前 allowed scope 的后续规划节点。
- `PACE_MAJOR_EVENT_OVERFLOW`：重大事件/升级/真相揭示数量超过本章预算。
- `REQUIRED_CONDITION_MISSING`：本章完成条件未满足。
- `FORBIDDEN_CHARACTER_EARLY`、`FORBIDDEN_ABILITY_EARLY`、`FORBIDDEN_ITEM_EARLY`。
- `FORESHADOW_WINDOW_VIOLATION`：伏笔埋设/推进/回收超出章节窗口。

blocker 必须阻止自动批准；模型不能把 blocker 降级。

## 5. 生成、抽取和质量门

### 生成

- 使用 `chinese_writer` 角色绑定的真实 OpenAI 兼容模型。
- 输入只能来自固定 ContextCompiler 包、锁定章节契约和本次作者补充说明。
- Prompt 必须要求只写当前章节，不总结后续卷，不生成状态 JSON。
- 输出正文以流式或完整调用均可，但数据库仅保存候选稿；模型失败明确报错，不回退模拟正文。
- 记录 `model_runs`，但不保存 API Key；模型输入输出正文属于项目数据，可进入项目数据库与备份，不进入 Git/日志。

### 结构化抽取

- 正文完成后独立调用结构化 JSON 抽取，不从生成模型的“自我说明”直接写状态。
- 非法/截断 JSON 只修复重试一次。
- Pydantic + Canon Schema + 第四阶段状态验证全部通过后才标记 `validated`。
- 抽取候选在章节批准前不得进入 official 状态。

### 双层质量门

第一层确定性检查：

- Canon/当前事实/知识边界/时间线/章节范围/revision。
- 人物、地点、组织、法宝、能力、等级、术式名称与固定施法细节一致性。
- 章节契约、伏笔窗口、必需人物、钩子、字数和 pace budget。
- 重复段落、明显占位符、章节标题/编号、空正文等机械质量。

第二层模型评审：

- `continuity_reviewer`：逻辑、因果、时空、人物知识与连续性。
- `story_editor`：节奏、冲突、场景功能、钩子、信息释放和是否提前消费后续内容。
- `style_reviewer`：中文可读性、视角、语体、重复、AI 套话；不得自行改剧情事实。

角色绑定应使用现有模型配置体系扩展；未配置必需 reviewer 时 job 明确进入 `human_review` 或失败，不能伪造通过报告。

## 6. 自动修订

- 只把 open findings、相关证据片段、章节契约和必要上下文发送给修订模型，不重复塞入整个项目数据库。
- 优先局部 patch；如果模型无法提供可靠定位，可生成完整新版本，但必须保留 parent draft 和 diff 摘要。
- 修订后必须重新运行全部确定性规则和受影响的模型评审，不能仅凭修订模型自报“已解决”。
- 两轮上限后：无 blocker/error 可进入待批准；仍有 blocker/error 转 `human_review`。
- 用户接受风险时记录 finding 状态、理由和审计，不删除原 finding。

## 7. 批准与正式提交

批准模式：

- `manual`：用户明确批准后提交。
- `guarded_auto`：所有确定性 gate 通过、模型评审无 blocker/error、修订轮次不超过上限，才允许自动批准。

正式提交事务：

1. 校验 contract、draft、state snapshot、plan node 和所有 expected revisions 未变化。
2. 创建/更新章节正式 commit。
3. 把 extraction 转换为第四阶段来源版本并原子提交状态。
4. 写状态快照、索引、正文 commit 和审计。
5. 更新项目 `currentChapter`，但不得超过 contract 章节。
6. 事务成功后原子写入 `manuscripts/chapter-XXXX.md` 镜像；镜像失败记录诊断，不回滚数据库真相。

任何 revision 漂移返回 409，job 回到 `human_review`，不得用旧上下文强行提交。

## 8. API 设计

章节契约：

- `POST /api/v1/projects/{project_id}/chapter-contracts/derive`
- `GET /api/v1/projects/{project_id}/chapter-contracts`
- `GET|PUT /api/v1/projects/{project_id}/chapter-contracts/{contract_id}`
- `POST /api/v1/projects/{project_id}/chapter-contracts/{contract_id}/lock`

任务与正文：

- `POST /api/v1/projects/{project_id}/chapter-jobs`
- `GET /api/v1/projects/{project_id}/chapter-jobs`
- `GET /api/v1/projects/{project_id}/chapter-jobs/{job_id}`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/run`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/cancel`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/retry`
- `GET /api/v1/projects/{project_id}/chapters/{chapter_number}/drafts`
- `GET /api/v1/projects/{project_id}/chapter-drafts/{draft_id}`

质量与批准：

- `GET /api/v1/projects/{project_id}/chapter-jobs/{job_id}/quality`
- `POST /api/v1/projects/{project_id}/quality-findings/{finding_id}/accept-risk`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/revise`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/approve`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/commit`

第一轮可以由同步测试 runner 驱动，但服务层必须按可恢复 job 状态机设计，不能把整条流水线塞进一个 HTTP 长事务。

## 9. 错误契约

至少新增：

- `CHAPTER_CONTRACT_NOT_LOCKED`
- `CHAPTER_CONTRACT_REVISION_CONFLICT`
- `CHAPTER_JOB_ALREADY_RUNNING`
- `CHAPTER_JOB_NOT_RESUMABLE`
- `CHAPTER_CONTEXT_STALE`
- `CHAPTER_DRAFT_EMPTY`
- `CHAPTER_EXTRACTION_INVALID`
- `CHAPTER_QUALITY_BLOCKED`
- `CHAPTER_REVISION_LIMIT_REACHED`
- `CHAPTER_STATE_CONFLICT`
- `CHAPTER_COMMIT_CONFLICT`
- `CHAPTER_MODEL_ROLE_NOT_CONFIGURED`

API 保持 camelCase、UUID4、UTC ISO 8601 和现有 `ApiError` 格式。

## 10. 自动化测试与验收

至少覆盖：

1. contract 从规划节点、Canon 和当前状态派生，锁定后不能原地修改。
2. 后续节点进入 `mustNotAdvance`，提前消费被确定性 gate 阻断。
3. 同一 idempotency key 不会创建两个 job。
4. 候选正文和抽取不会污染正式章节或 current state。
5. 模型调用期间不持有 SQLite 写事务。
6. 空正文、模型失败、取消和服务重启后状态正确收敛。
7. 抽取非法 JSON 只修复一次，仍失败时不提交状态。
8. 人物未知信息、能力等级、法宝归属、施法细节冲突能被检查发现。
9. 伏笔提前回收、超窗未回收和必需钩子缺失能被检查发现。
10. 不同事实无 `expectedCurrentValue` 时章节批准被阻断。
11. 一次修订生成新 draft，旧 draft 不覆盖且 diff 可追踪。
12. 两轮修订仍失败转 `human_review`，不会继续调用模型。
13. reviewer 未配置时不会伪造通过。
14. finding fingerprint 去重，接受风险保留原因与审计。
15. manual 模式未经批准不得 commit。
16. guarded_auto 仅在所有 gate 通过后批准。
17. 正式提交同时写正文、状态、快照、索引、currentChapter 和审计；注入故障时全部回滚。
18. revision 漂移返回 409，不使用旧 context trace 提交。
19. 重写已提交章节会 supersede 旧来源并正确回放状态/索引。
20. 两部作品、相同章节号和相同人物名完全隔离。
21. 备份恢复包含正文版本、质量报告和状态，不包含密钥/外部向量缓存。
22. 服务重启后 job、draft、finding、正式章节和检索均可恢复。

最终必须运行：

```powershell
npm run build
npm run test
npm run test:e2e
```

本阶段没有 UI 改动时，现有 6 条 Playwright 必须继续通过，不得修改视觉快照掩盖回归。

## 11. 明确禁止事项

- 禁止修改 `apps/web/**`、UI、CSS、设计令牌、截图和视觉基线。
- 禁止开始每日无人值守批量写作、平台自动发布、短篇策略或短剧改编。
- 禁止让正文模型直接写 locked Canon/current state。
- 禁止为了“自动通过”降低 blocker、跳过 reviewer 或超过两轮修订。
- 禁止把模型原始响应、API Key、`.data`、正文数据库、日志或备份 ZIP 提交 Git。
- 禁止修改或提交 `Story agent/` 和 `openclaw skill/`。

## 12. 另一台电脑完成后的交接要求

1. 先完整阅读 `HANDOFF.md` 与本计划，只实现第五阶段后端范围。
2. 每个工作包完成后运行相关测试；最终运行三条完整验收命令。
3. 更新 `HANDOFF.md`：迁移、表、API、状态机、测试、已知问题、起止提交。
4. 提交并推送 `agent/chapter-pipeline-foundation`，不合并 `main`。
5. 停止开发，等待当前 GPT-5.6 做完整审计；不要继续第六阶段。
