#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZHOU_Videodirector — Phase-3 Routing Benchmark 跑分器 (P3-5)

对 tests/fixtures/routing-cases.yaml（§76/§77 stress-test 数据集）逐 case 调用
modules/router/router.py 的 route_single(shot, context)，并按 §78 口径判定：

    pass      : 引擎 route ∈ expected_routes ∪ acceptable_alternatives，且 ∉ must_not_route
    soft_pass : route ∈ acceptable_alternatives 但 ∉ expected_routes（备选命中，记为警告）
    fail      : route ∈ must_not_route（严重）或 ∉ expected ∪ acceptable（偏离）
    must_not 规避率：引擎 route ∉ must_not_route 的 case 占比（§78：重点是避开明显错误）

CLI:
    python3 scripts/routing-benchmark.py [--fixture tests/fixtures/routing-cases.yaml]
                                         [--json] [--selftest]

退出码:
    0 = 全部 pass（可含 soft_pass）
    1 = 存在 must_not 命中或 hard fail
    2 = 参数/加载错误

依赖: Python 3 stdlib + PyYAML（仅读 fixture；路由引擎本身是 stdlib only）。
"""

import argparse
import json
import os
import sys

# ---------------------------------------------------------------------------
# Path bootstrap: 让脚本可以从任意 cwd 运行
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_HERE)  # .../ZHOU_Videodirector
FIXTURE_DEFAULT = os.path.join(PROJECT_ROOT, "tests", "fixtures", "routing-cases.yaml")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "modules"))

try:
    from router.router import route_single, ROUTES  # noqa: E402
except ImportError as e:  # pragma: no cover
    print("ERROR: cannot import router engine at %s: %s" % (
        os.path.join(PROJECT_ROOT, "modules", "router", "router.py"), e), file=sys.stderr)
    sys.exit(2)

try:
    import yaml
except ImportError as e:  # pragma: no cover
    print("ERROR: PyYAML is required (pip install pyyaml): %s" % e, file=sys.stderr)
    sys.exit(2)

# ---------------------------------------------------------------------------
# 判定口径（§78）
# ---------------------------------------------------------------------------


def judge(engine_route, case):
    """Classify one decision into pass / soft_pass / fail.

    Must-not 优先于 acceptable：即使 route 同时出现在 acceptable_alternatives 里，
    只要 ∈ must_not_route 就判 fail（避免"可接受集合里混进必须避开项"）。
    返回 (verdict, detail)：
      verdict: 'pass' | 'soft_pass' | 'fail'
      detail : 分类说明（如 'deviation' | 'must_not'）
    """
    exp = list(case.get("expected_routes") or [])
    acc = list(case.get("acceptable_alternatives") or [])
    mnr = list(case.get("must_not_route") or [])
    if engine_route in mnr:
        return "fail", "must_not"
    if engine_route in exp:
        return "pass", "expected"
    if engine_route in acc:
        return "soft_pass", "acceptable"
    return "fail", "deviation"


def run_case(case, engine_fn=route_single):
    """构造 shot/context，调引擎，返回 (decision, verdict, detail, extra_checks)。

    engine_fn 可注入（selftest 用桩引擎做确定性验证），默认 route_single。
    """
    shot = dict(case.get("shot") or {})
    ctx = dict(case.get("context") or {})
    decision = engine_fn(shot, ctx)
    verdict, detail = judge(decision["route"], case)
    extra = run_extra_checks(decision, case)
    return decision, verdict, detail, extra


def run_extra_checks(decision, case):
    """可选附加断言（不参与 pass/fail 与退出码，只作信息统计）。"""
    checks = []
    if "expect_confidence_max" in case:
        ok = decision["confidence"] <= float(case["expect_confidence_max"])
        checks.append((ok, "confidence<=%.2f (got %.2f)" % (
            case["expect_confidence_max"], decision["confidence"])))
    if "expect_confidence_min" in case:
        ok = decision["confidence"] >= float(case["expect_confidence_min"])
        checks.append((ok, "confidence>=%.2f (got %.2f)" % (
            case["expect_confidence_min"], decision["confidence"])))
    if "expect_prototype_required" in case:
        ok = bool(decision["prototype_required"]) == bool(case["expect_prototype_required"])
        checks.append((ok, "prototype_required=%s (got %s)" % (
            case["expect_prototype_required"], decision["prototype_required"])))
    if "expect_route_source" in case:
        ok = decision["route_source"] == case["expect_route_source"]
        checks.append((ok, "route_source=%s (got %s)" % (
            case["expect_route_source"], decision["route_source"])))
    return checks


# ---------------------------------------------------------------------------
# Fixture 校验
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = [
    "id", "description", "factors", "shot", "context",
    "expected_routes", "acceptable_alternatives", "must_not_route", "reason",
]


def validate_fixture(data):
    """结构校验。返回 (errors, warnings)。"""
    errors, warnings = [], []
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        errors.append("fixture 顶层必须有 cases 列表")
        return errors, warnings
    enum = set(data.get("route_enum") or ROUTES)
    seen = {}
    for idx, c in enumerate(data["cases"]):
        if not isinstance(c, dict):
            errors.append("cases[%d]: 必须是 mapping" % idx)
            continue
        cid = c.get("id", "?")
        for k in _REQUIRED_KEYS:
            if k not in c:
                errors.append("%s: 缺少必需字段 %s" % (cid, k))
        if cid in seen:
            errors.append("%s: 重复 id（与 cases[%d] 冲突）" % (cid, seen[cid]))
        seen[cid] = idx
        for field in ("expected_routes", "acceptable_alternatives", "must_not_route"):
            vals = c.get(field)
            if vals is None:
                continue
            if not isinstance(vals, list):
                errors.append("%s: %s 必须是列表" % (cid, field))
                continue
            for v in vals:
                if v not in enum:
                    errors.append("%s: %s 含非法 route %r（enum=%s）" % (cid, field, v, sorted(enum)))
        if not c.get("expected_routes"):
            warnings.append("%s: expected_routes 为空（判例无意义）" % cid)
        if not c.get("must_not_route"):
            warnings.append("%s: must_not_route 为空（§78 重点是避开明显错误，建议给值）" % cid)
        # 自相矛盾：expected 与 must_not 重叠
        inter = set(c.get("expected_routes") or []) & set(c.get("must_not_route") or [])
        if inter:
            warnings.append("%s: expected_routes 与 must_not_route 重叠 %s" % (cid, sorted(inter)))
    return errors, warnings


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


def build_report(cases, fixture_path, engine_fn=route_single):
    total = len(cases)
    counters = {"pass": 0, "soft_pass": 0, "fail": 0, "must_not_hit": 0}
    by_route = {r: {"cases": 0, "pass": 0, "soft_pass": 0, "fail": 0, "must_not_hit": 0}
                for r in ROUTES}
    per_case = []
    failures = []
    soft_passes = []
    extra_total, extra_ok = 0, 0

    for c in cases:
        decision, verdict, detail, extra = run_case(c, engine_fn)
        route = decision["route"]
        primary = (c.get("expected_routes") or ["?"])[0]

        counters[verdict] += 1
        is_must_hit = route in set(c.get("must_not_route") or [])
        if is_must_hit:
            counters["must_not_hit"] += 1

        if primary in by_route:
            by_route[primary]["cases"] += 1
            by_route[primary][verdict] += 1
            if is_must_hit:
                by_route[primary]["must_not_hit"] += 1

        for ok, desc in extra:
            extra_total += 1
            if ok:
                extra_ok += 1

        entry = {
            "id": c.get("id"),
            "category": c.get("category"),
            "expected_routes": c.get("expected_routes") or [],
            "acceptable_alternatives": c.get("acceptable_alternatives") or [],
            "must_not_route": c.get("must_not_route") or [],
            "engine_route": route,
            "engine_confidence": decision["confidence"],
            "verdict": verdict,
            "detail": detail,
        }
        per_case.append(entry)
        if verdict == "fail":
            entry["reason"] = c.get("reason", "")
            entry["expected_primary"] = primary
            entry["fail_hint"] = c.get("expect_fail_hint", "")
            entry["scores"] = decision["scores"]
            entry["extra_checks"] = [{"ok": ok, "desc": desc} for ok, desc in extra]
            failures.append(entry)
        elif verdict == "soft_pass":
            soft_passes.append(entry)

    pass_count = counters["pass"] + counters["soft_pass"]
    pass_rate = (pass_count / total) if total else 0.0
    must_not_total = sum(1 for c in cases
                         if set(c.get("must_not_route") or []))
    must_not_hit = counters["must_not_hit"]
    # §78：must_not 规避率 = 引擎 route 避开 must_not_route 的比例
    must_not_avoided = (1.0 - must_not_hit / must_not_total) if must_not_total else 1.0

    report = {
        "fixture": fixture_path,
        "engine": "modules/router/router.py::route_single",
        "total_cases": total,
        "counters": counters,
        "pass_rate": round(pass_rate, 4),
        "must_not_avoided": round(must_not_avoided, 4),
        "by_route": by_route,
        "per_case": per_case,
        "failures": failures,
        "soft_passes": [{"id": x["id"], "engine_route": x["engine_route"],
                         "expected_routes": x["expected_routes"]} for x in soft_passes],
        "extra_checks": {"checked": extra_total, "passed": extra_ok},
        "exit_code": 1 if (counters["fail"] > 0 or counters["must_not_hit"] > 0) else 0,
    }
    return report


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def print_human(report, fixture_warnings):
    total = report["total_cases"]
    cnt = report["counters"]
    print("== ZHOU_Videodirector Routing Benchmark ==")
    print("fixture: %s (%d cases)" % (report["fixture"], total))
    print("engine : %s" % report["engine"])
    print("")
    print("pass        : %d" % cnt["pass"])
    print("soft_pass   : %d  (acceptable alternative)" % cnt["soft_pass"])
    print("hard fail   : %d  (deviation)" % (cnt["fail"] - cnt["must_not_hit"]))
    print("must_not hit: %d" % cnt["must_not_hit"])
    print("pass_rate   : %.2f%%   (pass+soft_pass / total)" % (report["pass_rate"] * 100))
    print("must_not_avoided: %.2f%%" % (report["must_not_avoided"] * 100))
    print("extra_checks: %d/%d" % (report["extra_checks"]["passed"],
                                   report["extra_checks"]["checked"]))
    print("")
    print("Route breakdown (grouped by expected primary route):")
    print("  %-16s %6s %6s %6s %6s %12s" % ("route", "cases", "pass", "soft", "fail", "must_not"))
    for r in ROUTES:
        b = report["by_route"].get(r)
        if not b or b["cases"] == 0:
            continue
        print("  %-16s %6d %6d %6d %6d %12d" % (
            r, b["cases"], b["pass"], b["soft_pass"], b["fail"], b["must_not_hit"]))
    print("")
    if report["failures"]:
        print("Failures:")
        for f in report["failures"]:
            print("  - %s: got=%s (conf=%s), expected=%s, acceptable=%s, detail=%s" % (
                f["id"], f["engine_route"], f["engine_confidence"],
                f["expected_routes"], f["acceptable_alternatives"], f["detail"]))
            if f.get("fail_hint"):
                print("      hint: %s" % f["fail_hint"])
    if report["soft_passes"]:
        print("Soft passes (acceptable alternative hit):")
        for s in report["soft_passes"]:
            print("  - %s: got=%s, expected=%s" % (
                s["id"], s["engine_route"], s["expected_routes"]))
    if fixture_warnings:
        print("Fixture warnings:")
        for w in fixture_warnings:
            print("  - WARN %s" % w)
    print("")
    print("exit_code=%d" % report["exit_code"])


def _json_out(report):
    print(json.dumps(report, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run(fixture_path):
    with open(fixture_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    errors, warnings = validate_fixture(data)
    if errors:
        for e in errors:
            print("FIXTURE ERROR: %s" % e, file=sys.stderr)
        return None, 2
    report = build_report(data["cases"], fixture_path)
    return report, warnings


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    ap = argparse.ArgumentParser(
        description="ZHOU_Videodirector Phase-3 routing benchmark (§78)",
        add_help=True,
    )
    ap.add_argument("--fixture", default=FIXTURE_DEFAULT,
                    help="fixture yaml path (default: %(default)s)")
    ap.add_argument("--json", action="store_true", help="emit JSON report")
    ap.add_argument("--selftest", action="store_true",
                    help="validate judging logic + engine integration, exit 0")
    args = ap.parse_args(argv)

    if args.selftest:
        sys.exit(_selftest(args.fixture))
    if not os.path.isfile(args.fixture):
        print("ERROR: fixture not found: %s" % args.fixture, file=sys.stderr)
        sys.exit(2)
    report, warnings = run(args.fixture)
    if report is None:
        sys.exit(2)
    if args.json:
        _json_out(report)
    else:
        print_human(report, warnings)
    sys.exit(report["exit_code"])


# ---------------------------------------------------------------------------
# --selftest：判定逻辑正确性（含 must_not 命中必须判 fail）+ 引擎集成
# ---------------------------------------------------------------------------


def _selftest(fixture_path):
    errors = []

    def check(cond, msg):
        if cond:
            print("  PASS  %s" % msg)
        else:
            errors.append(msg)
            print("  FAIL  %s" % msg)

    print("== selftest: scripts/routing-benchmark.py ==")

    # 0) 判定逻辑（合成 decision，不依赖引擎）
    print("[judge] 判定逻辑（§78 口径）")
    cases = [
        ("expected 命中 -> pass",
         {"expected_routes": ["REMOTION"], "acceptable_alternatives": [],
          "must_not_route": ["GENERATIVE_VIDEO"]}, "REMOTION", ("pass", "expected")),
        ("acceptable 备选命中 -> soft_pass",
         {"expected_routes": ["REMOTION"], "acceptable_alternatives": ["REAL_FOOTAGE"],
          "must_not_route": []}, "REAL_FOOTAGE", ("soft_pass", "acceptable")),
        ("must_not 命中（严重）-> fail",
         {"expected_routes": ["REMOTION"], "acceptable_alternatives": [],
          "must_not_route": ["GENERATIVE_VIDEO"]}, "GENERATIVE_VIDEO", ("fail", "must_not")),
        ("must_not 与 acceptable 重叠 -> must_not 优先，fail",
         {"expected_routes": ["REMOTION"], "acceptable_alternatives": ["GENERATIVE_VIDEO"],
          "must_not_route": ["GENERATIVE_VIDEO"]}, "GENERATIVE_VIDEO", ("fail", "must_not")),
        ("偏离（不在 expected 也不在 acceptable）-> fail",
         {"expected_routes": ["REMOTION"], "acceptable_alternatives": [],
          "must_not_route": []}, "JY_NATIVE", ("fail", "deviation")),
    ]
    for name, case, route, want in cases:
        got = judge(route, case)
        check(got == want, "%s (route=%s -> %s)" % (name, route, got))

    # 1) 引擎集成：fixture 前 5 个 case 逐 case 跑 route_single
    print("[integration] fixture 前 5 个 case -> route_single")
    with open(fixture_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    errs, warns = validate_fixture(data)
    check(not errs, "fixture 结构校验通过 (errors=%d)" % len(errs))
    for c in data["cases"][:5]:
        decision, verdict, detail, extra = run_case(c)
        check(decision["route"] in ROUTES,
              "%s route=%s ∈ enum" % (c["id"], decision["route"]))
        check(verdict in ("pass", "soft_pass", "fail"),
              "%s verdict=%r" % (c["id"], verdict))
        check(0.0 <= decision["confidence"] <= 1.0,
              "%s confidence ∈ [0,1]" % c["id"])

    # 2) 故意错误 case：判定逻辑对错误数据必须判 fail（含 must_not 命中）
    print("[trap] 故意错误 case 必须判 fail")
    trap_must_not = {
        "id": "TRAP-1", "description": "synthetic: engine lands in must_not",
        "factors": {}, "shot": {}, "context": {},
        "expected_routes": ["REAL_FOOTAGE"],
        "acceptable_alternatives": ["GENERATIVE_VIDEO"],
        "must_not_route": ["GENERATIVE_VIDEO"],
        "reason": "selftest trap",
    }
    v1, d1 = judge("GENERATIVE_VIDEO", trap_must_not)
    check(v1 == "fail" and d1 == "must_not",
          "TRAP-1: must_not 命中必须判 fail (got %s/%s)" % (v1, d1))
    trap_deviation = {
        "id": "TRAP-2", "description": "synthetic: engine deviates",
        "factors": {}, "shot": {}, "context": {},
        "expected_routes": ["REMOTION"],
        "acceptable_alternatives": [],
        "must_not_route": ["GENERATIVE_VIDEO"],
        "reason": "selftest trap",
    }
    v2, d2 = judge("JY_NATIVE", trap_deviation)
    check(v2 == "fail" and d2 == "deviation",
          "TRAP-2: 偏离必须判 fail (got %s/%s)" % (v2, d2))

    # 3) 汇总/退出码逻辑（用桩引擎，确定性验证 build_report 的计数与 exit_code）
    print("[exit] 汇总退出码（桩引擎）")
    _STUB_DECISION = {
        "route": "REMOTION", "confidence": 0.9, "route_source": "AUTO",
        "prototype_required": False, "scores": {}, "constraints": [], "layers": [],
        "reason": {}, "decision_summary": "", "candidate_routes": [],
    }

    def _stub_engine(shot, ctx):
        d = dict(_STUB_DECISION)
        d["route"] = shot.get("__route__", "REMOTION")
        return d

    all_pass_cases = [
        {"expected_routes": ["REMOTION"], "acceptable_alternatives": [],
         "must_not_route": ["GENERATIVE_VIDEO"]},
        {"expected_routes": ["REMOTION"], "acceptable_alternatives": [],
         "must_not_route": ["THREE_D"]},
    ]
    r1 = build_report(all_pass_cases, fixture_path, engine_fn=_stub_engine)
    check(r1["counters"]["pass"] == 2 and r1["exit_code"] == 0,
          "全 pass -> exit_code=0 (got %d)" % r1["exit_code"])

    trap_must_case = {
        "expected_routes": ["REAL_FOOTAGE"], "acceptable_alternatives": [],
        "must_not_route": ["GENERATIVE_VIDEO"],
        "shot": {"__route__": "GENERATIVE_VIDEO"},
    }
    r2 = build_report([trap_must_case], fixture_path, engine_fn=_stub_engine)
    check(r2["counters"]["must_not_hit"] == 1 and r2["exit_code"] == 1,
          "含 must_not 命中 -> exit_code=1 (got %d)" % r2["exit_code"])

    dev_case = {
        "expected_routes": ["REMOTION"], "acceptable_alternatives": [],
        "must_not_route": ["GENERATIVE_VIDEO"],
        "shot": {"__route__": "JY_NATIVE"},
    }
    r3 = build_report([dev_case], fixture_path, engine_fn=_stub_engine)
    check(r3["counters"]["fail"] == 1 and r3["counters"]["must_not_hit"] == 0
          and r3["exit_code"] == 1,
          "偏离 fail（非 must_not）-> exit_code=1 (got %d)" % r3["exit_code"])

    if errors:
        print("")
        print("selftest FAILED (%d assertions)" % len(errors))
        for e in errors:
            print("  - " + e)
        return 1
    print("")
    print("selftest PASSED")
    return 0


if __name__ == "__main__":
    main()
