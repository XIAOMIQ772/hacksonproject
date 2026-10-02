"""Requirement tree loading, requirement cards and the product outline."""
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


def quoted_names(text: str) -> list[str]:
    return list(dict.fromkeys(QUOTED.findall(text)))


SENTENCE = re.compile(r"(?<=\.)\s+|(?<=。)\s*")  # "README.md" and "v1.0" are not sentence ends
BOILERPLATE_SHARE = 0.2  # a sentence in this share of all scenarios is template text, stated once in the outline


def sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE.split(text) if part.strip()]


def boilerplate(root: Node) -> list[str]:
    """Long sentences that recur in many scenarios of the product (template text such as the fresh browser
    session), in order of first appearance. Sentences with a quoted or backticked value (seed data, names)
    stay with each requirement."""
    scenarios = [sc for a in root.atomics for sc in a.scenarios]
    counts: dict[str, int] = {}
    for scenario in scenarios:
        for sentence in {t for step in scenario.get("steps") or [] for t in sentences(step.get("content", ""))}:
            counts[sentence] = counts.get(sentence, 0) + 1
    return [t for t, n in counts.items() if len(t) > 40 and not re.search(r"[`\"“”]", t)
            and n >= max(2, BOILERPLATE_SHARE * len(scenarios))]


def _scenarios(atomic: Node, common: frozenset[str] = frozenset()) -> str:
    """The scenarios without the product-wide template sentences and without sentences an earlier step of this
    requirement already stated; every other sentence (values, seed data, expected results) is kept verbatim."""
    seen: set[str] = set()
    parts = []
    for number, scenario in enumerate(atomic.scenarios, 1):
        lines = []
        for step in scenario.get("steps") or []:
            kept = [t for t in sentences(step.get("content", "")) if t not in common and t not in seen]
            seen.update(kept)
            if kept:
                lines.append(f"    {step.get('keyword', '')} {' '.join(kept)}")
        parts.append(f"  Scenario {number}:\n" + ("\n".join(lines) or "    (same as above)"))
    return "\n".join(parts)


def images(text: str) -> list[str]:
    return list(dict.fromkeys(IMAGE.findall(text)))


def card(atomic: Node, base: str = "", common: frozenset[str] = frozenset()) -> str:
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
        lines.append(_scenarios(atomic, common))
    return "\n".join(lines)


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
    common = boilerplate(root)
    if common:
        lines += ["", "Every acceptance scenario also states the following; requirement cards omit it:",
                  *(f"- {t}" for t in common)]
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
