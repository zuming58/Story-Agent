# 第八阶段 GPT-5.6 自审计记录

审计基线：`7a808b4`
审计分支：`agent/trial-ready-workbench`
结论：代码级实施已完成，等待用户 UI 与真模型单章冒烟验收。

## 审计范围

- Catalog/Project Alembic 迁移、模型连接状态和秘钥边界。
- 1/3/5 章 run 冻结、幂等、费用阻断、租约与跨作品隔离。
- Canon 草稿、AI 分析、锁定、变更申请和 revision 冲突。
- React Query 业务状态、刷新恢复、AI 作用域和两套桌面分辨率。
- API、Web、构建与 Playwright 回归。

## 发现并已修复

1. Canon 保存成功通知原来只在规划页渲染；改为 AppShell 全局通知，页面切换不丢失反馈。
2. Canon 实体或规则 JSON 输入错误会产生未处理 Promise；改为页面内错误并保留用户草稿。
3. 实体关系原来只能新增；补充草稿编辑与锁定后差异变更申请。
4. AI 分析后没有明显结构缺口反馈；补充无关系实体、空属性和空规则约束诊断。
5. Canon 锁定对话框层级低于遮罩，真实浏览器中按钮可见但无法点击；修正 z-index 并在两个分辨率验证。
6. Provider 成功连接记录原来无法用于就绪检查；增加持久化状态，且 Provider 编辑后必须重新测试。
7. 手动试写的 1/3/5 章选择原来会受后续 policy 变更影响；在 run 上冻结 `requestedChapterCount`。
8. 每日费用保护在密钥缺失时会掩盖价格缺失；改为同时返回两个可操作阻断项。
9. Canon/自动托管 AI 对话原来会附带当前规划节点，可能污染上下文；改为只传当前页面作用域与选区。
10. 内置 DeepSeek 模型标识已按官方文档核对为 `deepseek-v4-pro`，预设价格使用 2026-07-13 官方 USD cache-miss 输入/输出价。

## 剩余风险与验收边界

- 构建仍有既有 Vite chunk-size warning，不阻断本地试写，可在后续性能阶段做路由级拆包。
- 自动测试使用确定性 Provider，不会消费真实 API；真实模型单章冒烟需要用户在 UI 配置 Credential Manager 密钥后执行。
- 本阶段不含导出、外部发布、短篇策略、短剧改编和 Windows EXE。

## 2026-07-13 真实 Canon、规划与第一章验收增量

### 已验证

- 正式项目从 `currentChapter=0` 开始，未继承示例项目第 36 章状态。
- 真实 Canon 已生成、结构化、应用并锁定：19 实体、10 关系、16 规则。
- 1000 章七卷规划已应用，第 1—5 章精确节拍完整；1/3/5 章就绪检查通过。
- 第一章章节契约只消耗第 1 章节拍，明确禁止进入旧宅、获得巡夜灯、解释夜巡司或确认童年真相。
- 第一章原始稿、两轮修订稿均以独立候选版本保留，没有覆盖历史版本。
- 服务重启后 run/job 和候选稿均从 SQLite 恢复；旧 worker 租约过期后收敛为 `interrupted`，可继续 resume。

### 真实验收暴露并修复

1. Canon readiness 对“硬规则”做逐字匹配，产生语义误判；已改为结构化规则加语义检查，并在 apply 边界重算 readiness。
2. reviewer 提示携带完整未来计划且输出上限为 2048，真实 DeepSeek 返回 `content_truncated`；已压缩提示、提高到 3072，并增加唯一一次精简重试。
3. narrative extractor 未收到章节契约 `requiredForeshadows`，导致实际存在的异常来信无法映射到 `FOG-OLD-HOUSE-LETTER`；已透传精确 code、钩子和完成条件。
4. 自动测试 fake Provider 原先用 `contentMarkdown` 区分 reviewer，实际 reviewer 同样含正文，旧测试没有真正走 reviewer 响应；测试桩已按 `requiredOutput.findings` 分类并新增截断回归。

### 停止点

- 第一章 v3 为当前安全候选，2518 字，revision round=2。
- run/job 因主动重启处于 `interrupted`，没有正式 commit，项目仍为第 0 章。
- 按用户要求今晚停止；明天必须 resume 原 run，用新抽取逻辑完成质量门，不得重新生成正文或开启第三轮修订。
- 最新 API 全量为 115 passed / 1 failed；唯一失败是随后已修正的测试桩分类，两个相关专项测试已通过。修正后的全量 API、Web、build、e2e 尚待补跑。
