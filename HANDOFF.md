# Story Agent 第八阶段重制交接

更新时间：2026-07-13 20:10（Asia/Shanghai）
当前分支：`agent/trial-ready-workbench`
开发基线：`9277241`
草稿 PR：[#8](https://github.com/zuming58/Story-Agent/pull/8)
状态：**第八阶段重制进行中；真实模型调用已按用户要求停止，禁止跳过 Canon 直接写正文。**

## 1. 当前准确进度

本次重制的目标顺序是：

```text
正式空白作品（currentChapter=0）
→ 完整 Canon 提案
→ Canon 确定性审计与锁定
→ 1000 章分层规划提案
→ 第 1—5 章精确 ChapterBeat
→ 从第 1 章真实试写与质量复核
→ 连续验证第 2—5 章
```
当前停在 **Canon 生成的分段检查点已经写入本机 SQLite，但尚未形成可应用提案**：

- 正式作品：`夜巡人·正式试写`
- 本机 project id：`1ffdb07d-d717-42cf-8456-30e1475b2859`
- `projectKind=standard`
- `currentChapter=0`
- Canon 检查点 proposal id：`b9966e4e-26fc-45cd-b035-13486c6a7753`
- proposal 状态：`failed`（人为停止服务后由启动恢复逻辑收敛，不表示内容作废）
- 已完成并保留：`core` 1694 字符、`systems` 2745 字符
- 未完成：精简 Canon Analyzer、提案应用、Canon 锁定
- 正式规划尚未应用；第 1—5 章尚未生成；正式正文仍为 0 章

本机 `.data` 不进入 Git。另一台电脑只克隆仓库时不会自动获得上述 proposal 和正文数据；需要续用精确检查点时，应导入本机项目备份 ZIP。若不传备份，另一台电脑需用自己的 Windows Credential Manager 配置密钥并重新生成 Canon。

已生成可携带的恢复包（`isValid=true`，不包含 Credential Manager 密钥）：

```text
F:\Codex\story\.data\projects\1ffdb07d-d717-42cf-8456-30e1475b2859-story\backups\20260713-121449-7b76116e-ed8b-4de5-b7d2-3a9932f3ae0e.zip
```

备份 ID：`7b76116e-ed8b-4de5-b7d2-3a9932f3ae0e`，大小 51,388 bytes。请用 U 盘、局域网或个人云盘单独复制到另一台电脑，再通过项目恢复接口上传；不要提交 Git。恢复会创建一个新项目，不覆盖原项目。导入后仍需在另一台 Windows Credential Manager 单独配置 DeepSeek 密钥。

## 2. 已完成代码

### 2.1 演示项目与正式项目隔离

- 新增 `projectKind: demo | standard`。
- Catalog migration：`0006_project_kind.py`。
- Project migration：`0012_story_architecture.py`；规划节拍 migration：`0011_plan_node_chapter_beats.py`。
- 旧种子作品标记为 demo；正式项目始终 `currentChapter=0`。
- 工作区优先打开 standard 项目。
- demo 项目禁止真实付费自动写作；就绪检查新增 `TRIAL_STANDARD_PROJECT_REQUIRED`。

### 2.2 Story Architect 与 Canon 提案

- 新增 `StoryBrief`、`CanonGenerationProposal`、`CanonReadiness` 及持久化表/API。
- `/canon` 保留“墨曜指挥舱”视觉，增加故事架构器、提案预览、检查结果、接受与拒绝入口。
- Architect 改为分段生成，并新增持久化检查点：每完成一段即落盘；超时或服务重启后只续跑失败段。
- 启动恢复会把遗留 `generating` 收敛为 `failed`，但保留 `generationSections`。
- 第一次真实提案因 AI 自行安排章节导致法器和揭示时间冲突，已拒绝并保留审计记录，绝不能恢复为正式 Canon。

### 2.3 双层权威与确定性检查

- AI 只负责故事内核、世界、人物和规则细节。
- 系统生成 `AUTHORITATIVE_CANON_BOUNDARIES`，固定：七卷范围、第一卷升级预算、三件法器获得/使用窗口、分层揭示窗口、前五章契约和文风边界。
- AI 描述中的章节数字在合并前被剥离，章节预算只有一个权威来源。
- Canon Analyzer 改为精简创意补充；六阶、法器、揭示窗口等关键实体/关系/规则由确定性基线保证，不允许模型重定义。
- `_canon_checks` 由“任一关键词命中”改为完整硬边界检查。

### 2.4 分层长篇规划器

- 新增 `PlanGenerationProposal`、`StoryBudget` 及生成/接受/拒绝 API。
- 固定七卷连续覆盖 1—1000 章。
- 固定第 1—5 章 ChapterBeat。
- 固定等级、法器、纸童身份第一层和童年真相第一层的 earliest/target/latest 台账。
- `/planning` 增加分层规划入口；现有视觉结构不变。
- **代码与单元测试已完成，但尚未在真实 Canon 上运行和应用。**

### 2.5 章节流水线修复

- 章节契约必须读取当前章精确 ChapterBeat；缺少节拍时阻断。
- 抽取拆成 entities、facts、boundaries、events/foreshadows 四个小 JSON 请求。
- 每个抽取子任务最多精简重试一次；仍失败则保存 rejected 错误并隔离候选稿。
- 取消、失败、旧契约任务不得错误复用；安全中断候选可以恢复且不重复调用写作模型。
- 人工恢复重开失败计数窗口；同一窗口两次模型失败阻断。
- 候选稿不污染正式状态；正文、事实、伏笔、快照和提交仍保持原子事务。
- **尚未执行真实第 1—5 章验收。**

## 3. 真实模型试验记录

- DeepSeek 密钥只在本机 Windows Credential Manager；未写入 Git、SQLite、日志、备份或 API 响应。
- 首次单体 Canon 调用：`content_truncated`，未产生提案。
- 第二次分段调用形成提案 `a17a245e-...`，但审计发现章节台账冲突，已明确 `rejected`。
- 重制后调用出现一次 Analyzer `content_truncated`、一次 systems `timeout`，据此补上精简 Analyzer 和分段检查点。
- 最后一轮在用户要求停止前，core 与 systems 均已成功并写入检查点；外部调用已终止。
- 不得把模型超时误写成“第八阶段完成”，也不得为了赶进度直接锁定未审计内容。

## 4. 下一台电脑必须按此顺序执行

### 关卡 A：先完成代码收尾，不调用真实模型

1. 完整阅读本文件、`docs/plans/PHASE-8-REMAKE-REAL-WRITING.md`、原 PRD 和 Phase 4/5/7 文档。
2. 比较 `9277241..HEAD`，审计本轮未提交变更，特别检查 migration 链、proposal revision、检查点恢复和跨作品隔离。
3. 为 Canon 检查点补测试：
   - core 成功、systems 超时后 proposal 必须保存 core；
   - 服务重启后 `generating → failed`；
   - 相同 brief 重试只调用缺失段；
   - 不同 brief 或 Canon revision 变化不能复用旧检查点；
   - 两次 Analyzer 非法 JSON 后必须失败，不能应用半成品。
4. 运行 focused API、Web 单元测试和 build，先修代码问题。
5. 不修改 UI/CSS/设计令牌/视觉快照；UI 由当前电脑维护。

### 关卡 B：完成 Canon（获得用户密钥或备份后）

1. 若导入本机备份，确认 checkpoint 包含 `core` 和 `systems`；否则新建/确认正式项目从第 0 章开始。
2. 配置 DeepSeek Credential Manager，绝不要求用户把 Key 写进文件或对话日志。
3. 对同一 StoryBrief 再次调用 Canon generation endpoint；有检查点时只能运行 `architect:proposal-analysis`，不得重跑 core/systems。
4. 核对 proposal：六阶、四类法器、三件物品、人物知识边界、七卷、第一卷升级窗口、分层揭示窗口、前五章契约。
5. 自动检查全部 ready 后再 apply；随后二次确认 lock。
6. 记录本次 ModelRun、Token、费用和失败重试，不记录模型原始密钥。

### 关卡 C：规划与第 1—5 章

1. 生成并应用 1000 章分层规划；确认七卷连续且第 1—5 章都有独立 ChapterBeat。
2. 确认 `currentChapter=0`、chapter 1 readiness ready。
3. 只运行第 1 章；检查契约、候选稿、四组抽取、确定性质量门、多角色评审和正式原子提交。
4. 第 1 章通过后，依次生成第 2—5 章；不得直接从 3/5 章批次掩盖单章错误。
5. 逐章检查人物知识、等级、法器持有人/次数/代价/损坏状态、伏笔和目标消耗。
6. 重启 API，确认恢复到正确章节且不重复调用已完成步骤。
7. 生成正文和 `.data` 不提交 Git。

### 关卡 D：全量验证与交回

必须运行：

```powershell
npm run test
npm run build
npm run test:e2e
```

更新本文件，记录完成项、失败项、真实 ModelRun、费用、最新提交和测试结果；推送当前分支，不合并 `main`，然后停止等待 GPT-5.6 审计。

## 5. 当前已验证与未验证

已通过：

- `apps/api/tests/test_phase8_architecture.py`：2 passed。
- Phase 7 三个回归边界与上项合跑：5 passed。
- Web Vitest：3 files / 11 tests passed。
- Web build：通过，仅既有 Vite chunk-size warning。
- Python compileall：通过（在检查点代码之前通过；交接方需重跑）。

尚未完成：

- checkpoint 专项测试。
- API 全量测试（上一轮发现 3 个旧测试仍错误使用 demo，已改为 standard，focused 已通过）。
- Playwright 全量与两个分辨率视觉复验。
- 真实 Canon apply/lock。
- 真实规划 apply。
- 真实第 1—5 章及重启恢复。

## 6. 安全与禁止事项

- 不提交 `.data`、`.e2e-data`、API Key、SQLite、日志、备份 ZIP、真实生成正文或临时文件。
- 不修改或提交 `Story agent/` 和 `openclaw skill/`。
- 不把 rejected proposal `a17a245e-...` 应用为正式 Canon。
- 不从演示项目第 36/37 章继续真实小说。
- 不绕过 Canon 锁定、ChapterBeat、revision、提案确认、质量门或原子提交。
- 不在模型调用期间持有 SQLite 长写事务。
- 不修改 UI 风格；如发现 UI Bug，只记录到交接文件，返回当前电脑修复。
- 当前分支不得合并 `main`。

## 7. 另一台 Codex 提示词

```text
请接手 Story Agent 第八阶段重制。

仓库：https://github.com/zuming58/Story-Agent.git
分支：agent/trial-ready-workbench
草稿 PR：https://github.com/zuming58/Story-Agent/pull/8

开始前完整阅读：
1. HANDOFF.md
2. docs/plans/PHASE-8-REMAKE-REAL-WRITING.md
3. docs/plans/PHASE-5-CHAPTER-PIPELINE.md
4. docs/plans/PHASE-7-AUTOMATION.md
5. docs/prd/PRD-001.md

严格按 HANDOFF.md 的关卡 A→B→C→D 执行。先补检查点测试和完成代码审计，再进行真实模型验收。不得跳过 Canon/规划直接写章节。

UI、CSS、设计令牌和视觉快照由另一台电脑维护，本轮禁止修改。禁止提交密钥、.data、数据库、日志、备份 ZIP 和真实正文。完成后运行全量测试，更新 HANDOFF.md，提交并推送当前分支，不合并 main，然后停止等待 GPT-5.6 审计。
```
