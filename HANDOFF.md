# 2026-07-18 第十四阶段审计与创意孵化 UI 恢复点（GPT-5.6 WIP）

当前分支：`agent/model-backed-story-incubator`

审计基线：`081a01a`；另一台电脑交付：`cb73f21`、`a30e363`。

状态：**后端深度审计与修复已基本落盘；创意孵化 UI 已建立功能页面但尚未完成 CSS、页面测试、全量回归和最终推送。下次必须从本节继续，不得把 Phase 14 误报为已完成。**

## 已完成的审计与修复

- 研究模型调用已纳入 `ResearchJob` 费用上限，并在每次模型/外部调用前复核取消、运行时和 Brief 漂移，外部调用期间不持有 SQLite 长事务。
- 报告的事实、推断和观点均限制为当前任务证据；事实必须有引用，推断/观点必须带不确定性，不再允许跨任务 evidence ID。
- 覆盖率改为从“查询视角 → 来源 → 证据”真实计算，六类研究视角和最少来源类型缺失时不能伪装成充分证据。
- 故事机会和共创状态中的 evidence ID 必须属于冻结的当前研究任务；跨任务引用会被拒绝。
- Canon 改为 Architect 生成、独立 `research_analyst:canon-analyzer` 分析、确定性交叉检查、最多一次修复重试；空结构化实体/规则、缺故事内核/冲突/边界均不能通过。
- 开篇实验增加章节字数范围、三方案差异度、完整评审分数/取值范围和 finding 定位校验。
- 新增故事机会及待处理 StoryBrief 提案列表接口，刷新页面后能恢复业务状态。
- 研究任务创建可安全接收 Tavily/Firecrawl 密钥并写入 `SecretStore`；API、数据库、fingerprint 和日志不返回完整密钥。
- Phase 8 应用孵化 Canon 时重新执行通用 readiness，避免旧提案绕过新校验。
- 已补 Phase 14 专项回归测试；中断前专项结果为 `8 passed`，后续新增接口和密钥路径仍需重新执行。

## 已落盘但未完成的 UI

- 新增 `/incubator` 路由、侧栏“创意孵化”入口和 `StoryIncubatorPage.tsx`。
- 页面已串联六步真实流程：研究目标、市场调研、故事机会、人机共创、StoryBrief、Canon 与三开篇实验。
- React Query 读取 SQLite 权威数据，业务状态不写入 `localStorage`；页面刷新使用新增列表接口恢复。
- 固定右侧 Story Agent 已增加创意孵化作用域与“检查方向 / 整理决策 / 比较开篇”动作。
- **尚未为 `.incubator-*` 组件补齐墨曜指挥舱 CSS，也未完成 1440×1024、1280×800 视觉验收。**

## 下次恢复顺序

1. 先运行 `git status --short`，确认本节列出的修改仍在；不要回滚用户或其他阶段数据。
2. 完成 `apps/web/src/workbench.css` 的创意孵化样式和响应式布局，保持现有深海军蓝、金色、细边框设计令牌。
3. 补 Web 单测：路由入口、六阶段恢复、接受/拒绝与错误状态；不得用纯静态假数据替代后端语义。
4. 重跑 `apps/api/tests/test_phase13_incubator.py`，再运行 API 全量、Web 单测、Build、Playwright。
5. 审查 `git diff --check`、密钥泄露、`.data`/数据库/日志/正文是否误入 Git。
6. 更新本节为最终审计结果，提交并推送当前分支；不合并 `main`，等待用户检查 UI。

## 当前未验证项与严格边界

- 尚未得到本轮所有并行 API 分组的最终结果；旧的 167 API / 11 Web / 14 Playwright 是另一台电脑交付结果，不可冒充本轮审计结果。
- 尚未用真实 Tavily、Firecrawl、DeepSeek 完成一次端到端人工孵化；自动测试必须继续使用确定性 Provider，不能消费真实额度。
- 不修改 `.data`、API Key、Windows Credential Manager 中既有密钥、夜巡人正文和用户正式作品。
- 不修改已有页面的设计风格或视觉快照；UI 只在当前电脑完成。

---

# 2026-07-17 第十三阶段重制交接：市场研究与故事孵化

当前分支：`agent/general-story-incubator-foundation`

本轮后端实现提交：`f70daa9`（后续交接文档提交仅记录此实现结果）。

## 2026-07-18 Phase 13 后端 WIP 收敛点

状态：**已提交可恢复的后端 WIP 基线；未完成最终审计与全量验证。此处停止功能扩展，下一位模型应从本节继续。**

### 已完成实现

- 新增 project migration `0017_general_story_incubator_foundation`，创建 17 张 Phase 13 表：研究 Brief/任务/查询/来源/版本/证据、竞品/结论/机会、共创会话/消息、StoryBrief 版本/提案、开篇实验/候选/读者评审/StyleBaseline。
- 新增 `research_providers.py`：稳定 `SearchProvider`、`ContentFetchProvider`、确定性测试 Provider、Tavily 搜索、Firecrawl/公开 HTTP 抓取适配器；`ResearchSourcePolicy` 拒绝非 HTTP(S)、localhost、环回、私网、链路本地地址，并在每次跳转后复检 URL。
- 新增 `phase13.py` 和 API：Brief、研究状态机、来源/证据、竞品与 findings、机会评分/接受、共创、StoryBrief 权威链、通用 Canon 草稿、三种开篇、独立读者/编辑评审、人工选择、StyleBaseline、incubation readiness。
- 真实 Provider 只通过 `SecretStore` 的 `secretRef` 读取密钥；默认/测试路径使用确定性 Provider，不调用 Tavily、Firecrawl 或 DeepSeek。
- 研究外部调用位于 SQLite 写事务之外；写入前重验上游 revision/checksum。候选正文与评审未写入 ChapterCommit、Plan、StateSnapshot 或正式 Canon。
- `phase8.py` 对带 `incubation=true` 的 Canon 提案使用通用 StoryBrief 校验，固定夜巡人校验仅保留给旧模板残留；`phase5.py` 阻止已有 StyleBaseline 的项目对前 3 章做 `guarded_auto` 批准。
- 备份恢复已将全部 Phase 13 表列入 projectId 重映射；`Phase13Service.repair_restored_metadata` 为 Phase 13 内部 UUID 重新编号，并更新全部关系列、JSON 引用和 AuditEvent 实体 ID。

