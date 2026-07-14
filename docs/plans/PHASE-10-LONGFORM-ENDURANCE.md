# 第十阶段：长篇中程耐久测试与漂移监控

状态：等待另一台电脑实施后端基础，完成后返回当前 GPT-5.6 审计

建议分支：`agent/longform-endurance-foundation`

开始基线：第九阶段 GPT-5.6 审计后的 `agent/export-publishing-foundation` 最新提交

范围所有权：另一台电脑仅开发后端、数据库、公共类型和 API 测试；不得修改 `apps/web/**`、UI、CSS、设计令牌、Playwright 或视觉快照

## 1. 阶段目标

真实试写目前只完成第 1—5 章。第十阶段不直接扩展短篇或短剧，而是先建立可审计的 20—30 章中程耐久验证能力，专门发现长篇最危险的问题：

- 原定 100 章节奏在 10—20 章内被提前写完；
- 人物、能力、法器或真相提前出现；
- 人物知道了自己不应知道的信息；
- 伏笔遗漏、过期或错误回收；
- 服务重启、取消或模型失败后重复写章、重复扣费或产生多个 current commit；
- 候选稿、抽取失败或修订稿污染正式 Canon/状态；
- 运行费用、失败率和质量趋势在长批次中失控。

目标流程：

```text
选择 5/10/20/30 章耐久方案
  -> 确定性就绪检查
  -> 复用 Phase 7 自动托管逐章执行
  -> 每个正式 commit 后生成不可变 checkpoint
  -> 运行节奏/人物/能力/法器/知识/伏笔漂移规则
  -> 达到 blocker、预算或连续失败阈值时停止
  -> 输出中程趋势报告与可恢复位置
```

另一台电脑不得消耗真实 DeepSeek API。真实 20—30 章运行只在当前电脑完成代码审计后，由用户明确确认费用再执行。

## 2. 数据权威与架构边界

- 耐久运行是 Phase 7 自动化的监督层，不复制章节生成、抽取、质量门、修订或提交实现。
- 每个耐久批次引用一个或多个 `automation_runs`，不得绕过租约、预算、revision 和停止策略。
- checkpoint 只能在 current official `ChapterCommit` 成功后建立。
- checkpoint 保存当时的 commit/source/snapshot/checksum、剧情预算、人物知识、能力、法器、伏笔和费用摘要；不得保存 API Key。
- 漂移检查默认确定性执行，不调用模型；可解释规则必须返回规则编号、证据、影响章节和修复建议。
- 模型调用期间继续不得持有 SQLite 长写事务。
- 候选稿、失败抽取和未批准修订不能计入 checkpoint。
- 恢复运行必须从最后一个已验证 checkpoint 之后继续，不得重写已有 current official 章节。
- 同一作品同一时间最多一个 active endurance run；跨作品必须完全隔离。

## 3. 数据库设计

新增下一顺序项目迁移，表名建议如下：

### `endurance_suites`

- `id`、`project_id`、名称、起始章节、目标章节数 `5|10|20|30`。
- 每日/总费用上限、连续失败上限、停止严重度、启用规则、revision 与时间字段。

### `endurance_runs`

- `id`、`project_id`、`suite_id`、状态、起止章节、目标数、已完成数。
- 当前 automation run/item 引用、最后 checkpoint、累计 token/费用、停止原因、diagnostic。
- 状态：`queued|running|paused|blocked|completed|cancel_requested|cancelled|interrupted|failed`。
- 同作品只允许一个 active run；非空 idempotency key 唯一。

### `endurance_checkpoints`

- `run_id`、章节号、commit/source/snapshot ID 与 revision/checksum。
- Canon revision、Plan revision/预算摘要、人物知识摘要、能力/物品/伏笔摘要、费用摘要。
- checkpoint checksum、验证状态、创建时间；同一 run/chapter 唯一且不可原地覆盖。

### `endurance_findings`

- `run_id`、checkpoint、规则编号、严重度、章节、证据、修复建议、状态和 fingerprint。
- 同一 run/fingerprint 去重；规则重跑保留历史或显式 supersede。

### `endurance_reports`

- 批次汇总：成功/隔离/失败章节数、token、费用、平均修订轮数、质量趋势、漂移趋势、停止原因和 checksum。

## 4. 确定性漂移规则

至少实现：

