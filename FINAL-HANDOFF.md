# Story Agent 最终开发交付与接力说明

交付日期：2026-07-19

GitHub：`https://github.com/zuming58/Story-Agent.git`

当前完整开发分支：`agent/model-backed-story-incubator`

当前交付基线：`30d7829`，以及本文件所在的后续文档提交
当前稳定主分支：`main`，但只合并到第七阶段，**不能用它代替当前完整开发分支**。

## 1. 交付结论

Story Agent 已从 UI 原型发展为可本地运行的小说生产平台，长篇与短篇小说的主要技术链路已经具备：

```text
作品库
→ 模型与角色配置
→ 市场调研和故事创意孵化
→ StoryBrief
→ Canon 设定库
→ 分层故事规划和章节预算
→ 章节契约
→ 模型写作与事实抽取
→ 硬规则和多角色质量复核
→ 正式提交与状态更新
→ 1/3/5 章自动托管
→ 长篇耐力检查、短篇生产和导出后端
```

当前阶段应从“大规模新增功能”转为：

1. 真实用户测试；
2. 修复可复现 Bug；
3. 改善易用性和中文提示；
4. 调整模型提示、费用与质量规则；
5. 在不破坏既有架构的前提下做小范围 UI 优化。

另一台电脑可以接手 UI 小修，但必须完整遵守 [UI 设计系统](docs/ui/UI-DESIGN-SYSTEM.md)，不得把现有“墨曜指挥舱”改成普通后台模板。

## 2. 当前可用模块

| 模块 | 路由 | 状态 | 说明 |
|---|---|---:|---|
| 作品总览 | `/overview` | 可用 | 多作品独立目录/数据库、创建、切换、改名、试写引导 |
| 创意孵化 | `/incubator` | 可用 | 研究目标、真实调研、故事机会、共创、StoryBrief、Canon 候选、三开篇实验 |
| Canon | `/canon` | 可用 | 故事核心、实体、规则、关系、锁定、变更申请和检索索引 |
| 故事规划 | `/planning` | 可用 | 分层规划、里程碑、章节窗口、ChapterBeat、剧情预算和 AI 差异提案 |
| 章节写作 | `/writing` | 可用 | 章节契约、候选稿、多版本、事实抽取、任务恢复和正式提交 |
| 质量中心 | `/quality` | 可用 | 硬规则、连续性、故事编辑、文风、自动修订、人工批准 |
| 自动托管 | `/automation` | 可用 | 手动 1/3/5 章批次、队列、费用、恢复、补跑和每日策略 |
| 模型设置 | `/settings` | 可用 | Provider、模型、密钥、价格和角色绑定 |
| 安全审计 | `/settings` 内分栏 | 可用 | ZIP 备份恢复、审计事件、模型调用和错误诊断 |
| 故事状态 | `/state` | 占位 | 独立可视化状态台账尚未完成 |
| 短剧制作 | `/drama` | 暂缓 | 用户已明确当前不开发短剧 |

面向用户的图文说明见 [Story Agent 完整操作手册](docs/Story-Agent-使用手册.html)。

## 3. 十四个阶段已经做了什么

1. **产品与高保真 UI 原型**：建立“墨曜指挥舱”、规划中心和固定右侧故事 Agent。
2. **本地数据闭环**：FastAPI、SQLite、Alembic、多作品独立库、审计、备份恢复。
3. **模型基础**：OpenAI 兼容 Provider、Windows Credential Manager、流式调用、结构化提案。
4. **Canon 与记忆**：正式设定、实体关系、规则、状态台账、全文/向量检索边界。
5. **章节流水线**：章节契约、候选稿、事实抽取、质量门、多角色复核、原子提交。
6. **章节工作台 UI**：正文版本、人工修订、质量中心和恢复流程。
7. **自动托管后端**：批次、租约、预算、失败窗口、恢复和日报。
8. **真实试写版**：Canon/规划/1—5 章路线、试写就绪、自动托管 UI 和夜巡人验证。
9. **导出发布基础**：导出、版本和发布后端基础；外部平台真实发布不是当前验收范围。
10. **长篇耐力**：checkpoint、漂移、重复、预算和长程报告基础。
11. **短篇改编桥**：长篇到短篇的结构转换基础。
12. **短篇生产**：短篇预算、物化章节、质量回归和恢复隔离。
13. **通用创意孵化基础**：研究、机会、共创、StoryBrief、Canon 与开篇实验的数据模型和 API。
14. **真实模型驱动孵化**：研究/分析/创意/读者/开篇模型角色、真实 Provider 边界和正式 UI。

