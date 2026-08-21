# PROJECT_STATE — 新项目初始快照（INIT）

> 用途：本项目运行时的「Current Truth」（v0.2 §52），每次会话开始首先读取本文件。
> 本文件为新建项目的初始状态。字段格式与说明见 `templates/project-state.md`；阶段枚举见 `docs/state-machine.md`。

<!-- 字段块：随项目推进更新各字段值。list 为空写 []；Last Updated 使用 ISO8601。 -->

# Project:
   待用户输入（Project Brief 确定后填写项目名）。
# Production Mode: PRODUCT_TECH_SHORT
   默认值；Grill Me 后可改为 EDITORIAL_EXPLAINER / CUSTOM。
# Delivery Mode: BOTH
   推荐默认：Final Video + 可编辑剪映工程。
# Current Stage: PROJECT_INTAKE
   当前处于需求收集阶段（Grill Me）。
# Current Scene:
   暂无 Scene。
# Current Shot:
   暂无 Shot。
# Approved Stages: []
   尚无已批准阶段。
# Pending Decisions: []
   暂无待定决定。
# Blocked Items: []
   暂无阻塞项。
# Current Style:
   待 STYLE_DIRECTION 批准后填写。
# Current Audio Direction:
   待 SOUND_DIRECTION 批准后填写。
# Important Constraints: []
   需求收集过程中陆续补充。
# Next Action: Run Grill Me (workflows/project-intake.md)
   第一步：执行项目需求收集。
# Phase 6 External Visual 状态:
   空（Phase 6 未启动）。
   项目进入 Phase 6 后记录：external-visual/ 中间产物进度、已批准门禁（AP 记录）、
   三份 manifest 落盘情况（VISUAL_PROVENANCE_MANIFEST / TIMELINE_HANDOFF_MANIFEST /
   ASSET_PACKAGE_MANIFEST）。详见 docs/external-visual.md。
# Last Updated: YYYY-MM-DDTHH:MM:SS±HH:MM
   初始化时填写当前时间（ISO8601）。
