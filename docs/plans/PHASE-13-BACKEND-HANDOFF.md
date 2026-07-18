# 第十三阶段后端交接：市场研究与故事孵化基础

## 1. 唯一任务

另一台电脑只实现第十三阶段后端：把“有来源的竞品研究 → 故事机会 → 多轮共创 → StoryBrief → Canon 草稿 → 开篇候选”做成可持久化、可恢复、可审计的业务链。

禁止修改 `apps/web/**`、CSS、设计令牌、Playwright 页面用例和视觉快照。UI 由当前电脑 GPT-5.6 审计后开发。

当前分支：

```text
agent/general-story-incubator-foundation
```

开始前以远端最新提交为准，并依次完整阅读：

1. `HANDOFF.md`
2. `docs/plans/PHASE-13-GENERAL-STORY-INCUBATOR.md`
3. `docs/plans/PHASE-13-BACKEND-HANDOFF.md`
4. `docs/prd/PRD-001.md`
5. `docs/ui/UI-DESIGN-BASELINE.md`
6. `design-qa.md`

## 2. 开发前审计

- 核对 Alembic catalog/project 两套迁移 head，新增 project migration 使用下一个连续编号。
- 搜索 `phase8.py` 中夜巡人、沈砚、雾城、1000 章、七卷、六阶和固定 Beat；记录所有生产硬编码入口。
- 核对 Windows Credential Manager `SecretStore`、模型角色绑定、模型调用审计与备份恢复模式，复用既有基础。
- 不修改或删除用户 `.data`；《夜巡人》正式项目停在第 9 章，不发起模型或搜索调用。

## 3. 工作包 A：研究 Provider 与安全策略

定义稳定接口：

- `SearchProvider.search(query, domains, date_range, limit)`
- `ContentFetchProvider.fetch(url, max_chars)`
- 归一化结果必须包含 URL、标题、摘要、发布时间、抓取时间、来源域名、Provider 元数据和用量。
- 首个真实适配器使用 Tavily；Firecrawl 为可选页面提取适配器。
- 测试实现 `DeterministicSearchProvider` 与 `DeterministicContentFetchProvider`，固定 fixture，不访问网络。

安全边界：

- 密钥只保存在 Credential Manager，数据库只保存 `secretRef`/`hasSecret`。
- 禁止记录请求头、完整密钥或包含密钥的异常字符串。
- 只访问公开 HTTP(S) 页面；拒绝本机、环回、私有网段、`file:` 和其他协议，防止 SSRF。
- 重定向后的最终地址必须再次校验。
- 不绕过登录、付费墙、验证码、robots/站点限制或访问控制。
- 每个任务设置查询数、页面数、单页字符、总字符、费用和运行时间上限。
- 搜索、抓取和模型调用均在 SQLite 写事务外执行。

## 4. 工作包 B：研究目标、任务状态机与来源台账

新增模型：

- `MarketResearchBrief`
- `ResearchJob`
- `ResearchQuery`
- `ResearchSource`
- `ResearchSourceVersion`
- `ResearchEvidence`

状态机：

```text
draft → queued → planning → searching → fetching → analyzing
→ awaiting_review | insufficient_evidence | failed | cancelled
awaiting_review → accepted | rejected
insufficient_evidence/failed/cancelled → queued（显式恢复并开启新 attempt）
```

要求：

- Brief 保存平台、题材、受众、作品形态、篇幅、情绪价值、研究时间范围、域名范围和禁写内容。
- 启动任务冻结 brief revision/checksum 和 Provider 配置摘要。
- Query 记录研究视角、查询文本、顺序、状态、错误和用量。
- Source 以规范化 URL 去重；Version 保存内容 checksum、抓取时间和有界正文/摘要。
- Evidence 保存短片段、来源版本、位置、主张类型、置信度和关联结论；禁止保存完整版权章节。
- 研究至少覆盖平台趋势、同题材头部作品、读者好评、弃书原因、开篇策略和连载持续性。
- 证据少于策略阈值或来源类型不足时必须 `insufficient_evidence`，不得让模型补齐为事实。
- 取消、服务重启和租约恢复不得重复搜索、重复抓取或重复计费。

