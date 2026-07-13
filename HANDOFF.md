# Story Agent 第八阶段重制交接

更新时间：2026-07-13 夜间（GPT-5.6）

当前分支：`agent/trial-ready-workbench`

草稿 PR：[#8](https://github.com/zuming58/Story-Agent/pull/8)

状态：**正式 Canon 与 1000 章分层规划已完成；第一章保留 3 个安全候选稿，未正式提交。按用户要求今晚停止，明天继续真实验收。**

## 1. 今晚完成的正式数据

正式项目：

- 项目：`夜巡人·正式试写`
- Project ID：`1ffdb07d-d717-42cf-8456-30e1475b2859`
- `projectKind=standard`
- `currentChapter=0`
- 总章数：1000

Canon：

- 真实 DeepSeek Canon 已生成、分析、应用并锁定。
- Canon 文档 revision：3。
- 结构化数据：19 个实体、10 条关系、16 条规则。
- 六阶能力、四级法器、三个第一卷核心物品、七卷边界、升级窗口、揭示窗口和第 1—5 章节拍均存在。
- Canon 就绪检查：全部通过，无 blocked 项。

规划：

- 真实规划提案已生成并应用，Plan revision：2。
- 共 11 个规划节点，覆盖 1000 章七卷边界。
- 第一卷包含升级与真相预算；第 1—5 章均有精确 `ChapterBeat`。
- 项目仍为第 0 章，没有把演示项目第 36 章状态带入正式项目。
- 1、3、5 章试写就绪检查均通过。

## 2. 第一章真实验收保存点

自动化运行：

- Run ID：`d5dabe1d-ba2c-471d-ad43-e840c85cfd30`
- Chapter Job ID：`749f971f-ee3f-4dd0-be95-878fbb0bfd74`
- 当前安全状态：run=`interrupted`、item=`waiting`、job=`interrupted`
- `availableActions` 包含 `resume`
- 当前 revision round：2（已经达到允许的第二轮，不得再开启第三轮修订）
- 中断原因：为加载新抽取逻辑主动重启服务；租约过期后系统正确收敛为 `automation_lease_recovery`。

候选稿：

| 版本 | 类型 | 字数 | 当前稿 | 说明 |
|---|---:|---:|---:|---|
| v1 | generated | 4123 | 否 | 原始稿，超出 3000 字且钩子/节拍检查未完全通过 |
| v2 | revised | 2358 | 否 | 第一轮修订稿，模型审稿通过，仅精确伏笔代码未匹配 |
| v3 | revised | 2518 | 是 | 第二轮安全候选，等待用新逻辑重新完成抽取与质量门 |

重要边界：

- 第一章没有正式 commit，`currentChapter` 仍为 0。
- 3 个正文版本只存在本机 `.data`，没有进入 Git。
- 候选稿没有污染正式 Canon、状态快照或伏笔台账。
- 明天必须恢复现有 run，不得新建第一章 run，也不得重新调用写作模型。
- 第 2—5 章尚未生成；今晚按用户要求不再继续。

## 3. 真实验收发现并修复的代码问题

### Canon 提案应用边界

- 原校验要求模型逐字写出“硬规则”，即使已存在“怪异规则”和 16 条结构化硬约束也会误阻断。
- 现改为语义检查“怪异 + 规则”，结构化数量与约束仍由确定性规则检查。
- `apply` 不再信任旧 `readiness_json` 快照；在写入边界重新执行当前校验，避免旧规则产生误接受或误拒绝。
- 新增 stale-false 可重新通过、stale-true 必须被拒绝的回归测试。

### 真实审稿输出截断

- DeepSeek 连续性审稿首次因 `content_truncated` 安全失败；正文与正式状态均未被错误提交。
- 原因是审稿提示携带完整未来规划，且 reviewer 输出上限偏小。
- 已压缩 `mustNotAdvance` 为必要范围字段，将 reviewer 上限调整为 3072。
- reviewer 截断时只允许一次精简重试；仍失败就阻断。
- 新增测试证明只重试审稿，不重新生成正文或重复抽取。

### 精确伏笔代码缺失

- 真实验收发现 `FOG-OLD-HOUSE-LETTER` 未通过确定性门。
- 原因不是正文缺少异常来信，而是 narrative extractor 从未收到契约的 `requiredForeshadows`，无法稳定输出精确 code。
- 已把 `requiredForeshadows`、`requiredHooks` 和完成条件传给 narrative extractor，并要求命中时逐字保留契约 code。
- v3 需要明天恢复后用新逻辑重新抽取验证。

## 4. 真实模型调用记录

截至停止点，该正式项目共有：

- ModelRun：42 次
- succeeded：35
- failed：5（包含被安全拒绝的截断调用）
- interrupted：2
- 成功调用 Token 合计：191,978
- 系统估算费用合计：0.124352（按 Provider 配置价格计算；不在本文假定币种）

API Key 仅保存在 Windows Credential Manager，没有写入 Git、SQLite、日志或备份。用户曾在对话中粘贴过该 Key，完成验收后建议到 DeepSeek 控制台轮换。

## 5. 测试状态

已通过：

```powershell
uv run pytest tests/test_phase8_architecture.py -q
# 7 passed

uv run pytest tests/test_phase5.py::test_model_reviewer_retries_one_truncated_response_without_redrafting -q
# passed

uv run pytest tests/test_phase5.py::test_quality_accept_risk_and_revision_creates_new_draft `
  tests/test_phase5.py::test_model_reviewer_retries_one_truncated_response_without_redrafting -q
# 2 passed
```

最新全量运行：

```text
API：115 passed，1 failed，耗时 378.25s
```

唯一失败来自测试假 Provider 的请求分类顺序：reviser 和 reviewer 都包含 `requiredOutput`，测试桩误把 reviser 当 reviewer，返回了空正文。测试桩已修正，失败用例与新回归用例随后均通过。因用户要求今晚停止，**修正后尚未再次跑 6 分钟 API 全量、Web test、build 与 e2e**；明天交付前必须补跑。

## 6. 明天严格执行顺序

1. 确认 Git 工作区干净、API 未在后台自动运行。
2. 启动 API，读取上述 run/job，确认仍为 `interrupted` 且可 `resume`。
3. 调用现有 run 的 `/resume`；不得创建新 run。
4. 验证直接复用 v3，不调用 `chinese_writer` 和 `reviser`，只重新执行未完成的抽取/质量阶段。
5. 确认 narrative extraction 使用精确 `FOG-OLD-HOUSE-LETTER`。
6. 若 v3 所有 error/blocker 清零，执行 guarded approve 和原子 commit；确认 `currentChapter=1`。
7. 重启服务，确认第一章 commit、Canon、状态快照与费用记录恢复正确且没有重复调用。
8. 先跑全量 API/Web/build/e2e；通过后再决定是否逐章生成第 2—5 章。
9. 第 2—5 章必须一章一章验收，不得直接一次性放任 5 章付费运行。

## 7. 禁止事项

- 不修改 UI、CSS、设计令牌或视觉快照。
- 不修改或提交 `Story agent/` 与 `openclaw skill/`。
- 不提交 `.data`、SQLite、真实正文、API Key、日志或备份 ZIP。
- 不绕过两轮修订上限、revision、租约、质量门或原子提交。
- 不合并 `main`，直到第一章正式提交、重启恢复和全量测试通过。
- 不推进导出、外部发布、短篇、短剧或 EXE 打包。

## 8. 本地恢复点

原 Canon 恢复包仍在：

```text
F:\Codex\story\.data\projects\1ffdb07d-d717-42cf-8456-30e1475b2859-story\backups\20260713-121449-7b76116e-ed8b-4de5-b7d2-3a9932f3ae0e.zip
```

今晚新增 Canon、规划与第一章候选均在当前项目 SQLite 中；Git 只保存代码、测试和交接记录。
