# Story Agent 第四阶段审计与第五阶段交接

更新时间：2026-07-13
当前状态：GPT-5.6 第四阶段代码审计、修复和全量验证已完成；本文件所在提交为第四阶段最终审计恢复点
工作分支：`agent/canon-memory-foundation`
第四阶段基线：`90a4d3e`
第四阶段完整计划：`docs/plans/PHASE-4-CANON-MEMORY.md`
第五阶段完整计划：`docs/plans/PHASE-5-CHAPTER-PIPELINE.md`
UI 所有权：仅当前 GPT-5.6 电脑允许修改 `apps/web/**`、样式、设计令牌和视觉基线
第三阶段 UI 审计板：https://www.figma.com/design/6QL982fTRWQiTS79wXwWtN
第三阶段审计起点：`5fd8015`
代码完成终点：`bf3569d`
本机审计修复：推送后的最终 HEAD，提交信息为 `fix: address phase three audit findings`
最终审计终点：本文件所在提交；最终答复同步给出实际 hash。
第三阶段计划：`docs/plans/PHASE-3-MODEL-PROVIDER.md`

## 2026-07-13 GPT-5.6 最终审计记录（优先阅读）

审计范围：以 `90a4d3e` 为基线，复核另一台电脑推送到 `98c0e87` 的全部第四阶段实现。下列问题已在本文件所在提交修复并通过完整验证。

### 已确认并已在工作区修复的问题

1. `ContextCompiler` 查询不存在的 `CanonDocument.project_id`，上下文编译会必现运行时错误；同时 trace 使用只读 Session，生成后不会持久化。
2. Canon 实体变更调用 `_apply_canon_target_patch` 时引用未定义的 `session`，接受实体变更会返回 500。
3. Canon 草稿允许客户端直接提交 `status=locked`，可绕过正式锁定流程；revision 也可由客户端覆盖。
4. Canon 变更申请信任客户端提交的 `beforeJson`，无法作为可靠审计快照；变更申请也未强制要求 Canon 已锁定、目标存在和 `afterJson` 非空。
5. Canon 关系缺少主语、谓词和宾语引用校验；新增关系在校验前进入 Session，还会因 autoflush 先触发数据库 500。
6. Canon 分析把模型 Provider 错误也当成 JSON 修复重试，并把原始模型响应放进错误详情；草稿写入和审计原来不是同一事务。
7. Markdown 镜像写入失败时数据库已经提交，但 API 仍报失败，造成调用方误判；现在改为保留数据库真相并记录 `canon.mirror_failed` 诊断。
8. 状态事实冲突原实现会自动关闭旧事实并覆盖新值，违反“冲突必须阻断”；现在不同值必须提供匹配的 `expectedCurrentValue`，否则 409、事务回滚并单独记录冲突审计。
9. 状态候选对未知实体、未知类型、空字段、无效 confidence、无效事件和伏笔章节窗口会静默跳过，导致“提交成功但事实丢失”；现在统一在正式写入前返回 422。
10. 同一实体字段缺少数据库级“仅一条 current fact”约束；新增迁移 `0005_phase4_audit_fixes`，先清理历史重复 current，再建立 SQLite partial unique index。
11. `supersede` 可作用于 candidate/rejected；作废后旧事件、伏笔、快照和检索仍可能对外可见，也不会恢复上一个正式事实；现在只允许 official，按正式来源过滤查询，并回放最近仍有效事实。
12. 检索重建重复删除索引表、把非 official 来源写成 official，所谓向量层只是写死的方法；现在增加可插拔 `VectorSearchBackend` 协议、本地确定性适配器、不可用降级和重建失败诊断。
13. 上下文编译漏掉所选章节契约和角色知识边界，且未按来源 official 过滤事件/伏笔；现在固定实现 Canon → 任务契约 → 当前状态/知识边界 → 伏笔 → 事件 → 最近上下文 → 检索证据。
14. 备份恢复会给作品分配新 ID，但第四阶段所有表仍保留旧 `project_id`，导致恢复后数据库有数据而 API 返回空；现在在恢复事务中重映射所有第四阶段表，并从 SQLite 真相源重建派生索引。
15. 原第四阶段专项测试仅 2 条，未覆盖计划要求的 15 类验收；当前已扩展为 21 条，覆盖锁定边界、Schema、冲突回滚、来源失效、隔离、降级、上下文、备份恢复和重启。

