"""Requirement tree loading and per-group task cards."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

QUOTED = re.compile(r'"([^"\n]{1,80})"')
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")


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


def images(text: str) -> list[str]:
    return list(dict.fromkeys(IMAGE.findall(text)))


def card(atomic: Node, base: str = "") -> str:
    names = quoted_names(atomic.description)
    lines = [f"### {atomic.id} {atomic.name}", atomic.description]
    pictures = images(atomic.description)
    if pictures:
        lines.append("Reference images (read them to see the intended layout; names in the text win): "
                     + ", ".join(f"{base}/{p}" if base else p for p in pictures))
    if names:
        lines.append("Exact UI strings (accessible names / messages): " + "; ".join(f'"{n}"' for n in names))
    lines.append(f"Acceptance scenarios: {len(atomic.scenarios)}")
    if atomic.scenarios:
        lines.append(_scenarios(atomic))
    return "\n".join(lines)


def group_card(group: Node, base: str = "") -> str:
    head = f"## {group.id} {group.name}\n{group.description}".strip()
    pictures = images(group.description)
    if pictures:
        head += "\nReference images: " + ", ".join(f"{base}/{p}" if base else p for p in pictures)
    return head + "\n\n" + "\n\n".join(card(a, base) for a in group.atomics)


def shared(root: Node, atomic_ids: list[str] | None = None) -> str:
    """Descriptions of the groups containing the given atomic requirements (all groups when None).

    Group descriptions state rules that hold for every requirement below them (accessible names of shared
    UI, persistence, validation), so every session working on those requirements must see them."""
    wanted = set(atomic_ids) if atomic_ids is not None else None
    out: list[str] = []

    def walk(node: Node) -> bool:
        if node.type == "ATOMIC":
            return wanted is None or node.id in wanted
        hit = any([walk(c) for c in node.children])
        if hit and node.description:
            out.append(f"### {node.id} {node.name}\n{node.description}")
        return hit

    walk(root)
    return "\n\n".join(reversed(out))


def outline(root: Node) -> str:
    """Compact overview of the whole product for planning."""
    lines = [f"# {root.name}", root.description, ""]

    def walk(node: Node, depth: int) -> None:
        for child in node.children:
            if child.type == "ATOMIC":
                lines.append(f"{'  ' * depth}- {child.id} {child.name} ({len(child.scenarios)} tests)")
            else:
                lines.append(f"{'  ' * depth}- {child.id} {child.name}")
                if child.description:  # group-level rules apply to every requirement below them
                    lines.append(f"{'  ' * (depth + 1)}{' '.join(child.description.split())}")
                walk(child, depth + 1)

    walk(root, 0)
    return "\n".join(lines)


SEED = re.compile(r"(?:The evaluation seed contains|The seeded data is|Seed values:)\s*(.+?)(?:\.\s|$)", re.S)


def seed_facts(root: Node) -> str:
    """Distinct seed statements from scenario preconditions, with the requirements that use them."""
    facts: dict[str, list[str]] = {}
    for atomic in root.atomics:
        for scenario in atomic.scenarios:
            for step in scenario.get("steps") or []:
                if step.get("keyword") != "GIVEN":
                    continue
                for match in SEED.findall(step.get("content", "")):
                    text = " ".join(match.split()).rstrip(".")
                    ids = facts.setdefault(text, [])
                    if atomic.id not in ids:
                        ids.append(atomic.id)
    return "\n".join(f"- {text} (used by {', '.join(ids)})" for text, ids in facts.items())
