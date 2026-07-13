# Story Agent 第五阶段交接与 GPT-5.6 审计结果

更新时间：2026-07-13
分支：`agent/chapter-pipeline-foundation`
第五阶段基线：`565d7b3`
另一台电脑交付端点：`5b1ef1d`
草稿 PR：https://github.com/zuming58/Story-Agent/pull/4
当前状态：第五阶段实现已完成，GPT-5.6 深度审计及修复已完成，等待提交、推送并合并 PR #4。

## 1. 阶段目标与数据权威

第五阶段完成单章生产闭环：

```text
章节契约
  -> 固定上下文
  -> 候选正文
  -> 候选事实抽取
  -> 确定性质量门
  -> continuity / story_editor / style 三角色评审
  -> 最多两轮修订
  -> 人工或 guarded_auto 批准
  -> 正文、来源版本、状态、快照、索引和审计原子提交
```

- SQLite 是契约、候选稿、质量结果、正式正文与状态的唯一权威。
- `manuscripts/chapter-XXXX.md` 是可重建镜像，写入失败不会伪装成数据库提交失败。
- 模型生成、抽取和评审期间不持有项目数据库长事务。
- 候选正文与候选事实在正式提交前不会污染 Canon、current state 或正式正文。
- `apps/web/**` 页面组件、CSS、设计令牌和 UI 风格没有被修改；仅将 Playwright 测试端口由被占用的 4173 调整为 4174。

## 2. 已实现的数据与 API

项目迁移：`0006_chapter_pipeline`

新增表：

- `chapter_contracts`
- `chapter_jobs`
- `chapter_drafts`
- `chapter_extractions`
- `quality_runs`
- `quality_findings`
- `chapter_commits`

主要 API：

