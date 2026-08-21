#!/usr/bin/env python3
"""external-visual — Phase 6 External Visual 引擎包（Phase-6 Prompt §6-127；P6-2 部分）.

Generative Video / Real Footage 的引擎核心：Provider-neutral Production Packet（GV-###）、
Character / Environment 连续性档案、Visual Family、Scene Pack 与 Reference Frame Bank。

本包只产出 Packet / 档案 / 冲突记录，不产生资产文件、不调用任何生成服务（§25 模型无关、
§110 Reuse Map 生效：不重建 Asset 体系）。

模块清单（Phase 6 各工单并行添加，本文件只导出本工单的两个模块）：
- packet_builder.py（P6-2）：EV → GV Production Packet（§8-25 / §33-34 / §40-41 / §49）
- continuity.py（P6-2）：CP-CHAR / CP-ENV / VF / SP / RFB 档案（§85-89 / §122-127）
- gates.py（P6-06）：Approval Gates（§31-32/§64/§111/§115-116）
- workflow.py（P6-06）：MANUAL/ASSISTED/AUTOMATED 三档 + RO-###/PC-###（§29-30/§41/§78-79）
- provenance.py（P6-07）：VISUAL_PROVENANCE_MANIFEST（§96-99）
- handoff.py（P6-07）：TIMELINE_HANDOFF_MANIFEST（§133-134）
- footage.py / ingestion.py / review.py：见 P6-03..05 工单（footage/ingestion/review
  各自直接 import，不强制在 __all__ 声明）

技术约束：Python 3 stdlib only；无 LLM、无联网、确定性。
"""

__all__ = ["packet_builder", "continuity", "gates", "workflow",
           "provenance", "handoff"]
