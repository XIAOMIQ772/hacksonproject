"""Task graph produced by the planner: validation and scheduling order."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,40}$")


@dataclass
class Node:
    id: str
    title: str
    requirements: list[str]
    depends_on: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    notes: str = ""


def parse(text: str, atomic_ids: list[str]) -> tuple[list[Node], list[str]]:
    """Nodes from the planner's JSON and a list of problems (empty when the plan is usable)."""
    try:
        data = json.loads(text)
    except ValueError as error:
        return [], [f"not valid JSON: {error}"]
    raw = data.get("nodes") if isinstance(data, dict) else data
    if not isinstance(raw, list) or not raw:
        return [], ["expected {\"nodes\": [...]} with at least one node"]
    nodes, problems = [], []
    for item in raw:
        if not isinstance(item, dict) or not ID.match(str(item.get("id", ""))):
            problems.append(f"node needs an id of letters, digits, '-' or '_': {str(item)[:80]}")
            continue
        nodes.append(Node(str(item["id"]), str(item.get("title", "")),
                          [str(r) for r in item.get("requirements") or []],
                          [str(d) for d in item.get("depends_on") or []],
                          [str(f) for f in item.get("files") or []], str(item.get("notes", ""))))
    ids = [n.id for n in nodes]
    if len(set(ids)) != len(ids):
        problems.append("node ids must be unique")
    if "foundation" in ids:
        problems.append("do not include a foundation node; it already exists and every node depends on it")
    known = set(atomic_ids)
    covered = [r for n in nodes for r in n.requirements]
    unknown = sorted(set(covered) - known)
    missing = [a for a in atomic_ids if a not in covered]
    twice = sorted({r for r in covered if covered.count(r) > 1})
    if unknown:
        problems.append(f"unknown requirement ids: {', '.join(unknown)}")
    if missing:
        problems.append(f"requirements not assigned to any node: {', '.join(missing)}")
    if twice:
        problems.append(f"requirements assigned to more than one node: {', '.join(twice)}")
    for node in nodes:
        for dep in node.depends_on:
            if dep not in ids:
                problems.append(f"{node.id} depends on unknown node {dep}")
    if not problems and order(nodes) is None:
        problems.append("dependencies contain a cycle")
    return nodes, problems


def order(nodes: list[Node]) -> list[Node] | None:
    """Topological order, or None when there is a cycle."""
    done: set[str] = set()
    result: list[Node] = []
    pending = list(nodes)
    while pending:
        ready = [n for n in pending if all(d in done for d in n.depends_on)]
        if not ready:
            return None
        for node in ready:
            result.append(node)
            done.add(node.id)
            pending.remove(node)
    return result


def ready(nodes: list[Node], merged: set[str], started: set[str]) -> list[Node]:
    """Nodes whose dependencies are all merged and that have not started yet."""
    return [n for n in nodes if n.id not in started and all(d in merged for d in n.depends_on)]
