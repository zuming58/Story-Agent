# 第八阶段：可试写版与自动托管控制台

状态：开发完成，等待用户检查 UI 和单章流程后合并
基线：`7a808b4`
开发分支：`agent/trial-ready-workbench`
所有权：当前电脑同时负责架构、UI、实施、审计与修复

## 1. 目标用户流程

```text
配置模型 -> 完成并锁定 Canon -> 检查故事规划
-> 单章试写 -> 质量复核 -> 正式提交
-> 连续试写 3—5 章 -> 查看费用、错误与恢复状态
```

本阶段先让用户真正开始写作测试，不等导出、短剧或 EXE 才验证核心质量。

## 2. 后端与数据库

- Catalog 迁移 `0005_provider_connection_status`：保存 Provider 最后连接测试状态与时间；Provider 配置变更后自动作废旧测试结果。
- DeepSeek 官方预设使用当前 `deepseek-v4-pro`，并以 2026-07-13 官方 cache-miss USD 价格 0.435/0.87 填充输入/输出估算；正式长跑前需再核对 [DeepSeek 官方价格页](https://api-docs.deepseek.com/quick_start/pricing)。
- Project 迁移 `0010_trial_ready_workbench`：为 automation run 冻结本次手动试写的 `requested_chapter_count`。
- `GET /api/v1/projects/{project_id}/trial-readiness?chapterCount=1|3|5`：只读核对角色模型、密钥、连接测试、价格、Canon、规划窗口、正式章节、章节任务和活动托管。
- `POST /api/v1/projects/{project_id}/automation/runs` 新增可选 `chapterCount: 1 | 3 | 5`，未传时继续使用 policy 中的章节数。
- 幂等 key 返回原 run；每个 run 冻结请求章节数，不被后续策略修改污染。
- 仍复用 Phase 5/7 的契约、事实抽取、质量门、修订上限、SQLite 租约与原子提交；模型调用期间不持有长写事务。

## 3. Canon 设定库

- 故事核心 Markdown 草稿、未保存提示和 SQLite 刷新恢复。
- Architect 模型分析人物、地点、组织、物品、能力、事件、伏笔、关系与规则。
- 实体、别名、属性 JSON、关系、硬规则和约束的分栏编辑。
- 诊断无关系实体、空属性与空规则约束；JSON 输入错误保持在页面内可修复。
- Canon 锁定使用二次确认；锁定后文档、实体、关系和规则只能创建差异变更申请，接受时继续执行 revision 检查和索引重建。

## 4. 自动托管与引导 UI

- `/automation`：日常策略、1/3/5 章手动试写、运行队列、章节步骤、Token、预计费用、错误诊断、取消、恢复和补跑。
- 按钮只根据后端 `availableActions` 显示；手动试写不会自动打开日常定时。
- 就绪检查在作品首页、Canon 页和托管页复用，阻断项可直达修复页。
- 作品首页显示六步试写引导；右侧 AI 控制台自动携带 Canon 或托管运行作用域。
- 业务状态从 SQLite/HTTP 恢复，不写入 `localStorage`。

## 5. 安全边界

- 候选稿不能直接更新正式 Canon、故事状态或 `ChapterCommit`。
- 定时托管默认关闭，必须由用户主动开启。
- 本阶段不进行番茄等外部发布，不实施导出、短篇策略、短剧改编或 EXE 打包。
- API Key 仍只保存在 Windows Credential Manager，不返回、记录、备份或提交 Git。

## 6. 验收节奏

1. 用户先在本分支检查 Canon、就绪清单和自动托管 UI。
2. 配置真实 Provider 并成功连接测试后，使用独立测试作品写第一章。
3. 单章修复后扩展到 3—5 章；再扩展到 20—30 章中程测试。
4. 20—30 章稳定后才进行 100 章以上长篇压力测试。
5. 问题按“系统 Bug / 模型提示 / 故事质量 / 设定缺失”分类。

真实模型单章冒烟必须由用户在本地 Credential Manager 配好密钥后运行；自动测试不调用或消耗真实 DeepSeek API。
