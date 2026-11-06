## 变更说明

<!-- 做了什么、为什么；关联 Story/Issue（如 Story 8.14 / #12） -->

## 自查清单

- [ ] 三道门禁本地全绿：`pytest -q` / `ruff check packages tests examples` / `lint-imports`
- [ ] 新行为有测试锚定（新测试文件或既有文件的显式断言）
- [ ] 架构红线自查：AD-1 依赖单向 / 六段链不旁路（AD-4）/ 新依赖面 fail-closed（AD-12）
- [ ] 新增事件类型/系统流：目录与流清单快照已回写（守卫零漂移）
- [ ] 簿记同步：`docs/stories/` 记录 + `docs/sprint-status.yaml` 回写（Story 级变更时）
- [ ] 文档失实处已顺手修正（指南/README 与代码同步）
