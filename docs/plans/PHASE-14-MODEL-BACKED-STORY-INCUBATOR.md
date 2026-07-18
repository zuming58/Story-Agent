# 第十四阶段：真实模型驱动的故事孵化器

## 1. 阶段目标

第十三阶段已经建立市场研究、证据、竞品、故事机会、共创会话、
StoryBrief、Canon 提案和开篇实验的持久化骨架，但内容生成仍是确定性占位实现。

第十四阶段把这条链路接入真实、可审计的模型调用：

```text
研究目标
→ 模型规划查询
→ 搜索与正文提取
→ 有引用的证据抽取
→ 竞品/读者机制分析
→ 3—5 个差异化故事机会
→ 多轮人机共创
→ StoryBrief 提案
→ 通用 Canon 提案
→ 三种真实开篇
→ 独立读者与编辑评审
→ 人工批准三章
→ 锁定 Canon
```

本阶段由另一台电脑只开发后端。`apps/web/**`、CSS、设计令牌、页面组件、
Playwright 视觉快照全部禁止修改；相关 UI 由当前电脑后续单独完成。

## 2. 基线与范围

- 基线提交：`081a01a`
- 工作分支：`agent/model-backed-story-incubator`
- 后端入口：`apps/api/src/story_agent_api/phase13.py`
- 模型基础设施：现有 OpenAI-compatible Provider、RoleBinding、`ModelRun`、
  Windows Credential Manager `SecretStore`
- 已有模型角色：`research_planner`、`research_analyst`、`story_incubator`、
  `reader_simulator`、`opening_editor`
- 搜索/提取 Provider：Tavily、Firecrawl；测试使用确定性 Provider

不包含：

- 创意孵化 UI；
- 继续生成《夜巡人》第 10 章以后正文；
- 自动发布、短剧制作或 EXE 打包；
- 对真实 Provider 的自动化测试；
- “保证爆款”或模仿具体作者原文。

## 3. 权威原则

1. 搜索结果不是事实，只有与冻结来源版本关联的证据片段可以进入报告。
2. 模型输出始终是提案，不能自动接受研究报告、故事机会、StoryBrief、Canon
   或开篇。
3. 事实必须关联 `evidenceIds`；没有证据的内容只能标记为 inference、uncertain
   或 `notEstablished`。
4. 模型调用期间不得持有 SQLite 写事务。调用前冻结输入，调用后重新检查
   revision/checksum，再在短事务中写入。
5. 失败必须显式失败，禁止静默回退到第十三阶段占位文案。
6. 每个模型调用写入 `ModelRun`，记录角色、模型、Token、费用、重试、状态和错误，
   不记录 API Key。
7. 不保存或生成竞品大段原文，不生成模仿具体作者的提示词。

## 4. 后端实现

### 4.1 通用模型调用边界

为 Phase 13 增加可测试的模型调用适配层，复用现有 OpenAI-compatible Provider：

- 根据角色绑定解析 Provider 和模型；
- 从 `SecretStore` 读取密钥；
- 支持 JSON Object 输出、超时、取消、有限重试和错误归一化；
- 创建/收敛 `ModelRun`；
- 每次调用使用独立 request ID 和阶段子角色，例如
  `research_analyst:evidence`、`story_incubator:opportunities`；
- 测试可注入确定性 FakeModel，不访问真实 DeepSeek。

不得把 Phase 8 私有方法直接复制成多份；提炼共享、可测试的调用边界，且不得破坏
现有 Phase 3/5/8/12 调用。

### 4.2 查询规划

`research_planner` 根据冻结的 `MarketResearchBrief` 输出结构化查询计划，至少覆盖：

- 平台趋势；
- 同题材代表作品；
- 读者好评原因；
- 弃书/流失原因；
- 前三章与开篇钩子；
- 长期连载发动机。

模型只能在固定 perspective 白名单内输出。系统校验数量、重复、域名范围和成本预算。
非法 JSON 只允许一次修复调用；再次失败则任务失败，不使用硬编码查询冒充模型结果。

### 4.3 证据抽取与报告

`research_analyst` 对每个冻结的 bounded source version 分批抽取：

- `claimType`: fact / opinion / inference；
- claim；
- 原文短片段；
- locator；
- confidence；
- 可支持的 perspective/category。

确定性校验：

- excerpt 必须真实存在于该 source version；
- locator 必须落在冻结文本范围内；
- 禁止证据引用其他项目、其他 job 或其他 source version；
- 单条片段和总引用长度必须受限；
- 模型没有证据时不能自行补写事实。

随后由 `research_analyst` 生成竞品卡、共同模式、弃书模式和研究发现。报告中的每个
事实字段必须关联有效证据，推断必须列出不确定性。

### 4.4 故事机会

研究报告经用户接受后，`story_incubator` 生成 3—5 个真正不同的故事方向。每项包含：

- 高概念、主角、核心欲望、冲突和世界机制；
- 前三章阅读承诺；
- 连载发动机、差异点、风险；
- 分项分数、证据覆盖度、confidence 和 uncertainties。