历史阶段方案与审计记录都保留在 `docs/plans/`，不要把旧阶段文档当作当前待办重复实现。

## 4. 当前真实验收状态

- 《夜巡人·正式试写》已经完成多章真实模型生成，用于验证章节连续性、质量门和正式提交。
- 《夜巡人》早期开头是在市场研究和创意孵化完善前产生，不能作为商业故事质量标杆。
- 第十四阶段自动化测试已完成；真实 Tavily + Firecrawl + DeepSeek 的完整新作品孵化仍需要用户冒烟测试。
- 用户应新建一部测试作品，从 `/incubator` 开始，最终至少比较三个开篇并选出一个真正愿意继续读的方向。
- 在真实孵化测试通过前，不合并当前分支到 `main`，也不进行 100 章付费压力测试。

## 5. Git 分支现状

当前仓库采用阶段叠加分支，不能只看 `main`：

- `main`：只到 Phase 7 合并结果；
- Phase 8—13 的草稿 PR 仍以阶段链形式存在；
- 当前最完整代码：`agent/model-backed-story-incubator`；
- 下一台电脑应在此分支继续小修并推送；
- 两台电脑不能同时修改同一分支；
- 未经用户确认不得合并 `main`，不得重写/压平历史分支。

开始前必须确认：

```powershell
git fetch origin
git checkout agent/model-backed-story-incubator
git pull --ff-only
git status -sb
git log -3 --oneline
```

如果工作区不是干净状态，先判断变更归属，不得执行 `git reset --hard` 或覆盖用户文件。

## 6. 另一台电脑首次安装

```powershell
git clone https://github.com/zuming58/Story-Agent.git
cd Story-Agent
git checkout agent/model-backed-story-incubator
git pull --ff-only
npm install
npm --prefix apps/web install
uv sync --project apps/api --dev
```

然后双击根目录：

```text
START-STORY-AGENT.cmd
```

脚本会启动：

- API：`http://127.0.0.1:8765`
- Web：`http://127.0.0.1:5173/overview`

若目标电脑没有 `uv`，先安装 `uv`。本机 `F:\Cache\uv\cache` 只是缓存目录，不是必须复制的运行程序；另一台电脑可以使用自己的默认缓存。

## 7. 接力 Codex 必读顺序

开始任何修改前，依次完整阅读：

1. `FINAL-HANDOFF.md`
2. `HANDOFF.md` 顶部最新交接段
3. `docs/Story-Agent-使用手册.html`
4. `docs/ui/UI-DESIGN-SYSTEM.md`
5. `docs/prd/PRD-001.md`
6. 与当前问题有关的 `docs/plans/PHASE-*.md`
7. 实际代码与现有测试

若文档与代码冲突，以当前分支实际代码为准；记录差异，不要扩大范围猜测式重构。

## 8. 数据权威与安全边界

```text
.data/catalog.db
└── 作品目录 / project.json
    └── story.db
        ├── Canon / 规划 / 章节契约
        ├── 候选稿 / 正式提交
        ├── 状态 / 伏笔 / 审计
        └── 自动化 / 孵化 / 调研记录
```

- SQLite 是业务权威；React Query 管业务服务端状态，Zustand 只保存选择、面板宽度等 UI 状态。
- `.data/`、数据库、日志、API Key、备份 ZIP、生成正文和测试临时文件都禁止进入 Git。
- API Key 只进入 Windows Credential Manager/SecretStore；API、日志、备份和界面不得返回完整密钥。
- 每部作品独立 `story.db`，跨作品查询必须携带并验证 `project_id`。
- 所有写操作遵守 revision 乐观锁；过期版本返回 HTTP 409，不得静默覆盖。
- 模型调用期间不得持有 SQLite 长事务。
- 候选稿、AI 提案和 Canon 候选未经确认不得污染正式状态。
- 正文、事实、状态、伏笔和正式提交必须保持原子事务。
- 恢复备份创建新项目，不覆盖原项目。
- 不得修改或提交 `Story agent/`、`openclaw skill/` 两个本地参考目录。

## 9. 允许的后续工作

另一台电脑可以直接处理：

- 用户能够稳定复现的页面或 API Bug；
- 中文提示、空状态、错误解释、按钮禁用原因；
- 在 UI 规范内的对齐、间距、溢出、响应式和可读性修复；
- 缺失的单元测试、API 测试和 Playwright 回归；
- 模型提示、JSON 校验、费用统计和恢复边界的小范围修正；
- 操作手册和交接记录同步更新。

