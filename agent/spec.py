"""Requirement tree loading and per-group task cards."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

QUOTED = re.compile(r'"([^"\n]{1,80})"')


@dataclass
class Node:
    id: str
    name: str
    type: str
    description: str = ""
    scenarios: list = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)

    @property
    def atomics(self) -> list["Node"]:
        if self.type == "ATOMIC":
            return [self]
        return [a for c in self.children for a in c.atomics]


def _node(raw: dict) -> Node:
    return Node(str(raw.get("id", "")), str(raw.get("name", "")), str(raw.get("type", "")),
                str(raw.get("description") or "").strip(), raw.get("scenarios") or [],
                [_node(c) for c in raw.get("children") or []])


def load(requirement_dir: Path) -> Node:
    yml = requirement_dir / "requirements.yaml"
    if yml.is_file():
        return _node(yaml.safe_load(yml.read_text()))
    txt = requirement_dir / "requirement.txt"
    data = json.loads(txt.read_text())
    return _node(yaml.safe_load(data["requirements_yaml"]))


def groups(root: Node) -> list[Node]:
    """Nodes whose children are all atomic (the natural unit of work), in document order."""
    out: list[Node] = []

    def walk(node: Node) -> None:
        if node.type == "ATOMIC":
            return
        if node.children and all(c.type == "ATOMIC" for c in node.children):
            out.append(node)
            return
        for child in node.children:
            walk(child)
        if not node.children and node is not root:
            out.append(node)

    walk(root)
    return out or [root]


def quoted_names(text: str) -> list[str]:
    return list(dict.fromkeys(QUOTED.findall(text)))


def _scenarios(atomic: Node) -> str:
    """Scenarios are often templated duplicates; show each distinct one once with its count."""
    seen: dict[str, int] = {}
    for scenario in atomic.scenarios:
        steps = scenario.get("steps") or []
        text = "\n".join(f"    {s.get('keyword', '')} {s.get('content', '')}" for s in steps)
        seen[text] = seen.get(text, 0) + 1
    parts = []
    for text, count in seen.items():
        parts.append(f"  Scenario{f' (x{count})' if count > 1 else ''}:\n{text}")
    return "\n".join(parts)


def card(atomic: Node) -> str:
    names = quoted_names(atomic.description)
    lines = [f"### {atomic.id} {atomic.name}", atomic.description]
    if names:
        lines.append("Exact UI strings (accessible names / messages): " + "; ".join(f'"{n}"' for n in names))
    lines.append(f"Hidden acceptance tests for this requirement: {len(atomic.scenarios)}")
    if atomic.scenarios:
        lines.append(_scenarios(atomic))
    return "\n".join(lines)


def group_card(group: Node) -> str:
    head = f"## {group.id} {group.name}\n{group.description}".strip()
    return head + "\n\n" + "\n\n".join(card(a) for a in group.atomics)


def outline(root: Node) -> str:
    """Compact overview of the whole product for planning."""
    lines = [f"# {root.name}", root.description, ""]

    def walk(node: Node, depth: int) -> None:
        for child in node.children:
            if child.type == "ATOMIC":
                lines.append(f"{'  ' * depth}- {child.id} {child.name} ({len(child.scenarios)} tests)")
            else:
                lines.append(f"{'  ' * depth}- {child.id} {child.name}")
                walk(child, depth + 1)

    walk(root, 0)
    return "\n".join(lines)
