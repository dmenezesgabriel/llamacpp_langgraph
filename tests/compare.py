"""
Compares agent_results.json with ground_truth.json and produces a
detailed test report in tests/report.md.

Checks:
  - Intent correctly classified (data_query vs general_chat)
  - Key numeric values appear in the agent's final answer
  - SQL validity (re-runs agent's SQL directly against DuckDB and compares rows)
  - Reflection retries (signals SQL trouble)
  - Latency
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
GT_PATH   = TESTS_DIR / "ground_truth.json"
AR_PATH   = TESTS_DIR / "agent_results.json"
REPORT    = TESTS_DIR / "report.md"

# Questions that expect data_query intent
DATA_QUERY_IDS = {"Q2","Q3","Q4","Q5","Q6","Q7","Q8","Q9","Q10","Q11","Q12","Q13","Q14","Q15"}
GENERAL_IDS    = {"Q1"}


def load_json(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def extract_numbers(text: str) -> set[str]:
    """Pull all number-like tokens from a text string."""
    return set(re.findall(r"\d[\d,\.]*", text))


def validate_answer(gt: dict, ar: dict) -> tuple[str, list[str]]:
    """
    Returns (status, issues) where status is PASS / WARN / FAIL.
    """
    issues = []

    # ── 1. Check intent ──────────────────────────────────────────────────────
    expected_intent = "data_query" if ar["id"] in DATA_QUERY_IDS else "general_chat"
    if ar["intent"] != expected_intent:
        issues.append(f"Intent mismatch: got '{ar['intent']}', expected '{expected_intent}'")

    # ── 2. Check for errors ──────────────────────────────────────────────────
    if ar.get("error"):
        issues.append(f"Agent error: {ar['error']}")
        return "FAIL", issues

    if gt.get("error"):
        issues.append(f"GT query error: {gt['error']} — skipping numeric check")
        return "WARN", issues

    # ── 3. For data queries: validate SQL output ──────────────────────────────
    if ar["id"] in DATA_QUERY_IDS:
        # Re-run agent SQL in DuckDB and compare key values
        if ar.get("sql_query"):
            try:
                import duckdb
                from db.loader import get_connection
                conn = get_connection()
                rel  = conn.execute(ar["sql_query"])
                agent_rows = rel.fetchall()
                agent_cols = [d[0] for d in rel.description]
            except Exception as e:
                issues.append(f"Agent SQL failed to re-run: {e}")
                agent_rows = []
                agent_cols = []

            gt_rows = [tuple(r) for r in gt["rows"]]

            # Compare row counts
            if len(agent_rows) != len(gt_rows):
                issues.append(
                    f"Row count mismatch: agent SQL returned {len(agent_rows)}, "
                    f"GT has {len(gt_rows)}"
                )

            # Compare first-column values (main answer metric)
            if gt_rows and agent_rows:
                gt_first  = {str(r[0]) for r in gt_rows}
                ag_first  = {str(r[0]) for r in agent_rows}
                overlap   = gt_first & ag_first
                if len(overlap) < max(1, len(gt_first) * 0.5):
                    issues.append(
                        f"Key values mismatch — GT: {sorted(gt_first)[:5]}, "
                        f"Agent: {sorted(ag_first)[:5]}"
                    )

            # Check that numeric GT values appear in final answer text
            if gt_rows and len(gt["columns"]) >= 1:
                # Take the first numeric value from GT result and check presence in answer
                for row in gt_rows[:3]:
                    for val in row:
                        sval = str(val)
                        if re.match(r"^\d[\d,\.]+$", sval) and float(sval.replace(",","")) > 0:
                            # Check if the rounded value appears in agent answer
                            try:
                                fval = float(sval.replace(",",""))
                                rounded = str(round(fval))
                                if rounded not in ar["final_answer"] and sval not in ar["final_answer"]:
                                    issues.append(
                                        f"Expected value ~{sval} not found in agent answer"
                                    )
                                break
                            except ValueError:
                                pass
                        break
        else:
            issues.append("Agent produced no SQL for a data_query intent")

    # ── 4. Reflection retries ─────────────────────────────────────────────────
    retries = ar.get("reflection_retries", 0)
    if retries >= 3:
        issues.append(f"Hit max reflection retries ({retries}) — answer may be wrong")
    elif retries > 0:
        issues.append(f"WARN: needed {retries} reflection retry/retries")

    if not issues:
        return "PASS", []
    # Distinguish warnings from failures
    has_fail = any(
        kw in i for i in issues
        for kw in ("mismatch", "failed", "error", "no SQL", "max reflection")
    )
    return ("FAIL" if has_fail else "WARN"), issues


def build_report(gt_list: list[dict], ar_list: list[dict]) -> str:
    gt_map = {g["id"]: g for g in gt_list}
    ar_map = {a["id"]: a for a in ar_list}

    lines = [
        "# Agent Test Report",
        "",
        "Validation: agent results vs. direct DuckDB ground truth.",
        "",
        "| ID | Question (short) | Intent | Retries | Time(s) | Status | Notes |",
        "|-----|-----------------|--------|---------|---------|--------|-------|",
    ]

    detailed = []
    summary = {"PASS": 0, "WARN": 0, "FAIL": 0, "MISSING": 0}

    all_ids = sorted(gt_map.keys(), key=lambda x: int(x[1:]))
    for qid in all_ids:
        gt = gt_map.get(qid, {})
        ar = ar_map.get(qid)
        if ar is None:
            summary["MISSING"] += 1
            lines.append(f"| {qid} | {gt.get('description','?')[:40]} | — | — | — | ❓ MISSING | Not run |")
            continue

        status, issues = validate_answer(gt, ar)
        summary[status] += 1

        emoji = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(status, "❓")
        q_short = ar["question"][:45] + ("…" if len(ar["question"]) > 45 else "")
        issue_str = "; ".join(issues[:2]) if issues else "—"

        lines.append(
            f"| {qid} | {q_short} | {ar['intent']} | {ar.get('reflection_retries',0)} "
            f"| {ar.get('elapsed_s','?')} | {emoji} {status} | {issue_str} |"
        )

        detailed.append((qid, ar, gt, status, issues))

    lines += [
        "",
        f"**Summary:** ✅ {summary['PASS']} PASS  ⚠️ {summary['WARN']} WARN  "
        f"❌ {summary['FAIL']} FAIL  ❓ {summary['MISSING']} MISSING",
        "",
        "---",
        "",
        "## Detailed Results",
        "",
    ]

    for qid, ar, gt, status, issues in detailed:
        lines += [
            f"### {qid} — {ar['question']}",
            "",
            f"**Status:** {status}  |  **Intent:** `{ar['intent']}`  "
            f"|  **Table:** `{ar['target_table']}`  "
            f"|  **Retries:** {ar.get('reflection_retries',0)}  "
            f"|  **Time:** {ar.get('elapsed_s','?')}s",
            "",
        ]
        if ar.get("sql_query"):
            lines += [
                "**Agent SQL:**",
                "```sql",
                ar["sql_query"],
                "```",
                "",
            ]
        if gt.get("sql"):
            lines += [
                "**Ground Truth SQL:**",
                "```sql",
                gt["sql"].strip(),
                "```",
                "",
            ]
        if gt.get("rows"):
            lines.append("**Ground Truth Result (first 5 rows):**")
            cols = gt.get("columns", [])
            lines.append("```")
            lines.append(" | ".join(cols))
            for row in gt["rows"][:5]:
                lines.append(" | ".join(str(v) for v in row))
            lines.append("```")
            lines.append("")
        if ar.get("final_answer"):
            lines += [
                "**Agent Answer:**",
                f"> {ar['final_answer'][:600]}",
                "",
            ]
        if issues:
            lines.append("**Issues:**")
            for issue in issues:
                lines.append(f"- {issue}")
            lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    if not GT_PATH.exists():
        print(f"ERROR: {GT_PATH} not found. Run tests/ground_truth.py first.")
        sys.exit(1)
    if not AR_PATH.exists():
        print(f"ERROR: {AR_PATH} not found. Run tests/run_agent_tests.py first.")
        sys.exit(1)

    gt_list = load_json(GT_PATH)
    ar_list = load_json(AR_PATH)

    report_md = build_report(gt_list, ar_list)

    with open(REPORT, "w") as f:
        f.write(report_md)

    print(report_md)
    print(f"\n📄  Report saved to: {REPORT}")


if __name__ == "__main__":
    main()