### 已通过验证

```text
Phase 13 focused/API/SSRF/backup-restore: 3 passed
Projects regression: 3 passed
Backup regression: 7 passed
Phase 8 architecture regression: 7 passed
python compileall apps/api/src apps/api/tests: passed
git diff --check: passed (only Windows LF/CRLF warnings)
```

### 尚未完成或必须审计

- `apps/api/tests` 全量命令及 Phase 5/9/10/11/12 分组在桌面执行环境的 124 秒命令上限被终止，未得到失败断言。下一位模型应以更长可用超时或按更小文件/测试拆分跑完，并记录精确结果。
- 尚未运行本轮要求的 `npm run test`、`npm run build`、`npm run test:e2e`；切换模型后继续运行。根目录 API 脚本依赖 `uv`，若 PATH 无 `uv`，使用 `apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests` 作为等价 API 回归并如实记录。
- 对 `phase13.py` 做完整代码审计，重点检查：恢复 UUID 重映射的所有 JSON 字段、`ResearchJob` 租约/取消边界、真实 Provider 异常处理、竞争条件、证据不足条件和恢复状态。
- 增加更细 API 测试：Brief 漂移、任务 cancel/resume/accept/reject、密钥缺失/限流/超时、来源 URL 去重与多版本、竞品排除后旧报告不变、跨项目资源访问、开篇全部拒绝和前三章自动托管拒绝。
- 不要修改 `apps/web/**`，不要修改 `.data`、密钥、数据库、日志、备份 ZIP 或夜巡人正文；不要合并 main/PR。

### 当前代码范围

```text
apps/api/migrations/project/versions/0017_general_story_incubator_foundation.py
apps/api/src/story_agent_api/research_providers.py
apps/api/src/story_agent_api/phase13.py
apps/api/tests/test_phase13_incubator.py
apps/api/src/story_agent_api/models.py
apps/api/src/story_agent_api/schemas.py
apps/api/src/story_agent_api/main.py
apps/api/src/story_agent_api/services.py
apps/api/src/story_agent_api/phase5.py
apps/api/src/story_agent_api/phase8.py
```

基线：`agent/general-story-incubator-foundation@b4f08aada8edda56f46115900622738814ec8c26`。当前 WIP 提交：`3f4d62fdebfbd04b09fa0d994b9b1563a83b8da2`。

正式方案：`docs/plans/PHASE-13-GENERAL-STORY-INCUBATOR.md`

后端执行清单：`docs/plans/PHASE-13-BACKEND-HANDOFF.md`

另一台 Codex 提示词：`docs/plans/PHASE-13-OTHER-CODEX-PROMPT.md`

状态：**开发计划已经重制完成，等待另一台电脑只实施后端；当前电脑 GPT-5.6 负责最终审计、修复和全部 UI。**

## 本轮产品结论

- 《夜巡人·正式试写》已正式提交第 1—9 章，但用户阅读前两章后明确判定正文干涩、档案编号重复、人物与情绪牵引不足，没有继续阅读欲望。
- 这证明既有系统可以保证 Canon、状态、连续性和自动生产，却不能证明作品“值得读”；测试通过不能再作为小说质量完成标准。
- 《夜巡人》停止第 10 章以后生成，保留为失败样本和回归数据；不得继续消费真实模型费用。
- 第十三阶段前移为：市场目标 → 联网竞品研究 → 爆款机制/弃书原因 → 差异化故事机会 → 多轮共创 → StoryBrief → Canon 草稿 → 三种开篇 → 人工愿读确认。
- “爆款潜力”只能提供分项、有证据、有不确定性的评估，禁止宣称保证爆款。
- 前三章必须人工选择和批准；没有用户愿意继续读的开篇时必须返回共创，不得进入规划和自动托管。

## 协作边界

- 另一台电脑完整实现 `PHASE-13-BACKEND-HANDOFF.md`，包括研究 Provider、来源证据、竞品矩阵、故事机会、StoryBrief、通用 Canon 和开篇实验后端。
- 另一台电脑禁止修改 `apps/web/**`、CSS、设计令牌、页面组件和视觉快照。
- 当前电脑在另一台推送后审计来源追溯、SSRF、密钥、事务、revision、版权边界、状态隔离、备份恢复和测试，再独立开发 UI。
- GitHub 是唯一代码权威；两台电脑不得同时修改当前功能分支。

---

# 2026-07-16 历史记录：夜巡人第 6 章质量门修复

## 夜巡人第 6 章真实试写质量门修复

- 正式项目第 6 章已生成 v3 候选稿（2379 字），连续性、故事编辑与文风复核通过，但确定性质量门误报 `PACE_MAJOR_EVENT_OVERFLOW`。
- 根因是旧规则把事实抽取中的所有场景事件都当作“重大事件”：铜铃来源调查、下楼查看防火门、空白登记被计为 3 项；其中下楼查看只是第一项调查的过程步骤，规划实际仍只有 2 个重大事件。
- 新抽取协议要求每个事件提供 `isMajor` JSON boolean，并把契约 `paceBudget` 传给事实抽取模型；同一调查目标中的移动、观察和记录必须合并或标为非重大。
- 质量门现在只统计明确标记为 `isMajor=true` 的事件。旧版抽取缺少分类时产生 warning，不再凭空升级为 blocker；真正明确超出预算的重大事件仍会阻断。
- 已直接重新校验现有 v3，没有重写正文、没有再次调用 DeepSeek 写作模型。当前任务保持 `human_review`，`currentRevisionRound=2`，`openBlockingCount=0`。
- 用户下一步只需刷新质量中心，阅读 v3 后点击“质量通过并提交”；提交前不得重新启动第 6 章试写。
- 回归结果：Phase 5 全部通过，Phase 7 自动托管全部通过，专项 3 项通过。

当前分支：`agent/general-story-incubator-foundation`

准确基线：`agent/short-story-production-foundation@7120d2f`

完整方案：`docs/plans/PHASE-13-GENERAL-STORY-INCUBATOR.md`

执行清单：`docs/plans/PHASE-13-BACKEND-HANDOFF.md`

