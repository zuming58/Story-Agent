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
