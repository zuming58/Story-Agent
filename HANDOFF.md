# Story Agent 第十阶段：长篇中程耐久测试与漂移监控交接

更新时间：2026-07-14（Codex）

当前分支：`agent/longform-endurance-foundation`

草稿 PR：[#9](https://github.com/zuming58/Story-Agent/pull/9)

GPT-5.6 核心审计提交：`3ede241`

准确开发基线：`agent/export-publishing-foundation@c81be33`

最新提交：以 `agent/longform-endurance-foundation` 分支 HEAD 为准（交付回复会给出推送后的短 hash）。

状态：**第十阶段已经由 GPT-5.6 完整审计、修复并通过全量验证；可交接第十一阶段后端开发。**

完整审计记录：`docs/plans/PHASE-10-AUDIT.md`。

## 第十阶段 GPT-5.6 审计结果

- 修复真实 Phase 7 异步执行下“首批未完成即把未来章节判为缺章”的核心状态机错误。
- 增加 Phase 7 终态回调；5 章正式收口后再建立 checkpoint、运行规则并派发下一批。
- 10 章专项已验证为两个 5 章批次，第二批完成前不会误报第 6—10 章。
- Checkpoint 只接纳本次 endurance automation item 的 committed 章节，并保存正确 run/item 和单章费用归属。
- 补强 commit/draft/extraction/source/snapshot 的作品归属、互相引用、状态、revision 与实际 checksum 链。
- 漂移规则已经适配 Phase 5 真实 `entities/facts/boundaries/events/foreshadows` 抽取结构。
- Cancel/resume/evaluate 必须携带 `expectedRevision`；恢复同时校验 checkpoint、Canon 与 Plan revision。
- 评估会 resolve 旧 finding 后按当前权威状态重建；恢复不再被旧问题永久阻断。
- 备份恢复会 remap Phase 10 JSON 并重算 checkpoint/finding/report checksum。
- 新增 `ENDURANCE_CONSECUTIVE_FAILURE_LIMIT`，并修正费用、历史重复任务和里程碑逾期误报。
- 未修改 `apps/web/**`、UI、CSS、设计令牌、Playwright 或视觉快照。

## 第十阶段完成内容

- 新增项目数据库迁移 `0014_longform_endurance_foundation`。
- 新增数据表：
  - `endurance_suites`
  - `endurance_runs`
  - `endurance_checkpoints`
  - `endurance_findings`
  - `endurance_reports`
- 新增 `Phase10Service`，作为 Phase 7 自动托管和 Phase 5 章节流水线之上的监督层。
- Endurance run 通过 Phase 7 `create_manual_run` 派发批次，不复制章节生成、抽取、质量复核、修订或正式提交逻辑。
- 每个 checkpoint 只在 current official `ChapterCommit`、official `SourceVersion`、`StateSnapshot` 和 approved draft 链路完整时创建。
- Checkpoint 冻结 commit/source/snapshot revision 与 checksum、Canon/Plan revision、预算摘要、人物知识、能力、物品、伏笔和费用摘要。
- 服务启动时将 active endurance run 收敛为 `interrupted`，将 `cancel_requested` 收敛为 `cancelled`，不会自动继续消耗模型费用。
- Resume 会校验最后 checkpoint 与当前 official 状态一致；漂移返回 `ENDURANCE_CHECKPOINT_DRIFT`。
- Cancel 会标记 endurance run，并沿用 Phase 7 cancel 语义取消当前 automation run。
- 备份恢复会 remap endurance 表 project ID，并将 active endurance run 标为 `interrupted`、清除当前 automation 指针。
- 未修改 `apps/web/**`、UI、CSS、设计令牌、Playwright 用例或视觉快照。
- 未调用真实 DeepSeek；专项测试使用 fake Phase 7 派发与确定性本地数据。

## 第十阶段 API

- `GET /api/v1/projects/{project_id}/endurance/readiness?chapterCount=5|10|20|30`
- `POST /api/v1/projects/{project_id}/endurance/suites`
- `GET /api/v1/projects/{project_id}/endurance/suites`
- `PUT /api/v1/projects/{project_id}/endurance/suites/{suite_id}`
- `POST /api/v1/projects/{project_id}/endurance/runs`
- `GET /api/v1/projects/{project_id}/endurance/runs`
- `GET /api/v1/projects/{project_id}/endurance/runs/{run_id}`
- `POST /api/v1/projects/{project_id}/endurance/runs/{run_id}/cancel`
- `POST /api/v1/projects/{project_id}/endurance/runs/{run_id}/resume`
- `POST /api/v1/projects/{project_id}/endurance/runs/{run_id}/evaluate`
- `GET /api/v1/projects/{project_id}/endurance/runs/{run_id}/findings`
- `GET /api/v1/projects/{project_id}/endurance/runs/{run_id}/report`

## 第十阶段确定性规则

- `ENDURANCE_COMMIT_SEQUENCE_GAP`
- `ENDURANCE_DUPLICATE_CURRENT_COMMIT`
- `ENDURANCE_STATE_NON_ATOMIC`
- `ENDURANCE_PACING_EARLY`
- `ENDURANCE_PACING_LATE`
- `ENDURANCE_CHARACTER_EARLY`
- `ENDURANCE_ABILITY_WINDOW`
- `ENDURANCE_ITEM_STATE_DRIFT`
- `ENDURANCE_KNOWLEDGE_LEAK`
- `ENDURANCE_FORESHADOW_MISSED`
- `ENDURANCE_REVISION_LIMIT_BREACH`
- `ENDURANCE_COST_LIMIT`
- `ENDURANCE_RESTART_DUPLICATION`
- `ENDURANCE_CONSECUTIVE_FAILURE_LIMIT`

严重度支持 `info|warning|error|blocker`；suite 的 `stopSeverity` 控制 error/blocker 是否阻断后续运行。

## 第十阶段测试结果

```text
Phase 10 focused API: 8 passed
Full API: 138 passed, 295 warnings
Web unit: 3 files / 11 tests passed
Build: passed（仅既有 Vite chunk-size warning）
Playwright e2e: 14 passed（1440×1024 与 1280×800）
```

## 已知限制与下一步

- 本阶段只提供后端基础和 API；没有新增 UI。
- `POST /endurance/runs` 会派发 Phase 7 批次；真实 20—30 章运行前必须由用户确认模型费用和本地 Provider 配置。
- 真实 20—30 章中程运行尚未执行；当前全量测试全部使用本地确定性数据，不消费 DeepSeek。
- FastAPI TestClient 与 SQLite datetime adapter 仍有上游 deprecation warning。

## 当前交给另一台电脑的任务

第十一阶段方案：`docs/plans/PHASE-11-SHORTFORM-ADAPTATION-BRIDGE.md`。

另一台电脑只实现“短篇策略与短剧改编桥梁”的后端基础、迁移、公共类型和 API 测试；不得修改 `apps/web/**`、UI、CSS、设计令牌、Playwright 或视觉快照，不调用真实 DeepSeek。完成后推送 `agent/shortform-adaptation-foundation` 并停止，返回当前 GPT-5.6 做完整审计。

---

# Story Agent 第九阶段：作品导出与发布准备交接

更新时间：2026-07-14（Codex）

当前分支：`agent/export-publishing-foundation`

第九阶段开始基线：`dc1eeb8`（来自 `agent/trial-ready-workbench`，未合并 main）

第九阶段审计提交：`b71d12c`

草稿 PR：[#7](https://github.com/zuming58/Story-Agent/pull/7)（叠加在尚未合并的 PR #8 之上）

状态：**第九阶段后端已由 GPT-5.6 完整审计、修复、全量验证并推送；可作为第十阶段开发基线。**

## 第九阶段完成内容

- 新增项目数据库迁移 `0013_export_publishing_foundation`。
- 新增数据表：`export_profiles`、`export_jobs`、`export_job_chapters`、`export_artifacts`、`publication_records`。
- 新增 `Phase9Service`，从冻结的 current official `ChapterCommit` 渲染 TXT、Markdown、DOCX、EPUB。
- 正式导出只允许 current official commit；审阅导出允许缺章，但只使用已有正式正文，并加入审阅水印与问题附录。
- 导出冻结在短 SQLite 写事务内完成；TXT/Markdown/DOCX/EPUB 渲染在事务外执行；落盘前再次校验 commit/source/draft/snapshot revision 与 checksum。
- 导出文件先写入 `exports/.tmp`，再原子 rename 到 `exports/{export_id}/`；失败、取消、漂移不登记可下载半成品。
- 支持状态机：`queued`、`validating`、`rendering`、`completed`、`blocked`、`failed`、`cancel_requested`、`cancelled`、`interrupted`。
- 服务启动时将遗留 `validating`/`rendering` 收敛为 `interrupted`，将 `cancel_requested` 收敛为 `cancelled`。
- 恢复导出复用已冻结快照；源数据漂移返回 `EXPORT_SOURCE_REVISION_CONFLICT` 并阻止继续。
- 备份保留导出元数据和 manifest，不包含 `exports/` 实体文件；恢复为新项目时 remap project ID，并将 artifacts 标为 `missing`、不可下载。
- 下载只通过 artifact ID，校验 project/export 归属和路径 containment，防止路径穿越与跨作品下载。
- publication record 仅记录用户手动确认的发布结果，不调用任何外部平台。
- 未修改 `apps/web/**`、UI、CSS、设计令牌、Playwright 用例或视觉基线。

## 第九阶段 API

- `GET /api/v1/projects/{project_id}/exports/profile`
- `PUT /api/v1/projects/{project_id}/exports/profile`
- `POST /api/v1/projects/{project_id}/exports/readiness`
- `POST /api/v1/projects/{project_id}/exports`
- `GET /api/v1/projects/{project_id}/exports`
- `GET /api/v1/projects/{project_id}/exports/{export_id}`
- `POST /api/v1/projects/{project_id}/exports/{export_id}/cancel`
- `POST /api/v1/projects/{project_id}/exports/{export_id}/resume`
- `GET /api/v1/projects/{project_id}/exports/{export_id}/artifacts/{artifact_id}/download`
- `POST /api/v1/projects/{project_id}/exports/{export_id}/publication-records`
- `GET /api/v1/projects/{project_id}/publication-records`

## 第九阶段导出就绪规则

- `EXPORT_CHAPTER_GAP`
- `EXPORT_COMMIT_NOT_CURRENT`
- `EXPORT_QUALITY_BLOCKED`
- `EXPORT_EXTRACTION_INVALID`
- `EXPORT_STATE_REFERENCE_BROKEN`
- `EXPORT_RETRIEVAL_STALE`
- `EXPORT_AUTOMATION_ISOLATED`
- `EXPORT_SOURCE_REVISION_CONFLICT`

## 第九阶段测试结果

```text
Focused Phase 9 API: 8 passed
Full API: 130 passed, 287 warnings
Web unit: 3 files / 11 tests passed
npm run test: passed
Build: passed
Playwright e2e: 14 passed
```

## 第九阶段 GPT-5.6 审计修复

- 补强 current official commit、approved draft、official source 与 state snapshot 的作品归属、互相引用、状态、revision、checksum 和正文实际摘要校验。
- 断裂或非 official 的来源链在审阅模式下也不会读取候选正文冒充正式稿。
- 修正空格式静默回退、作品总章数越界、历史隔离永久阻断和检索新鲜度判断。
- DOCX 增加标题层级、分页、目录字段、中文字体回退与审阅附录。
- EPUB 增加 EPUB 3 必需元数据、审阅说明和问题附录。
- 下载和发布登记前验证文件大小及 SHA-256，篡改 artifact 不可下载或登记。
- 恢复为新项目时 remap 导出 JSON 的 projectId 并重算 manifest checksum。

完整记录：`docs/plans/PHASE-9-AUDIT.md`。

## 当前交给另一台电脑的任务

第十阶段方案：`docs/plans/PHASE-10-LONGFORM-ENDURANCE.md`。

另一台电脑只实现“长篇中程耐久测试与漂移监控”后端基础，不修改 UI，不调用真实 DeepSeek，不操作本机正式作品数据。完成后推送 `agent/longform-endurance-foundation` 并停止，返回当前 GPT-5.6 做完整审计。

已知非阻断项：

- FastAPI TestClient 与 SQLite datetime adapter 仍有上游 deprecation warning。
- `npm run test` 需要约 7 分钟；请给审计环境设置足够超时时间。
- 第九阶段仅实现后端导出/发布准备；没有开发外部平台发布、自动发布、短剧或第十阶段功能。

---

# Story Agent 第八阶段重制交接

更新时间：2026-07-14（GPT-5.6）

当前分支：`agent/trial-ready-workbench`

草稿 PR：[#8](https://github.com/zuming58/Story-Agent/pull/8)

状态：**第八阶段代码与真实第 1—5 章验收已经完成；等待用户检查页面与试写结果后再决定是否合并 `main`。**

## 1. 当前可用能力

- 正式项目与示例项目已隔离，正式项目从第 0 章开始。
- Canon 故事架构器可生成、分析、校验、应用和锁定完整设定。
- Canon 覆盖人物、地点、组织、物品、能力、规则、关系、升级窗口与揭示边界。
- 长篇规划器已支持全书、卷、故事弧和下一批精确 `ChapterBeat`。
- 章节流水线会生成章节契约、编译上下文、写作、分段事实抽取、多角色质量复核、至多两轮修订和原子正式提交。
- 自动托管支持 1/3/5 章试写、预算保护、取消、恢复、补跑、租约恢复和运行报告。
- 候选正文、正式 Canon、状态快照和正式正文保持隔离；未经批准的候选不会污染正式状态。
- 写作模型调用期间不持有 SQLite 长写事务。

## 2. 正式试写项目

- 项目：`夜巡人·正式试写`
- Project ID：`1ffdb07d-d717-42cf-8456-30e1475b2859`
- `projectKind=standard`
- 总章数：1000
- 当前正式进度：`currentChapter=5`

Canon：

- 已通过真实 DeepSeek 完成生成、结构化分析、应用和锁定。
- 当前结构化基线为 19 个实体、10 条关系、16 条规则。
- 六阶能力、四级法器、三个第一卷核心物品、七卷边界、升级窗口和真相揭示窗口均已落盘。

规划：

- 1000 章、七卷分层规划已经应用。
- 第一卷具有升级预算、真相预算和故事弧边界。
- 第 1—5 章均有独立精确节拍，没有继承示例项目第 36 章状态。

正文验收：

| 章节 | 标题 | 结果 |
|---:|---|---|
| 1 | 午夜多出的档案袋 | 已质量复核并正式提交 |
| 2 | 不存在的门牌 | 已质量复核并正式提交 |
| 3 | 灯照旧路 | 两轮修订后正式提交 |
| 4 | 纸人不看人 | 中断恢复、两轮修订后正式提交 |
| 5 | 被遗忘的一句话 | 首稿通过阻断门并正式提交；仅保留字数 warning |

每章均有且只有一个 current official commit；本地 `canon/chapters/chapter-0001.md` 至 `chapter-0005.md` 镜像存在。真实正文、SQLite、模型密钥和费用数据只保存在本机 `.data`/Credential Manager，不进入 Git。

## 3. 本轮真实验收修复

1. 新增公开的章节任务恢复接口，服务重启后可复用已有安全候选稿，不重复调用写作模型。
2. 新增带 `expectedJobRevision` 的确定性质量重检接口；规则升级可审计地清除旧误报，不改写正文、不调用模型。
3. 修正自然中文与规划语句逐字不一致造成的完成条件误报，包括夜雾改路、巡夜灯显路、记忆代价、利用规则脱险和两次规则验证。
4. Canon 描述性名称允许受控的人物称谓变化，例如“纸童/纸人”；普通二、三字人名仍保持精确匹配。
5. 事实抽取拆成实体、状态事实、知识边界、事件伏笔四个紧凑 JSON 请求；过长或非法输出只精简重试一次。
6. 抽取置信度兼容数值和 `high/medium/low`，并强制收敛到 0—1，避免模型元数据使有效候选整体失败。
7. 写作与修订提示显式携带章节字数、人物、完成条件、钩子、伏笔和禁写边界；修订稿不得压缩到下限以下。
8. 真实审稿截断时只允许一次精简重试，不重新生成正文，也不重复抽取。
9. 第 4 章验证了人工恢复后继续同一任务；第 1—5 章验证了两轮修订上限、revision 和正式提交边界。

新增/补充接口：

- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/resume`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/quality/revalidate`

## 4. 重启与数据恢复验收

在第 1—5 章全部提交后关闭并重新启动 API，验证结果：

- `currentChapter` 仍为 5。
- 第 1—5 章 current official commit 均可读取。
- 没有残留 active chapter job。
- Canon、规划、状态快照和章节 Markdown 镜像均可恢复。
- 中断任务恢复不会创建第三轮修订，也不会重新写作已有安全候选。

## 5. 最终测试结果

```text
API：122 passed
Web：3 files / 11 tests passed
Build：passed
Playwright：14 passed，覆盖 1440×1024 与 1280×800
git diff --check：passed（仅 Windows LF/CRLF 提示）
```

已知非阻断项：

- FastAPI TestClient 与 SQLite datetime adapter 存在上游 deprecation warning。
- Vite 仍有现存 chunk-size warning；不影响当前本地试写，后续可做路由级拆包。
- 第 5 章正文略超 3000 字，质量门将其保留为 warning，未出现 error/blocker。

## 6. 安全与禁止事项

- 不提交 `.data`、SQLite、真实正文、API Key、日志、备份 ZIP、测试临时数据库或生成导出文件。
- 不修改或提交 `Story agent/` 与 `openclaw skill/` 两个参考目录。
- 不绕过 Canon 锁定、revision、租约、两轮修订上限、质量门或原子提交。
- 用户曾在对话中粘贴 DeepSeek Key；第八阶段验收完成后建议到 DeepSeek 控制台轮换该密钥。
- 当前 PR 保持草稿状态，未经用户确认不合并 `main`。

## 7. 下一阶段

第九阶段方案已写入 `docs/plans/PHASE-9-EXPORT-PUBLISHING.md`，目标是从 current official `ChapterCommit` 生成可审计的 TXT、Markdown、DOCX 和 EPUB，不直接登录或发布到番茄等外部平台。

开始第九阶段前应先：

1. 用户在 Canon、规划、章节工作台、质量中心和自动托管页面检查第八阶段体验。
2. 用户阅读第 1—5 章并把问题分类为系统 Bug、模型提示问题、故事质量问题或设定缺失。
3. 修复阻断性问题后再合并 PR #8；从最新 `main` 创建第九阶段分支。

## 8. 本地恢复点

Canon 生成前恢复包：

```text
F:\Codex\story\.data\projects\1ffdb07d-d717-42cf-8456-30e1475b2859-story\backups\20260713-121449-7b76116e-ed8b-4de5-b7d2-3a9932f3ae0e.zip
```

第 1—5 章的最新权威数据在当前项目 `story.db` 中；Git 只保存代码、测试、方案和交接记录。