状态：**第十三阶段交接文档与分支已准备，但按用户决定暂停开发，不交给另一台电脑执行。当前优先进行夜巡人连续写作测试。第 6 章 v3 候选稿已经生成，误报的节奏 blocker 已修复并重新校验为 0 个阻断；现在必须由用户阅读 v3 并点击“质量通过并提交”，不得重新启动第 6 章。提交成功、进度变为 6/1000 后，再连续测试第 7—9 章。**

## 夜巡人试写准备（已完成）

- 本机正式项目 `夜巡人·正式试写` 的项目 ID 为 `1ffdb07d-d717-42cf-8456-30e1475b2859`，当前 `currentChapter=5`，Canon 已锁定。
- 修复前已创建项目备份 `afa35e54-c2de-45ff-988b-e7fe812c6c7c`；备份 ZIP 位于项目本地 `.data`，不进入 Git。
- `Phase7Service.trial_readiness` 现在对故事弧、章节窗口或其他覆盖节点统一要求当前章存在精确 Beat；缺失时不再同时返回 `TRIAL_PLAN_READY`，安全批次上限也不会越过缺失章节。
- 回归测试将缺 Beat 的节点明确设置为 `故事弧`，并验证 ready=false、`TRIAL_CHAPTER_BEAT_MISSING` 与不存在伪就绪状态。
- 正式项目现有规划节点已通过真实 Plan API 增加第 6—10 章唯一精确 Beat，节点 revision 从 1 更新到 2；第 1—5 章 Beat 保持不变。
- 第 6—10 章标题依次为《地底的第四声铃》《空白值夜表》《借钉之前》《归还时间写在明天》《见雾者登记》；升级、法器、知识和揭示边界均已写入 Beat。
- 实际 API 检查结果：`chapterCount=1` 对应第 6 章、`chapterCount=3` 对应第 6—8 章、`chapterCount=5` 对应第 6—10 章，三者均 ready=true，`maxSafeChapterCount=5`。
- 第 6 章已经生成 v3 候选稿并进入 `human_review`，正文尚未正式提交；不要再次点击“开始第 6—6 章”。详细复核步骤见 `docs/testing/PHASE-12-NIGHT-WATCH-TRIAL.md`。
- 本次真实正文与质量数据仅保存在本机 `.data`，不进入 Git；没有实施 Phase 13，也没有把备份、密钥或模型输出加入 Git。

## 本轮验证结果

```text
Phase 8 trial-readiness focused: 7 passed
API full: passed
Web unit: 3 files / 11 tests passed
Build: passed（仅既有 Vite chunk-size warning）
Playwright: 14 passed（1440×1024 与 1280×800）
python compileall: passed
git diff --check: passed（仅 Windows LF/CRLF 提示）
```

根目录 `npm run test` 仍依赖系统 PATH 中的 `uv`；本机清理 C 盘后 PATH 无 `uv`，因此本轮使用项目自带 `apps/api/.venv/Scripts/python.exe` 执行相同的完整 API 测试。产品运行与测试本身均通过。

## 历史任务（已被 2026-07-17 重制方案替代，不得执行）

完整执行 `PHASE-13-BACKEND-HANDOFF.md`：

- 持久化创意会话、消息、StoryBrief 版本和修改提案。
- 提供多轮构思、固化 StoryBrief、接受/拒绝和版本查询 API。
- 将 Phase 8 的夜巡人固定逻辑重构为可选模板，生产默认路径改为通用长篇/短篇架构器。
- 通用 Canon 校验按作品实际体系启用；没有等级、法宝或怪异规则时不得强行生成。
- 根据作品形态、目标章节和总字数动态生成分层规划与下一批 5 章节拍。
- 补齐作品归档、复制等书库后端能力。
- 不修改任何 UI，不调用真实 DeepSeek，不碰 `.data` 和用户正式作品。

## 严格禁止

- 禁止修改 `apps/web/**`、CSS、设计令牌、Playwright 视觉基线。
- 禁止提交 API Key、SQLite、日志、备份 ZIP、测试临时目录或生成正文。
- 禁止把夜巡人、沈砚、雾城、1000 章、七卷、六阶能力作为通用默认值。
- 禁止模型回复直接修改正式 StoryBrief、Canon 或 Plan；必须经过提案确认和 revision 校验。
- 禁止模型调用期间持有 SQLite 长事务。
- 禁止合并任何分支或提前进入第十四阶段。

## 历史交付要求（仅供追溯）

1. 运行 Phase 13 专项、API 全量、Web 单测、Build 和 Playwright。
2. 更新本文件，记录迁移、表、API、测试、已知限制和准确提交。
3. 提交并推送 `agent/general-story-incubator-foundation`。
4. 停止开发，等待当前电脑 GPT-5.6 审计和 UI 实施。

---

# 2026-07-16 第十二阶段最终审计与产品入口交接（GPT-5.6）

当前分支：`agent/short-story-production-foundation`

审计基线：`356689b`

另一台电脑交付：`ce1583c`

前一审计检查点：`3207135`

状态：**第十二阶段已经完成 GPT-5.6 最终审计、直接修复和全量验证，可以推送交付。短篇生产后端可进入真实 Provider 冒烟准备；普通用户短篇 UI 和通用故事孵化器仍属于第十三阶段，不能误报为已完成。**

## 本轮审计修复

- 短篇策略模型现在收到有界的真实 Canon、结构化实体/关系/规则、规划摘要和正式章节上下文，不再只收到无法用于改编的 checksum。
- 模型请求剥离重复的完整 source manifest，只保留可审计 checksum 台账，避免 1000 章规划重复占用上下文；数据库仍保存完整冻结快照。
- 结构化 Canon 在 workspace 创建后发生变化会触发 source drift，不能用旧策略覆盖新设定。
- 非法“总字数/章节数”组合在创建目标项目前阻断；readiness 同时核对所有 ChapterBeat 字数区间总和。
- 章节契约会把同一规划窗口内未来 ChapterBeat 的边界和关键词加入禁止提前消费范围，避免第 1 章提前写完第 2—5 章内容。
- 保留 Phase 12 双 SQLite staged/retry、自然键 Canon 映射、备份 remap、最终章停止和正式提交原子边界。

## 产品入口与本地运行

