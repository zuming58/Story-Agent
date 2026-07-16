# 第十三阶段后端交接：通用故事孵化器与多作品书库

## 1. 任务边界

本轮由另一台电脑只实现第十三阶段后端。不得修改 `apps/web/**`、CSS、设计令牌、页面组件、Playwright 用例或视觉快照。

准确开发基线：

```text
agent/short-story-production-foundation@7120d2f
```

工作分支：

```text
agent/general-story-incubator-foundation
```

开始前完整阅读：

1. `HANDOFF.md`
2. `docs/plans/PHASE-13-GENERAL-STORY-INCUBATOR.md`
3. `docs/plans/PHASE-12-AUDIT.md`
4. `docs/prd/PRD-001.md`
5. `docs/ui/UI-DESIGN-BASELINE.md`

## 2. 工作包 A：创意会话与 StoryBrief 权威链

新增项目库迁移与模型：

- `IdeationSession`：projectId、status、revision、createdAt、updatedAt。
- `IdeationMessage`：sessionId、role、content、modelRunId、scope、createdAt。
- `StoryBriefVersion`：projectId、version、status、briefJson、sourceSessionId、checksum、revision。
- `StoryBriefProposal`：sessionId、baseVersionId、beforeJson、afterJson、reason、impactJson、status、revision。

状态要求：

- 对话消息只是创意素材，不是正式设定。
- 只有 accepted `StoryBriefProposal` 能原子生成新的 current `StoryBriefVersion`。
- 拒绝提案不得改变 current Brief。
- 所有写操作携带 expected revision；过期写入返回 HTTP 409。
- 同一项目只能有一个 current Brief；历史版本永久保留。
- 模型调用在事务外完成，保存前重新校验 project/session/base Brief revision。

实现 API：

- `POST /api/v1/projects/{project_id}/ideation/sessions`
- `GET /api/v1/projects/{project_id}/ideation/sessions`
- `GET /api/v1/projects/{project_id}/ideation/sessions/{session_id}`
- `POST /api/v1/ideation/sessions/{session_id}/messages`
- `POST /api/v1/ideation/sessions/{session_id}/story-brief-proposals`
- `GET /api/v1/projects/{project_id}/story-brief/versions`
- `GET /api/v1/projects/{project_id}/story-brief/current`
- `POST /api/v1/story-brief-proposals/{proposal_id}/apply`
- `POST /api/v1/story-brief-proposals/{proposal_id}/reject`

模型输出使用 JSON，非法或空 JSON 只允许一次修复。API、日志、审计和备份不得包含完整密钥。

## 3. 工作包 B：通用 StoryBrief 契约

Brief 至少支持：

- format：`long-form | short-form`
- title、genre、audience、targetChapters、targetWords、chapterWordRange。
- premise、theme、tone、pov、pace、endingDirection。
- protagonist、coreDesire、coreConflict、worldPreferences。
- progressionPreference、romanceIntensity、forbiddenContent。
- referenceTraits：只能保存抽象特征，不保存模仿原文的指令。
- confirmedDecisions、openQuestions、conflicts、aiSuggestions。

必须提供确定性规范化和验证：

- 长篇/短篇范围与章节、总字数一致。
- 空白必填项、互相冲突的结局/基调、非法章节范围形成 findings。
- 没有能力体系、法宝、怪异规则的作品允许标记为 `notApplicable`，不能强制补成玄幻或怪谈。
- `StoryBriefReadiness` 区分 blocker、warning、ready。

## 4. 工作包 C：移除夜巡人生产硬编码

审计 Phase 8 的 `VOLUMES`、`FIRST_BEATS`、`AUTHORITATIVE_CANON_BOUNDARIES`、固定标题/人物/城市/等级等常量。

目标结构：

- 夜巡人数据迁移为显式模板，例如 `templateId=night-watch-demo`。
- 只有请求明确选择该模板时才能使用夜巡人固定决策。
- 空白项目默认从 current StoryBrief 生成，不能出现夜巡人残留。
- 生成提案仍遵循“pending → apply/reject”，不得直接锁定 Canon。
- Canon 提案冻结 StoryBrief version/checksum；Brief 漂移阻止 apply。

通用 Canon 至少支持条件化模块：

- 故事内核、世界边界、时代地域。
- 人物、知识边界、关系、组织。
- 物品、资源、职业/能力体系及限制代价。
- 世界硬规则、冲突规则、异常处理。
- 主线、支线、伏笔、揭示窗口、禁止提前完成项。
- 文风、视角、节奏、单章结构和禁写约束。

确定性校验只能检查 Brief 声明存在的体系。非玄幻故事不能因为没有等级或法宝而被阻断。

## 5. 工作包 D：动态规划生成

从 current StoryBrief + accepted Canon 生成：

- 长篇：全书层、动态卷层、5—20 章故事弧和下一批 5 章精确 ChapterBeat。
- 短篇：可不设置卷，按目标总字数/章节数生成紧凑弧线和下一批 5 章或全部剩余节拍。
- 里程碑保存最早/目标/最晚章节、前置/完成条件和关联伏笔。
- 人物出场、物品获得、能力变化和真相揭示均保存最早允许窗口。
- 生成结果必须覆盖 1..targetChapters，不重号、不缺号、不越界。
- 当前精确 Beat 仍驱动章节契约；未来 Beat 进入禁止提前消费边界。

不得再固定 1000 章、七卷或第一卷 1—100。动态算法必须有确定性边界，模型只填充创意内容。

## 6. 工作包 E：作品库后端

补充：

- `POST /api/v1/projects/{project_id}/archive`
- `POST /api/v1/projects/{project_id}/unarchive`
- `POST /api/v1/projects/{project_id}/duplicate`

要求：

- 复制产生新的项目 ID、目录和独立 SQLite。
- 可选择只复制 Brief/Canon/Plan，默认不复制正式正文、模型运行和费用记录。
- 恢复/复制必须 remap 项目 ID 和项目内 UUID 引用。
- demo 项目复制后才能成为 standard；不得直接付费自动托管 demo。
- 归档不删除目录；列表 API 支持是否包含 archived。

## 7. 测试要求

必须新增并通过：

- 三轮 ideation 消息重启恢复。
- Brief 提案接受、拒绝、历史版本、revision 冲突和模型期间漂移。
- 模型调用期间不持有写事务。
- 非怪谈长篇生成结果中不存在夜巡人、沈砚、雾城、六阶和七卷残留。
- 无等级/法宝体系短篇可以通过 Canon readiness。
- 长篇 120 章与短篇 6 章动态范围、卷/弧/Beat 校验。
- 两部作品的会话、Brief、Canon、Plan 完全隔离。
- duplicate/archive/restore 的 ID remap 和跨作品隔离。
- 候选提案不能污染正式 Brief、Canon 和 Plan。
- 备份恢复后 current Brief、会话和提案状态正确。

最终运行：

```powershell
npm run test
npm run build
npm run test:e2e
apps\api\.venv\Scripts\python.exe -m compileall -q apps/api/src apps/api/tests
git diff --check
```

测试必须使用确定性本地 Provider，不调用真实 DeepSeek，不消耗用户余额。

## 8. 完成交付

完成后：

1. 更新 `HANDOFF.md`，记录迁移、表、API、状态机、测试和已知限制。
2. 提交并推送 `agent/general-story-incubator-foundation`。
3. 不合并 base、main 或任何 PR。
4. 不开始 UI，不开始用户真实测试，不进入下一阶段。
5. 停止并让用户回到当前电脑，交给 GPT-5.6 做完整审计、修复和 UI。
