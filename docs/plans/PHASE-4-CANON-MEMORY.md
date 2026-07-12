# Story Agent 第四阶段：Canon、状态台账与检索基础

状态：已确认，交由另一台电脑实施，完成后由当前 GPT-5.6 审计
基线：`main` 的第三阶段合并提交 `90a4d3e`
工作分支：`agent/canon-memory-foundation`
范围所有权：另一台电脑只实现后端、数据库、公共类型和自动化测试；UI 由当前电脑独占维护

## 1. 阶段目标

本阶段建立长篇小说的“外部记忆内核”，让后续章节写作不再依赖会话记忆：

- 作者确认的 Canon 是最高权威，AI 不得静默改写。
- SQLite 精确状态是运行时唯一真相源。
- Markdown 是作者可读镜像，不反向覆盖已锁定状态。
- FTS 与向量索引是可删除、可重建的派生数据。
- 每条事实、关系、伏笔和状态变化都能追溯来源与版本。
- 上下文编译固定遵循 Canon → 精确状态 → 未完成伏笔 → 检索证据的优先级。
- 本阶段不生成正式章节正文，不实现自动发布，也不开发页面。

完成后，系统应能回答并给出证据：

- “角色 A 当前在哪里、知道什么、拥有什么？”
- “能力 B 的等级、前置条件、使用方式和代价是什么？”
- “伏笔 F09 在哪里埋设、推进，允许何时回收？”
- “某条事实来自哪个正式来源版本，旧版本是否已经失效？”
- “为下一章编译上下文时，为什么选择了这些 Canon 和证据？”

## 2. 不可违反的数据权威规则

```text
锁定 Canon（作者意图与硬规则）
            ↓ 约束
SQLite 当前有效状态（精确事实）
            ↓ 补充证据
正式来源版本／事件／状态增量
            ↓ 派生
FTS5 与向量索引
            ↓ 编译
Agent 上下文包与检索追踪
```

1. 锁定 Canon 只能经变更申请修改；普通 Agent 对话、分析或检索不得直接改写。
2. 同一实体同一字段只能存在一条“当前有效”精确状态；历史状态保留但失效。
3. 派生索引不得覆盖精确状态；冲突时返回精确状态并标记旧索引。
4. 所有正式写入使用 revision、短事务和审计事件。
5. 候选分析不得污染正式状态；确认提交后才生效。
6. 来源版本失效时，它产生的事实、状态、伏笔和索引必须在同一事务中失效。
7. `.data`、数据库、索引文件、模型输入输出和 API Key 不进入 Git。

## 3. 工作包一：Canon 数据模型与生命周期

### 数据库

新增项目库迁移 `0004_canon_memory`，至少包含：

- `canon_documents`
  - `id`、`title`、`kind`、`content_markdown`、`status(draft|locked|superseded)`
  - `revision`、`created_at`、`updated_at`、`locked_at`
- `canon_entity_types`
  - 通用类型与作品专属类型；`name`、`display_name`、`schema_json`、`is_system`
- `canon_entities`
  - `entity_type_id`、`canonical_name`、`aliases_json`、`attributes_json`
  - `status`、`revision`、`source_document_id`
- `canon_relations`
  - `subject_entity_id`、`predicate`、`object_entity_id/object_value_json`
- `canon_rules`
  - `rule_code`、`category`、`statement`、`severity`、`constraint_json`
  - `status`、`revision`、`source_document_id`
- `canon_change_requests`
  - 修改前后、原因、影响摘要、`pending|accepted|rejected`、revision

约束：

- 默认通用实体类型：人物、地点、组织、物品、能力、事件、情报、伏笔、时间点。
- `schema_json` 只能使用平台允许的 JSON Schema 子集，禁止可执行表达式。
- `attributes_json` 写入前必须按对应 Schema 验证。
- 锁定操作必须在同一事务中写入 Canon、revision 和审计事件。
- 锁定后普通更新返回 409；只能创建 Canon 变更申请。
- Markdown 镜像写入 `canon/story-core.md`，数据库提交成功后原子替换文件；镜像失败必须可重建并产生诊断，不回滚已提交的数据库真相。

### Canon 分析

- `POST /api/v1/projects/{project_id}/canon/analyze`
- 使用 `architect` 角色绑定的真实 OpenAI 兼容模型。
- 只生成候选草稿，输出严格 JSON；非法 JSON 只修复重试一次。
- 候选白名单：文档、实体类型、实体、关系和规则。
- 禁止分析结果直接进入 locked 状态。
- 模型不可用时明确失败，不回退伪造数据；仍允许 API 手工创建草稿。