### 当前工作区修改

- `apps/api/src/story_agent_api/phase4.py`
- `apps/api/src/story_agent_api/models.py`
- `apps/api/src/story_agent_api/services.py`
- `apps/api/migrations/project/versions/0005_phase4_audit_fixes.py`（新增）
- `apps/api/tests/test_phase4.py`
- `apps/web/e2e/planning.spec.ts`（仅把独立 SQLite 初始化后的 URL 等待由 5 秒调整为 15 秒，不改变 UI、样式或视觉基线）
- `docs/plans/PHASE-5-CHAPTER-PIPELINE.md`（新增）
- `HANDOFF.md`

未修改任何页面组件、CSS、设计令牌、截图或视觉基线；UI 所有权规则保持不变。

### 已完成验证

- `uv run --project apps/api pytest apps/api/tests/test_phase4.py -q`：`21 passed`。
- `npm run test`：通过；API `54 passed`，Web `3 files / 8 tests passed`。
- `npm run build`：通过；只有既有 Vite 主 chunk 约 534 KB 警告。
- `python -m compileall` 与 `git diff --check`：通过。
- `npm run test:e2e`：通过，1440×1024 与 1280×800 共 `6 passed`。
- 敏感信息扫描：无真实 API Key；唯一命中为测试假值 `Bearer unit-test-secret-value`。`.data`、`.e2e-data` 和 `test-results` 均保持 Git ignored。

### 审计收口结果

1. 第四阶段计划要求的 15 类验收均已有自动化覆盖，专项测试共 21 条。
2. 新增迁移已在全新作品、服务重启和备份恢复链路中验证。
3. 第四阶段可以合并 `main`；后续功能必须从合并后的 `main` 创建第五阶段分支。
4. 第五阶段计划已经落盘，另一台电脑只负责后端实施，不得修改 UI。

## 当前任务：第五阶段接力准备

第四阶段由另一台电脑实施、当前 GPT-5.6 完整审计修复并通过验证，范围覆盖：

1. Canon 数据模型、草稿/锁定/变更申请和 Markdown 镜像。
2. 通用与作品专属实体、精确状态、事件、delta、伏笔、知识边界和快照。
3. FTS5、可插拔向量适配层、来源版本失效和索引重建。
4. 可解释上下文编译器和 trace。
5. 后端迁移、API、公共类型与自动化测试。

第四阶段期间未修改 `apps/web/**`，也未修改 CSS、设计令牌、UI 截图或 Playwright 视觉基线。第三阶段已通过 PR #2 合并到 `main`，合并提交为 `90a4d3e`。以下内容保留为已完成历史与审计依据。

## 完成内容

工作包一 `029c78f Add model provider configuration foundation`

- 新增目录库模型配置基础：Provider、模型配置、角色绑定。
- 新增 `SecretStore` 抽象，生产默认 Windows Credential Manager，测试使用 `MemorySecretStore`。
- 支持 DeepSeek 预设：`https://api.deepseek.com` 与 `deepseek-v4-pro`。
- Provider API 响应只返回 `hasApiKey` 和脱敏尾号，不回显完整密钥。
- Base URL 默认要求 HTTPS，仅 `localhost` 与 `127.0.0.1` 允许 HTTP。
- 完成模型设置 UI：Provider 创建/编辑、密钥保存后清空、连接测试、模型参数和角色绑定。

工作包二 `58ad383 Add streaming model-backed planning agent`

