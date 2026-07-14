# 第十二阶段：短篇小说正文生产闭环

## 目标

把第十一阶段的短篇策略从“可保存的压缩方案”升级为真正可写、可审、可提交、可导出的短篇小说。短剧和短视频暂停，不在本阶段范围内。

最终用户路径：

```text
建立短篇项目或从长篇生成短篇策略
→ 确认短篇 Canon 与 1—30 章节拍
→ 生成候选正文
→ 事实抽取与多角色质量复核
→ 人工确认或最多两轮自动修订
→ 正式提交
→ 连续生成全篇
→ TXT / Markdown / DOCX / EPUB 导出
```

## 核心架构决定

短篇正文必须写入独立的 `mode=short-form` 标准项目，不能写进来源长篇项目的 `ChapterCommit`。这样长篇进度、Canon、状态台账、检索索引、费用与备份不会被短篇改编污染。

支持两种入口：

1. 原生短篇：直接新建 `short-form` 项目，从零建立 Canon 和短篇策略。
2. 长篇压缩为短篇：在来源长篇生成并确认 strategy，再物化为新的 `short-form` 项目；目标项目保存不可变的来源快照和 strategy checksum。

第十二阶段后端不修改 `apps/web/**`。UI 仍由当前电脑单独设计和实现。

## 后端实施内容

### 1. 短篇项目规则

- `mode=short-form` 的正式项目总章数限制为 1—30 章。
- `currentChapter` 初始为 0。
- Canon、Plan、章节契约、候选稿、事实抽取、质量门、正式提交继续复用现有权威表和事务规则。
- 短篇项目不得创建 31 章及以上契约、自动化任务或正式提交。
- 长篇与短篇项目的 SQLite、备份、检索索引、费用和模型运行完全隔离。

### 2. 来源物化与溯源

新增不可变的短篇来源记录，至少保存：

- sourceProjectId、sourceWorkspaceId、sourceStrategyId；
- strategy revision/checksum；
- frozen Canon/Plan/commit source manifest；
- 目标项目 ID、创建状态、失败诊断和创建时间。

新增接口建议：

- `POST /api/v1/projects/{source_project_id}/adaptation-workspaces/{workspace_id}/materialize-short-story`
- `GET /api/v1/projects/{project_id}/short-story/origin`
- `GET /api/v1/projects/{project_id}/short-story/readiness`

物化必须验证来源 workspace 为 `short_story`、状态可用、strategy active/checksum 正确、无 open error/blocker、source manifest 未漂移。重复幂等请求返回同一目标项目；参数不同复用同一键返回 409。

目标项目初始化失败时必须可诊断、可重试，不能留下被误认为 ready 的半成品项目。禁止跨两个 SQLite 假装原子事务；使用显式 staged 状态与补偿/恢复流程。

### 3. 策略转为 Canon 与 Plan

- 从来源快照复制必要的世界规则，不直接引用可变的来源数据库行。
- 把 character merge、compression rules、forbidden reveals 写入目标 Canon/Plan 的明确边界。
- 根据 `targetChapterCount` 生成连续 1—N 章 ChapterBeat。
- 每章必须有目标、允许事件数、钩子/回收、人物知识边界、能力与物品边界、目标字数和禁止提前揭示内容。
- ChapterBeat 必须与 strategy chapterBudget 一一对应；缺号、重号、越界或空事件阻断物化。
- 接受物化结果后锁定目标 Canon；后续修改只能走既有 Canon 变更申请。

### 4. 复用章节生产流水线

- 复用 Phase 5 的契约、上下文、候选版本、分段事实抽取、确定性质量门、多角色复核、两轮修订上限和原子正式提交。
- 写作提示必须注入 short-form 模式、短篇策略、全篇剩余字数/事件预算和当前章预算。
- 每完成一章同步扣减短篇预算，不能提前消耗后续章的高潮、真相、升级或伏笔回收。
- 候选稿不得修改正式 Canon、状态事实或检索索引；只有正式提交事务可以更新。
- 模型调用期间不得持有 SQLite 写事务。
- 服务重启后复用安全候选稿，不重复计费或重复提交。

### 5. 短篇质量门

至少增加：

- `SHORT_STORY_CHAPTER_RANGE`：仅允许 1—30 章及目标范围内章节。
- `SHORT_STORY_EVENT_BUDGET`：本章重大事件不超预算。
- `SHORT_STORY_TOTAL_WORD_BUDGET`：全篇累计与剩余字数合理。
- `SHORT_STORY_HOOK_MISSING`：开篇钩子与章节钩子缺失。
- `SHORT_STORY_REVEAL_EARLY`：禁止事项提前揭露。
- `SHORT_STORY_FORESHADOW_DROPPED`：结尾前应回收伏笔未回收。
- `SHORT_STORY_ENDING_INCOMPLETE`：最终章未完成主冲突、代价和情绪闭环。
- `SHORT_STORY_CANON_DRIFT`：人物、能力、物品或规则违反目标 Canon。

error/blocker 必须阻止正式提交；warning 可以人工接受并记录原因。

### 6. 自动托管与导出

- Phase 7 自动托管支持 short-form 项目，但批次不得越过目标最终章。
- 默认先单章试写，再连续 3 章，最后生成剩余全篇。
- 最终章提交后自动停止，不创建额外任务。
- Phase 9 导出支持 short-form 完整作品，仍只读取 current official commits。
- 导出前验证 1—N 连续、无缺章、无 open blocker/error、结尾质量门通过。

## 测试与验收

必须覆盖：

- 原生短篇项目从第 0 章开始且总章数不超过 30。
- 长篇策略只能物化到新的短篇项目，不能污染来源项目。
- 幂等物化、半成品恢复、失败重试和跨作品隔离。
- strategy/Canon/Plan/commit manifest 漂移阻断。
- 1—N ChapterBeat 连续、预算一致及 revision 冲突。
- 模型期间无长事务，候选稿不污染正式状态。
- 两轮修订上限、取消、恢复、重复计费与重复提交。
- 最终章自动停止，31 章请求被拒绝。
- 备份恢复后来源快照与目标短篇项目可独立使用。
- API 全量、Web 单测、build、Playwright 全部通过。
- 使用确定性本地 Provider 测试，不消费真实 DeepSeek。

## 交付规则

- 分支建议：`agent/short-story-production-foundation`。
- 另一台电脑只开发后端、迁移、API 和测试，不修改 `apps/web/**`、CSS、设计令牌、Playwright 或视觉快照。
- 不删除第十一阶段短剧表，但不新增任何短剧、短视频功能。
- 完成后更新 `HANDOFF.md`，记录基线、提交、迁移、接口、测试和已知限制，推送后停止，等待 GPT-5.6 审计。
