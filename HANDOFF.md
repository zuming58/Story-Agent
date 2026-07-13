# Story Agent 第六阶段交接

更新时间：2026-07-13
分支：`agent/chapter-workbench`
阶段基线：`bbc366d`（PR #4 合并提交）
第六阶段实现提交：`452d744`
当前状态：第六阶段代码、视觉验收与全量本地验证已完成，等待最终提交、推送和草稿 PR。

## 1. 本阶段完成内容

第六阶段把第五阶段章节流水线接入正式桌面 UI：

- `/writing`：章节状态轨道、契约生成/编辑/锁定、任务创建/运行/取消/恢复、上下文追踪、候选正文编辑、版本历史与差异。
- `/quality`：确定性规则、连续性审稿、故事编辑、文风审稿、问题证据、风险接受、自动修订、人工批准与 guarded_auto 正式提交。
- `/settings`：增加“模型配置 / 安全审计”分栏，原备份与调用诊断页面不再占用质量中心路由。
- 右侧故事 Agent 在写作/质量页面显示章节、契约、正文版本和选区作用域；AI 选区建议必须由用户应用到编辑缓冲区并保存为新候选版本。
- 页面使用真实第五阶段 API，不依赖静态业务模拟。

UI 仍沿用“墨曜指挥舱”：深墨蓝、暖金操作、紧凑章节轨道和固定右侧 Agent。1440×1024 与 1280×800 均无横向溢出；1280 下生产流水线自动下沉，不压缩正文编辑区。

## 2. 数据库与后端扩展

新增项目迁移：

- `0007_chapter_draft_current`

`chapter_drafts` 新增 `is_current`：

- 每个 chapter job 只允许一份当前候选稿；
- 迁移时将每个任务版本号最高的旧稿标记为 current；
- 新生成、自动修订和人工编辑均创建新版本，不覆盖旧稿；
- 用户可恢复历史候选版本；正式正文和 current state 不受候选版本切换影响。

新增接口：

- `GET /api/v1/projects/{project_id}/chapters/{chapter_number}/commits`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/manual-revisions`
- `POST /api/v1/projects/{project_id}/chapter-jobs/{job_id}/drafts/{draft_id}/activate`

人工正文保存要求 parent draft revision 与 job revision；保存后重新运行事实抽取和完整质量门。外部模型调用仍位于短事务之外。

## 3. 前端数据权威

- React Query：章节契约、任务、候选稿、抽取、质量报告、上下文追踪和提交历史。
- Zustand：当前章节、当前任务、Agent 面板和选区等 UI 状态。
- 业务正文、质量报告和提交状态不写入 `localStorage`。
- 刷新页面后从 SQLite 恢复契约、任务、当前候选版本、质量结果和正式提交。
- 409 revision 冲突会刷新服务端最新数据，不覆盖其他操作。

## 4. 验证结果

- 第五/六阶段专项 API：`23 passed`
- `npm run test`：API `76 passed`；Web `3 files / 9 tests passed`
- `npm run build`：通过，仅保留既有 Vite chunk-size warning
- `npm run test:e2e`：Playwright `10 passed`；覆盖契约锁定、任务刷新恢复、质量中心与两个桌面分辨率
- 浏览器人工视觉检查：1440×1024、1280×800 无横向溢出，Agent 不遮挡编辑区
- Python compileall 与敏感文件检查：推送前最终执行

## 5. 已知限制

- 本阶段没有实现后台定时器、每日多章队列、费用日限额和自动日报；这些属于第七阶段。
- 当前章节 run/revise 接口是同步请求驱动，但状态写入采用可恢复阶段机，模型调用期间不持有项目写事务。
- Playwright 不调用真实付费模型；模型生成、抽取、三 reviewer 和 reviser 由 API 测试中的本地 OpenAI 兼容假服务覆盖。
- 当前构建单 chunk 仍大于 500 kB，后续前端阶段可做路由级 lazy loading。

## 6. 下一台电脑当前任务

只实施 [docs/plans/PHASE-7-AUTOMATION.md](docs/plans/PHASE-7-AUTOMATION.md) 中定义的第七阶段自动托管后端。

禁止事项：

- 不修改 `apps/web/**`、CSS、设计令牌、Playwright 视觉与 UI 文案；UI 仍由当前电脑独占维护。
- 不提前开发短篇策略、短剧改编、外部平台自动发布或 Windows 打包。
- 不提交 API Key、`.data`、SQLite、日志、备份 ZIP、测试临时文件、`Story agent/` 和 `openclaw skill/`。
- 不绕过 Phase 5 的契约、revision、质量门、候选状态和原子提交规则。

完成第七阶段后必须运行 API 全量测试、更新本文件、提交并推送指定分支，然后停止等待 GPT-5.6 审计。

## 7. 常用命令

```powershell
npm --prefix apps/web install
uv sync --project apps/api --dev
npm run dev
npm run build
npm run test
npm run test:e2e
```