- 多作品目录库已经存在：每本小说使用独立目录和 `story.db`，可在作品总览创建、切换并重启恢复。
- 新建作品现在进入 Canon/构思入口，不再直接跳到规划页。
- 新增根目录 `START-STORY-AGENT.cmd`：双击后分别启动 API/Web 并打开作品总览。
- 启动已有环境直接使用 `apps/api/.venv`，不依赖 PATH 中的 `uv`；首次初始化才需要安装 `uv`。
- `F:\Cache\uv` 当前保存的是 uv 下载缓存和 receipt，不是 `uv.exe` 安装目录；脚本只将其作为 `UV_CACHE_DIR` 使用。
- Playwright 也改用项目 `.venv` 的 Python，避免用户移动 uv 缓存后测试无法启动。
- 本机当前 Node 为 v25.2.1，构建和测试通过；长期项目运行时仍应按既定基线切换到 Node 24 LTS。

## 重要产品结论

- `Canon` 通常读作“卡农”，在本项目中表示作品的正式权威设定，不是普通 note。
- 当前 Canon 页面有故事架构器和右侧 AI 对话，但生产逻辑仍带有夜巡人、1000 章、七卷、沈砚、雾城等固定决策。
- 因此当前可以测试既有“夜巡人”长篇链路和多作品存储，但**不能把任意题材的多轮构思 → StoryBrief → 通用 Canon/规划宣称为已完成**。
- Phase 11/12 短篇生产后端已经具备，普通用户短篇策略/物化向导 UI 尚未补齐。
- 下一阶段固定为 `docs/plans/PHASE-13-GENERAL-STORY-INCUBATOR.md`：通用故事孵化器、多作品书库完善、移除夜巡人硬编码，并补齐短篇 UI。

## 当前验证结果

```text
API full: 159 passed
Web unit: 3 files / 11 tests passed
Build: passed（仅既有 Vite chunk-size warning）
python compileall: passed
Playwright failed-case rerun: 2 passed（desktop-1280）
Playwright full: 14 passed（1440×1024 与 1280×800）
START-STORY-AGENT.cmd: API 200、Web 200、重复启动路径通过
git diff --check: passed（仅 Windows LF/CRLF 提示）
```

## 下一步

1. 提交并推送当前分支，建立以 Phase 11 分支为 base 的草稿 PR，不合并 `main`。
2. 当前“夜巡人”可以做既有长篇链路和多作品保存/切换测试。
3. 任意新题材的真实付费生成应等 Phase 13 移除夜巡人硬编码后再开放。
4. 当前电脑下一阶段实现 Phase 13 的通用创意工作室 UI；另一台电脑只可接后端任务，不得修改 UI。

---

# 2026-07-16 夜间审计检查点（GPT-5.6）

当前分支：`agent/short-story-production-foundation`

被审计基线：`356689b`

另一台电脑交付提交：`ce1583c`

状态：**第十二阶段最终审计尚未全部结束；今晚已完成一个独立修复步骤并安全暂停。不能把本检查点视为最终验收通过。**

## 今晚已经完成

- 确认分支、远端 HEAD、工作区和第十二阶段差异范围。
- 阅读 Phase 11/12 的数据模型、迁移、短篇策略、物化流程、章节契约、质量门、备份恢复与专项测试。
- 发现真实模型验收的关键缺口：此前短篇策略模型只收到 checksum/manifest，没有收到可用于改编的实际 Canon 和正式章节内容；模拟模型测试无法发现这个问题。
- `Phase11Service` 现会给模型提供有长度上限且可审计的 `sourceContext`：锁定 Canon Markdown、完整规划 manifest、正式章节摘要、抽取状态和正文摘录；`short_story_strategy` 来源会携带活动策略快照。
- 修正短篇总字数与章节数不可能同时满足的情况：少于每章 500 字的总预算在创建目标项目之前返回 `SHORT_STORY_WORD_BUDGET_INVALID`。
- 物化项目的每章字数预算现在直接由总字数平均值生成，不再强制把平均值抬到 1000 字而造成总预算失真。
- 短篇章节契约的字数上下限以已锁定的 ChapterBeat `paceBudget` 为权威，调用方不能用随意参数绕过规划预算。
- 新增 Canon/Plan/正式章节真实上下文、非法总字数预算以及契约字数权威性的回归覆盖。

## 今晚验证结果

第一次运行 Phase 11 + Phase 12 合并专项时有 1 条新增断言依赖种子标题而失败；该断言已改为验证结构和 checksum，不属于产品代码失败。

修正后，与今晚变更直接相关的 5 条回归全部通过：

```text
5 passed
```

本检查点已运行 `git diff --check` 并通过（仅 Windows LF/CRLF 提示）；**尚未运行**完整 API、Web、Build、Playwright 和 compileall，这些是明天第一项工作。

## 明天从这里继续

1. 继续审计完成态 origin、双 SQLite staged/retry、source manifest、Canon 映射、最终章节停止、备份 remap、正式导出与跨作品隔离。
2. 运行 Phase 11 + Phase 12 全部专项，确认不再有遗漏。
3. 运行完整 API、Web 单测、Build、Playwright、compileall 和 `git diff --check`。
4. 若发现明显问题，直接修复并补回归；随后更新本文件为最终审计结论。
5. 全量验证通过后，才判断可以开始哪一级测试：API 技术测试、真实 DeepSeek 短篇生成冒烟，或普通用户 UI 试用。

## 当前限制

- 本轮没有修改 `apps/web/**` 或 UI 风格。
- 第十二阶段仍只有后端/API，普通用户尚无短篇策略和物化向导 UI。
- 今晚没有调用真实 DeepSeek，没有读取或写入用户正式作品与 `.data`。
- 不提交 API Key、SQLite、日志、备份 ZIP、临时文件或生成正文。

---

# Story Agent 当前交接：第十二阶段短篇正文生产后端基础完成

更新时间：2026-07-15（Codex）

当前分支：`agent/short-story-production-foundation`

准确开发基线：`agent/shortform-adaptation-foundation@356689b`

最新提交：以 `agent/short-story-production-foundation` 分支 HEAD 为准（交付回复给出推送后的准确短 hash；提交不能在自身内容中记录自身 hash）。

状态：**第十二阶段后端、项目数据库迁移、公共 API 类型与专项测试已完成并通过全量回归；未修改 Web，已停止继续开发，等待 GPT-5.6 完整代码审计。**

## Codex 自审修复

