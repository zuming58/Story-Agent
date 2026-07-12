# 第三阶段：真实模型与双电脑轮流审计

状态：已确认，按关卡实施  
计划日期：2026-07-12  
实现分支：`agent/model-provider-foundation`

## 1. 阶段目标

把当前确定性模拟 Agent 升级为可配置、可审计的真实模型基础，同时保持正式规划只能经用户确认写入。

本阶段按四个关卡顺序推进，每个关卡都必须由实施 Agent 完成测试、更新 `HANDOFF.md` 并推送，然后停止，等待 GPT-5.6 审计。未经审计通过不得提前实现下一关。

## 2. 共同约束

- 支持通用 OpenAI 兼容接口，提供 DeepSeek 官方预设和自定义中转地址。
- DeepSeek 预设使用 `https://api.deepseek.com` 与 `deepseek-v4-pro`，不把旧模型别名写死。
- API Key 使用 Windows Credential Manager 保存；SQLite、日志、API 响应、备份和 Git 中不得出现完整密钥。
- 模型失败必须明确失败，不允许用模拟内容冒充真实回复。
- 模型或 Agent 生成的规划修改仍是待确认提案，不能直接写入正式规划。
- SQLite 是业务数据唯一真相源；所有正式状态改变继续遵守 revision、事务和审计规则。
- 两台电脑不得同时修改同一功能分支，GitHub 是唯一代码权威。

### 电脑与 Agent 分工

- 另一台电脑的 GPT-5.5 只负责 `apps/api` 后端、数据库迁移、SecretStore、Provider 适配器和后端自动化测试。
- 当前电脑的 GPT-5.6 负责全部 `apps/web` UI、React Query 接入、CSS、交互和 Playwright 视觉测试。
- GPT-5.5 不得修改 `apps/web` 下任何文件，也不得以“接口联调”为由制作临时 UI。
- 每个后端关卡由 GPT-5.5 推送后停止；GPT-5.6 先审计后端，再在同一阶段分支完成对应 UI 和集成验收。

## 3. 关卡一：模型配置基础

本关是当前唯一允许实施的范围。

### 后端与数据

- 在目录库新增 Provider、模型配置和角色绑定表，并通过 catalog Alembic 迁移创建。
- Provider 至少包含名称、类型、Base URL、超时、重试、启用状态、密钥引用、创建时间和更新时间。
- 模型配置至少包含 Provider、模型 ID、显示名称、温度、最大输出、思考开关和启用状态。
- 角色绑定预留建筑师、规划师、中文写手、事实抽取、逻辑审稿、文风审稿、修订器和 Embedding；本关只配置，不调用。
- 定义可替换 `SecretStore`；Windows 生产实现使用 Credential Manager，测试使用内存实现。
- Base URL 默认必须是 HTTPS；仅 `localhost` 与 `127.0.0.1` 允许 HTTP。
- 删除 Provider 时，如果仍被模型或角色绑定引用则返回明确冲突，不级联静默删除。

### API

- `GET|POST /api/v1/model-providers`
- `GET|PATCH|DELETE /api/v1/model-providers/{providerId}`
- `POST /api/v1/model-providers/{providerId}/test`
- `GET|POST /api/v1/model-providers/{providerId}/models`
- `PATCH|DELETE /api/v1/models/{modelId}`
- `GET /api/v1/model-role-bindings`
- `PUT /api/v1/model-role-bindings/{role}`

所有 Provider 响应只允许返回 `hasApiKey` 和必要的脱敏提示，不得返回密钥、Credential Manager 条目内容或可逆密钥引用。

连接测试必须设置短超时，返回成功状态、实际模型或错误分类；不保存模型回复正文，不修改规划，不创建 Agent 消息。

### 前端接口契约

- GPT-5.5 只需保证 OpenAPI、Pydantic Schema、camelCase JSON 和错误响应完整，不开发前端。
- API 响应必须足以支持 Provider 管理、连接测试、模型参数和角色绑定，不允许要求前端读取数据库或 Credential Manager。

### 关卡一 UI 集成（仅当前电脑 GPT-5.6）

后端关卡一经审计通过后，由 GPT-5.6 实施：