- 新增 OpenAI 兼容 Provider 适配器，支持 SSE `/chat/completions` 流式解析、用量统计、超时/鉴权/限流/网络错误分类和一次重试。
- 新增项目库 `model_runs`，记录角色、Provider、模型、状态、token、耗时、错误码、request id、retry，不记录密钥或完整上下文。
- 新增 SSE Agent 接口，事件包含 `run_started`、`text_delta`、`completed`、`failed`、`cancelled`。
- 调用期间不持有 SQLite 长事务；成功/失败以短事务写入助手消息和运行结果。
- 支持停止、客户端断开取消和启动时恢复 running 调用为 `interrupted`。
- UI 逐字显示回复，并展示 Provider/模型、运行状态、停止和失败重试。

工作包三 `05a185b Add structured planning proposal generation`

- `action` 支持 `chat`、`replan`、`logic_check`、`complete_dependencies`。
- 普通对话只做自然语言流式回复；修改类动作在自然语言完成后发起独立 JSON 提案调用。
- JSON 调用使用 `response_format: {"type":"json_object"}`，空 JSON、非法 JSON、截断输出只修复重试一次。
- 提案只允许白名单字段：章节窗口、依赖/完成条件/伏笔/契约、备注、节奏状态。
- 校验目标节点、revision、章节范围、依赖引用和字段类型；非法提案只记录失败审计和 model run 诊断，不写入正式提案，不改变规划。
- 接受、拒绝、撤销继续走原有事务闭环；新增 JSON 值列兼容列表/文本类提案，旧数字提案仍可用。
- UI 区分自然语言建议、结构化提案生成中/成功/失败、正式提案结果。

工作包四 `bf3569d Add backup recovery audit and diagnostics UI`

- 新增备份列表、下载、上传恢复 API；恢复仍创建新项目，不覆盖原项目。
- 备份列表读取 ZIP manifest，显示大小和 SHA-256 校验状态。
- 恢复继续校验 ZIP、manifest、SHA-256 和路径穿越；恢复 canon 文件不再使用递归删除。
- 审计事件支持按 event/entity 类型过滤。
- 模型调用记录支持按状态和角色过滤，诊断 UI 展示 request id、retry、错误码、中断/失败状态和安全诊断摘要。
- 新增“安全与审计”页面，承载备份管理、审计时间线、模型调用记录和错误诊断；1440×1024 与 1280×800 e2e 均验证右侧 Agent 不遮挡。

本机审计修复 `fix: address phase three audit findings`

- 修复 SSE 客户端断开和手动停止后的 `model_runs` 状态收敛：断开写入 `cancelled/client_disconnected`，手动停止最终写入 `cancelled`，启动恢复同时处理遗留 `running` 与 `cancel_requested`。
- 修复停止后的会话 active run 判断，不再把 `cancel_requested` 记录继续暴露为活动调用。
- 修复 Windows Credential Manager 删除校验：`CredDeleteW` 失败会抛错，`not found` 作为幂等成功；删除 Provider 时先确认凭据清理成功，再删除目录库 Provider 行。
- 修复 `logic_check` 无修改建议语义：空 `operations` 现在返回 `proposal_skipped`，记录 `proposal.noop` 审计和成功的结构化诊断，不再冒充失败。
- 修复模型调用 `retryCount`：记录真实发生的重试次数，而不是 Provider 配置值。
- 前端新增 `proposal_skipped` 事件处理，逻辑检查无修改时显示成功通知并刷新审计/调用记录。
- 新增 API 测试覆盖 Credential 删除失败、取消最终状态、SSE 断开清理、`logic_check` 空提案成功语义。

GPT-5.6 完整复审修复（本文件所在提交）