## 5. 工作包 C：竞品卡、研究结论与故事机会

新增模型：

- `CompetitorProfile`
- `ResearchFinding`
- `StoryOpportunity`

竞品卡字段至少覆盖：阅读承诺、目标读者、开篇钩子、主角欲望、情绪回报、世界辨识度、连载发动机、阶段满足、好评原因、弃书原因、风险、证据列表和置信度。

规则：

- 事实字段必须引用 Evidence；AI 综合必须标为 inference。
- 不保存大段原文、人物/设定复刻建议或“模仿某作者文风”的指令。
- 竞品被排除后生成新报告 revision；旧报告和证据保留。
- 每个 StoryOpportunity 保存高概念、人物、欲望、冲突、世界机制、前三章承诺、连载发动机、差异化、风险和证据。
- 爆款潜力分项固定总分 100：平台适配 15、开篇钩子 15、情绪回报 15、差异化 15、连载发动机 15、人物黏性 10、世界观发动机 10、可读性 5。
- 同时输出 `evidenceCoverage`、`confidence` 和 `uncertainties`；不允许只有一个“爆款分数”。
- 接受/拒绝机会携带 expected revision；同一项目只有一个 accepted current opportunity。

## 6. 工作包 D：创意会话与 StoryBrief 权威链

新增或扩展：

- `IdeationSession`
- `IdeationMessage`
- `StoryBriefVersion`
- `StoryBriefProposal`

要求：

- 会话冻结 accepted opportunity 与 research report checksum。
- 每轮模型输出结构化维护 `confirmedDecisions`、`openQuestions`、`aiSuggestions`、`conflicts` 和证据引用。
- 对话消息只是创意素材，不是正式设定。
- StoryBrief 包含 format、platform、audience、篇幅、premise、readerPromise、theme、tone、pov、pace、endingDirection、protagonist、coreDesire、coreConflict、worldMechanism、serialEngine、emotionalRewards、differentiators、forbiddenContent、referenceTraits 和上游研究引用。
- 只有 accepted `StoryBriefProposal` 能原子创建新的 current `StoryBriefVersion`。
- 拒绝不改变 current；历史版本永久保留；旧 research/opportunity 漂移阻止 apply。
- 模型 JSON 空或非法只允许一次修复；模型调用期间不持有写事务。

## 7. 工作包 E：通用 Canon 与夜巡人模板隔离

- 将 Phase 8 固定夜巡人数据迁移为显式 `night-watch-demo` 模板。
- 空白项目必须从 current StoryBrief 生成，不能出现夜巡人、沈砚、雾城、1000 章、七卷或六阶残留。
- Canon 提案冻结 StoryBrief version/checksum、research checksum 和 opportunity id。
- Canon 条件化支持人物/关系、世界规则、资源/能力/职业、代价、秘密层级、揭示窗口、文风和禁写边界。
- Brief 未声明等级、法宝、怪异规则时允许 `notApplicable`，不能强制补成玄幻/怪谈。
- Canon 只生成草稿提案，不自动锁定，不直接创建 1000 章规划。
- 上游漂移、revision 冲突和不完整 findings 阻止应用。

## 8. 工作包 F：开篇实验后端

新增：

- `OpeningExperiment`
- `OpeningCandidate`
- `ReaderEvaluation`
- `StyleBaseline`

要求：

- 从同一 current StoryBrief + Canon 草稿生成三种策略：强事件、强人物、强悬念；允许 API 传入自定义策略。
- 第一轮每个候选只生成第一章；用户选择后才允许扩展为前三章。
- 候选正文和评审不能写入正式 ChapterCommit、Canon、Plan 或状态快照。
- 使用独立 `reader_simulator` 与 `opening_editor` 角色评审，不得只用写作模型自评。
- finding 覆盖第一屏钩子、人物欲望、情绪牵引、场景张力、解释密度、编号/术语重复、对话/动作/说明比例和章末继续阅读欲望。
- 读者评审需保存定位片段/范围和建议；不得只返回总分。
- 前三章禁止自动批准或自动提交。
- 用户 reject 全部候选后返回 Brief 共创；select 候选时创建 StyleBaseline，保存正文 checksum、抽象文风规则和禁用模式。
- StyleBaseline 不是正式正文，直到后续 UI 流程由用户明确批准物化。

