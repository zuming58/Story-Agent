# 第九阶段：作品导出与发布准备

状态：已由第八阶段“可试写版”顺延，等待第八阶段用户验收后实施
建议分支：`agent/export-publishing-foundation`
范围所有权：先完成导出后端、数据库、文件渲染、公共 API 类型和 API 测试；UI 继续由当前电脑维护

## 1. 阶段目标

把已经正式通过质量门的章节，稳定地生成可发布文件，并保留可审计、可重复、可恢复的导出快照：

```text
选择正式章节范围
  -> 发布前就绪检查
  -> 在短事务中冻结 commit/source/snapshot/checksum 清单
  -> 在事务外渲染 TXT / Markdown / DOCX / EPUB
  -> 校验源 revision 未漂移
  -> 原子写入 exports/ 并生成 SHA-256 manifest
  -> 用户可下载，或手工登记已发布记录
```

本阶段不登录番茄等外部平台，不发送文件到第三方，不开发短篇策略和短剧改编。

## 2. 数据权威与不变式

- 正式导出的唯一正文来源是每章 `is_current = true` 的 `ChapterCommit` 及其 `approved_draft_id`，禁止读取 current candidate 充当正式正文。
- `SourceVersion` 必须为 `official`，且 `ChapterCommit`、`SourceVersion`、`StateSnapshot`、approved draft 的引用必须一致。
- 正式导出范围必须章节连续；任一缺章、非 current commit、open blocker/error、失效抽取、状态引用断裂或待更新检索都会阻止正式导出。
- 审阅版允许缺章和隔离章节，但只能输出已有正式正文；缺口用明显水印与问题附录表示，不能偷偷用候选稿补齐。
- 选章快照在短 SQLite 事务内冻结；DOCX/EPUB/TXT/Markdown 渲染必须在事务外执行。
- 文件落盘前重新校验 commit revision、is_current 和 checksum。漂移时返回 `EXPORT_SOURCE_REVISION_CONFLICT`，不得发布过期产物。
- 所有文件先写入 `exports/.tmp/`，完成校验后原子 rename；失败、取消和冲突不得留下可下载的半成品。
- 下载路径必须由 artifact ID 解析，且经过 resolved-path containment 检查；API 不接受任意文件路径。
- 导出不获取自动写作租约，可与写作并行，但必须依靠冻结快照与最终 revision 校验保证一致性。

## 3. 数据库设计

新增项目迁移 `0011_export_publishing_foundation`（如前序审计新增迁移导致编号变化，以实际 head 顺延）：

### `export_profiles`

- 每项目一条：`project_id`、默认格式、书名/作者/简介、章节命名模板、是否附带质量摘要、revision 与时间字段。
- 更新必须携带 `expectedRevision`。

### `export_jobs`

- `id`、`project_id`、`mode(formal|review)`、章节起止、格式清单、idempotency key。
- 状态：`queued|validating|rendering|completed|blocked|failed|cancel_requested|cancelled|interrupted`。
- 冻结快照摘要、问题摘要、停止原因、diagnostic、revision 与时间字段。
- 同项目非空 idempotency key 唯一。

### `export_job_chapters`

- `export_job_id`、章节号、顺序号、`chapter_commit_id`、`approved_draft_id`、`source_version_id`、`state_snapshot_id`。
- 保存各源 revision、正文 checksum、source checksum 和质量摘要。
- 同一 job/chapter 唯一。

### `export_artifacts`

- `export_job_id`、format、相对路径、MIME、文件名、SHA-256、字节数、manifest、状态与时间字段。
- 同一 job/format 只允许一个 current artifact；重生成保留历史或明确 supersede，不得原地静默覆盖。

### `publication_records`

- 只记录用户明确确认的人工发布结果：artifact、平台、外部作品/章节引用、发布时间、备注、revision。
- 该表不触发任何网络发布；不能凭导出完成自动创建“已发布”记录。

## 4. 就绪检查

新增确定性的 readiness service，至少返回：

- `ready`、`mode`、范围、可导出章节数。
- blocker/warning 列表：规则编号、章节、证据、修复建议。
- 缺章、非 current commit、open blocker/error、抽取失效、source/state 断链、检索陈旧、自动化 isolated/blocked item。
- 当前可安全导出的格式与预计文件名。

建议规则编号：

