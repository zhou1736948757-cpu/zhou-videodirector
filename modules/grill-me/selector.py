#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Grill Me Selector — 决定 Grill Me 的下一步：问哪个问题，还是停止。

对应 workflow : workflows/project-intake.md（PROJECT_INTAKE 阶段）
问题 Taxonomy : modules/grill-me/questions.json
数据契约      : schemas/project.schema.json（field_target 对齐 project.* 字段）

仅使用 Python 3 标准库。

用法：
    from selector import select_next_question
    result = select_next_question(intake_state)
    # result = {"action": "ask", "next": {question_dict}, "reason": "..."}
    #       或 {"action": "stop", "next": null, "reason": "..."}

自检：
    python3 modules/grill-me/selector.py
"""

import json
import os
import sys

QUESTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "questions.json")

# 视为「用户已有完整需求材料」的快捷标记：命中任一即停止提问。
# user_already_has_brief 为共享契约约定；user_has_script / user_has_storyboard
# 对应 workflows/project-intake.md 的「用户已有脚本 / Storyboard 分支」。
BRIEF_READY_FLAGS = ("user_already_has_brief", "user_has_script", "user_has_storyboard")

# Stop Asking Rule：Tier 2 至少回答的 blocking 问题数（questions.json stop_rules.tier2_min_answered）
TIER2_MIN_ANSWERED = 5


def load_questions(path=None):
    """加载问题 Taxonomy，返回 questions 列表。"""
    path = path or QUESTIONS_PATH
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("questions.json 缺少非空 questions 列表")
    return questions


def _answers_of(intake_state):
    """返回答案字典；兼容 answers 嵌套与顶层平铺两种形式。"""
    answers = intake_state.get("answers")
    return answers if isinstance(answers, dict) else {}


def is_answered(intake_state, question):
    """判断某个问题是否已被回答。

    匹配 key 优先级：
      1) intake_state.answers[question.id]
      2) intake_state[question.id]
      3) field_target 的末段（如 project.primary_goal → primary_goal，answers 或顶层）
    布尔值 False 与数值 0 均为有效回答（用 is not None 判断）。
    """
    qid = question["id"]
    answers = _answers_of(intake_state)
    if answers.get(qid) is not None:
        return True
    if intake_state.get(qid) is not None:
        return True
    field_target = question.get("field_target") or ""
    if field_target.startswith("project."):
        key = field_target.split(".", 1)[1]
        if answers.get(key) is not None or intake_state.get(key) is not None:
            return True
    return False


def select_next_question(intake_state):
    """决定下一步。

    参数 intake_state: dict，形如
        {"user_already_has_brief": bool, "user_has_script": bool,
         "user_has_storyboard": bool, "answers": {question_id: value}}

    返回:
        {"action": "ask",  "next": {question_dict}, "reason": str}
        {"action": "stop", "next": None,            "reason": str}

    行为:
      - 优先级 Tier 1 → Tier 2 → Tier 3；Tier 3（director_inferred）永不提问。
      - 跳过已回答的问题与 blocking=false 的问题。
      - Stop 触发条件（Stop Asking Rule，v0.2 §4）：
          1) Tier 1 全部回答 + Tier 2 已答 >= 5 + Tier 3 全部 assumed；或
          2) intake_state 命中 user_already_has_brief / user_has_script / user_has_storyboard = true。
    """
    intake_state = intake_state if isinstance(intake_state, dict) else {}
    questions = load_questions()

    tier1 = [q for q in questions if q.get("tier") == 1]
    tier2 = [q for q in questions if q.get("tier") == 2]
    tier3 = [q for q in questions if q.get("tier") == 3]

    # 停止条件 2：用户已提供完整需求材料
    for flag in BRIEF_READY_FLAGS:
        if intake_state.get(flag) is True:
            return {
                "action": "stop",
                "next": None,
                "reason": "用户已提供完整需求材料（%s=true），不再提问，直接生成 Project Brief。" % flag,
            }

    answered_ids = {q["id"] for q in questions if is_answered(intake_state, q)}

    # Tier 1：必须全部回答（blocking 项）
    tier1_pending = [
        q for q in tier1
        if q["id"] not in answered_ids and q.get("blocking", True)
    ]
    if tier1_pending:
        q = tier1_pending[0]
        return {
            "action": "ask",
            "next": q,
            "reason": "Tier 1 必答题未完成：%s — %s" % (q["id"], q.get("question", "")),
        }

    # Tier 2：至少回答 TIER2_MIN_ANSWERED 个 blocking 项
    tier2_answered = sum(1 for q in tier2 if q["id"] in answered_ids)
    if tier2_answered < TIER2_MIN_ANSWERED:
        tier2_pending = [
            q for q in tier2
            if q["id"] not in answered_ids and q.get("blocking", True)
        ]
        if tier2_pending:
            q = tier2_pending[0]
            return {
                "action": "ask",
                "next": q,
                "reason": "Tier 2 已答 %d/%d，继续：%s — %s"
                          % (tier2_answered, TIER2_MIN_ANSWERED, q["id"], q.get("question", "")),
            }

    # Tier 3：全部 assumed（可推断，永不提问）
    tier3_pending = [q for q in tier3 if q["id"] not in answered_ids]
    tier3_all_assumed = all(q.get("assumable", False) for q in tier3_pending)

    # 停止条件 1：Tier 1 全答 + Tier 2 >= 5 + Tier 3 全 assumed
    if tier2_answered >= TIER2_MIN_ANSWERED and tier3_all_assumed:
        return {
            "action": "stop",
            "next": None,
            "reason": "Tier 1 全部回答 + Tier 2 已答 %d（>= %d）+ Tier 3 全部 assumed，"
                      "达到可进行创意设计的程度（Stop Asking Rule）。"
                      % (tier2_answered, TIER2_MIN_ANSWERED),
        }

    # 兜底：仍有 blocking 且不可 assumed 的问题 → 继续问
    pending = [
        q for q in questions
        if q["id"] not in answered_ids
        and q.get("blocking", True)
        and not q.get("assumable", False)
    ]
    if pending:
        q = pending[0]
        return {
            "action": "ask",
            "next": q,
            "reason": "继续收集影响决策的信息：%s — %s" % (q["id"], q.get("question", "")),
        }

    return {
        "action": "stop",
        "next": None,
        "reason": "没有需要继续提问的 blocking 问题，停止 Grill Me。",
    }


def self_test():
    """内置自检：覆盖 >= 6 个典型场景（all_missing / tier1_done / tier2_partial /
    fully_answered / user_has_script / user_has_storyboard / tier3_only_left）。"""
    qs = load_questions()
    ids = [q["id"] for q in qs]
    tier1_ids = [q["id"] for q in qs if q.get("tier") == 1]
    tier2_ids = [q["id"] for q in qs if q.get("tier") == 2]

    def sample_value(qid):
        for q in qs:
            if q["id"] == qid:
                if q.get("kind") == "boolean":
                    return True
                if q.get("kind") == "number":
                    return 0
                return "sample_answer"
        return "sample_answer"

    def full_answers(qid_list):
        return {qid: sample_value(qid) for qid in qid_list}

    scenarios = [
        ("all_missing", {}, "ask", tier1_ids[0]),
        ("tier1_done", {"answers": full_answers(tier1_ids)}, "ask", tier2_ids[0]),
        ("tier2_partial",
         {"answers": full_answers(tier1_ids + tier2_ids[:3])},
         "ask", tier2_ids[3]),
        ("fully_answered",
         {"answers": full_answers(ids)},
         "stop", None),
        ("user_has_script", {"user_has_script": True}, "stop", None),
        ("user_has_storyboard", {"user_has_storyboard": True}, "stop", None),
        ("tier3_only_left",
         {"answers": full_answers(tier1_ids + tier2_ids)},
         "stop", None),
    ]

    failed = 0
    for name, state, exp_action, exp_next in scenarios:
        result = select_next_question(state)
        got_next = result.get("next")
        got_next_id = got_next.get("id") if isinstance(got_next, dict) else None
        ok = (result.get("action") == exp_action) and (got_next_id == exp_next)
        if not ok:
            failed += 1
        print("[%s] %-18s action=%-4s next=%-20s reason=%s"
              % ("PASS" if ok else "FAIL", name, result.get("action"),
                 str(got_next_id), result.get("reason")))

    print("=" * 80)
    if failed:
        print("SELF TEST FAILED: %d/%d scenarios" % (failed, len(scenarios)))
        return 1
    print("SELF TEST PASSED: %d scenarios" % len(scenarios))
    return 0


if __name__ == "__main__":
    sys.exit(self_test())