- 物化前严格校验并规范化 `maxMajorEvents`，非法类型、范围或事件溢出在创建目标项目前返回确定性 409，不再产生 500 或多余项目。
- `targetWordCount` 覆盖值现在统一驱动源/目标 origin、目标 Plan、章节契约与自动托管字数预算。
- 已完成物化的目标项目总章数不可通过普通项目更新缩短或扩展；readiness 同时核对 origin、Plan 范围、重复/缺失/越界 Beat 和每章事件预算。
- 公共 `ChapterBeat` 新增 `paceBudget`、知识边界、允许/禁止能力与物品边界，Plan GET/PATCH 往返不再静默删除短篇预算。
- completed 幂等请求先匹配冻结请求，即使 workspace 后续合法修改，原请求仍返回同一目标；新请求指纹包含 sourceProjectId。
- 来源项目恢复为克隆时，旧外部目标链接转为 `detached` 历史记录并释放幂等键；恢复后的来源只能物化新的独立目标，不能认领原目标。
- 短篇 Canon freshness 冲突明确返回 `SHORT_STORY_CANON_DRIFT`，并与其他 stale contract 一样阻止重检/提交。
- 新增非法预算、字数覆盖、Plan round-trip、章数不可变、来源恢复、staged 恢复、最终章停止及短篇质量门回归测试。

## 第十二阶段完成内容

- 新增项目数据库迁移 `0016_short_story_production_foundation`。
- 新增 `short_story_origins` 表，保存来源项目/workspace/strategy、strategy revision/checksum、冻结 source manifest、策略快照、目标项目、幂等指纹、创建状态、失败诊断和时间戳。
- 新增 `Phase12Service`，将已确认且 checksum 有效的短篇 strategy 物化为新的独立 `mode=short-form` 标准项目。
- 物化前复核 workspace 类型/状态/revision、active strategy checksum、open error/blocker 和 Canon/Plan/current official commit source manifest 漂移。
- 物化采用 `creating -> staged -> completed|failed` 状态，不跨两个 SQLite 假装原子事务；目标创建后立即回写 ID，失败保留诊断，同幂等键重试复用原目标项目。
- 来源长篇与目标短篇使用不同项目目录和 SQLite；目标 Canon/Plan/ChapterBeat 从冻结快照复制，来源长篇进度、ChapterCommit、状态、检索与费用不被写入。
- Canon 类型、实体、关系和规则按目标自然键映射并重连目标 UUID，避免引用来源数据库主键或与目标系统默认类型冲突。
- `short-form` 项目限制为 1-30 章且从第 0 章开始；项目更新和章节契约均拒绝超出范围。
- 连续 1-N `ChapterBeat` 写入目标 Plan；缺号、重号、越界、空重大事件和请求章数冲突会阻断物化。
- Phase 5 契约注入当前章事件/字数预算、全篇剩余预算、strategy checksum、核心钩子与结局边界；继续复用候选稿、事实抽取、多角色复核、两轮修订和原子正式提交。
- 新增短篇确定性质量规则：`SHORT_STORY_CHAPTER_RANGE`、`SHORT_STORY_EVENT_BUDGET`、`SHORT_STORY_TOTAL_WORD_BUDGET`、`SHORT_STORY_HOOK_MISSING`、`SHORT_STORY_REVEAL_EARLY`、`SHORT_STORY_FORESHADOW_DROPPED`、`SHORT_STORY_ENDING_INCOMPLETE`、`SHORT_STORY_CANON_DRIFT`。
- Phase 7 继续使用既有 `min(totalChapters, requestedEnd)` 批次边界，最终章后 readiness 阻止额外批次；Phase 9 正式短篇导出要求完整 1-N 范围并只读取 current official commits。
- 备份恢复会 remap 目标 origin 的 `projectId/targetProjectId` 和快照内项目 ID；外部来源长篇 ID 保持为独立溯源引用。
- 未新增短剧、短视频、分镜、图片、配音、视频发布或 EXE 能力。
- 未修改 `apps/web/**`、UI、CSS、设计令牌、Playwright 用例或视觉快照。

## 第十二阶段 API

- `POST /api/v1/projects/{source_project_id}/adaptation-workspaces/{workspace_id}/materialize-short-story`
- `GET /api/v1/projects/{project_id}/short-story/origin`
- `GET /api/v1/projects/{project_id}/short-story/readiness`

公共请求/响应类型：`ShortStoryMaterializeCreate`、`ShortStoryMaterializeOut`、`ShortStoryOriginOut`、`ShortStoryReadinessOut`。

## 第十二阶段验证结果

```text
Phase 12 focused API: 9 passed
Full API: 156 passed
Web unit: 3 files / 11 tests passed
Build: passed（仅既有 Vite chunk-size warning）
Playwright e2e: 14 passed（1440×1024 与 1280×800）
python compileall: passed
git diff --check: passed（仅 Windows LF/CRLF 提示）
```

所有短篇 strategy/物化测试使用确定性本地替身，没有调用真实 DeepSeek，没有读取或修改用户 `.data`、正式正文、API Key、日志或备份。

## 已知限制与审计重点

- 本阶段只提供后端与 API；原生短篇仍通过既有 Canon/Plan API 建立生产基础，没有新增 UI。
- 失败的 staged 目标项目不会被静默删除；它保持 readiness blocked 和来源侧失败诊断，同幂等键可安全重试复用，需审计这一补偿语义是否满足产品期望。
- 短篇字数、钩子、提前揭示、伏笔与结局规则是确定性基础门；真实作品质量仍需后续本地 Provider 验收，不应把测试替身结果视为真实成稿验收。
- FastAPI TestClient、Python SQLite datetime adapter 和 Vite chunk-size 仍有既有非阻断 warning。
- GPT-5.6 应重点审计双 SQLite staged/retry、来源 manifest 不可变性、Canon 自然键映射、备份 remap、质量门误报/漏报以及 Phase 7 最终章停止语义。

下一步只做 GPT-5.6 完整代码审计；不要继续开发，不要合并任何分支。

---

# Story Agent 第十一阶段审计交接：范围收敛为长篇与短篇小说

更新时间：2026-07-14（GPT-5.6）

当前分支：`agent/shortform-adaptation-foundation`

准确审计基线：`agent/longform-endurance-foundation@b20b7e2`

被审计提交：`2f94b1f`

状态：**第十一阶段短篇策略后端已完成 GPT-5.6 审计与修复。短剧/短视频开发暂停；当前产品范围只保留长篇小说和短篇小说。**