### API

- `GET /api/v1/projects/{project_id}/canon`
- `POST /api/v1/projects/{project_id}/canon/analyze`
- `PUT /api/v1/projects/{project_id}/canon/draft`
- `POST /api/v1/projects/{project_id}/canon/lock`
- `POST /api/v1/projects/{project_id}/canon/change-requests`
- `POST /api/v1/canon/change-requests/{id}/apply`
- `POST /api/v1/canon/change-requests/{id}/reject`

## 4. 工作包二：实体状态、来源版本与伏笔台账

### 数据库

- `source_versions`
  - 通用来源版本，先支持 `canon`、`manual`、`import`；预留 `chapter`。
  - `source_id`、`version_number`、`status(candidate|official|superseded|rejected)`、checksum。
- `story_entities`
  - 运行时实体，关联 Canon 实体；支持作品专属类型。
- `state_facts`
  - `entity_id`、`field_path`、`value_json`、`valid_from`、`valid_to`
  - `source_version_id`、`confidence`、`is_current`、revision。
- `story_events`
  - 发生时间、叙事顺序、地点、参与实体、来源版本。
- `state_deltas`
  - 事件导致的 before/after 状态变化；候选与正式分离。
- `foreshadows`
  - 埋设、推进、回收状态；最早/目标/最晚章节窗口；来源和证据。
- `knowledge_boundaries`
  - 某实体在某来源版本后知道/不知道的情报。
- `state_snapshots`
  - 快照序号、来源版本、状态摘要、checksum；支持回放校验。

### 事务规则

- 提交来源版本、事件、状态增量、当前状态切换、伏笔变化、快照与审计必须原子完成。
- 同一项目同一时间只允许一个正式状态提交任务。
- `expectedRevision` 过期返回 409。
- 冲突事实不得自动覆盖；记录 `state.conflict_detected` 并阻断依赖该事实的正式提交。
- 旧来源版本 supersede 时，旧事实和索引失效，新版本状态通过 delta 重放生成。
- 本阶段提供手工/测试来源提交接口，为下一阶段章节事实抽取准备，不生成正文。

### API

- `GET /api/v1/projects/{project_id}/state/entities`
- `GET /api/v1/projects/{project_id}/state/entities/{entity_id}`
- `GET /api/v1/projects/{project_id}/state/foreshadows`
- `GET /api/v1/projects/{project_id}/state/timeline`
- `POST /api/v1/projects/{project_id}/state/candidates`
- `POST /api/v1/state/candidates/{id}/commit`
- `POST /api/v1/source-versions/{id}/supersede`
- `GET /api/v1/projects/{project_id}/state/snapshots`

## 5. 工作包三：FTS5、向量适配层与版本失效

### 检索层级

1. 精确实体名、别名、类型与字段查询。
2. SQLite FTS5：Canon、实体、事件、伏笔和证据文本。
3. 可插拔 `VectorIndex`：`upsert`、`search`、`delete_source_version`、`rebuild`。
4. 返回原文证据和来源版本。

实现要求：

- 默认实现可以使用本地内存/SQLite 测试适配器；不得把某个向量扩展写死为唯一依赖。
- Embedding 调用使用 `embedding` 角色绑定；未配置时精确查询和 FTS 仍可用。
- 每个索引项必须包含 `project_id`、`source_version_id`、`entity_id`、`kind` 和 checksum。
- 搜索结果过滤非 official 或 superseded 来源。
- 重写/失效必须删除旧版本的 FTS 与向量记录。
- 提供全量重建命令与 API；索引可以从 SQLite 真相源完全重建。

API：

- `POST /api/v1/projects/{project_id}/retrieval/search`
- `POST /api/v1/projects/{project_id}/retrieval/rebuild`
- `GET /api/v1/projects/{project_id}/retrieval/status`

## 6. 工作包四：上下文编译器与可解释追踪

实现 `ContextCompiler`，输入项目、任务角色、选中规划节点、查询和 token 预算，输出：

- 锁定 Canon 规则与相关实体。
- 当前精确状态和知识边界。
- 未回收伏笔与章节窗口。
- 相关事件、FTS/向量证据和最近上下文。
- 每段内容的来源、版本、优先级、选择原因与估算 token。
- 被压缩或舍弃内容及原因。