- `EXPORT_CHAPTER_GAP`
- `EXPORT_COMMIT_NOT_CURRENT`
- `EXPORT_QUALITY_BLOCKED`
- `EXPORT_EXTRACTION_INVALID`
- `EXPORT_STATE_REFERENCE_BROKEN`
- `EXPORT_RETRIEVAL_STALE`
- `EXPORT_AUTOMATION_ISOLATED`
- `EXPORT_SOURCE_REVISION_CONFLICT`

## 5. 文件格式

第一版必须同时支持：

- TXT：UTF-8，统一章节标题与换行。
- Markdown：作品元数据、目录和章节正文；正文保持 Markdown。
- DOCX：有效 Office Open XML，标题层级、分页、目录字段或可读目录、中文字体回退。
- EPUB：有效 EPUB 3 容器、metadata、nav、spine、每章独立 XHTML。

四种格式必须来自同一冻结快照，manifest 中记录全部 commit/checksum。正式版不得带内部诊断；审阅版必须带水印、缺口和问题附录。

## 6. API

- `GET|PUT /api/v1/projects/{project_id}/exports/profile`
- `POST /api/v1/projects/{project_id}/exports/readiness`
- `POST /api/v1/projects/{project_id}/exports`
- `GET /api/v1/projects/{project_id}/exports`
- `GET /api/v1/projects/{project_id}/exports/{export_id}`
- `POST /api/v1/projects/{project_id}/exports/{export_id}/cancel`
- `POST /api/v1/projects/{project_id}/exports/{export_id}/resume`
- `GET /api/v1/projects/{project_id}/exports/{export_id}/artifacts/{artifact_id}/download`
- `POST /api/v1/projects/{project_id}/exports/{export_id}/publication-records`
- `GET /api/v1/projects/{project_id}/publication-records`

JSON 使用 camelCase，ID 使用 UUID4，时间使用 UTC ISO 8601。所有错误沿用 `ApiError`；幂等重试返回原 job，不重复生成文件。

## 7. 恢复、备份与隔离

- 服务启动把遗留 `validating/rendering/cancel_requested` 收敛为 `interrupted/cancelled`；不得自动继续生成文件。
- resume 复用冻结章节快照；若当前正式源已漂移，必须重新 readiness/重新创建 job，不得继续旧快照。
- 项目备份保留导出 job、章节快照、artifact manifest 和 publication history，但 `exports/` 实体文件作为派生数据不进入 ZIP。
- 恢复为新项目时 remap 所有 project ID；artifact 标记为 `missing`/不可下载，可按未漂移快照重新生成。
- 两个作品的文件目录、job、artifact、manifest 和发布记录完全隔离。

## 8. 测试与验收

必须覆盖：

- 1—N 章连续正式 commit 能生成四种格式，内容与章节顺序一致。
- 缺章、非 current commit、open blocker/error、source/state 断链阻止正式导出。
- 审阅版对缺章输出水印与问题附录，且不读取候选稿冒充正文。
- 渲染期间源 revision 漂移会整体失败，不产生 current artifact。
- 渲染异常、取消、磁盘写入失败不会留下半文件，数据库状态与文件系统一致。
- TXT/Markdown 编码正确；DOCX 可被 zip/XML 校验打开；EPUB mimetype、container、nav、spine 有效。
- idempotency、并发创建、restart/interrupted/resume 行为确定。
- 路径穿越、跨作品 artifact 下载和猜测 ID 均被拒绝。
- 备份恢复保留元数据与发布历史，但恢复项目不把缺失 artifact 标记成可下载。
- publication record 只有显式 API 调用才能创建，不执行外部网络请求。
- 全量 API 测试通过；不得修改或运行 UI 快照更新。

## 9. 交付规则

1. 从第八阶段验收合并后的最新 `main` 创建 `agent/export-publishing-foundation`。
2. 完成后更新 `HANDOFF.md`，记录迁移、表、接口、状态机、格式验证、测试数和已知问题。
3. 提交并推送功能分支，不合并 `main`。
4. 不修改 `apps/web/**`、CSS、设计令牌、UI 文案或 Playwright 文件。
5. 不提交 `.data`、API Key、SQLite、导出成品、备份 ZIP、日志和临时文件。
6. 停止开发，等待当前 GPT-5.6 审计；不要提前开发自动托管 UI 或第九阶段。

第九阶段先以稳定导出为目标，不登录或自动发布到番茄等外部平台。
