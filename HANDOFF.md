# Story Agent 第四阶段交接

更新时间：2026-07-12
当前状态：第四阶段已完成后端实施、验证、提交并推送，等待 GPT-5.6 审计
工作分支：`agent/canon-memory-foundation`
第四阶段基线：`90a4d3e`
第四阶段完整计划：`docs/plans/PHASE-4-CANON-MEMORY.md`
UI 所有权：仅当前 GPT-5.6 电脑允许修改 `apps/web/**`、样式、设计令牌和视觉基线
第三阶段 UI 审计板：https://www.figma.com/design/6QL982fTRWQiTS79wXwWtN
第三阶段审计起点：`5fd8015`
代码完成终点：`bf3569d`
本机审计修复：推送后的最终 HEAD，提交信息为 `fix: address phase three audit findings`
最终审计终点：本文件所在提交；最终答复同步给出实际 hash。
第三阶段计划：`docs/plans/PHASE-3-MODEL-PROVIDER.md`

## 当前任务：第四阶段后端实施

第四阶段已由当前电脑完整实现并通过验证，范围覆盖：

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
- 未开发 Canon、向量检索、章节正文生成、短剧制作、媒体生成或发布能力；这些仍属于后续阶段。
- 未合并 `main`。
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
  - API：35 passed，5 个 warnings。
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

- 当前完成提交：`d1af9b0 feat: complete phase four canon memory foundation`
- 变更文件：`apps/api/src/story_agent_api/main.py`、`apps/api/src/story_agent_api/models.py`、`apps/api/src/story_agent_api/schemas.py`、`apps/api/src/story_agent_api/services.py`、`apps/api/src/story_agent_api/phase4.py`、`apps/api/migrations/project/versions/0004_canon_memory.py`、`apps/api/tests/test_phase4.py`
- 验证结果：`npm run build`、`npm run test`、`npm run test:e2e` 全部通过
- 推送状态：`agent/canon-memory-foundation` 已推送到远端
- 最终审计终点：`d1af9b0`

## 下一步工作

- 等待 GPT-5.6 审计第四阶段实现。
- 若审计发现问题，仅基于 `agent/canon-memory-foundation` 做后续修复并重新推送。
- UI 仍由当前 GPT-5.6 电脑负责；本次未修改 `apps/web/**`。

## 下一台电脑接力口令

```text
请接手 Story Agent 第四阶段审计。

仓库：https://github.com/zuming58/Story-Agent.git
分支：agent/canon-memory-foundation
基线：90a4d3e

开始前依次完整阅读：
1. HANDOFF.md
2. docs/plans/PHASE-4-CANON-MEMORY.md
3. docs/prd/PRD-001.md
4. docs/plans/PHASE-3-MODEL-PROVIDER.md

第四阶段已完成。请基于当前分支做完整审计，如发现问题请修复并重新推送，然后停止等待 GPT-5.6 审计。

禁止修改 apps/web/**、CSS、设计令牌、UI 截图和 Playwright 视觉基线。UI 只由另一台 GPT-5.6 电脑维护。
禁止修改或提交 Story agent/ 与 openclaw skill/，禁止提交 API Key、.data、日志、备份 ZIP 和模型原始响应。
```