- `POST /api/v1/projects/{project_id}/chapter-contracts/derive`
- `GET /api/v1/projects/{project_id}/chapter-contracts`
- `GET|PUT /api/v1/projects/{project_id}/chapter-contracts/{contract_id}`
- `POST /api/v1/projects/{project_id}/chapter-contracts/{contract_id}/lock`
- `POST /api/v1/projects/{project_id}/chapter-jobs`
- `GET /api/v1/projects/{project_id}/chapter-jobs`
- `GET /api/v1/projects/{project_id}/chapter-jobs/{job_id}`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/run|cancel|retry|revise|approve|commit`
- `GET /api/v1/projects/{project_id}/chapters/{chapter_number}/drafts`
- `GET /api/v1/projects/{project_id}/chapter-drafts/{draft_id}`
- `GET /api/v1/projects/{project_id}/chapter-jobs/{job_id}/quality`
- `POST /api/v1/projects/{project_id}/quality-findings/{finding_id}/accept-risk`

## 3. GPT-5.6 审计发现及已完成修复

### P0/P1 边界修复

1. **防止提前消费后续剧情**
   - 原实现会把第 8 章里程碑作为第 1 章的 `mustAdvance`，会直接制造“100 章内容 10—20 章写完”的问题。
   - 现在里程碑到达允许窗口前只能做最小铺垫，并进入 `mustNotComplete`；完成条件只在允许窗口内启用。
   - 增加全书章节范围、后续节点、禁提前人物/能力/道具、重大事件预算和伏笔窗口校验。

2. **契约上下文防漂移**
   - 锁定、运行和正式提交前均校验 plan node revision、最新 official state snapshot 及完整 locked Canon digest。
   - Canon 文档、实体类型、实体、关系或规则发生变化后，旧契约不能继续运行或提交。

3. **任务状态机与取消恢复**
   - 补齐 queued/run、failed/interrupted/retry、cancel_requested/cancelled 的合法转换和 revision 递增。
   - 在上下文、生成、抽取、校验和各 reviewer 边界检查取消请求。
   - 服务启动可收敛遗留运行任务；已完成任务不能被取消。

4. **修订失败不破坏既有证据**
   - 原实现会在修订模型成功前提前 supersede 质量问题，模型失败后丢失审计证据并卡住任务。
   - 现在仅在新稿、抽取和质量流程成功后 supersede 旧 findings；失败时回到 `human_review`，保留旧 findings 和修订轮次。

5. **guarded_auto 与风险接受**
   - guarded_auto 必须有成功的确定性质量门、三个成功 reviewer、validated extraction，且无 open/accepted-risk 的 error 或 blocker。
   - 风险接受只能作用于 open finding；接受严重问题不能绕过自动批准。

6. **正式提交原子性与失败收敛**
   - 正文、SourceVersion、状态变化、快照、索引、ChapterCommit 和审计在同一项目事务内提交。
   - revision/context 漂移、状态冲突和注入式异常均回滚正式数据，并把任务持久化收敛到 `human_review`。
   - Catalog `currentChapter` 改为项目事务成功后的 best-effort 同步，失败会审计但不会谎报项目事务失败。
   - 重复 commit 幂等返回现有正式提交。

7. **正式章节重写**
   - 已发布章节可创建新契约；锁定新契约时旧 locked contract 原子转为 `superseded`。
   - 未发布章节仍严格禁止两个 locked contract。
   - 新正文提交后旧 SourceVersion、旧 current fact 和旧 current ChapterCommit 被正确取代，历史版本保留。

8. **模型与抽取安全**
   - 密钥存储/Provider 异常统一为脱敏错误，`model_runs` 正确收敛为 failed。
   - 非法抽取 JSON 只允许一次修复重试；失败不会生成 official state。
   - 增加 `expectedCurrentValue` 的提交前冲突检查。

## 4. 新增审计测试覆盖

第五阶段专项测试从 5 条扩展为 20 条，新增覆盖：

- 早期章节契约防抢跑、章节越界和非法空值更新；
- plan、Canon、snapshot/revision 漂移；
- expectedCurrentValue 状态冲突；
- guarded_auto reviewer 完整性及严重风险不可绕过；
- 修订失败保留 findings 与轮次；
- 启动恢复、重试时间字段和取消收敛；
- 跨作品隔离；
- 提交异常全事务回滚；
- 非法抽取只重试一次；
- 模型调用期间不持有项目写锁；
- 禁提前内容、节奏预算；
- 正式章节重写及历史版本替换；
- 备份/恢复包含第五阶段数据和正文镜像。

## 5. 最终验证结果

- 第五阶段专项：`20 passed`
- `npm run test`：API `74 passed`；Web `3 files / 8 tests passed`
- `npm run build`：通过；仅保留既有 Vite chunk-size warning
- `npm run test:e2e`：`6 passed`，覆盖 1440×1024 与 1280×800
- `git diff --check`：通过，仅有 Windows LF/CRLF 提示
- UI 视觉代码：未修改

第一次并行运行 build/test/e2e 时，端到端测试与迁移争用同一个隔离测试库并超时；已删除且仅删除 `apps/web/.e2e-data` 测试残留，改用空闲端口 4174 后独立复跑 6/6 通过。正式 `.data` 未被读取、修改或删除。

## 6. 已知限制

- 第五阶段只交付后端生产闭环和测试，尚未开发章节工作台 UI；UI 仍由当前 GPT-5.6 电脑独占维护。
- 当前 runner 由同步 HTTP 请求驱动，但所有外部模型调用前后使用短事务；后续可换后台队列而不改变状态机语义。
- SQLite 的 Python 3.13 datetime adapter 及 Starlette TestClient 有上游弃用警告，不影响当前功能。
- Web 构建仍有既有单 chunk 大于 500 kB 的警告，可在后续前端阶段做路由级拆包。

## 7. 下一步与协作边界

1. 当前电脑提交并推送本次审计修复。
2. 确认 PR #4 远端检查及差异后合并到 `main`。
3. 合并后再制定第六阶段计划；不要让另一台电脑在本分支继续扩大范围。
4. 下一阶段若包含 UI，仍由当前电脑实现；另一台电脑只负责明确划定的后端、数据库和自动化测试。

禁止提交：API Key、`.data`、SQLite 文件、日志、备份 ZIP、临时文件、`Story agent/` 和 `openclaw skill/`。

## 8. 常用命令

```powershell
npm --prefix apps/web install
uv sync --project apps/api --dev
npm run dev
npm run build
npm run test
npm run test:e2e
```