完整审计记录：`docs/plans/PHASE-11-AUDIT.md`。

下一阶段方案：`docs/plans/PHASE-12-SHORT-STORY-PRODUCTION.md`。

## 本轮 GPT-5.6 修复

- 严格隔离短篇与短剧 workspace/proposal 类型。
- 给幂等请求增加请求指纹，错误复用返回 409。
- 模型调用前后及 proposal apply 时复核 workspace revision，禁止旧结果覆盖新目标。
- finding 指纹加入 proposalId，拒绝提案同时关闭其 findings，防止重复坏提案绕过质量门或永久阻断。
- 短篇 workspace 缺少 active/checksum-valid strategy 时不再显示 ready，也不能锁定。
- 锁定/归档 workspace 进入只读状态。
- source manifest 冻结完整 Plan、PlanNode、StoryMarker 与 current official commit/draft/source/snapshot 权威链。
- 模型合法 JSON 中的错误字段类型转成确定性 findings，不再直接触发响应 500。
- 新增 4 个专项回归场景，第十一阶段专项由 5 项增至 9 项。
- 未修改 `apps/web/**`、UI、CSS、设计令牌或视觉快照。

## 当前验证结果

```text
Phase 11 focused API: 9 passed
Full API: 147 passed, 298 warnings
Web unit: 3 files / 11 tests passed
Build: passed（仅既有 Vite chunk-size warning）
Playwright e2e: 14 passed（1440×1024 与 1280×800）
```

## 当前能力判断

- 长篇：Canon、1000 章分层规划、章节生产、质量复核、自动托管、导出和 5/10/20/30 章耐久监控基础已经具备；真实 20—30 章付费试写仍是上线前验收项。
- 短篇：已经能生成、校验和保存短篇压缩策略，但还不能把策略独立生产成完整短篇正文。
- 短剧/短视频：代码作为休眠基础保留，不继续开发，不作为当前完成度或验收目标。

## 下一台电脑的唯一任务

只实施 `docs/plans/PHASE-12-SHORT-STORY-PRODUCTION.md` 的后端部分：让短篇策略物化为独立 `short-form` 项目，并复用现有章节生产、质量门、自动托管和导出链路。禁止修改 UI；完成后推送分支并停止，等待 GPT-5.6 审计。

---

# 历史交接：第十一阶段原始实现记录

更新时间：2026-07-14（Codex）

当前分支：`agent/shortform-adaptation-foundation`

准确开发基线：`agent/longform-endurance-foundation@b20b7e2`

最新提交：交付分支 HEAD 为准（最终回复给出推送后的短 hash；提交 hash 无法在同一提交内自引用）。

状态：**第十一阶段“短篇策略与短剧改编桥梁”的后端基础、数据库迁移、公共类型与 API 测试已完成；未开发 UI，等待 GPT-5.6 完整代码审计。**

## 第十一阶段完成内容

- 新增项目数据库迁移 `0015_shortform_adaptation_foundation`。
- 新增数据表：
  - `adaptation_workspaces`
  - `short_story_strategies`
  - `adaptation_proposals`
  - `drama_episodes`
  - `drama_scenes`
  - `drama_script_versions`
  - `adaptation_findings`
- 新增 `Phase11Service`，负责短篇/短剧 workspace、source manifest 冻结、proposal 生成/接受/拒绝、短篇 strategy 落盘、短剧 episode/scene/script candidate、script approve 与 findings。
- 新增模型角色绑定占位：
  - `short_story_architect`
  - `drama_adapter`
  - `script_writer`
  - `adaptation_reviewer`
- Workspace 创建会冻结 locked Canon revision/checksum、可选 Plan revision/checksum、连续 current official chapter commit manifest，或 active short story strategy checksum。
- Proposal 生成在短事务内冻结输入，模型调用在事务外执行；JSON 非法只允许一次 repair；保存前重新校验 source manifest 漂移。
- 所有 apply/reject/approve/update 都携带 expected revision，并做 project/workspace/proposal/episode/script 归属校验。
- 短篇 strategy apply 不覆盖 Canon、Plan 或正式 ChapterCommit；旧 active strategy 显式 supersede。
- 短剧 outline apply 只生成 `drama_episodes` 与 `drama_scenes`；不生成分镜图、角色图、视频、配音或外部发布。
- Script proposal 只生成 candidate `drama_script_versions`；approve 时同 episode 只允许一个 current approved，冲突返回 `DRAMA_APPROVAL_CONFLICT`。
- 备份恢复会 remap adaptation JSON/manifest 中的 project ID，重算 strategy/episode/scene/script/finding checksum/fingerprint，并将 copied `generating` proposal 收敛为 `interrupted`。
- 未修改 `apps/web/**`、UI、CSS、设计令牌、Playwright 用例或视觉快照。
- 未调用真实 DeepSeek；Phase11 API 测试使用 monkeypatch 的确定性本地模型输出。

## 第十一阶段 API

- `POST /api/v1/projects/{project_id}/adaptation-workspaces`
- `GET /api/v1/projects/{project_id}/adaptation-workspaces`
- `GET /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}`
- `PUT /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}`
- `GET /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}/readiness`
- `POST /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}/short-story-proposals`
- `POST /api/v1/adaptation-proposals/{proposal_id}/apply`
- `POST /api/v1/adaptation-proposals/{proposal_id}/reject`
- `POST /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}/drama-outline-proposals`
- `GET /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}/episodes`
- `POST /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}/episodes/{episode_id}/script-proposals`
- `POST /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}/script-versions/{version_id}/approve`
- `GET /api/v1/projects/{project_id}/adaptation-workspaces/{workspace_id}/findings`

## 第十一阶段确定性规则

- `ADAPTATION_SOURCE_DRIFT`
- `ADAPTATION_CANON_DEVIATION_UNDECLARED`
- `SHORTFORM_EVENT_BUDGET_OVERFLOW`
- `SHORTFORM_FORESHADOW_DROPPED`
- `DRAMA_EPISODE_DURATION_OUT_OF_RANGE`
- `DRAMA_SCENE_DURATION_OVERFLOW`
- `DRAMA_CHARACTER_KNOWLEDGE_LEAK`
- `DRAMA_ABILITY_RULE_BREACH`
- `DRAMA_OPENING_HOOK_MISSING`
- `DRAMA_ENDING_CLIFFHANGER_MISSING`
- `DRAMA_DIALOGUE_WITHOUT_SOURCE_OR_PURPOSE`
- `DRAMA_APPROVAL_CONFLICT`