- `ENDURANCE_COMMIT_SEQUENCE_GAP`：正式章节不连续。
- `ENDURANCE_DUPLICATE_CURRENT_COMMIT`：同章出现多个 current official commit。
- `ENDURANCE_STATE_NON_ATOMIC`：commit、source、snapshot、正文或状态引用不一致。
- `ENDURANCE_PACING_EARLY`：里程碑在 earliest/window 前完成。
- `ENDURANCE_PACING_LATE`：超过 latest 仍未完成。
- `ENDURANCE_CHARACTER_EARLY`：人物早于允许章节出场。
- `ENDURANCE_ABILITY_WINDOW`：能力等级早于升级窗口或缺少前置条件。
- `ENDURANCE_ITEM_STATE_DRIFT`：法器持有人、次数、代价、损坏状态不连续。
- `ENDURANCE_KNOWLEDGE_LEAK`：人物知识超出正式知识边界。
- `ENDURANCE_FORESHADOW_MISSED`：伏笔逾期未回收或未埋设即回收。
- `ENDURANCE_REVISION_LIMIT_BREACH`：单章修订超过两轮。
- `ENDURANCE_COST_LIMIT`：预测或实际费用超过批次限制。
- `ENDURANCE_RESTART_DUPLICATION`：恢复后重复创建任务、扣费或 commit。

严重度至少区分 `info|warning|error|blocker`。blocker 必须停止后续章节；warning 允许继续但进入报告。

## 5. 服务与 API

建议新增：

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

API 使用 camelCase、UUID4、UTC ISO 8601 和现有 `ApiError`。所有更新携带 expected revision；创建运行支持 idempotency key。

## 6. 执行与恢复

- 默认只创建/驱动 5 章测试；10/20/30 章需要明确传入目标数。
- 运行建立后，逐章复用现有自动化调度，不得一次把 30 章全部标记 running。
- 每次 official commit 后在短事务中冻结 checkpoint，再在事务外执行较重的报告聚合。
- 服务重启把 active endurance run 收敛为 `interrupted`，不得自动继续消耗模型费用。
- resume 校验最后 checkpoint 和当前 official 状态一致；漂移时返回 409，不得覆盖现有章节。
- cancel 后不得继续派发下一章；正在进行的模型调用沿用 Phase 7 取消语义。
- 备份保留 suite、run、checkpoint、finding 和 report；恢复为新项目时 remap project ID、清除运行权和活动租约，并把 active run 标为 interrupted。

## 7. 测试要求

必须使用确定性测试 Provider，不调用真实 DeepSeek：

- 5/10/20/30 章参数、边界和就绪检查。
- 同作品 active run 唯一、幂等并发创建和跨作品隔离。
- 每章最多一个 checkpoint；checkpoint 必须引用 current official commit。
- 章节缺口、重复 commit、来源链断裂、revision 漂移阻止继续。
- 人物提前、能力升级窗口、法器状态、知识泄露、伏笔逾期和节奏提前规则。
- warning 可继续，error/blocker 按停止策略停止。
- 取消期间不继续派发；重启后 interrupted；恢复不重复章节和费用。
- 模型失败、抽取失败、质量隔离时不产生正式 checkpoint。
- 事务失败时 checkpoint、finding、run 计数整体回滚。
- 备份恢复 remap、活动状态收敛和跨项目隔离。
- 全量 API 测试通过。

不得修改或运行 UI 快照更新；可运行现有 Web/Playwright 回归确认无意外改动。

## 8. 交付规则

1. 从第九阶段审计提交创建 `agent/longform-endurance-foundation`。
2. 开发前完整阅读 `HANDOFF.md`、本文、第八/九阶段方案及审计记录。
3. 只做本阶段后端、迁移、公共类型和测试，不做 UI。
4. 不运行真实 DeepSeek，不修改 `.data` 中用户正式作品，不提交正文、密钥、数据库、日志或备份。
5. 完成后运行 API 全量测试、Web 单测、构建和现有 Playwright。
6. 更新 `HANDOFF.md`，记录迁移、表、API、规则、测试数、提交号和已知限制。
7. 提交并推送功能分支，不合并 main；停止等待 GPT-5.6 审计。

第十阶段审计通过后，当前电脑才执行真实 20—30 章中程试写。中程稳定后，第十一阶段再进入短篇策略和短剧改编桥梁。
