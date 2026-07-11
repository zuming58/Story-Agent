# Story Agent

本地优先的小说创作与短剧改编平台。当前版本是第一轮高保真交互原型，重点验证故事规划、固定 AI 控制台、人工编辑与 AI 修改确认闭环。

## 当前实现

- React + TypeScript + Vite 桌面 Web 原型；
- 故事规划时间轴、里程碑契约和前端边界校验；
- 全局故事 Agent、模拟对话、字段级差异和影响预览；
- 接受、拒绝、逐项选择、撤销和浏览器本地持久化；
- 1440×1024 与 1280×800 桌面适配；
- Vitest 单元测试与 Playwright 核心流程。

## 本地运行

项目运行时固定为 Node.js 24。

```powershell
npm --prefix apps/web install
npm run dev
```

常用验证命令：

```powershell
npm run build
npm run test
npm run test:e2e
```

## 目录

- `apps/web`：当前前端原型；
- `apps/api`：下一轮 FastAPI 后端预留；
- `docs/prd`：产品需求文档；
- `docs/ui`：选定 UI 基线和视觉稿。
