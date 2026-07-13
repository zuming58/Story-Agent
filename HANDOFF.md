# Story Agent 第八阶段后端开发交接

更新时间：2026-07-13
当前分支：`agent/export-publishing-foundation`
第七阶段基线：`86c849c`
另一台电脑交付终点：`26b292e`
GPT-5.6 审计修复：`e17db9a`
第七阶段审计 PR：`#6`（已合并）
第八阶段基线：`7a808b4`
第八阶段草稿 PR：`#7`
当前任务：由另一台电脑只实施第八阶段导出与发布准备后端

## 1. 当前完成状态

第七阶段“每日自动托管与可恢复生产队列”已经完成实现、GPT-5.6 完整审计、问题修复、全量验证并合并到 `main`。

已具备：

- 每作品自动托管策略、IANA 时区、每日到期检查、missed/catch-up。
- 手动运行、幂等重试、多章节严格串行、取消、恢复和中断收敛。
- Phase 5 契约、候选稿、事实抽取、多角色质量门、最多两轮修订、guarded approval 和原子正式提交复用。
- 项目级 SQLite 租约、心跳、租约过期收敛与 commit-time fencing。
- 模型 token、估算费用、真实执行日预算、连续模型失败阈值与日报。
- 自动化 policy/run/item/lease/report 的备份恢复和跨作品隔离。
- run/item/ModelRun 的精确关联、available actions 与诊断信息。

完整审计记录见 [docs/plans/PHASE-7-AUDIT.md](docs/plans/PHASE-7-AUDIT.md)。

## 2. GPT-5.6 本轮修复

- 恢复作品同时 remap `automation_runs.policy_id`。
- 恢复克隆清除原进程运行时租约，active run/job 收敛为 `interrupted`。
- 租约过期、被替换或取消后，旧执行器不能继续模型调用、批准或正式 commit。
- 第二个进程启动时不再错误中断另一个有效租约持有者的 ChapterJob。
- 调度器周期性回收过期租约；queued run 在同作品前序运行完成后串行分发。
- queued run 可立即取消；手动 run 与 catch-up 幂等重试不重复审计或生成。
- 当天费用按 ModelRun 真实执行时间与策略时区统计，旧日期补跑不能绕过预算。
- missed/interrupted 会进入日报；崩溃后会补同步 token 与费用。
- 正式 commit 已成功但 item acknowledgement 未落库时，恢复会认领同一 job 的 commit，不误记 skipped、不重复付费。
- Playwright 每次使用独立数据目录；冷启动迁移等待提高到 45 秒，避免测试超时杀死 Alembic。

## 3. 数据权威与禁止绕过的规则

- Catalog SQLite：作品目录、模型 Provider、模型配置和角色绑定。
- 每部作品独立 `story.db`：Canon、状态、检索、章节契约、候选稿、质量、正式提交和自动化运行。
- `ChapterCommit.is_current = true` 才是正式正文；候选稿不能直接进入 Canon/current state。
- 自动化只能通过 Phase 5 的 guarded approval 和原子 commit，不能直接写正式状态。
- 模型调用与文件渲染期间不得持有 SQLite 写事务。
- 同作品只有有效租约持有者可进行自动化正式提交；租约校验必须在 commit 事务内再次执行。
- GitHub 是两台电脑唯一代码权威；`.data` 和本地 E2E 数据不通过 Git 同步。

## 4. 最终验证

- Phase 7 专项：`18 passed`
- `npm run test`：API `95 passed`；Web `3 files / 9 tests passed`
- `npm run build`：通过，仅保留既有 Vite chunk-size warning
- `npm run test:e2e`：Playwright `10 passed`，覆盖 1440×1024 与 1280×800
- Python compileall：通过
- `git diff --check`：通过，仅有 Windows LF/CRLF 提示
- 未修改页面组件、CSS、设计令牌或视觉风格；只调整 Playwright 数据隔离与冷迁移等待

## 5. 下一台电脑唯一任务

只实施 [docs/plans/PHASE-8-EXPORT-PUBLISHING.md](docs/plans/PHASE-8-EXPORT-PUBLISHING.md) 定义的第八阶段“作品导出与发布准备后端”。

工作分支：

```text
agent/export-publishing-foundation
```

开始前依次完整阅读：

1. `HANDOFF.md`
2. `docs/plans/PHASE-8-EXPORT-PUBLISHING.md`
3. `docs/plans/PHASE-7-AUTOMATION.md`
4. `docs/plans/PHASE-5-CHAPTER-PIPELINE.md`
5. `docs/prd/PRD-001.md`
6. `docs/ui/UI-DESIGN-BASELINE.md`

禁止事项：

- 不得修改 `apps/web/**`、CSS、设计令牌、UI 文案和 Playwright；UI 继续由当前电脑独占维护。
- 不得开发自动托管 UI、导出 UI、短篇策略、短剧改编、外部平台登录发布或 Windows 打包。
- 不得把 candidate draft 当作正式导出正文。
- 不得在渲染 DOCX/EPUB/TXT/Markdown 时持有 SQLite 写事务。
- 不得提交 API Key、`.data`、SQLite、导出成品、日志、备份 ZIP 和临时文件。
- 不得修改或提交 `Story agent/` 与 `openclaw skill/` 参考目录。

完成后必须运行 API 全量测试，更新本文件，提交并推送功能分支，不合并 `main`，停止等待 GPT-5.6 审计。

## 6. 常用命令

```powershell
npm --prefix apps/web install
uv sync --project apps/api --dev
npm run build
npm run test
npm run test:e2e
```

另一台电脑本轮只改后端，通常只需运行 API 专项与 API 全量测试；交回当前电脑后，由 GPT-5.6 再运行包含 UI 的全量验证。

## 7. 返回当前电脑时的固定回复

```text
第八阶段已经完成并推送。分支为 agent/export-publishing-foundation，最新提交为 <commit>，请以 7a808b4 为基线，读取 HANDOFF.md 和 docs/plans/PHASE-8-EXPORT-PUBLISHING.md，进行完整审计、修复并运行全量测试。未修改 apps/web/**。
```
