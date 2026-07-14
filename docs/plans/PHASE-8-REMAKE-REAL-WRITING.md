# 第八阶段重制：从零建立小说并完成真实试写

状态：进行中  
分支：`agent/trial-ready-workbench`  
原则：保留墨曜指挥舱 UI；先建立正式 Canon 和分层规划，再从第 1 章开始写作。

## 1. 废止的错误验收路线

旧“夜巡人”是从第 36 章开始的演示数据。第 37 章只保留为技术验收记录，第 38—40 章没有正式提交。任何真实写作不得把演示项目当作小说进度，也不得从演示数据续写。

正式验收作品为 `夜巡人·正式试写`，`projectKind=standard`，`currentChapter=0`。

## 2. 目标流程

```text
StoryBrief
→ AI 分段生成世界/人物/体系
→ 系统注入等级/法器/揭示/章节硬边界
→ Canon Analyzer 生成结构化补充
→ 确定性完整性与冲突检查
→ 待确认提案
→ 原子应用与 Canon 锁定
→ 七卷/故事弧/ChapterBeat/剧情预算
→ 第 1 章候选与质量门
→ 正式提交
→ 第 2—5 章连续验证
```

## 3. Canon 双层权威

AI 可以创造：具体人物细节、地点质感、组织内部关系、规则表现形式、代价的叙事表达。

系统必须固定：

- 六阶：见雾、识祟、执灯、立契、巡界、守夜。
- 第一卷：1—10 见雾；11—40 识祟；41—89 稳定训练；90—100 三条件后执灯；不得立契。
- 四类法器：遗物、巡器、封物、祟核。
- 巡夜灯：3—5 章临时使用；第 3 章仅被动显示路径。
- 镇纸钉：8—15 章获得。
- 潮湿账页：20—30 章获得。
- 无脸纸童身份第一层：43—60 章；370 章前不得完整揭示。
- 童年真相第一层：92—100 章；580 章前不得完整复述。
- 七卷固定范围与前五章固定 ChapterBeat。

模型输出中的章节数字不能成为第二事实源；合并时剥离，再由系统权威台账注入。

## 4. 长任务检查点

Canon 生成分为：

1. `core`
2. `systems`
3. `proposal-analysis`
4. deterministic readiness

`core` 或 `systems` 成功后立即写入 `CanonGenerationProposal.structured_json.generationSections`。模型调用期间没有 SQLite 长事务。失败状态保留检查点；服务启动将遗留 `generating` 收敛为 `failed`；相同 StoryBrief 且 Canon revision 未变化时重试只运行缺失步骤。

不同 StoryBrief、不同作品或 Canon revision 变化不得复用检查点。提案完成前不得 apply 或 lock。

## 5. 分层规划与预算

- 全书：1000 章终局与七卷边界。
- 卷：每卷范围、阶段冲突、必须回收内容。
- 故事弧：5—20 章，目标与节奏预算。
- 章节：只精确生成下一批 5 个 ChapterBeat。
- StoryBudget 保存 earliest、targetMin、targetMax、latest、前置条件和状态。

每章只能消耗当前 ChapterBeat 和当前预算，不能直接完成后续故事弧。

## 6. 真实验收

1. 完成、审计、应用并锁定 Canon。
2. 应用七卷规划、第一卷预算和第 1—5 章节拍。
3. 确认第 1 章就绪；只启动 1 章。
4. 检查写作候选、四组抽取、expectedCurrentValue、确定性质量门、多角色评审、最多两轮修订和原子提交。
5. 通过后逐章执行第 2—5 章。
6. 重启服务，验证当前章节、候选/正式状态、运行记录和费用可恢复且不重复付费调用。

真实正文与本地 SQLite 只留在 `.data`，不进入 Git。

## 7. 完成定义

- checkpoint、demo isolation、proposal revision、跨作品隔离有自动测试。
- `npm run test`、`npm run build`、`npm run test:e2e` 全部通过。
- 两个目标分辨率视觉无退化。
- 真实 Canon、规划和第 1—5 章均有可追溯 ModelRun/费用记录。
- 用户确认前不合并 `main`。