- 将设置入口连接到高保真“模型与费用设置”页面，并保持墨曜指挥舱视觉语言；
- 支持 Provider 新建、编辑、删除、DeepSeek 预设、自定义 OpenAI 兼容接口和连接测试；
- 支持模型参数编辑与角色绑定，提供完整空状态、加载、失败和恢复状态；
- 密钥输入保存后立即清空，刷新页面只显示已配置状态和脱敏尾号；
- 保留所有页面右侧 Agent，但不在本关切换为真实模型；
- 增加 React Query、组件单元测试和两档 Playwright 验收。

### 关卡一验收

- 数据库迁移可从现有 catalog 正常升级，升级前备份机制不退化。
- 新建、修改、删除、连接测试和角色绑定均可重启恢复。
- API Key 不出现在 SQLite、日志、HTTP 响应、项目备份 ZIP 或 Git diff 中。
- Credential Manager 不可用时保存失败并给出可操作错误，不退回明文文件。
- Provider 被引用时删除返回 409；无引用 Provider 可删除且同步清理对应凭据。
- 使用本地假 OpenAI 服务完成连接测试，不在自动化测试中调用付费模型。
- GPT-5.5 完成后端测试并运行现有全量测试，证明没有回归；不得通过修改前端测试规避失败。
- GPT-5.6 完成 UI 集成后，`npm run build`、`npm run test`、`npm run test:e2e` 全部通过。
- 1440×1024 与 1280×800 的设置页视觉验收由 GPT-5.6 负责。

## 4. 关卡二：流式模型调用

仅在关卡一经 GPT-5.6 审计通过后开放。

- 实现统一 `ModelProvider` 和 OpenAI 兼容流式适配器。
- 增加 `model_runs` 调用审计，记录角色、Provider、实际模型、状态、Token、耗时和错误码，不记录密钥或完整上下文。
- 增加 SSE 消息接口、停止、取消、超时、一次网络重试和中断恢复。
- 规划 Agent 使用真实模型；模型失败时明确报错，不回退模拟回复。
- 本关只产生自然语言回复，不生成结构化修改提案。
- GPT-5.5 交付后端与协议后停止；SSE 前端消费、逐字显示、停止按钮和错误交互由 GPT-5.6 审计后实现。

## 5. 关卡三：结构化规划提案

仅在关卡二审计通过后开放。

- 快捷动作使用明确 `action`：普通对话、重排节奏、逻辑检查和补全依赖。
- 自然语言回复完成后，修改类动作再执行独立的 JSON 提案调用。
- JSON 空内容、截断或非法结构只允许一次修复重试；仍失败则不落库。
- 提案只能修改白名单字段，并通过章节范围、依赖和 revision 校验。
- 接受、拒绝和撤销继续使用现有事务与审计规则。
- GPT-5.5 不修改现有提案 UI；快捷动作和提案交互由 GPT-5.6 审计后集成。

## 6. 关卡四：安全管理页面

仅在前三关审计通过后开放，并完全由当前电脑 GPT-5.6 实施。

- 完成备份列表、创建、下载、恢复上传和完整性错误展示。
- 完成审计时间线、模型调用记录、错误诊断、重试和恢复状态。
- 对 1440×1024、1280×800、Windows 125% 缩放进行最终视觉验收。

## 7. 双电脑工作流

另一台电脑只实施 `HANDOFF.md` 标明的当前关卡。完成后必须：

1. 运行当前关卡要求的全部测试；
2. 更新 `HANDOFF.md` 的完成项、未完成项、测试结果、已知问题和最新提交；
3. 提交并推送当前功能分支；
4. 不合并 `main`；
5. 停止继续开发，等待 GPT-5.6 审计。

GPT-5.6 返回后对关卡起止提交做差异审计，覆盖迁移、密钥安全、API、错误处理、UI 和测试。审计修复推送后，才在 `HANDOFF.md` 开放下一关。

## 8. 禁止事项

- 不修改或提交 `Story agent/` 和 `openclaw skill/`。
- 不提交 API Key、`.data/`、`.e2e-data/`、日志、备份 ZIP 或临时文件。
- 不让 Provider 配置改变作品数据结构。
- 不绕过 revision、事务或提案确认机制。
- 不提前实施后续关卡。
- 另一台电脑不得修改 `apps/web`。
