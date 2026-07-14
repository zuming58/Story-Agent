# 第九阶段代码审计记录

审计日期：2026-07-14

审计基线：`dc1eeb8`

实施提交：`0e15607`

审计范围：`agent/export-publishing-foundation`

## 结论

第九阶段的数据库表、API、冻结快照、事务外渲染、恢复、下载和人工发布记录主路径成立，但初始实现不能直接视为发布级完成。审计发现并修复了正式稿来源链不完整、恢复后 manifest 身份残留、DOCX/EPUB 结构不足、空格式回退、越界范围和文件篡改未被检测等问题。

修复并完成全量验证后，第九阶段后端可以作为下一阶段基线。UI 未修改。

## 已修复问题

1. 正式导出现在同时校验 commit、approved draft、official source、state snapshot 的作品归属、互相引用、状态、revision 和 checksum。
2. 增加正文实际内容与 draft checksum 的二次核验，防止只改正文、不更新 revision/checksum 的局部篡改进入正式导出。
3. 非 official current commit 或断裂 source/snapshot 链在审阅模式下也不再读取候选正文，只能作为缺口展示。
4. 检索就绪改为检查索引是否实际重建且具有 checksum，不再把可选向量后端是否可用等同于索引新鲜度。
5. 自动化隔离只检查当前未解决状态；已被后续正式 commit 解决的历史隔离不再永久阻止导出。
6. 显式空格式数组返回 `EXPORT_FORMAT_REQUIRED`，不再静默回退默认格式。
7. 导出范围不得超过作品总章数，新增 `EXPORT_RANGE_OUT_OF_BOUNDS`。
8. DOCX 增加标题层级、章节分页、可更新目录字段、样式表、中文字体回退和审阅问题附录。
9. EPUB 增加作者、EPUB 3 修改时间元数据；审阅版增加独立审阅说明和问题附录 XHTML，并写入 nav、manifest 和 spine。
10. 下载和登记发布记录前重新计算文件大小与 SHA-256；篡改文件返回 `EXPORT_ARTIFACT_INTEGRITY_FAILED`。
11. 恢复项目时校验 `project.json` 与 story.db 原项目 ID 一致，remap 导出 JSON 中嵌入的 projectId，并重新计算 manifest checksum。
12. 恢复项目继续将实体导出文件标记为 missing，不把来源项目的 artifact 当成可下载文件。

## 补充测试

- 第九阶段专项由 6 项增加到 8 项。
- 增加空格式、越界范围、断裂 source/snapshot 链测试。
- 增加 DOCX 标题、分页、目录和中文字体结构断言。
- 增加 EPUB 审阅说明及问题附录断言。
- 增加 artifact 篡改后禁止下载和发布登记测试。
- 增加恢复后 job/artifact manifest projectId 与 checksum 重建测试。

## 最终验证

```text
npm run test
  API: 130 passed, 287 warnings
  Web: 3 files / 11 tests passed

npm run build
  passed（仅现有 Vite chunk-size warning）

npm run test:e2e
  14 passed（1440×1024 与 1280×800）

uv run pytest tests/test_phase9_export.py -q
  8 passed

git diff --check
  passed（仅 Windows LF/CRLF 提示）
```

## 非阻断项

- FastAPI TestClient 和 SQLite datetime adapter 仍有上游弃用 warning。
- 前端存在既有 Vite chunk-size warning；第九阶段未修改 UI。
- 第九阶段仅提供人工下载与发布记录，不登录番茄等第三方平台。
- 第九阶段尚无正式导出 UI，后续仍由当前电脑按既有视觉基线实现。
