#!/usr/bin/env python3
"""Validate and advance a SubTube dispatch plan.

This is the deterministic state/queue half of the controller. Agent spawning and
waiting are host actions (the main Codex session owns multi_agent tools); this
script prevents the host from losing dependencies, budget, or terminal state.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional


ALLOWED_SP = {1, 2, 3, 5}
STATES = {
    "todo",
    "planned",
    "in_progress",
    "review_ready",
    "review_feedback",
    "qa",
    "completed",
    "blocked",
}
TERMINAL = {"completed", "blocked"}
COMPLETION_MODES = {"each_ticket"}
TRANSITIONS = {
    "todo": {"planned", "in_progress", "blocked"},
    "planned": {"in_progress", "blocked"},
    "in_progress": {"review_ready", "blocked"},
    "review_ready": {"review_feedback", "in_progress", "qa", "blocked"},
    "review_feedback": {"in_progress", "blocked"},
    "qa": {"completed", "in_progress", "blocked"},
    "completed": set(),
    "blocked": set(),
}


class PlanError(ValueError):
    """Raised when a plan cannot be safely dispatched."""


def load_plan(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanError(f"cannot read plan {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanError("plan root must be an object")
    return data


def item_map(plan: dict[str, Any]) -> dict[int, dict[str, Any]]:
    raw_items = plan.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise PlanError("plan.items must be a non-empty array")
    result: dict[int, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            raise PlanError("every plan item must be an object")
        issue = item.get("issue")
        if not isinstance(issue, int) or issue <= 0:
            raise PlanError("every item.issue must be a positive integer")
        if issue in result:
            raise PlanError(f"duplicate issue #{issue}")
        result[issue] = item
    return result


def dependency_ids(item: dict[str, Any]) -> list[int]:
    deps = item.get("depends_on", [])
    if not isinstance(deps, list) or not all(isinstance(dep, int) and dep > 0 for dep in deps):
        raise PlanError(f"issue #{item.get('issue')} depends_on must be integer array")
    return deps


def validate(plan: dict[str, Any]) -> dict[int, dict[str, Any]]:
    items = item_map(plan)
    max_ticket = plan.get("max_ticket_sp", 5)
    if max_ticket != 5:
        raise PlanError("SubTube max_ticket_sp must remain 5")
    budget = plan.get("budget_sp")
    if not isinstance(budget, int) or budget <= 0:
        raise PlanError("budget_sp must be a positive integer")
    max_retries = plan.get("max_retries", 3)
    if not isinstance(max_retries, int) or max_retries < 1:
        raise PlanError("max_retries must be a positive integer")
    max_in_flight = plan.get("max_in_flight", 2)
    if not isinstance(max_in_flight, int) or max_in_flight < 1 or max_in_flight > 3:
        raise PlanError("max_in_flight must be 1, 2, or 3")
    completion_mode = plan.get("completion_mode", "each_ticket")
    if completion_mode not in COMPLETION_MODES:
        raise PlanError("completion_mode must be each_ticket")
    review_policy = plan.get("review_policy", "rework_until_closed")
    if review_policy != "rework_until_closed":
        raise PlanError("review_policy must be rework_until_closed")

    for issue, item in items.items():
        estimate = item.get("estimate_sp")
        if estimate not in ALLOWED_SP or estimate > max_ticket:
            raise PlanError(f"issue #{issue} has invalid estimate_sp={estimate}; use 1/2/3/5")
        state = item.get("state", "todo")
        if state not in STATES:
            raise PlanError(f"issue #{issue} has invalid state={state}")
        for dep in dependency_ids(item):
            if dep not in items:
                raise PlanError(f"issue #{issue} depends on missing issue #{dep}")
        for field in ("writer", "reviewer"):
            if not isinstance(item.get(field), str) or not item[field]:
                raise PlanError(f"issue #{issue} requires {field}")
        if item["writer"] == item["reviewer"]:
            raise PlanError(f"issue #{issue} writer and reviewer must be different")
        qa = item.get("qa")
        if qa is not None and qa in {item["writer"], item["reviewer"]}:
            raise PlanError(f"issue #{issue} QA must be independent from writer/reviewer")
        attempts = item.get("attempts", 0)
        if not isinstance(attempts, int) or attempts < 0 or attempts > max_retries:
            raise PlanError(f"issue #{issue} attempts must be between 0 and {max_retries}")
        review_cycles = item.get("review_cycles", 0)
        if not isinstance(review_cycles, int) or review_cycles < 0:
            raise PlanError(f"issue #{issue} review_cycles must be a non-negative integer")

    targets = plan.get("targets", list(items))
    if not isinstance(targets, list) or not targets or not all(isinstance(issue, int) for issue in targets):
        raise PlanError("targets must be a non-empty integer array")
    for issue in targets:
        if issue not in items:
            raise PlanError(f"target issue #{issue} is not in plan.items")

    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(issue: int) -> None:
        if issue in visiting:
            raise PlanError(f"dependency cycle includes #{issue}")
        if issue in visited:
            return
        visiting.add(issue)
        for dep in dependency_ids(items[issue]):
            visit(dep)
        visiting.remove(issue)
        visited.add(issue)

    for issue in items:
        visit(issue)
    return items


def closure(items: dict[int, dict[str, Any]], targets: list[int]) -> list[int]:
    result: set[int] = set()

    def add(issue: int) -> None:
        if issue in result:
            return
        result.add(issue)
        for dep in dependency_ids(items[issue]):
            add(dep)

    for issue in targets:
        add(issue)
    return sorted(result)


def execution_order(items: dict[int, dict[str, Any]], ids: list[int]) -> list[int]:
    """Return dependency-first order for the independent ticket closeouts."""
    allowed = set(ids)
    ordered: list[int] = []
    visiting: set[int] = set()
    visited: set[int] = set()

    def add(issue: int) -> None:
        if issue in visited:
            return
        if issue in visiting:
            raise PlanError(f"dependency cycle includes #{issue}")
        visiting.add(issue)
        for dep in dependency_ids(items[issue]):
            if dep in allowed:
                add(dep)
        visiting.remove(issue)
        visited.add(issue)
        ordered.append(issue)

    for issue in ids:
        add(issue)
    return ordered


def required_sp(items: dict[int, dict[str, Any]], ids: list[int]) -> int:
    return sum(items[issue]["estimate_sp"] for issue in ids if items[issue].get("state", "todo") not in TERMINAL)


def next_action(plan: dict[str, Any], items: dict[int, dict[str, Any]]) -> dict[str, Any]:
    targets = plan.get("targets", list(items))
    ids = execution_order(items, closure(items, targets))
    blocked = [issue for issue in ids if items[issue].get("state", "todo") == "blocked"]
    if blocked:
        return {
            "controller_state": "blocked",
            "stop_reason": "dependency_or_item_blocked",
            "blocked_issues": blocked,
        }

    unfinished = [issue for issue in ids if items[issue].get("state", "todo") != "completed"]
    if not unfinished:
        return {
            "controller_state": "completed",
            "stop_reason": "all_dependency_closure_tickets_completed",
            "completion_mode": plan.get("completion_mode", "each_ticket"),
            "closed_issues": ids,
        }

    required = required_sp(items, ids)
    budget = plan["budget_sp"]
    if required > budget:
        return {
            "controller_state": "needs_budget",
            "stop_reason": "dependency_closure_exceeds_budget",
            "budget_sp": budget,
            "required_sp": required,
            "target_budget_sp": plan.get("target_budget_sp"),
            "closure": ids,
        }

    for issue in ids:
        item = items[issue]
        state = item.get("state", "todo")
        if state in TERMINAL:
            continue
        deps = dependency_ids(item)
        unmet = [dep for dep in deps if items[dep].get("state", "todo") != "completed"]
        if unmet:
            return {
                "controller_state": "resolve_dependency",
                "stop_reason": "dependency_pending",
                "issue": issue,
                "unmet_dependencies": unmet,
                "next_dependency": unmet[0],
                "required_sp": required,
                "budget_sp": budget,
                "completion_mode": plan.get("completion_mode", "each_ticket"),
            }
        if state == "review_feedback":
            return {
                "controller_state": "dispatch_writer",
                "stop_reason": "review_feedback_non_terminal",
                "issue": issue,
                "writer": item["writer"],
                "reviewer": item["reviewer"],
                "qa": item.get("qa"),
                "estimate_sp": item["estimate_sp"],
                "review_cycles": item.get("review_cycles", 0),
                "completion_mode": plan.get("completion_mode", "each_ticket"),
                "review_policy": plan.get("review_policy", "rework_until_closed"),
                "next": "rework writer from review feedback; continue until the ticket closes",
            }
        if state in {"todo", "planned"}:
            return {
                "controller_state": "dispatch_writer",
                "issue": issue,
                "writer": item["writer"],
                "reviewer": item["reviewer"],
                "qa": item.get("qa"),
                "estimate_sp": item["estimate_sp"],
                "required_sp": required,
                "budget_sp": budget,
                "completion_mode": plan.get("completion_mode", "each_ticket"),
                "review_policy": plan.get("review_policy", "rework_until_closed"),
                "next": "spawn writer, wait for final, then transition to review_ready",
            }
        return {
            "controller_state": "wait_for_agent",
            "issue": issue,
            "state": state,
            "completion_mode": plan.get("completion_mode", "each_ticket"),
            "next": "wait; consume final evidence; do not return while this dispatch is active",
        }

    raise PlanError("plan has unfinished targets but no next action")


def atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def transition(
    plan: dict[str, Any],
    items: dict[int, dict[str, Any]],
    issue: int,
    state: str,
    evidence: Optional[str],
    note: Optional[str],
) -> None:
    if issue not in items:
        raise PlanError(f"issue #{issue} is not in plan")
    current = items[issue].get("state", "todo")
    if state not in STATES:
        raise PlanError(f"invalid state={state}")
    if state != current and state not in TRANSITIONS[current]:
        raise PlanError(f"invalid transition #{issue}: {current} -> {state}")
    if state in {"review_ready", "qa", "completed"} and not (evidence or items[issue].get("evidence")):
        raise PlanError(f"issue #{issue} requires evidence before state={state}")
    if state == "review_feedback" and not (evidence or note or items[issue].get("evidence") or items[issue].get("last_note")):
        raise PlanError(f"issue #{issue} requires review findings before state=review_feedback")
    if state == "review_feedback":
        items[issue]["review_cycles"] = items[issue].get("review_cycles", 0) + 1
    if state == "in_progress" and current != "in_progress":
        unmet = [dep for dep in dependency_ids(items[issue]) if items[dep].get("state", "todo") != "completed"]
        if unmet:
            raise PlanError(f"issue #{issue} cannot start before dependencies: {unmet}")
        # Review/QA feedback is rework, not an agent retry and never becomes
        # terminal under review_policy=rework_until_closed. max_retries only
        # limits fresh dispatch attempts after an agent/process failure.
        if current not in {"review_ready", "review_feedback", "qa"}:
            attempts = items[issue].get("attempts", 0) + 1
            if attempts > plan.get("max_retries", 3):
                raise PlanError(f"issue #{issue} exceeded max_retries={plan.get('max_retries', 3)}")
            items[issue]["attempts"] = attempts
    if evidence:
        items[issue]["evidence"] = evidence
    if note:
        items[issue]["last_note"] = note
    items[issue]["state"] = state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--next", action="store_true", dest="show_next")
    parser.add_argument("--transition", nargs=2, metavar=("ISSUE", "STATE"))
    parser.add_argument("--evidence", help="Evidence attached to a transition")
    parser.add_argument("--note", help="Failure trace or transition note")
    args = parser.parse_args()

    try:
        plan = load_plan(args.plan)
        items = validate(plan)
        if args.transition:
            transition(
                plan,
                items,
                int(args.transition[0]),
                args.transition[1],
                args.evidence,
                args.note,
            )
            atomic_write(args.plan, plan)
        if args.validate or args.transition:
            print(json.dumps({"valid": True, "plan": plan.get("dispatch_id"), "items": len(items)}, ensure_ascii=False))
        action = None
        if args.show_next or args.transition:
            action = next_action(plan, items)
            print(json.dumps(action, ensure_ascii=False, indent=2))
        if not (args.validate or args.show_next or args.transition):
            parser.error("choose --validate, --next, or --transition")
        if action and action["controller_state"] == "needs_budget":
            return 3
        if action and action["controller_state"] == "blocked":
            return 4
    except (PlanError, ValueError) as exc:
        print(f"dispatch_loop: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