严重度支持 `info|warning|error|blocker`；open error/blocker 会阻断 proposal apply、workspace lock 或 script approve。

## 第十一阶段测试结果

```text
Phase 11 focused API: 5 passed
Full API + Web via npm run test: API 143 passed, 298 warnings; Web 3 files / 11 tests passed
Build: passed（仅既有 Vite chunk-size warning）
Playwright e2e: 14 passed（1440×1024 与 1280×800）
```

## 已知限制与下一步

- 本阶段只提供后端基础和 API；没有新增 UI。
- 未调用真实 DeepSeek；真实短篇/短剧 proposal 生成需要用户配置新模型角色后再由后续审计确认。
- 当前短篇/短剧规则为后端基础确定性检查，不包含完整多角色审稿或真实剧本质量模型评审。
- 未实现短篇正文生成、分镜图、人物图、视频、配音、外部发布、EXE 或任何媒体资产链路。
- FastAPI TestClient 与 SQLite datetime adapter 仍有既有上游 deprecation warning。
- Vite 仍有既有 chunk-size warning。

## 当前交给 GPT-5.6 的任务

请对 `agent/shortform-adaptation-foundation` 做完整代码审计，重点检查：

1. source manifest 冻结、漂移阻断与备份恢复 remap 是否完整；
2. workspace/proposal/episode/script 的跨作品归属校验是否有遗漏；
3. expected revision、事务边界和 proposal apply/approve 回滚语义是否足够严格；
4. 短篇 strategy 和短剧 script candidate 是否可能反向污染 Canon、Plan 或正式 ChapterCommit；
5. 新增 API 测试是否覆盖足够真实的 Phase11 风险。

---

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
# 2026-07-18 Phase 13 后端收敛交接

当前分支：`agent/general-story-incubator-foundation`

状态：**Phase 13 后端基础已实现并完成 API 回归；停止继续开发，等待 GPT-5.6 审计。**

本次收敛补充：
- 研究任务现在会将缺失凭据、Provider 和预算错误持久化为可恢复的 `failed` 状态；执行路径在每次外部调用前检查运行时预算，并在持久化结果前拒绝超出费用预算，抓取达到总字符上限后不再发起下一页请求。
- 同一次研究分析的竞品、findings、任务 checksum 使用同一份新 report revision；排除竞品时复制出新报告版本，历史报告保持不可变。
- 通用 Canon 提案 apply 时重新校验 current StoryBrief、accepted opportunity 和 research checksum，避免上游 authority 漂移后覆盖 Canon。
- 带有 StyleBaseline 的项目禁止自动托管提交前 3 章；人工流程与 Canon/revision/事务边界保持不变。
- Phase 12 质量门测试显式标记 `isMajor` 事件，和既有“只统计明确重大事件”的规则一致。

迁移与表：`0017_general_story_incubator_foundation`，覆盖研究 Brief/任务/查询/来源/版本/证据、竞品/findings/机会、共创/StoryBrief、开篇候选/评审/StyleBaseline 共 17 张项目库表；备份恢复会 remap Phase 13 全部 UUID、关系、JSON 引用和 AuditEvent 实体 ID。

接口：研究 Brief 与状态机、来源/证据/竞品/findings/机会、共创与 StoryBrief 权威链、通用 Canon 提案、三种开篇实验、人工选择、三章扩展与 incubation readiness 均已挂载在 `/api/v1`。默认测试路径使用确定性 Provider，不调用 Tavily、Firecrawl 或 DeepSeek。

验证结果：
- API 全量按桌面 124 秒命令上限分片完成：`162 passed`。
- `npm run test` 已执行，但 API 全量阶段被桌面 124 秒硬上限中断；其等价 API 分片与 `npm run test:web` 均通过，Web 为 `3 files / 11 tests`。
- `npm run build` 通过，仅有既有 Vite chunk-size warning。
- `npm run test:e2e` 已执行但被同一 124 秒上限中断，未产生失败断言；需要在无此上限的环境完整复跑，不能报为通过。
- `python -m compileall -q apps/api/src apps/api/tests` 与 `git diff --check` 通过。

已知限制：真实 Provider 适配器存在但本轮未进行真实网络烟测；不得在审计前调用真实 Provider、修改 `apps/web/**`、`.data`、密钥、数据库、日志、备份或用户正文。
# 2026-07-18 Phase 13 final audit checkpoint (GPT-5.6)

Current branch: `agent/general-story-incubator-foundation`
Audited range: `b4f08aa..adbd3d5`, plus local audit fixes pending commit.

## Audit result

Phase 13's persistence, provider boundary, source/evidence ledger, StoryBrief
authority chain, Canon proposal handoff, opening experiment records and backup
remapping are in place. It is safe to continue as a **backend foundation**, but
it is **not yet the real market-research and creative-generation product**:

- Research findings, competitor profiles, opportunities, ideation replies,
  Canon drafts, opening prose and reader/editor scores are deterministic
  scaffolds. They do not yet call the configured research, writer, reader or
  editor model roles. Do not present their output as live research or as an
  evidence-based prediction of commercial success.
- There is no Phase 13 UI yet. Do not modify `apps/web/**` in backend follow-up
  work. The current computer owns the visual product work.
- No real provider, user `.data`, API key, database, backup archive, or Night
  Watch manuscript was touched during this audit.

## Audit fixes added locally

1. Research Brief revisions now advance across replacements. A job only starts
   from the current Brief and detects a replaced Brief before or during provider
   work (`RESEARCH_BRIEF_DRIFT`). `POST /api/v1/research/jobs/{id}/run` provides
   the missing explicit start action for queued jobs.
2. Saved include/exclude domain scope is enforced after search results return;
   an excluded domain can no longer enter the source ledger merely because a
   provider ignored its filter.
3. Removed the application-side `public-http` fetch option. The old
   resolve-then-connect approach was vulnerable to DNS rebinding. Research uses
   Firecrawl or the deterministic test provider until a pinned-address transport
   exists. Credential references are no longer exposed by the job API.
4. Opportunities, ideation, StoryBrief and Canon proposals now require an
   accepted, current research authority rather than just a matching checksum.