- 修复取消竞态：最后一个 SSE delta 后收到停止请求时不再误写成功；自然语言回复已经成功、结构化提案仍运行时断开，只取消提案运行，不覆盖已完成回复。
- 结构化提案支持手动停止和客户端断开收敛，子生成器被显式关闭，不再遗留 `running`；非 `logic_check` 动作的空提案按失败处理。
- 流式 Provider 在已经向 UI 发出文本后不再自动重放请求，避免网络中断重试导致开头内容重复。
- Windows Credential Manager 读取失败会区分“未找到”和真实系统错误，后者不再伪装成缺少密钥。
- Provider Base URL 禁止内嵌账号、密码、查询参数和 URL fragment，避免凭据随配置进入 SQLite。
- DeepSeek 官方预设改为幂等创建；默认 `deepseek-v4-pro` 已按 2026-07-12 官方接入文档复核。
- 备份恢复改为只解包清单白名单文件，补充 Windows 反斜杠/盘符穿越、ZIP 展开上限、512 MB 上传上限、清单结构和时间校验。
- 损坏备份不会拖垮整个备份列表，仍可下载排查；恢复失败会同时回滚新目录与 catalog 行，不留下半成品项目。
- 恢复项目同步保留 `currentChapter`、模式和总章节数，校验项目数据库必须包含作品元数据。
- 实际浏览器复核规划中心、模型设置和质量中心；目标宽度无横向溢出、Agent 未遮挡主操作区，控制台无 error/warning。

第四阶段完成 `d1af9b0 feat: complete phase four canon memory foundation`

- 新增 `canon_documents`、`canon_entity_types`、`canon_entities`、`canon_relations`、`canon_rules`、`canon_change_requests`、`source_versions`、`story_entities`、`state_facts`、`story_events`、`state_deltas`、`foreshadows`、`knowledge_boundaries`、`state_snapshots` 与检索索引状态迁移。
- 新增 `apps/api/src/story_agent_api/phase4.py`，统一实现 Canon 草稿/锁定/变更申请、状态候选提交/失效、FTS/向量混合检索、上下文编译与 trace。
- 新增第四阶段 API 路由与公共类型，补齐 `/canon`、`/state`、`/retrieval`、`/context` 相关接口。
- 新增 `apps/api/tests/test_phase4.py`，覆盖别名输出与检索索引命中。
- 本次提交未修改 UI，未引入 API Key、本地数据库、日志、备份 ZIP、截图或 `.e2e-data`。

## 未完成内容与范围边界

- 第四阶段范围内未留下阻塞性未完成项。
- 第三阶段范围内未留下阻塞性未完成项。
- 低优先级视觉债务：部分 9–10px 辅助说明文字对比度偏低；不影响本阶段功能验收，建议在下一轮统一可访问性校准时处理。
- 低优先级构建债务：Vite 主 JS chunk 约 534 KB，建议功能模块继续增多前引入路由级拆包。
- Canon、状态台账、FTS 和可插拔本地向量检索基础已经完成；章节正文生产、短剧制作、媒体生成和发布仍属于后续阶段。
- 第五阶段只开发单章生产、自动质检和修订闭环，不提前进入无人值守批量写作或发布。
- 未提交 API Key、本地数据库、日志、备份 ZIP、截图、trace 或 `.e2e-data`。

## 数据库迁移

Catalog:

- `0001_catalog`：既有目录库基础。
- `0002_model_provider`：`model_providers`、`model_configs`、`model_role_bindings`。

Project:

- `0001_project`：既有项目规划、会话、提案、审计基础。
- `0002_model_runs`：`model_runs`。
- `0003_structured_proposals`：`change_operations.before_json`、`change_operations.after_json`、`model_runs.diagnostic_json`。
- `0004_canon_memory`：Canon、状态、检索与上下文编译基础。
- `0005_phase4_audit_fixes`：清理历史重复 current fact，并建立同一实体字段仅一条 current fact 的 partial unique index。

## API 清单

模型配置:

- `GET|POST /api/v1/model-providers`
- `GET|PATCH|DELETE /api/v1/model-providers/{provider_id}`
- `POST /api/v1/model-providers/{provider_id}/test`
- `POST /api/v1/model-providers/deepseek-preset`
- `GET|POST /api/v1/model-providers/{provider_id}/models`
- `PATCH|DELETE /api/v1/models/{model_id}`
- `GET /api/v1/model-role-bindings`
- `PUT /api/v1/model-role-bindings/{role}`

Agent 与调用审计:

- `POST /api/v1/agent/sessions/{session_id}/messages/stream`
- `POST /api/v1/projects/{project_id}/model-runs/{run_id}/cancel`
- `GET /api/v1/projects/{project_id}/model-runs?status=&role=&limit=`

SSE 事件补充：

- `proposal_skipped`：结构化逻辑检查无正式修改建议时返回，代表诊断成功但不创建待确认提案。

提案闭环:

- `GET /api/v1/projects/{project_id}/change-proposals`
- `POST /api/v1/change-proposals/{proposal_id}/apply`
- `POST /api/v1/change-proposals/{proposal_id}/reject`
- `POST /api/v1/projects/{project_id}/audit-events/{event_id}/undo`

备份与审计:

- `POST /api/v1/projects/{project_id}/backups`
- `GET /api/v1/projects/{project_id}/backups`
- `GET /api/v1/projects/{project_id}/backups/{backup_id}/download`
- `POST /api/v1/projects/restore`
- `GET /api/v1/projects/{project_id}/audit-events?event_type=&entity_type=&limit=`

Canon、状态、检索与上下文:

- `GET /api/v1/projects/{project_id}/canon`
- `POST /api/v1/projects/{project_id}/canon/analyze`
- `PUT /api/v1/projects/{project_id}/canon/draft`
- `POST /api/v1/projects/{project_id}/canon/lock`
- `POST /api/v1/projects/{project_id}/canon/change-requests`
- `POST /api/v1/canon/change-requests/{change_request_id}/apply`
- `POST /api/v1/canon/change-requests/{change_request_id}/reject`
- `GET /api/v1/projects/{project_id}/state/entities`
- `GET /api/v1/projects/{project_id}/state/entities/{entity_id}`
- `GET /api/v1/projects/{project_id}/state/foreshadows`
- `GET /api/v1/projects/{project_id}/state/timeline`
- `POST /api/v1/projects/{project_id}/state/candidates`
- `POST /api/v1/state/candidates/{candidate_id}/commit`
- `POST /api/v1/source-versions/{source_version_id}/supersede`
- `GET /api/v1/projects/{project_id}/state/snapshots`
- `POST /api/v1/projects/{project_id}/retrieval/search`
- `POST /api/v1/projects/{project_id}/retrieval/rebuild`
- `GET /api/v1/projects/{project_id}/retrieval/status`
- `POST /api/v1/projects/{project_id}/context/compile`
- `GET /api/v1/projects/{project_id}/context/traces/{trace_id}`

## 密钥安全与验证

- API Key 只经 `SecretStore` 保存；默认实现使用 Windows Credential Manager。
- 自动化测试使用 `MemorySecretStore` 和本地假 OpenAI 服务。
- Provider 响应只返回 `hasApiKey` 与 `apiKeyPreview`。
- Provider 删除会先确认 Credential Manager 密钥删除成功，再删除目录库 Provider 行，避免密钥残留且无引用可追踪。
- `model_runs` 和诊断记录不保存密钥或完整模型上下文。
- 备份 ZIP 来源为 `project.json`、`story.db` 和 canon 文件，不包含目录库 Provider 密钥引用或 Credential Manager 内容。
- 恢复上传限制为 512 MB，ZIP 展开总量限制为 1 GB；仅 manifest 白名单文件会写入临时恢复目录。
- 已运行敏感扫描：`rg "sk-[A-Za-z0-9_-]{16,}"` 无命中真实密钥；仅测试中保留 `unit-test-*` 假密钥。

## 测试结果

最终验收命令：

