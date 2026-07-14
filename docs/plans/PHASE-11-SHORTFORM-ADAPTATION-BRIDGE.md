# 第十一阶段：短篇策略与短剧改编桥梁（后端基础）

状态：等待另一台电脑实施，完成后返回当前 GPT-5.6 审计

建议分支：`agent/shortform-adaptation-foundation`

开始基线：第十阶段 GPT-5.6 审计后的 `agent/longform-endurance-foundation` 最新提交

范围所有权：另一台电脑只开发后端、迁移、公共类型与 API 测试；不得修改 `apps/web/**`、UI、CSS、设计令牌、Playwright 或视觉快照

## 1. 阶段目标

在不复制 Canon、规划、章节流水线和质量门的前提下，为同一个故事内核增加两种可审计的产物策略：

```text
正式 Canon / 人物 / 世界规则
  ├─ 长篇网文策略：继续使用现有 Plan + Chapter pipeline
  ├─ 短篇小说策略：压缩为 1—30 章的独立叙事预算
  └─ 短剧改编策略：从已批准短篇或正式章节生成剧集/场景/台词提案
```

本阶段只建立“短篇小说 -> 短剧剧本”的结构化桥梁和后端状态机，不生成分镜图、角色图、视频，也不发布到外部平台。

## 2. 权威关系与不可破坏边界

- Canon、CanonEntity/Relation/Rule 仍是故事事实和能力边界权威。
- 长篇 Plan 和正式 ChapterCommit 不得被短篇/短剧提案反向覆盖。
- 短篇可以从同一 Canon 创建独立 adaptation workspace，但必须冻结来源 Canon revision/checksum。
- 改编允许压缩、合并、调序和视角变化；任何改变人物身份、能力规则、因果或结局的操作必须显式标记为 `canonDeviation`。
- 结构化提案未经接受不得进入正式短篇规划或短剧剧本。
- 任何模型调用必须在 SQLite 写事务之外；冻结输入和应用结果使用短事务。
- API Key、正文缓存、模型原始敏感请求不得写入 Git、备份清单或 API 响应。
- 跨作品、跨 workspace、跨 proposal 的 ID 必须做归属校验。

## 3. 数据模型

新增下一顺序项目迁移，建议表：

### `adaptation_workspaces`

- `id/project_id/name/kind`，kind 为 `short_story|short_drama`。
- 来源类型与 ID、冻结 Canon/Plan/commit revision 和 checksum。
- 目标篇幅、目标章节/集数、单章或单集时长、受众、平台约束、状态、revision。
- 状态：`draft|analyzing|ready|locked|archived`。

### `short_story_strategies`

- workspace、核心卖点、开场钩子、主冲突、情绪曲线、结局、视角、目标字数。
- 章节预算、人物合并方案、伏笔保留/删除清单、升级压缩规则、禁止提前揭示项。
- revision/checksum/状态。

### `adaptation_proposals`

- workspace、proposal kind、输入快照、结构化输出、diff、影响范围、canon deviations。
- 模型运行引用、状态 `pending|applied|rejected|superseded|failed`、revision、错误与时间。
- 非空 idempotency key 在 workspace 内唯一。

### `drama_episodes`

- workspace、集号、标题、logline、目标时长、开场钩子、结尾卡点、来源章节/节拍。
- 状态 `draft|approved|superseded`、revision/checksum。

### `drama_scenes`

- episode、场号、内外景、地点、日夜、角色、目标、冲突、转折、视觉动作、预计时长。
- 来源证据、Canon 引用、revision/checksum。

### `drama_script_versions`

- episode、版本号、parent、kind、Fountain/Markdown 正文、结构化台词、字数与预计时长。
- 候选/批准/废弃状态、模型 run、revision/checksum；同 episode 只允许一个 current approved。

### `adaptation_findings`

- workspace/proposal/episode/scene、规则编号、严重度、证据、建议、fingerprint、状态。
- 同 workspace/fingerprint 去重，保留 resolved 历史。

## 4. 短篇策略生成

新增 deterministic + model 两段流程：

1. 冻结 Canon 与可选来源章节/规划。
2. 计算目标字数、章节数和每章事件预算。
3. 模型角色 `short_story_architect` 生成 JSON 策略提案。
4. 确定性检查长度、人物、规则、升级窗口、伏笔和结局闭环。
5. 允许一次 JSON 修复；仍非法则失败，不写正式策略。
6. 用户接受后原子写入正式 short story strategy；拒绝不改变 workspace。

至少检查：

- 开场 1—2 章必须建立钩子和核心异常。
- 每章重大事件数量不超过预算。
- 结局必须回收标记为“保留”的主伏笔。
- 删除/合并人物必须保留功能映射和因果责任。
- 能力升级压缩不能跳过 Canon 的硬前置或代价。
- 真相揭示不得早于策略允许窗口。
- 目标字数、章节数和结局类型彼此一致。

