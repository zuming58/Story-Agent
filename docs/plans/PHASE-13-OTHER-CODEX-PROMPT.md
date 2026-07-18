# 第十三阶段：粘贴给另一台 Codex 的执行提示词

把下面整段复制到另一台电脑的 Codex 对话窗口：

```text
请接手 Story Agent 第十三阶段后端开发。

GitHub 仓库：
https://github.com/zuming58/Story-Agent.git

工作分支：
agent/general-story-incubator-foundation

如果本地没有仓库，请自行克隆；如果已有仓库，请获取远端最新提交并切换到指定分支。必须确认本地 HEAD 与远端分支一致、工作区干净后再开始。

开始开发前，必须依次完整阅读：

1. HANDOFF.md
2. docs/plans/PHASE-13-GENERAL-STORY-INCUBATOR.md
3. docs/plans/PHASE-13-BACKEND-HANDOFF.md
4. docs/prd/PRD-001.md
5. docs/ui/UI-DESIGN-BASELINE.md
6. design-qa.md

本轮完整执行 docs/plans/PHASE-13-BACKEND-HANDOFF.md，只开发后端：

- 市场研究 Brief、研究任务状态机、搜索/网页提取 Provider 接口；
- 来源、版本、证据、查询和研究用量台账；
- 竞品矩阵、研究 findings、故事机会与爆款潜力分项；
- 多轮创意会话、StoryBrief 提案和版本权威链；
- 通用 Canon 草稿生成，隔离夜巡人硬编码；
- 三种开篇实验、独立读者/故事编辑评审、人工选择和 StyleBaseline；
- revision、事务、跨作品隔离、备份恢复、审计和完整测试。

实现要求：

1. 可插拔 SearchProvider 与 ContentFetchProvider；实现 Tavily 搜索适配器、可选 Firecrawl 提取适配器，以及测试专用确定性 Provider。
2. 所有真实搜索、抓取和模型调用在 SQLite 写事务外执行，落盘前重新校验上游 revision/checksum。
3. 密钥只能保存在 Windows Credential Manager；API、日志、数据库和备份不得出现完整密钥。
4. 必须防止 SSRF：拒绝环回、私网、file/非 HTTP(S) 协议，并重新校验重定向最终地址。
5. 不绕过登录、付费墙、验证码、robots/站点限制或反爬；不保存完整版权小说或大段原文。
6. 没有足够证据时返回 insufficient_evidence，禁止模型虚构市场事实。
7. StoryBrief、Canon、开篇候选必须使用 pending → apply/reject 或人工 select 流程，未经确认不得污染正式状态。
8. 前三章禁止自动批准和自动提交。

严格禁止：

- 不修改 apps/web/**、CSS、设计令牌、页面组件、Playwright 页面用例或视觉快照；
- 不调用真实 Tavily、Firecrawl、DeepSeek，不消费用户余额；
- 不触碰或提交 .data、API Key、数据库、日志、抓取缓存、备份 ZIP、临时文件或生成正文；
- 不继续生成《夜巡人》第 10 章；
- 不把夜巡人、沈砚、雾城、1000 章、七卷、六阶能力写成通用默认值；
- 不合并 main，不关闭或合并 PR，不提前开发 UI。

如果发现文档与现有代码冲突，以实际代码和数据安全为准，先在 HANDOFF.md 记录差异，再采用兼容迁移；不得删除用户数据或扩大修改范围。

完成后必须：

1. 运行 Phase 13 专项、API 全量、Web 单测、npm run build、npm run test:e2e、compileall 和 git diff --check；
2. 更新 HANDOFF.md，记录完成项、迁移、表、API、状态机、事务边界、测试结果、已知问题和最新提交；
3. 提交并推送 agent/general-story-incubator-foundation；
4. 确认本地与远端 HEAD 一致且工作区干净；
5. 停止开发，等待 GPT-5.6 审计，不要继续做下一阶段。

最终回复请给出：分支、基线提交、最新提交、修改文件数量、迁移 head、测试明细、已知限制和远端推送结果。
```

另一台电脑完成后，回到当前电脑对 GPT-5.6 发送：

```text
另一台电脑已经完成第十三阶段后端并推送。

请读取 HANDOFF.md、docs/plans/PHASE-13-GENERAL-STORY-INCUBATOR.md、docs/plans/PHASE-13-BACKEND-HANDOFF.md，并以交接文件记录的基线审计 agent/general-story-incubator-foundation 最新提交。

重点审计研究来源可追溯性、证据不足降级、SSRF、密钥安全、搜索/模型调用长事务、revision 漂移、竞品版权边界、爆款评分证据、StoryBrief/Canon/开篇候选隔离、前三章人工门、跨作品隔离、备份恢复和测试完整性。发现问题请直接修复并运行全量测试；不要修改 UI 风格。
```
