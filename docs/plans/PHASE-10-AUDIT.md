# 第十阶段 GPT-5.6 代码审计记录

审计日期：2026-07-14

实现基线：`4c52862`

审计分支：`agent/longform-endurance-foundation`

## 审计结论

第十阶段原始实现不能直接用于真实长篇耐久运行。静态检查与 5 个专项测试虽然通过，但真实 Phase 7 是后台异步执行，原监督器会在第一批尚未完成时立即检查全部目标章节，把未来章节误判为缺章并阻断；10/20/30 章也只派发首批 5 章，没有可靠的终态回调继续下一批。

本次已直接修复核心状态机、检查点权威关系、真实抽取结构适配、并发 revision、费用归属和备份恢复问题，并补充异步批次回归测试。修复后可作为第十阶段后端基础，但仍未消耗真实 DeepSeek 运行 20—30 章。

## 已修复问题

- Phase 7 后台任务终态回调 Phase 10；每批正式收口后再评估并派发下一批。
- 只对已经终态执行的章节检查缺口，不再把未来章节判为缺章。
- 10 章专项验证会真实拆成两个 5 章批次；剩余章节数只使用 Phase 7 支持的 1/3/5 规模，不越界。
- Checkpoint 只接纳本次 endurance run 对应 automation item 的 committed 章节，不读取无关历史 commit。
- Checkpoint 保存正确的 automation run/item 归属；费用只统计该 item，避免重试或历史任务重复计费。
- 检查 commit、approved draft、validated extraction、official source、snapshot 的作品归属、互相引用、状态、revision、正文摘要和实际 checksum。
- Resume 重新校验 checkpoint checksum、Canon/Plan revision 和完整正式来源链；漂移返回 409。
- Cancel 不再吞掉底层取消失败；后台 callback 异常会把耐久运行安全收敛为 interrupted。
- Cancel、resume、evaluate API 必须携带 `expectedRevision`，过期写入返回 409。
- 每轮评估先关闭旧 finding，再根据当前权威状态重建；已修复问题不会永久阻断恢复。
- 费用规则在最新 checkpoint 汇总后执行，同时检查单次总上限和每日上限。
- Restart duplication 只统计本次 endurance run 的 automation items，不误伤其他历史运行。
- 新增连续失败阈值规则 `ENDURANCE_CONSECUTIVE_FAILURE_LIMIT`。
- 将 Phase 10 漂移规则适配 Phase 5 真实结构：`entities/facts/boundaries/events/foreshadows`。
- 里程碑逾期只检查 milestone，不把普通 ChapterBeat 误报为逾期。
- 备份恢复 remap Phase 10 JSON 中的 project ID，并重新计算 checkpoint/finding/report checksum。
- 未修改 `apps/web/**`、UI、CSS、设计令牌、Playwright 或视觉快照。

## 新增回归覆盖

- 真实异步形态下首批运行中无未来章节缺口误报。
- 第一批 5 章终态后自动派发第二批，10 章完成后形成 10 个 checkpoint。
- stale revision 的 resume 返回 409。
- 生产抽取 schema 能触发人物提前、能力窗口、法器漂移、知识泄露、伏笔与节奏规则。
- 既有恢复漂移、幂等、报告和备份恢复覆盖继续通过。

## 最终验证

```text
Phase 10 focused API: 8 passed
Full API + Web: API 138 passed; Web 3 files / 11 tests passed
npm run build: passed
npm run test:e2e: 14 passed
```

仅保留既有非阻断 warning：

- FastAPI TestClient 的 httpx2 迁移提示；
- Python 3.13 SQLite datetime adapter deprecation；
- Vite 单 chunk 大于 500 kB。

## 尚未执行

- 未调用真实 DeepSeek。
- 未在“夜巡人·正式试写”上运行 20—30 章付费中程测试。
- 第十阶段没有 UI；UI 仍由当前电脑维护。
- 是否合并 main 由用户在真实中程试写或下一次 UI 验收后决定。