- `npm run build`：通过。Vite 仅提示 chunk size warning。
- `npm run test`：通过。
  - API：54 passed；warnings 为既有 Starlette/httpx 弃用提示与 Python 3.13 SQLite datetime adapter 提示。
  - Web：3 files passed，8 tests passed。
- `npm run test:e2e`：通过。
  - 1440×1024：规划提案接受/撤销、直接编辑持久化、安全审计页，共 3 条通过。
  - 1280×800：同 3 条通过。
  - 总计 6 passed。

环境说明：

- 本机 Playwright 期望 `chromium_headless_shell-1228`，缓存中已有 `1223`。`playwright install chromium` 下载超时后，为完成本地 e2e 验证，临时在用户缓存目录创建了指向既有 `1223` 的本地 Junction；该操作不在仓库内，不进入提交。

## GPT-5.6 审计结论

- 已以 `5fd8015` 为基线复核全部第三阶段提交及上一轮自审提交。
- 密钥边界、SSE 状态机、结构化提案白名单/revision/确认事务、备份恢复与前端主路径均通过复审。
- 修复后敏感扫描无真实密钥命中；新增边界测试全部通过。
- DeepSeek 预设模型名依据 [DeepSeek 官方接入文档](https://api-docs.deepseek.com/) 与 [官方模型价格页](https://api-docs.deepseek.com/quick_start/pricing) 复核。
- 结论：第三阶段已通过 PR #2 合并到 `main`，合并提交 `90a4d3e`。

## 第四阶段审计结论

- 外部实现终点：`98c0e87`；GPT-5.6 最终审计修复为本文件所在提交。
- 已复核 Canon 权威边界、状态事务、来源失效/replay、FTS/向量降级、上下文编译、备份恢复和重启持久化。
- 发现的 15 类问题均已修复，并由 21 条第四阶段专项测试覆盖。
- 验证结果：`npm run build`、`npm run test`、`npm run test:e2e`、compileall、diff check 和敏感扫描全部通过。
- 结论：第四阶段审计通过，可以合并 PR #3。

## 下一步工作

- 第五阶段实施 `docs/plans/PHASE-5-CHAPTER-PIPELINE.md`：章节契约、候选正文、事实抽取、确定性检查、多角色模型质检、最多两轮修订和正式状态提交。
- 另一台电脑只实现后端、迁移、公共类型和自动化测试；完成后推送并停止，等待 GPT-5.6 审计。
- UI 仍由当前 GPT-5.6 电脑负责，另一台电脑禁止修改 `apps/web/**`。

## 下一台电脑接力口令

```text
请接手 Story Agent 第五阶段后端开发。

仓库：https://github.com/zuming58/Story-Agent.git
分支：agent/chapter-pipeline-foundation
基线：第四阶段 PR #3 合并后的 main

开始前依次完整阅读：
1. HANDOFF.md
2. docs/plans/PHASE-5-CHAPTER-PIPELINE.md
3. docs/prd/PRD-001.md
4. docs/plans/PHASE-4-CANON-MEMORY.md
5. docs/plans/PHASE-3-MODEL-PROVIDER.md

只执行第五阶段计划，不提前实现无人值守批量写作、发布或短剧功能。完成全部后端工作包与测试后：

1. 运行 npm run build、npm run test、npm run test:e2e；
2. 更新 HANDOFF.md，记录迁移、表、API、状态机、完成项、未完成项、测试结果、已知问题和最新提交；
3. 提交并推送 agent/chapter-pipeline-foundation；
4. 不合并 main；
5. 停止继续开发，等待 GPT-5.6 完整审计。

禁止修改 apps/web/**、CSS、设计令牌、UI 截图、Playwright 用例和视觉基线。UI 只由当前 GPT-5.6 电脑维护。
禁止修改或提交 Story agent/ 与 openclaw skill/，禁止提交 API Key、.data、日志、备份 ZIP 和模型原始响应。
```
