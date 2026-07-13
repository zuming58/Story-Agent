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