需要用户或主架构审计后才能做：

- 数据库表结构大改或迁移历史重写；
- 取消 revision、确认门、候选稿隔离或事务边界；
- 统一合并所有历史分支；
- 启用外部平台自动发布；
- Windows EXE/WebView2 打包；
- 短剧生产和角色图/分镜工作流；
- 真实付费 100 章以上压力测试。

## 10. Bug 反馈分类

收到用户反馈后先分类，不要把所有问题都当代码 Bug：

| 类型 | 示例 | 处理方式 |
|---|---|---|
| 系统 Bug | 按钮无响应、重复创建、状态恢复错误 | 复现、修代码、补回归测试 |
| UI/文案问题 | 不知道按钮含义、禁用原因不清楚 | 改文案/提示/引导，不改业务规则 |
| 模型输出问题 | 文风干涩、重复、JSON 不稳 | 检查提示、上下文和模型配置 |
| 故事质量问题 | 核心创意不吸引、开头读不下去 | 回创意孵化，不应只修章节流水线 |
| 设定缺失 | 人物、等级、物品没有边界 | 补 StoryBrief/Canon/规划，再重新生成 |
| 外部 Provider | 搜索、抓取、模型超时或额度 | 保存诊断，允许恢复，不伪造成功结果 |

## 11. 每轮修改必须运行

最小验证按改动范围执行，交接前必须全量执行：

```powershell
npm run build
npm run test
npm run test:e2e
git diff --check
```

UI 修改必须同时验证：

- 1440×1024；
- 1280×800；
- 页面无整体横向溢出；
- 右侧 Agent 不遮挡中央操作；
- disabled、loading、empty、error、success、409 状态；
- 刷新后从 SQLite 恢复业务状态；
- 不改变未涉及页面的视觉快照。

测试不得调用真实 DeepSeek、Tavily 或 Firecrawl；使用本地确定性 Provider。真实 Provider 只做用户明确授权的最小人工冒烟测试。

## 12. 每轮结束的交付格式

1. 更新 `HANDOFF.md` 顶部，记录问题、修复、测试和未完成项；
2. 必要时同步 `FINAL-HANDOFF.md`、UI 规范和用户手册；
3. 确认没有提交 `.data`、密钥、日志、ZIP 或生成正文；
4. 提交并推送 `agent/model-backed-story-incubator`；
5. 返回分支、提交号、测试结果、已知限制；
6. 停止继续扩大开发范围，等待用户测试反馈。

## 13. 直接复制给另一台 Codex 的提示词

```text
请接手 Story Agent 项目的后续小修、调试和真实用户测试问题处理。

GitHub：
https://github.com/zuming58/Story-Agent.git

工作分支：
agent/model-backed-story-incubator

如果没有仓库，请自行克隆；如果已有仓库，请 fetch 后切换到指定分支并执行 git pull --ff-only。不要从 main 开发，main 只合并到第七阶段。

开始修改前必须依次完整阅读：
1. FINAL-HANDOFF.md
2. HANDOFF.md 顶部最新交接
3. docs/Story-Agent-使用手册.html
4. docs/ui/UI-DESIGN-SYSTEM.md
5. docs/prd/PRD-001.md
6. 与当前问题相关的阶段文档和实际测试

今后允许你修改 UI，但必须严格保持“墨曜指挥舱”视觉系统，不得改成普通后台模板，不得擅自更换全局色彩、字体、三栏外壳、固定右侧 Agent 或现有交互语义。UI 改动必须通过 1440×1024 和 1280×800 的 Playwright 验收。

只处理用户反馈、可复现 Bug、易用性、文案、测试和小范围质量修复。不要擅自扩大为新阶段，不要开发短剧，不要启用外部平台发布，不要改写数据库迁移历史，不要绕过 revision、事务、候选稿、Canon 锁定、提案确认或质量门。

禁止读取、修改或提交用户 .data、API Key、日志、备份 ZIP、正式正文、Story agent/ 和 openclaw skill/。自动测试不得消费真实 Provider 额度。

修改完成后必须运行：
npm run build
npm run test
npm run test:e2e
git diff --check

随后更新 HANDOFF.md，提交并推送当前分支，返回提交号、测试结果、已知限制，然后停止扩大工作范围，等待用户下一条反馈。
```
