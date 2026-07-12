# 第三阶段：真实模型完整闭环

状态：已确认，连续完成后统一审计
计划日期：2026-07-12
实现分支：`agent/model-provider-foundation`
审计基线：`5fd8015`

## 1. 阶段目标与执行方式

把当前确定性模拟 Agent 升级为可配置、可审计的真实模型系统，并补齐模型配置、流式规划 Agent、结构化提案、备份恢复和审计 UI。

另一台电脑的 GPT-5.5 连续完成本文件全部四个工作包，包括后端和 UI。工作包之间不等待 GPT-5.6 审计，但每完成一包应先运行对应测试并提交一个独立 Git commit，便于最终逐包审计。全部完成、全量测试通过并推送后停止，统一交回 GPT-5.6 审计。

## 2. 全阶段不可破坏的约束

- 支持通用 OpenAI 兼容接口，提供 DeepSeek 官方预设和自定义中转地址。
- DeepSeek 预设使用 `https://api.deepseek.com` 与 `deepseek-v4-pro`，不把旧模型别名写死。
- API Key 使用 Windows Credential Manager 保存；SQLite、日志、API 响应、备份和 Git 中不得出现完整密钥。
- 模型失败必须明确失败，不允许用模拟内容冒充真实回复。
- Agent 生成的规划修改只能形成待确认提案，不能直接写入正式规划。
- SQLite 是业务数据唯一真相源；正式状态改变继续遵守 revision、事务和审计规则。
- 保持现有墨曜指挥舱视觉语言，每个页面继续提供右侧 Agent。
- 不重写第一、二阶段架构，不把 Provider 或模型厂商写死进作品数据结构。

## 3. 工作包一：模型配置基础

### 数据与安全

- 在目录库新增 Provider、模型配置和角色绑定表，并通过 catalog Alembic 迁移创建。
- Provider 至少包含名称、类型、Base URL、超时、重试、启用状态、密钥引用和时间戳。
- 模型至少包含 Provider、模型 ID、显示名称、温度、最大输出、思考开关和启用状态。
- 角色绑定覆盖建筑师、规划师、中文写手、事实抽取、逻辑审稿、文风审稿、修订器和 Embedding。
- 定义可替换 `SecretStore`；Windows 生产实现使用 Credential Manager，自动化测试使用内存实现。
- Base URL 默认必须是 HTTPS；仅 `localhost` 与 `127.0.0.1` 允许 HTTP。
- 被模型或角色引用的 Provider 删除返回 409；无引用 Provider 删除时同步清理凭据。

### API

- `GET|POST /api/v1/model-providers`
- `GET|PATCH|DELETE /api/v1/model-providers/{providerId}`
- `POST /api/v1/model-providers/{providerId}/test`
- `GET|POST /api/v1/model-providers/{providerId}/models`
- `PATCH|DELETE /api/v1/models/{modelId}`
- `GET /api/v1/model-role-bindings`
- `PUT /api/v1/model-role-bindings/{role}`

Provider 响应只返回 `hasApiKey` 和必要的脱敏尾号。连接测试使用短超时，返回成功状态、实际模型或标准错误分类，不保存回复正文，不创建 Agent 消息。

### UI

- 将设置入口连接到高保真“模型与费用设置”页面。
- 支持 DeepSeek 预设、自定义 Provider、模型参数、角色绑定和连接测试。
- 密钥保存后清空输入；刷新后只显示已配置状态和脱敏尾号。
- 提供空数据、加载、连接成功、鉴权失败、超时和 Credential Manager 不可用状态。

## 4. 工作包二：流式真实规划 Agent

- 实现统一 `ModelProvider` 和 OpenAI 兼容流式适配器。
- 增加 `model_runs`，记录角色、Provider、实际模型、状态、Token、耗时、错误码、会话和时间戳，不记录密钥或完整上下文。
- 新增 SSE 消息接口，事件至少包含运行开始、文本增量、完成、失败和取消。
- 支持停止、客户端断开取消、超时、一次网络重试和启动时中断恢复。
- 调用期间不持有 SQLite 长事务；成功后用短事务提交助手消息和运行结果。
- 上下文只包含系统规则、当前作品/卷/故事弧、选中里程碑、相关窗口和最近 12 条消息；本阶段不伪装已有 Canon/RAG。
- 规划 Agent 使用真实模型；未配置模型时引导用户前往设置，调用失败时显示明确错误与重试。
- UI 逐字显示回复，展示实际 Provider/模型、运行状态、停止按钮和失败重试。

## 5. 工作包三：结构化规划提案

- 消息请求增加 `action`：`chat`、`replan`、`logic_check`、`complete_dependencies`。
- 普通对话只执行流式自然语言调用；修改类快捷动作在回复完成后执行独立 JSON 提案调用。
- DeepSeek JSON Output 使用 `response_format: {"type":"json_object"}`；空内容、截断或非法结构只允许一次修复重试。
- 提案只能修改现有白名单字段，并通过章节范围、依赖、目标节点和 revision 校验。
- 非法提案记录失败原因但不落入正式提案表，不改变规划。
- 现有逐项接受、全部接受、拒绝和撤销事务继续有效。
- UI 明确区分自然语言建议、结构化提案、提案生成失败和正式规划结果。

## 6. 工作包四：安全管理与审计 UI

- 增加备份列表、创建、下载和恢复上传 API；恢复仍创建新项目，不覆盖原项目。
- 完成备份管理页面，显示时间、大小、校验状态、来源项目和恢复结果。
- 完成审计时间线和模型调用记录，支持按事件类型、状态和时间筛选。
- 显示错误诊断、请求 ID、重试和中断恢复状态，但不得显示完整密钥或完整模型上下文。
- 保留现有项目 SHA-256 校验、路径穿越防护和事务回滚语义。

## 7. 测试与最终验收

- 数据迁移可从阶段二数据库升级，迁移前备份机制不退化。
- Provider、模型、角色绑定和密钥配置在服务重启后正确恢复。
- 密钥不出现在 SQLite、日志、HTTP 响应、备份 ZIP、错误详情、截图或 Git diff 中。
- 使用内存 SecretStore 和本地假 OpenAI 服务测试，自动化测试不得调用付费模型。
- 覆盖流式分片、Token 统计、连接失败、鉴权失败、超时、取消、客户端断开和启动恢复。
- 覆盖合法提案、空 JSON、非法 JSON、修复重试、白名单拒绝、revision 冲突和事务回滚。
- 覆盖备份创建、下载、损坏拒绝、路径穿越拒绝和恢复为新项目。
- 1440×1024 与 1280×800 下无横向遮挡，Agent 不覆盖表单；增加设置、流式对话、提案和恢复的 Playwright 路径。
- 最终必须通过 `npm run build`、`npm run test`、`npm run test:e2e`。

## 8. 提交与停止条件

建议独立提交：模型配置、流式 Agent、结构化提案、安全管理 UI、最终测试与交接。禁止把所有工作压成一个无法审计的提交。

全部完成后更新 `HANDOFF.md`，写明实际完成、未完成、迁移、API、测试结果、最新提交和审计区间；推送 `agent/model-provider-foundation` 后停止，不合并 `main`，等待 GPT-5.6 审计。

## 9. 禁止事项

- 不修改或提交 `Story agent/` 和 `openclaw skill/`。
- 不提交 API Key、`.data/`、`.e2e-data/`、日志、备份 ZIP 或临时文件。
- 不绕过 revision、事务、质量校验或提案确认机制。
- 不接入 Canon、向量检索、章节正文生成或短剧功能；这些属于后续阶段。
- 不合并 `main`，不关闭审计入口。
