# Story Agent 第三阶段交接

更新时间：2026-07-12
当前状态：第三阶段已完成，本机审计问题已修复，停止开发，等待另一台 GPT-5.6 复审
工作分支：`agent/model-provider-foundation`
审计起点：`5fd8015`
代码完成终点：`bf3569d`
本机审计修复：推送后的最终 HEAD，提交信息为 `fix: address phase three audit findings`
最终审计终点：推送后的 `agent/model-provider-foundation` 分支 HEAD，本文件所在交接提交；最终答复同步给出实际 hash。
完整计划：`docs/plans/PHASE-3-MODEL-PROVIDER.md`

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

## 未完成内容与范围边界

- 第三阶段范围内未留下已知未完成项。
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

## 密钥安全与验证

- API Key 只经 `SecretStore` 保存；默认实现使用 Windows Credential Manager。
- 自动化测试使用 `MemorySecretStore` 和本地假 OpenAI 服务。
- Provider 响应只返回 `hasApiKey` 与 `apiKeyPreview`。
- Provider 删除会先确认 Credential Manager 密钥删除成功，再删除目录库 Provider 行，避免密钥残留且无引用可追踪。
- `model_runs` 和诊断记录不保存密钥或完整模型上下文。
- 备份 ZIP 来源为 `project.json`、`story.db` 和 canon 文件，不包含目录库 Provider 密钥引用或 Credential Manager 内容。
- 已运行敏感扫描：`rg "sk-[A-Za-z0-9_-]{16,}"` 无命中真实密钥；仅测试中保留 `unit-test-*` 假密钥。

## 测试结果

最终验收命令：

- `npm run build`：通过。Vite 仅提示 chunk size warning。
- `npm run test`：通过。
  - API：23 passed，1 个 StarletteDeprecationWarning。
  - Web：3 files passed，8 tests passed。
- `npm run test:e2e`：通过。
  - 1440×1024：规划提案接受/撤销、直接编辑持久化、安全审计页，共 3 条通过。
  - 1280×800：同 3 条通过。
  - 总计 6 passed。

环境说明：

- 本机 Playwright 期望 `chromium_headless_shell-1228`，缓存中已有 `1223`。`playwright install chromium` 下载超时后，为完成本地 e2e 验证，临时在用户缓存目录创建了指向既有 `1223` 的本地 Junction；该操作不在仓库内，不进入提交。

## 审计建议入口

请 GPT-5.6 以 `5fd8015` 为基线，审计 `agent/model-provider-foundation` 到最终推送 HEAD 的全部提交。上一轮本机审计已发现并修复停止/断开、Credential 删除、空提案和 retry 统计问题；复审重点关注：

- 密钥是否只存在 Credential Manager / `MemorySecretStore`，是否可能进入 SQLite、备份、日志或响应。
- 流式 Agent 是否在失败、手动停止、客户端断开和启动恢复时明确收敛为正确状态，不回退模拟内容冒充成功。
- 结构化 JSON 提案是否严格白名单、revision 校验、事务落库和失败不改变规划。
- `logic_check` 无修改建议时的 `proposal_skipped`/`proposal.noop` 是否符合产品语义。
- 备份恢复是否保留 SHA-256、路径穿越防护和新项目恢复语义。
- 1440×1024 与 1280×800 UI 是否无右侧 Agent 遮挡。

## 下一步工作建议

- 先由另一台 GPT-5.6 对 `5fd8015..最终 HEAD` 做代码审计，不要合并 `main`。
- 重点跑新增边界测试，并人工试一次真实浏览器停止流式调用、断网/关闭标签页、Credential Manager 不可用/删除失败。
- 审计通过后再进入下一阶段设计，不要在第三阶段分支里继续开发 Canon、向量检索、章节正文生成或短剧功能。

## 返回 GPT-5.6 的口令

```text
另一台电脑已经完成第三阶段并完成一轮本机审计修复，请读取 HANDOFF.md，以 5fd8015 为基线复审全部提交，重点检查停止/断开、Credential Manager、结构化提案和备份恢复，并运行全量测试。
```