修正第十三阶段评分错误：分项各自在固定上限内，`totalScore` 是分项自然求和，范围
为 0—100；禁止要求每个候选都刚好 100 分。分数必须能低于满分，且不能代替证据。

若模型生成失败，任务返回明确错误；禁止回退到 `Evidence-led direction 1/2/3`。

### 4.5 多轮共创与 StoryBrief

`story_incubator` 对每轮用户消息输出：

- 面向用户的回复；
- confirmed decisions；
- open questions；
- AI suggestions；
- conflicts；
- evidence IDs。

每轮消息均持久化并关联 `modelRunId`。模型只能更新会话候选状态，不能直接修改正式
StoryBrief。

用户请求 StoryBrief 提案时，模型根据完整会话和冻结上游生成结构化 StoryBrief。
系统校验必填字段、上游 checksum、引用、禁写要求和 no-imitation 规则，用户接受后才
形成 current version。

### 4.6 通用 Canon 提案

用 `story_incubator` 替换 `_generic_canon()` 占位模板：

- 根据作品实际类型生成需要的体系；
- 不强制每个故事都出现等级、法宝、怪异或组织；
- 但 StoryBrief 中存在的关键体系必须结构化保存；
- 输出 Story Core Markdown、entities、relations、rules；
- 包含人物欲望、知识边界、世界规则、冲突发动机、物品/能力状态、代价、揭示边界、
  文风及开篇约束；
- Canon Analyzer 独立抽取并与生成结果交叉校验；
- 缺项仅允许一次模型修复，仍不完整则保留失败提案，不能应用。

Canon 继续经过现有 proposal/revision/人工确认机制，不得自动锁定。

### 4.7 三种开篇与独立评审

`story_incubator` 根据同一个 StoryBrief/Canon 分别生成三种明显不同的第一章：

- 强事件；
- 强人物欲望；
- 强悬念。

每章必须达到 StoryBrief 的目标字数范围，并禁止简单替换标题形成“伪三方案”。

`reader_simulator` 与 `opening_editor` 必须分别独立调用：

- 不读取对方结论；
- 返回分项分数、具体原文位置、问题、修改建议和是否愿意继续读；
- 禁止使用固定分数；
- 评审失败不能伪装成通过。

用户选中一个方向后，再生成第 2、3 章。三章仍保持实验稿身份，不写入正式
`ChapterCommit`。只有三章均经用户逐章批准，才创建 `StyleBaseline` 并允许锁定孵化
Canon。保留第十三阶段审计增加的人工关卡。

### 4.8 恢复、幂等和预算

- 服务重启后，已完成的来源、证据、模型输出和候选稿可复用；
- 运行中的模型调用重启后收敛为可诊断失败，不得永远停在 running；
- 相同 idempotency key + 相同冻结输入返回原结果；输入不同返回 409；
- 每次模型调用前检查研究任务预算和已用费用；
- 超时、429、Provider 错误和非法 JSON 都有稳定错误码；
- 取消后晚到的模型结果不得写入；
- 上游 revision 漂移后输出不得落入当前权威链。

## 5. API 兼容要求

尽量沿用第十三阶段已有路由和 JSON 语义。新增接口仅限真实需要，例如：

- 重试指定研究分析步骤；
- 重新生成单个故事机会提案；
- 重试某个开篇候选或评审；
- 查询 Phase 13 模型运行记录。

所有新增写接口都必须带 expected revision。API 保持 camelCase、UUID4、UTC ISO 8601。

## 6. 测试计划

自动测试全部使用确定性搜索/抓取 Provider 和 FakeModel：

- 查询规划覆盖六个 perspective，非法/重复计划被拒绝；
- 证据 excerpt、locator、跨 job/项目引用及无证据事实校验；
- 竞品字段未知时保持 `notEstablished`，不编造；
- 故事机会分数可以低于 100，且 total 等于分项求和；
- 共创多轮状态、模型失败、revision 漂移和消息恢复；
- StoryBrief 接受/拒绝不污染 current version；
- 通用 Canon 不带《夜巡人》硬编码，且按 StoryBrief 动态要求体系；
- 三个开篇内容确实不同，读者/编辑为两个独立 `ModelRun`；
- 只选中开篇不能创建 StyleBaseline；三章逐章批准后才允许锁 Canon；
- 模型调用期间无 SQLite 长事务；取消后的晚到结果不落库；
- 预算、超时、429、非法 JSON 一次修复上限、重启恢复；
- 备份恢复和跨作品隔离；
- 现有 Phase 3/4/5/8/12/13 回归。

必须运行并记录：

```text
Phase 14 focused tests
API full suite
Web unit tests（只验证未破坏，禁止修改 UI）
npm run build
npm run test:e2e
python compileall
git diff --check
```

## 7. 交付标准

完成后：

1. 更新 `HANDOFF.md`，记录实现、表/API 变化、审计风险、测试结果和最新提交；
2. 提交并推送 `agent/model-backed-story-incubator`；
3. 不合并 `main`；
4. 不修改 `apps/web/**`；
5. 不调用真实 DeepSeek/Tavily/Firecrawl，不消费真实费用；
6. 停止开发，等待当前电脑 GPT-5.6 完整审计与 UI 开发。

