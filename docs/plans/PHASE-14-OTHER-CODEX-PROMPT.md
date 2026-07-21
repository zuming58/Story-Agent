# 第十四阶段另一台 Codex 提示词

把下面整段复制到另一台电脑的 Codex 对话窗口：

```text
请接手 Story Agent 第十四阶段后端开发。

GitHub 仓库：
https://github.com/zuming58/Story-Agent.git

工作分支：
agent/model-backed-story-incubator

基线提交：
081a01a

如果本地没有仓库，请自行克隆；如果已有仓库，请获取远端最新提交，确认工作区干净，
然后切换到指定分支。不要从旧的 Phase 13 本地分支继续猜测开发。

开始前必须依次完整阅读：

1. HANDOFF.md 顶部最新审计段落
2. docs/plans/PHASE-14-MODEL-BACKED-STORY-INCUBATOR.md
3. docs/plans/PHASE-13-GENERAL-STORY-INCUBATOR.md
4. docs/plans/PHASE-13-BACKEND-HANDOFF.md
5. docs/prd/PRD-001.md

本轮只实施第十四阶段真实模型后端：

- 把查询规划、证据抽取、竞品分析、故事机会、多轮共创、StoryBrief、通用 Canon、
  三种开篇及读者/编辑评审接入现有 OpenAI-compatible 模型基础设施；
- 复用 research_planner、research_analyst、story_incubator、reader_simulator、
  opening_editor 角色绑定；
- 所有模型调用创建并收敛 ModelRun，调用期间不得持有 SQLite 写事务；
- 保持来源证据、上游 checksum、revision、提案确认、三章人工批准和 Canon 锁定关卡；
- 修正机会评分必须总计 100 的错误：totalScore 应为 0—100 的自然求和；
- 失败必须明确失败，不得静默返回占位调研、占位创意、模板 Canon、模板开篇或固定评分；
- 自动测试使用 FakeModel 和确定性搜索/抓取 Provider，不调用真实服务。

严格禁止：

- 不修改 apps/web/**、CSS、设计令牌、页面组件和 Playwright 视觉快照；
- 不提交 API Key、.data、SQLite、日志、备份 ZIP、模型正文或测试临时文件；
- 不读取、修改或继续生成用户的《夜巡人》正式作品；
- 不调用真实 DeepSeek、Tavily 或 Firecrawl；
- 不自动接受研究、StoryBrief、Canon 或开篇；
- 不把竞品原文、专有设定或模仿作者风格写入提示词；
- 不合并 main，不提前实施 UI 或后续阶段。

开发结束前必须：

1. 运行 Phase 14 专项、API 全量、Web 单测、Build、Playwright、compileall 和
   git diff --check；若环境限制无法完成，必须如实记录，禁止误报通过；
2. 更新 HANDOFF.md 顶部，写明完成项、未完成项、数据库/API 变化、测试结果、
   已知风险和最新提交；
3. 提交并推送 agent/model-backed-story-incubator；
4. 停止开发，等待 GPT-5.6 审计，不要继续扩展功能。

完成后在对话中回复准确分支、基线、最新提交和测试结果。
```