## 9. API

至少实现：

- `POST/GET /api/v1/projects/{project_id}/research/briefs`
- `POST/GET /api/v1/projects/{project_id}/research/jobs`
- `GET /api/v1/research/jobs/{job_id}`
- `POST /api/v1/research/jobs/{job_id}/cancel`
- `POST /api/v1/research/jobs/{job_id}/resume`
- `GET /api/v1/research/jobs/{job_id}/sources`
- `GET /api/v1/research/jobs/{job_id}/evidence`
- `GET /api/v1/research/jobs/{job_id}/competitors`
- `GET /api/v1/research/jobs/{job_id}/findings`
- `POST /api/v1/research/jobs/{job_id}/opportunities`
- `POST /api/v1/story-opportunities/{id}/accept|reject`
- `POST/GET /api/v1/projects/{project_id}/ideation/sessions`
- `GET /api/v1/projects/{project_id}/ideation/sessions/{session_id}`
- `POST /api/v1/ideation/sessions/{session_id}/messages`
- `POST /api/v1/ideation/sessions/{session_id}/story-brief-proposals`
- `GET /api/v1/projects/{project_id}/story-brief/versions|current`
- `POST /api/v1/story-brief-proposals/{id}/apply|reject`
- `POST/GET /api/v1/projects/{project_id}/opening-experiments`
- `GET /api/v1/opening-experiments/{id}`
- `POST /api/v1/opening-candidates/{id}/select|reject`
- `POST /api/v1/opening-experiments/{id}/expand-to-three-chapters`
- `GET /api/v1/projects/{project_id}/incubation-readiness`

JSON 使用 camelCase，ID 使用 UUID4，时间使用 UTC ISO 8601。所有写接口携带 expected revision；冲突返回 409 和 current revision。

## 10. 备份恢复与审计

- 项目 ZIP 必须包含所有新表和有界来源内容，继续使用 SHA-256 manifest。
- 恢复为新项目时 remap project id、session/job/opportunity/Brief/Canon/opening UUID 及所有外键。
- Provider 密钥、抓取缓存、完整外部页面、用户 `.data` 路径和临时文件不得进入备份。
- AuditEvent 记录启动、取消、恢复、接受、拒绝、漂移、Provider 错误和人工选择，不记录模型思维链或完整密钥。
- 搜索/抓取/模型用量进入模型或研究运行审计，能够按 job 汇总费用。

## 11. 测试要求

新增专项覆盖：

- 研究 Brief 冻结与 revision 漂移。
- SSRF：环回、私网、重定向私网和非法协议全部拒绝。
- 密钥缺失、超时、限流、取消、恢复、租约丢失和幂等重试。
- URL 去重、页面版本、证据引用和证据不足状态。
- 竞品排除后重新综合且旧报告不变。
- 爆款潜力分项合计、覆盖度、置信度和证据关联。
- 机会/Brief 接受拒绝、上游漂移、跨作品隔离和事务回滚。
- 非怪谈长篇/无等级短篇无夜巡人残留并通过 Canon readiness。
- 开篇三策略结构差异、候选隔离、独立角色评审和人工选择限制。
- 自动提交前三章必须被拒绝。
- 服务重启、备份恢复、UUID remap 和审计完整性。

最终必须运行：

```powershell
npm run test
npm run build
npm run test:e2e
apps\api\.venv\Scripts\python.exe -m compileall -q apps/api/src apps/api/tests
git diff --check
```

测试只使用本地确定性 Provider，不调用真实 Tavily、Firecrawl、DeepSeek，不消费用户余额。

## 12. 完成交付

1. 更新 `HANDOFF.md`，写明迁移、表、接口、状态机、事务边界、测试和已知限制。
2. 提交并推送 `agent/general-story-incubator-foundation`。
3. 不修改 UI，不合并 main，不关闭或合并 PR。
4. 不对《夜巡人》继续生成，不触碰用户 `.data`、密钥、正文或备份 ZIP。
5. 推送后停止开发，等待 GPT-5.6 从本文件基线做完整审计和修复。