## 5. 短剧改编提案

来源只允许：

- 已锁定的 short story strategy；
- 或一段连续 current official ChapterCommit。

流程：

1. 冻结来源 manifest（commit/source/draft/checksum 或 strategy checksum）。
2. 生成剧集 outline，默认支持 6/12/24 集。
3. 每集生成 episode contract：开场钩子、核心冲突、结尾卡点、预计时长。
4. 再生成 scenes 和 script candidate。
5. 运行确定性检查与多角色评审。
6. 只有人工批准的 script version 才成为 current approved。

确定性规则至少包括：

- `ADAPTATION_SOURCE_DRIFT`
- `ADAPTATION_CANON_DEVIATION_UNDECLARED`
- `SHORTFORM_EVENT_BUDGET_OVERFLOW`
- `SHORTFORM_FORESHADOW_DROPPED`
- `DRAMA_EPISODE_DURATION_OUT_OF_RANGE`
- `DRAMA_SCENE_DURATION_OVERFLOW`
- `DRAMA_CHARACTER_KNOWLEDGE_LEAK`
- `DRAMA_ABILITY_RULE_BREACH`
- `DRAMA_OPENING_HOOK_MISSING`
- `DRAMA_ENDING_CLIFFHANGER_MISSING`
- `DRAMA_DIALOGUE_WITHOUT_SOURCE_OR_PURPOSE`
- `DRAMA_APPROVAL_CONFLICT`

blocker/error 未解决时不得批准剧本版本。

## 6. API 建议

- `POST /api/v1/projects/{project_id}/adaptation-workspaces`
- `GET /api/v1/projects/{project_id}/adaptation-workspaces`
- `GET /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}`
- `PUT /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}`
- `GET /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}/readiness`
- `POST /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}/short-story-proposals`
- `POST /api/v1/adaptation-proposals/{proposal_id}/apply`
- `POST /api/v1/adaptation-proposals/{proposal_id}/reject`
- `POST /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}/drama-outline-proposals`
- `GET /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}/episodes`
- `POST /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}/episodes/{episode_id}/script-proposals`
- `POST /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}/script-versions/{version_id}/approve`
- `GET /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}/findings`

所有更新/接受/拒绝/批准必须携带 `expectedRevision`。创建操作支持 idempotency key。响应 camelCase、UUID4、UTC ISO 8601，并沿用现有 `ApiError`。

## 7. 模型与事务要求

- 新增角色可以绑定现有 OpenAI-compatible Provider：`short_story_architect`、`drama_adapter`、`script_writer`、`adaptation_reviewer`。
- 使用现有 ModelRun 审计、费用计算、超时、停止和失败语义。
- 单次模型输出只生成一种结构；outline、episode、scene/script 分开调用。
- JSON 输出非法只允许一次精简修复。
- 模型调用前在短事务中冻结 source manifest；调用完成后重新校验 revision/checksum，再在短事务中保存 proposal。
- 不自动回退模拟回复；真实模型失败必须明确失败。

## 8. 测试要求

必须使用确定性本地 Provider，不调用真实 DeepSeek：

- workspace 创建、更新、锁定、revision 与跨作品隔离。
- Canon/Plan/commit source manifest 冻结和漂移阻断。
- 短篇策略提案接受、拒绝、幂等、非法 JSON 一次修复。
- 人物合并、能力前置、事件预算、伏笔保留和结局闭环规则。
- 6/12/24 集范围、episode 顺序、时长预算、开场钩子和结尾卡点。
- scene 顺序、预计时长、人物知识和 Canon deviation。
- 候选 script 不覆盖 approved；批准冲突返回 409。
- 模型调用期间不持有 SQLite 长写事务。
- 任意应用步骤失败时 proposal/strategy/episode/script/findings 整体回滚。
- 备份恢复 remap workspace JSON/manifest，active generation 收敛 interrupted。
- 全量 API 测试通过。

## 9. 交付规则

1. 从第十阶段审计提交创建并推送 `agent/shortform-adaptation-foundation`。
2. 开发前完整阅读 `HANDOFF.md`、本文、PRD、第八至第十阶段方案与审计记录。
3. 本轮只实现后端、迁移、公共类型和 API 测试；不得修改 `apps/web/**`。
4. 不调用真实 DeepSeek，不修改用户正式作品，不提交密钥、`.data`、正文、日志、数据库或备份。
5. 不实现图片、分镜图、角色图、视频、配音、外部发布或 EXE。
6. 完成后运行 `npm run test`、`npm run build` 和 `npm run test:e2e`。
7. 更新 `HANDOFF.md`，提交并推送功能分支，不合并 main；停止等待 GPT-5.6 审计。

第十一阶段审计通过后，当前电脑再开发短篇/短剧 UI；分镜图和视频生产进入后续独立阶段。