优先级不可由模型改变：

```text
锁定 Canon > 章节/任务契约 > 当前精确状态 > 未完成伏笔
> 相关正式事件 > 最近上下文 > FTS/向量补充证据
```

API：

- `POST /api/v1/projects/{project_id}/context/compile`
- `GET /api/v1/projects/{project_id}/context/traces/{trace_id}`

本阶段只提供编译预览和追踪，不接入正式章节写作。

## 7. 公共类型与错误契约

新增或扩展：

- `CanonDocument`、`CanonEntityType`、`CanonEntity`、`CanonRule`
- `CanonChangeRequest`、`SourceVersion`
- `StoryEntity`、`StateFact`、`StoryEvent`、`StateDelta`
- `Foreshadow`、`KnowledgeBoundary`、`StateSnapshot`
- `RetrievalQuery`、`RetrievalHit`、`RetrievalStatus`
- `ContextCompileRequest`、`ContextPackage`、`ContextTraceItem`

API 保持 camelCase；ID 使用 UUID4；时间使用 UTC ISO 8601。

标准错误至少包含：

- `CANON_LOCKED`
- `CANON_NOT_LOCKED`
- `CANON_SCHEMA_INVALID`
- `CANON_ANALYSIS_INVALID`
- `STATE_REVISION_CONFLICT`
- `STATE_FACT_CONFLICT`
- `SOURCE_VERSION_NOT_OFFICIAL`
- `RETRIEVAL_INDEX_UNAVAILABLE`
- `CONTEXT_BUDGET_EXCEEDED`

## 8. 自动化测试与验收

必须新增测试并全部通过：

1. Canon 草稿可编辑；锁定后普通更新返回 409。
2. Canon 分析非法 JSON 只重试一次，失败不写入正式数据。
3. 自定义实体 Schema 能验证属性，非法字段或类型被拒绝。
4. Canon 变更申请未确认前不改变 locked Canon。
5. 同一实体字段不会同时出现两条当前有效事实。
6. 候选状态不影响正式查询；提交后状态、delta、快照和审计原子生效。
7. 任一步骤故障时整个状态提交回滚。
8. supersede 来源版本后，旧事实、伏笔、FTS 和向量命中全部失效。
9. 两个项目的数据、FTS 和向量命名空间完全隔离。
10. 无向量 Provider 时精确查询与 FTS 正常降级。
11. 索引删除后可以从 SQLite 重建，结果 checksum 一致。
12. 上下文预算不足时始终保留锁定 Canon 和精确状态。
13. Context trace 能解释每个片段的来源、版本与选择原因。
14. 备份恢复包含新增数据库状态和 Canon Markdown，但不包含密钥或外部向量缓存。
15. 服务重启后 locked Canon、当前状态、快照和 FTS 仍然存在。

最终必须运行：

```powershell
npm run build
npm run test
npm run test:e2e
```

本阶段没有 UI 改动时，现有 Playwright 6 条必须保持通过；不得修改视觉快照来掩盖回归。

## 9. 明确禁止事项

- 禁止修改 `apps/web/**`、UI 截图、CSS、设计令牌和 Playwright 视觉基线。
- 禁止修改或提交 `Story agent/` 与 `openclaw skill/`。
- 禁止开始章节正文生成、自动修订、托管发布或短剧功能。
- 禁止让模型直接写 locked Canon 或 current state。
- 禁止把向量搜索当作事实真相源。
- 禁止提交 `.data`、API Key、日志、备份 ZIP、模型原始响应和临时文件。
- 禁止绕过 revision、事务、来源版本和审计事件。

如果后端公共类型确实需要前端同步才能通过 TypeScript 构建，只记录差异并停止，不修改 `apps/web`；由当前 GPT-5.6 电脑完成 UI/前端适配。

## 10. 另一台电脑完成后的交接要求

另一台电脑完成全部工作包后：

1. 运行全部测试。
2. 更新 `HANDOFF.md`：提交号、迁移、表、API、测试、已知问题。
3. 提交并推送 `agent/canon-memory-foundation`。
4. 不合并 `main`，不创建 UI。
5. 停止开发，等待当前 GPT-5.6 电脑审计。

返回口令：

```text
另一台电脑已经完成第四阶段并推送。请以 90a4d3e 为基线读取 HANDOFF.md 和最新提交，完整审计 Canon 权威边界、状态事务、版本失效、FTS/向量降级和上下文编译器；修复问题并运行全量测试。
```
