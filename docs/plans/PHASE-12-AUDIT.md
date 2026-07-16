# 第十二阶段 GPT-5.6 审计记录

日期：2026-07-16

分支：`agent/short-story-production-foundation`

审计基线：`356689b`

另一台电脑交付：`ce1583c`

## 结论

第十二阶段“短篇策略物化为独立短篇项目”的后端架构成立，但交付版本的确定性测试没有暴露真实模型输入不足、总字数预算不闭合以及同一窗口未来节拍可被提前消费的问题。本次已直接修复并补充回归。

短篇生产后端可以进入真实 Provider 冒烟准备；普通用户仍缺少短篇策略/物化 UI，不能把整个短篇产品体验标记为完成。

## 主要审计发现与修复

### 1. 真实创作上下文

- 原策略模型只收到 source manifest/checksum，缺少可实际改编的 Canon 和正式章节正文。
- 现在提供有界的 Canon Markdown、结构化类型/实体/关系/规则、规划摘要、正式章节摘要/抽取状态/正文摘录。
- 完整冻结 manifest 继续写入提案审计；模型请求只携带紧凑 checksum 台账，避免完整 1000 章规划重复占用上下文。
- 结构化 Canon 的任何变更都会改变 manifest checksum 并触发 source drift。

### 2. 字数与章节预算

- 策略总字数少于每章最低 500 字时直接形成 blocking finding。
- 物化前拒绝不可能满足的总字数/章节数组合，不创建多余目标项目。
- 目标 ChapterBeat 与章节契约使用同一字数权威；readiness 验证每章区间总和能覆盖锁定总字数。

### 3. 防止剧情提前消费

- 契约继续绑定当前章节的精确 ChapterBeat。
- 同一 PlanNode 中未来 ChapterBeat 的标题、目标、完成条件和重大事件进入 `mustNotAdvance` 与 `futureKeywords`。
- 第 1 章不能因为第 2—5 章共用章节窗口而提前完成后续转折。

### 4. staged/retry 与隔离

- 保留来源、staged 目标和 completed 目标之间的补偿语义。
- 幂等键与冻结请求匹配后才可复用目标。
- 来源恢复后外部目标链接保持 detached 历史，不认领原目标。
- 目标短篇继续使用独立目录和 SQLite，不写入来源长篇正式状态。

### 5. 本地开发入口

- 新建正式作品进入 Canon 构思入口。
- 新增 `START-STORY-AGENT.cmd` 并完成真实启动验证。
- 运行已有环境直接使用 `apps/api/.venv`；Playwright 同样不再依赖 PATH 中的 uv。
- 脚本同时等待 API health 与 Web 页面就绪后才打开主页。

## 验证

```text
API full: 159 passed
Web unit: 3 files / 11 tests passed
Build: passed（仅既有 Vite chunk-size warning）
Playwright: 14 passed（1440×1024 与 1280×800）
python compileall: passed
START-STORY-AGENT.cmd: API 200、Web 200，重复启动路径通过
git diff --check: passed（仅 Windows LF/CRLF 提示）
```

## 剩余产品缺口

- Phase 8 故事架构器仍硬编码夜巡人、1000 章和七卷。
- 多轮创意访谈尚不能固化为通用 StoryBrief。
- 作品库缺少完整归档、复制和历史筛选。
- 短篇策略与物化只有后端/API，缺少普通用户 UI。

下一阶段按 `PHASE-13-GENERAL-STORY-INCUBATOR.md` 实施。
