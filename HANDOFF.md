# Story Agent 第八阶段重制交接

更新时间：2026-07-13 21:17（Asia/Shanghai）
当前分支：`agent/trial-ready-workbench`
开发基线：`9277241`
草稿 PR：[#8](https://github.com/zuming58/Story-Agent/pull/8)
状态：**第八阶段重制 A 关卡代码收尾已完成并通过全量自动化测试；B/C 真实恢复与试写未执行，因为本机缺少 HANDOFF 指定恢复 ZIP。**

## 1. 本轮实际完成内容

本轮接手后已完整阅读：

1. `HANDOFF.md`
2. `docs/plans/PHASE-8-REMAKE-REAL-WRITING.md`
3. `docs/plans/PHASE-5-CHAPTER-PIPELINE.md`
4. `docs/plans/PHASE-7-AUTOMATION.md`
5. `docs/prd/PRD-001.md`

按 A 关卡完成代码审计与测试补强：

- 审计 `9277241..HEAD` 的 Phase 8 Canon/规划、Phase 5 章节流水线、Phase 7 自动化恢复相关改动。
- 为 Canon 分段检查点补充专项 API 测试：
  - `core` 成功、`systems` 超时后，failed proposal 保留 `core` 检查点；
  - 服务恢复将遗留 `generating` proposal 收敛为 `failed`，且不丢失 `generationSections`；
  - 相同 StoryBrief 重试只补缺失段，不重跑已完成的 `core`；
  - Canon revision 变化或 StoryBrief 变化时不会复用旧检查点；
  - Analyzer 连续两次非法 JSON 后 proposal 失败，不能 apply 半成品。
- 审计并修复 Phase 7 resume 竞态：手动 resume 可能发生在旧自动化 worker 已标记 run failed、但尚未从 `_running_threads` 清理的短窗口内。旧逻辑会直接忽略新 dispatch，导致 run 永久停在 `queued`；现已增加 pending redispatch，等待旧线程完全结束后自动重新派发。
- 未修改 `apps/web/**`、CSS、设计令牌或视觉快照；仅运行了 Web build/test/e2e。

## 2. 未完成内容与阻塞原因

HANDOFF 之前指定的恢复包路径：

```text
F:\Codex\story\.data\projects\1ffdb07d-d717-42cf-8456-30e1475b2859-story\backups\20260713-121449-7b76116e-ed8b-4de5-b7d2-3a9932f3ae0e.zip
```

本机检查结果：

- `Test-Path` 返回 `False`。
- `F:\Codex\story` 目前只有 `.git` 目录，没有 `.data` 恢复包。
- `F:\Codex\storyagent\.data` 只有 `catalog.db`，没有项目数据库和备份 ZIP。
- 在 `F:\Codex\story` 与 `F:\Codex\storyagent\.data` 中递归查找 `*.zip` 未找到可导入备份。

因此没有执行 B/C 真实验收：

- 未导入项目恢复 ZIP；
- 未确认本地恢复项目中的 `core` 和 `systems` 检查点；
- 未继续 `architect:proposal-analysis`；
- 未 apply/lock 真实 Canon；
- 未生成/apply 真实 1000 章规划；
- 未执行真实第 1—5 章试写；
- 未产生新的真实 ModelRun、Token、费用或正文数据。

下一台 GPT-5.6 审计/继续前必须先取得恢复 ZIP，或由用户明确允许在本机重新生成 Canon。若导入恢复 ZIP，必须确认 `generationSections.core` 与 `generationSections.systems` 已存在，只继续 `architect:proposal-analysis`，不得重跑 core/systems。

## 3. 代码变更摘要

### Canon checkpoint 测试

文件：`apps/api/tests/test_phase8_architecture.py`

- 新增 `_brief()` 测试 helper。
- 新增 4 个 checkpoint/恢复/隔离/失败闭环测试。
- 测试全部使用 monkeypatch fake model，不调用真实付费模型，不写入 API Key。

### Phase 7 resume 竞态修复

文件：`apps/api/src/story_agent_api/phase7.py`

- `Phase7Service` 新增 `_pending_dispatches`。
- `dispatch_run()` 在发现同一 run 的旧 worker 仍存活时，不再静默丢弃 dispatch；它会创建一个 daemon delayed-dispatch 线程，等待旧 worker `join()` 完成并清理 pending 标记后重新调用 `dispatch_run()`。
- 该修复用于保证手动 resume、失败窗口重开和旧 worker 退出之间不会留下永久 `queued` run。

## 4. 迁移、数据库表与 API

本轮没有新增迁移、表或 API。

仍需审计的第八阶段既有迁移：

- Catalog：`0006_project_kind.py`
- Project：`0011_plan_node_chapter_beats.py`
- Project：`0012_story_architecture.py`

相关既有 API：

- `POST /api/v1/projects/{project_id}/canon/generation-proposals`
- `GET /api/v1/projects/{project_id}/canon/generation-proposals`
- `POST /api/v1/canon/generation-proposals/{proposal_id}/apply`
- `POST /api/v1/canon/generation-proposals/{proposal_id}/reject`
- `GET /api/v1/projects/{project_id}/canon/readiness`
- `POST /api/v1/projects/{project_id}/plan/generation-proposals`
- `POST /api/v1/plan/generation-proposals/{proposal_id}/apply`
- `POST /api/v1/plan/generation-proposals/{proposal_id}/reject`

## 5. 测试结果

本轮已运行并通过：

```powershell
uv run --project apps/api pytest apps/api/tests/test_phase8_architecture.py -q
# 6 passed

uv run --project apps/api pytest apps/api/tests/test_phase8_trial_ready.py -q
# 7 passed

uv run --project apps/api pytest apps/api/tests/test_phase7_automation.py -q
# 18 passed

uv run --project apps/api pytest apps/api/tests/test_phase5.py -q
# 25 passed

npm run test
# API: 113 passed
# Web: 3 files / 11 tests passed

npm run build
# passed；仅既有 Vite chunk-size warning

npm run test:e2e
# 14 passed，desktop-1440 与 desktop-1280 均通过
```

## 6. 安全与禁止事项确认

- 未提交 `.data`、SQLite、日志、备份 ZIP、模型原始响应、真实正文或临时文件。
- 未提交 API Key；测试继续使用内存 SecretStore 与 fake/local provider。
- 未修改或提交 `Story agent/` 与 `openclaw skill/`。
- 未合并 `main`。
- 未继续短剧、导出发布或第九阶段范围。

## 7. 下一步给 GPT-5.6 的审计提示

请以 `9277241` 为代码基线审计当前分支 `agent/trial-ready-workbench`。

重点审计：

1. Canon checkpoint 测试是否完整覆盖 HANDOFF A 关卡要求；
2. `phase7.dispatch_run()` 的 delayed redispatch 是否会产生重复执行、线程泄露或跨 run 干扰；
3. `0011/0012` migration 链与 ProjectMeta/CatalogProject 双层 `project_kind` 是否符合预期；
4. Phase 8 Canon apply/lock 与 planning apply 在真实恢复包导入后是否仍保持 revision、跨作品隔离和半成品不可应用；
5. 恢复 ZIP 缺失导致 B/C 未执行，需要由用户补齐恢复包或明确允许重新生成 Canon 后再继续。

当前分支不得合并 `main`。拿到恢复 ZIP 前，不要跳过 Canon/规划直接写章节。
