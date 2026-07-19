# Story Agent 双电脑开发工作流

## 权威来源

- GitHub 仓库：`https://github.com/zuming58/Story-Agent.git`
- 稳定分支：`main`
- 当前开发分支以根目录 `HANDOFF.md` 为准，不在长期工作流中写死。
- 当前阶段的范围、状态和恢复点以仓库根目录 `HANDOFF.md` 为准。
- 最终交付快照以 `FINAL-HANDOFF.md` 为准，产品边界以 `docs/prd/PRD-001.md` 为准，视觉边界以 `docs/ui/UI-DESIGN-SYSTEM.md` 为准。

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

## 本机一键启动

- 正常开发环境初始化完成后，双击仓库根目录 `START-STORY-AGENT.cmd`。
- 脚本分别启动 API 与 Web，等待就绪后自动打开 `http://127.0.0.1:5173/overview`。
- 已有 `apps/api/.venv` 时运行不依赖 `uv`；只有首次初始化 API 环境才需要 `uv`。
- 当前机器把 uv 下载缓存放在 `F:\Cache\uv\cache`，脚本会自动设置 `UV_CACHE_DIR`，但缓存目录本身不包含 `uv.exe`。
- 关闭两个最小化的 `Story Agent API`、`Story Agent Web` 命令窗口即可停止本地服务。

## 第二台电脑首次接力

```powershell
git clone https://github.com/zuming58/Story-Agent.git
cd Story-Agent
git checkout agent/model-backed-story-incubator
git pull --ff-only
npm install
npm --prefix apps/web install
uv sync --project apps/api --dev
npm run dev
```

让接力 Agent 依次完整阅读：

1. `HANDOFF.md`
2. `FINAL-HANDOFF.md`
3. `docs/Story-Agent-使用手册.html`
4. `docs/ui/UI-DESIGN-SYSTEM.md`
5. `docs/prd/PRD-001.md`
6. `design-qa.md`

接力 Agent 在同一功能分支提交并推送，草稿 PR 会自动更新。禁止直接合并 `main`，禁止改动 `Story agent/` 和 `openclaw skill/` 参考目录。

## 回到第一台电脑审核

```powershell
git checkout agent/model-backed-story-incubator
git pull --ff-only
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