5. Selecting an opening is no longer equivalent to approving it. The selected
   option must be expanded to three experimental chapters and each chapter must
   be explicitly approved through
   `POST /api/v1/opening-candidates/{id}/chapters/approve` before the system
   creates a `StyleBaseline` or permits an incubation Canon to be locked.

## Verification status

- `python -m compileall -q apps/api/src`: passed.
- `git diff --check`: passed (Windows LF/CRLF warnings only).
- Phase 13 focused tests were run in small groups because this desktop runner
  cuts long command output: original full workflow, SSRF, backup restore,
  credential/competitor handling, Brief drift/domain scope/direct-fetch block,
  and cost limit all passed (7 tests total).
- `npm run build` was started but this desktop runner cut the captured command
  before its final completion line. Re-run build, full API suite, web tests and
  Playwright after the audit commit in an unrestricted terminal; do not report
  them as passed from this checkpoint.

## Next implementation gate

Before Phase 13 can be called usable for new novels, implement model-backed
analysis with explicit role bindings and structured outputs: query planning,
evidence extraction, competitor analysis, opportunity generation, ideation,
Canon draft generation, three distinct opening drafts, and independent reader
and editor evaluations. Every non-factual conclusion must retain evidence IDs,
uncertainty and no-imitation constraints. Keep provider calls outside SQLite
write transactions and retain the current proposal/approval gates.

---
# 2026-07-18 Phase 14 handoff: model-backed story incubator

Current branch: `agent/model-backed-story-incubator`

Base commit: `081a01a` (`agent/general-story-incubator-foundation`, Phase 13
GPT-5.6 audit fixes).

Status: **Phase 14 backend plan is ready for the other computer. No Phase 14
implementation has started on this branch.**

Authoritative plan:
`docs/plans/PHASE-14-MODEL-BACKED-STORY-INCUBATOR.md`

Copy/paste prompt for the other Codex:
`docs/plans/PHASE-14-OTHER-CODEX-PROMPT.md`

Scope split:

- The other computer implements only the model-backed backend and tests.
- The current computer owns all Phase 14 UI, CSS, design tokens, page components
  and visual snapshots after the backend returns for audit.
- The other computer must not use real provider credentials or touch `.data`
  and must not continue the Night Watch manuscript.
- GitHub is the code authority. Do not work on this branch simultaneously from
  both computers.

The next audit must treat deterministic Phase 13 prose and scores as scaffolding,
not as a fallback. A model failure must remain a visible failure. The opening
human gate added in `081a01a` must remain intact: selection alone is insufficient;
all three experimental chapters require explicit approval before StyleBaseline
creation and incubation Canon locking.

---
# 2026-07-19 Phase 14 模型驱动故事孵化器后端交接

当前分支：`agent/model-backed-story-incubator`

准确基线：`081a01ae9614bde42309cbf34ad39019ffad00d1`

本轮后端实现提交：`cb73f21`（后续交接文档提交仅记录该实现结果）。

状态：**第十四阶段后端实现与本地确定性回归已完成；停止继续开发，等待 GPT-5.6 审计。**

## 本轮完成

- 复用现有 OpenAI-compatible Provider、RoleBinding、SecretStore 和 ModelRun；Phase 13 新增统一 JSON 模型调用边界，非法 JSON 只允许一次独立修复调用，仍失败则显式报错。
- `research_planner` 生成并校验六个固定 perspective 的查询计划；Provider 凭据在规划前校验，查询重复、缺失或越界均使任务失败。
- `research_analyst` 分批抽取短证据并综合竞品和 findings；excerpt/locator 必须匹配冻结来源版本，fact 必须引用同 job evidenceId。
- `story_incubator` 生成 3-5 个机会、多轮共创回复、StoryBrief、通用 Canon、三种开篇和选中方向的第 2/3 章实验稿；所有写入前重验 revision/checksum。
- `reader_simulator` 与 `opening_editor` 分别独立调用并各自关联 ModelRun；失败不生成固定评分或伪通过评审。
- 修正机会评分：各分项仍受固定上限约束，`totalScore` 为 0-100 自然求和，不再强制等于 100；专项验证模型机会得到 74 分。
- 保持研究、机会、StoryBrief、Canon 和开篇的人工接受机制；只选中开篇不会创建 StyleBaseline，三章逐章人工批准后才允许孵化 Canon 锁定。
- 所有模型调用均位于 SQLite 写事务外；模型错误、缺失绑定、凭据错误和研究分析失败均显式收敛，研究任务不会悬挂在运行状态。

## 数据库与 API

- 本阶段无新增迁移、无新增表；复用 `model_runs`、角色绑定和 Phase 13 的 17 张项目表。
- 无新增 UI 或公开路由；沿用 Phase 13 的研究、机会、共创、StoryBrief、Canon、开篇、逐章批准和 `/model-runs` API，JSON 语义升级为真实模型输出。
- 自动测试使用本地 FakeModel HTTP Provider 与确定性搜索/抓取 Provider；未调用 DeepSeek、Tavily 或 Firecrawl。

## 验证结果

- Phase 14/13 focused：`7 passed`。
- API full suite 按桌面 124 秒上限分片完成：`167 passed`。
- `npm run test` 已运行，但单命令在 API 阶段被 124 秒环境上限终止；等价 API 分片全部通过，`npm run test:web` 为 `3 files / 11 tests passed`。
- `npm run build`：通过，仅有既有 Vite chunk-size warning。
- Playwright：整套命令受 124 秒上限终止；按项目拆分后 `desktop-1440 7 passed`、`desktop-1280 7 passed`，合计 `14 passed`。
- `python -m compileall -q apps/api/src apps/api/tests`：通过。
- `git diff --check`：通过，仅有 Windows LF/CRLF 提示。

## 已知风险与未完成项

- 真实模型和真实搜索/抓取 Provider 尚未进行付费烟测；审计后应使用全新测试项目和最小预算人工执行，不得复用或读取《夜巡人》项目。
- 真实模型输出质量、token 成本和长上下文截断仍需 GPT-5.6 审计及后续受控验收；本轮不承诺真实模型生成内容达到出版质量。
- 未修改 `apps/web/**`、用户 `.data`、密钥、SQLite、日志、备份 ZIP、正式正文或视觉快照。
