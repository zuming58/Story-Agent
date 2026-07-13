# 第七阶段 GPT-5.6 完整审计

审计日期：2026-07-13
审计基线：`86c849c`
被审计终点：`26b292e`
审计分支：`agent/automation-foundation`

## 审计结论

另一台电脑交付的第七阶段主路径成立：自动托管策略、调度、串行章节生产、费用统计、日报、租约、恢复和 API 已形成后端闭环，且未修改 `apps/web/**`。但原有测试没有覆盖若干崩溃、跨进程和恢复边界，不能直接合并。

本轮已直接修复：

1. 恢复新作品时同时重映射 `automation_runs.policy_id`，避免它继续指向原作品 ID。
2. 恢复克隆不继承原进程的活租约；复制来的 active run/job 收敛为 `interrupted`，等待明确恢复。
3. 活租约增加 fencing；租约过期、被替换或取消后，旧执行器不能继续模型调用、批准或正式提交。
4. 第二个 API 进程启动时，如果发现另一个进程仍持有有效自动化租约，不再错误中断其 Phase 5 ChapterJob。
5. 调度器每轮收敛过期租约；不再出现租约到期后 run 永久停在 `running` 的情况。
6. 同作品已有运行时，新 run 保持 `queued`，不再误记为 `AUTOMATION_LEASE_BUSY/blocked`；调度器随后串行分发。
7. 尚未实际启动的 queued run 可立即取消并进入终态，不再停在 `cancel_requested`。
8. 手动 run 与 catch-up 的幂等重试可重新分发遗留 queued run，但不会重复审计或改写终态。
9. 每日费用上限按模型调用的真实执行日与策略时区统计，旧日期 catch-up 不能绕过当天预算。
10. `missed`、`interrupted` 和崩溃后补记的 token/费用会刷新到日报。
11. “正式提交已成功、item acknowledgement 尚未落库”时，恢复会按同一 ChapterJob 认领原 commit，记为 `committed`，不会误记成外部已存在章节的 `skipped`，也不会重复调用模型。
12. Playwright 使用每次独立的 E2E 数据目录，并将 Windows 冷启动迁移等待提高到 45 秒，避免超时终止服务留下半迁移测试库。

## 不变式复核

- 外部模型调用不位于 SQLite 写事务内。
- 自动化仍只调用 Phase 5 契约、候选、质量门、guarded approval 与原子 commit 流程。
- 候选正文、抽取与质量结果在正式提交前不改变 Canon/current state。
- 同一作品同一时刻只有有效租约持有者可进入自动化正式提交事务。
- 两部作品的 run、item、lease、日报和费用仍位于各自独立 `story.db`。
- 未修改 `apps/web/**`、CSS、设计令牌或视觉基线。

## 验证状态

- Phase 7 专项：`18 passed`
- Python compileall：通过
- `git diff --check`：通过，仅有 Windows LF/CRLF 提示
- `npm run test`：API `95 passed`；Web `3 files / 9 tests passed`
- `npm run build`：通过，仅保留既有 Vite chunk-size warning
- `npm run test:e2e`：`10 passed`，覆盖 1440×1024 与 1280×800
