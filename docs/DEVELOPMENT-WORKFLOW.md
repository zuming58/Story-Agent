# Story Agent 双电脑开发工作流

## 权威来源

- GitHub 仓库：`https://github.com/zuming58/Story-Agent.git`
- 稳定分支：`main`
- 当前开发分支：`agent/local-data-foundation`
- 当前阶段的范围、状态和恢复点以仓库根目录 `HANDOFF.md` 为准。
- 产品边界以 `docs/prd/PRD-001.md` 为准，视觉边界以 `docs/ui/UI-DESIGN-BASELINE.md` 为准。

## 第一台电脑结束工作

```powershell
git status -sb
npm run build
npm run test
npm run test:e2e
git add <本轮文件>
git commit -m "本轮摘要"
git push
```

提交前更新 `HANDOFF.md`：写明已完成项、未完成项、测试结果、最新提交和下一位 Agent 的第一项任务。不要提交 `.data/`、`.e2e-data/`、密钥、日志、ZIP 备份或两个本地参考项目。

## 第二台电脑首次接力

```powershell
git clone https://github.com/zuming58/Story-Agent.git
cd Story-Agent
git checkout agent/local-data-foundation
git pull
npm install
npm --prefix apps/web install
uv sync --project apps/api --dev
npm run dev
```

让接力 Agent 依次完整阅读：

1. `HANDOFF.md`
2. `docs/prd/PRD-001.md`
3. `docs/ui/UI-DESIGN-BASELINE.md`
4. `design-qa.md`

接力 Agent 在同一功能分支提交并推送，草稿 PR 会自动更新。禁止直接合并 `main`，禁止改动 `Story agent/` 和 `openclaw skill/` 参考目录。

## 回到第一台电脑审核

```powershell
git checkout agent/local-data-foundation
git pull
npm install
npm --prefix apps/web install
uv sync --project apps/api --dev
npm run build
npm run test
npm run test:e2e
```

审查重点：数据库事务边界、revision 冲突处理、数据权威关系、迁移与备份安全、两档桌面布局以及是否偏离 PRD。审核修复后再将草稿 PR 标记为可评审并合入 `main`。

## 冲突处理原则

- 开始工作前先 `git pull`，结束工作立即推送。
- 同一时间只让一台电脑修改同一功能分支。
- `.data/` 是机器本地数据，不通过 Git 同步；需要迁移作品时使用应用生成的备份 ZIP。
- 发生代码冲突时保留双方提交，人工逐文件合并；不要使用 `git reset --hard` 覆盖另一台电脑的工作。
