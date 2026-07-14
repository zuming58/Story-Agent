# 第十一阶段 GPT-5.6 审计记录

更新时间：2026-07-14  
审计基线：`agent/longform-endurance-foundation@b20b7e2`  
被审计提交：`agent/shortform-adaptation-foundation@2f94b1f`

## 结论

第十一阶段的数据库迁移、短篇策略提案、来源快照和备份恢复基础可保留。审计发现的并发、幂等、来源权威和质量门漏洞已在当前分支修复。短剧相关后端作为休眠代码保留，但从本次审计起不再列入当前产品开发范围；当前范围仅为长篇小说与短篇小说。

必须明确：本阶段只生成并保存 `ShortStoryStrategy`，还没有把策略变成可正式提交的短篇正文，因此短篇小说尚未形成完整生产闭环。

## 已修复问题

1. 短篇工作区可以调用短剧提案接口，短剧工作区也可以错误应用短篇策略。现在按 proposal kind 强制校验 workspace kind。
2. 同一工作区的幂等键可被不同指令或不同 proposal kind 复用。现在保存请求指纹，不同请求复用同一键返回 409。
3. 模型调用期间用户修改目标字数等工作区数据，旧模型结果仍会进入 pending 并可应用。现在生成完成与应用时都校验 workspace revision；漂移结果标记 failed，不写入策略。
4. 两个坏提案产生相同 finding 时，第二个提案可能复用第一个 finding，绕过 apply 阻断。finding 指纹现在包含 proposalId；拒绝提案会关闭其 findings。
5. 新建短篇工作区在没有策略时被错误报告为 ready，并可直接锁定。现在 readiness 和 lock 都要求 active 且 checksum 有效的策略。
6. 锁定或归档的工作区仍可直接修改。现在锁定工作区只允许归档，归档工作区完全只读。
7. Plan manifest 只冻结节点编号和范围，修改目标、前置条件、伏笔、章节节拍等内容无法检测。现在冻结完整 Plan/PlanNode/StoryMarker 内容。
8. chapter range 只冻结 commit 行，没有验证 approved draft、official source、state snapshot 与正文 checksum 链。现在冻结并复核完整权威链及各 revision/checksum。
9. 模型返回合法 JSON 但字段类型错误时，响应或 apply 可能直接 500。现在对响应公共字段归一化，并把短篇必填字段、目标字数、章节预算、伏笔和压缩规则的错误转成确定性 finding。
10. readiness 在来源对象被删除或损坏时直接返回错误。现在返回 blocked 状态和明确 diagnostic，不把只读检查变成 500/404。

## 新增回归覆盖

- 短篇/短剧接口分型。
- 幂等键请求冲突。
- 模型调用期间 workspace revision 漂移。
- 重复坏提案的 finding 隔离。
- Plan 内容无 revision 篡改检测。
- 正式章节正文与状态引用篡改检测。
- 缺少策略时 readiness/lock 阻断。

## 验证结果

```text
Phase 11 focused API: 9 passed
Full API: 147 passed, 298 warnings
Web unit: 3 files / 11 tests passed
Build: passed（仅既有 Vite chunk-size warning）
Playwright: 14 passed（1440×1024 与 1280×800）
```

现有 warnings 来自 FastAPI TestClient、Python 3.13 SQLite datetime adapter 等上游弃用提示，不是本阶段新增失败。

## 后续边界

- 不继续短剧、短视频、分镜、图像、配音或外部视频发布开发。
- 长篇继续使用现有 Canon、Plan、Phase 5 章节流水线、Phase 7 自动托管、Phase 9 导出和 Phase 10 耐久监控。
- 下一阶段只补齐短篇小说正文生产闭环，方案见 `PHASE-12-SHORT-STORY-PRODUCTION.md`。
