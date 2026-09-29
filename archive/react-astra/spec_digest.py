"""Requirement digest for the lean agent.

Loads the requirement tree, groups ATOMIC requirements into work units and renders
the compact text the coding model reads: a product overview, per-unit spec text,
pre-existing (seed) data facts and the exact UI strings of every unit.

Nothing here is task specific: every name and value is taken verbatim from the
requirement files at runtime. Text is never paraphrased, only filtered:
image/reference lines are removed and repeated sentences are dropped.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

import yaml

OVERVIEW_BUDGET = 14_000
UNIT_BUDGET = 24_000
SEED_BUDGET = 12_000
MERGE_LIMIT = 4

REQUIREMENT_FILES = ("requirements.yaml", "requirements.yml", "requirement.yaml",
                     "requirement.yml", "requirement.txt")
_EMBEDDED_KEYS = ("requirements_yaml", "requirement_yaml", "requirements_yml")
_TYPES = {"ATOMIC", "FOLDER", "COMPOSITE"}
_SKIP_KEYS = {"scenarios", "steps", "dependencies", "visual_reference"}
_CHILD_KEYS = {"children", "subrequirements", "sub_requirements", "requirements"}

# --------------------------------------------------------------------------- text helpers

_INLINE_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_IMAGE_WORDS = r"(?:reference|references|image|images|screenshot|screenshots|mockup|mockups|diagram|figure)"
# A short label that introduces an image, e.g. "Page reference:", "Dropdown image:", "Reference image".
_IMAGE_LABEL = re.compile(
    r"(?:^|(?<=[.;!?])\s+)((?:[^\s.;:!?]+\s+){0,4}?" + _IMAGE_WORDS
    + r"(?:\s+(?:for|of)\s+[^\s.;:!?]+(?:\s+[^\s.;:!?]+){0,2}|\s+" + _IMAGE_WORDS + r")?\s*:?\s*)$", re.I)
_REFERENCE_LINE = re.compile(
    r"^(?:[^\s.;:!?]+\s+){0,4}?" + _IMAGE_WORDS
    + r"(?:\s+(?:for|of)\s+[^\s.;:!?]+(?:\s+[^\s.;:!?]+){0,2}|\s+" + _IMAGE_WORDS + r")?\s*:$", re.I)
_ABBREVIATIONS = {"e.g", "i.e", "etc", "vs", "mr", "mrs", "ms", "dr", "no", "fig", "approx",
                  "incl", "cf", "st", "eg", "ie"}
_SENTENCE_END = re.compile(r"([.!?]+)([”\"’'`)\]]*)(\s+)(?=[A-Z0-9“\"‘'`(\[*_<-])")
_SEED_VALUES = re.compile(r"^seed values?\s*:", re.I)
_BACKTICK = re.compile(r"`([^`\n]+)`")
_QUOTED = re.compile(r"“([^“”\n]{1,200}?)”|\"([^\"\n]{1,200}?)\"|‘([^‘’\n]{2,200}?)’")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_as_text(item) for item in value)
    if isinstance(value, dict):
        return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).rstrip()
    return str(value)


def _clean_text(text: Any) -> str:
    """Verbatim text minus image markdown / "Page reference:" lines, whitespace normalised."""
    raw = _as_text(text).replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for line in raw.split("\n"):
        had_image = bool(_INLINE_IMAGE.search(line))
        if had_image:
            pieces = _INLINE_IMAGE.split(line)
            kept = []
            for number, piece in enumerate(pieces):
                if number < len(pieces) - 1:  # text before an image: drop its trailing label
                    piece = _IMAGE_LABEL.sub("", piece)
                kept.append(piece)
            line = " ".join(kept)
        line = re.sub(r"[ \t ]+", " ", line).strip()
        if had_image and not line:
            while lines and not lines[-1]:
                lines.pop()
            if lines and _REFERENCE_LINE.match(lines[-1]):
                lines.pop()  # "Screenshot reference:" on the line above the image
            continue
        if _REFERENCE_LINE.match(line) and len(line) <= 40 and re.search(r"reference|screenshot", line, re.I):
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


_BLOCK_START = re.compile(r"^(?:[-*+>|#]|\d+[.)]\s)")


def _logical_lines(text: str) -> list[str]:
    """Lines with soft wraps joined: a plain line continues the previous plain line unless a
    blank line, list item, heading, table row or a label line ending in ":" intervenes."""
    lines: list[str] = []
    joinable = False
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            joinable = False
            continue
        if joinable and not _BLOCK_START.match(line):
            lines[-1] = f"{lines[-1]} {line}"
        else:
            lines.append(line)
        joinable = not line.endswith(":") and not re.match(r"^[#|]", line)
    return lines


def _split_sentences(text: str) -> list[str]:
    """Split on sentence ends outside quotes/backticks; soft-wrapped lines are joined first."""
    sentences: list[str] = []
    for line in _logical_lines(text):
        line = line.strip()
        if not line:
            continue
        start = 0
        for match in _SENTENCE_END.finditer(line):
            cut = match.end(2)
            head = line[:cut]
            word = re.search(r"([\w.]+)$", line[:match.start(1)])
            if word and word.group(1).lower().strip(".") in _ABBREVIATIONS:
                continue
            if head.count("`") % 2 or head.count("“") > head.count("”") or head.count('"') % 2:
                continue
            piece = line[start:cut].strip()
            if piece:
                sentences.append(piece)
            start = match.end()
        piece = line[start:].strip()
        if piece:
            sentences.append(piece)
    return sentences


def _sentence_key(sentence: str) -> str:
    key = re.sub(r"\s+", " ", sentence).strip()
    key = key.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return key.rstrip(" .;:,").strip()


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _backticked(text: str) -> list[str]:
    return [value.strip() for value in _BACKTICK.findall(text) if value.strip()]


def _quoted(text: str) -> list[str]:
    return [next(group for group in match.groups() if group is not None).strip()
            for match in _QUOTED.finditer(text)]


# --------------------------------------------------------------------------- loading

def _find_embedded(payload: Any, depth: int = 0) -> Any:
    if not isinstance(payload, dict) or depth > 2:
        return None
    for key in _EMBEDDED_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return yaml.safe_load(value)
        if isinstance(value, (dict, list)):
            return value
    for value in payload.values():
        found = _find_embedded(value, depth + 1)
        if found is not None:
            return found
    return None


def _parse_requirement_text(text: str) -> Any:
    payload: Any = None
    stripped = text.lstrip("﻿").strip()
    if stripped[:1] in "{[":
        try:
            payload = json.loads(stripped)
        except ValueError:
            payload = None
    if payload is None:
        try:
            payload = yaml.safe_load(stripped)
        except yaml.YAMLError:
            payload = None
    embedded = _find_embedded(payload)
    if embedded is not None:
        return embedded
    if isinstance(payload, (dict, list)):
        return payload
    for block in re.findall(r"```[ \t]*(?:ya?ml|json)?[ \t]*\n(.*?)```", text, re.S | re.I):
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if isinstance(data, (dict, list)):
            return _find_embedded(data) or data
    raise ValueError("no YAML/JSON requirement structure found")


def read_requirements_data(requirements_dir: Path) -> Any:
    """Parsed requirement document: requirements.yaml | .yml | requirement.yaml | requirement.txt
    (JSON/YAML, optionally with an embedded `requirements_yaml` string or a fenced YAML block)."""
    requirements_dir = Path(requirements_dir)
    errors: list[str] = []
    for name in REQUIREMENT_FILES:
        path = requirements_dir / name
        if not path.is_file():
            continue
        try:
            return _parse_requirement_text(path.read_text(encoding="utf-8", errors="replace"))
        except (ValueError, yaml.YAMLError) as exc:
            errors.append(f"{name}: {exc}")
    if errors:
        raise ValueError("unreadable requirement files: " + "; ".join(errors))
    raise FileNotFoundError(f"no requirements.yaml or requirement.txt in {requirements_dir}")


def _raw_id(value: dict) -> str:
    raw = value.get("req_id") or value.get("requirement_id") or value.get("id")
    return str(raw).strip() if raw is not None else ""


def _scenario_list(value: Any) -> list | None:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return None


def load_requirements(requirements_dir: Path) -> list[dict]:
    """Pre-order list of requirement nodes (see docs/lean-design.md)."""
    data = read_requirements_data(Path(requirements_dir))
    found: list[dict] = []
    by_id: dict[str, dict] = {}

    def visit(value: Any, parent_id: str | None, key_hint: str = "", in_children: bool = False) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item, parent_id, "", in_children)
            return
        if not isinstance(value, dict):
            return
        hinted = key_hint if key_hint.upper().startswith("REQ-") else ""
        node_id = _raw_id(value) or hinted
        kind = str(value.get("type") or "").strip().upper()
        looks = bool(value.get("req_id") or value.get("requirement_id")
                     or node_id.upper().startswith("REQ-") or kind in _TYPES
                     or (in_children and (node_id or value.get("name") or value.get("title"))))
        current = parent_id
        if looks:
            if not node_id:
                node_id = f"NODE-{len(found) + 1}"
            if node_id not in by_id:
                name = _as_text(value.get("name") or value.get("title") or value.get("label")
                                or node_id).strip()
                description = _as_text(value.get("description") or value.get("desc")
                                       or value.get("content") or value.get("requirement") or name)
                children = value.get("children") or value.get("children_ids")
                child_ids: list[str] = []
                if isinstance(children, list):
                    for child in children:
                        child_id = _raw_id(child) if isinstance(child, dict) else (
                            str(child).strip() if isinstance(child, (str, int)) else "")
                        if child_id:
                            child_ids.append(child_id)
                dependencies = value.get("dependencies")
                if isinstance(dependencies, str):
                    dependencies = [dependencies]
                declared_parent = value.get("parent_id") or value.get("parent")
                node = {
                    "id": node_id,
                    "name": name,
                    "type": kind if kind in _TYPES else "",
                    "description": description,
                    "scenarios": _scenario_list(value.get("scenarios")),
                    "parent_id": parent_id if parent_id is not None else (
                        str(declared_parent).strip() if isinstance(declared_parent, (str, int)) else None),
                    "children_ids": child_ids,
                    "dependencies": dependencies if isinstance(dependencies, list) else [],
                    "depth": 0,
                }
                found.append(node)
                by_id[node_id] = node
            current = node_id
        for key, child in value.items():
            if key in _SKIP_KEYS:
                continue
            if isinstance(child, (dict, list)):
                visit(child, current, str(key), looks and str(key) in _CHILD_KEYS)

    visit(data, None)
    if not found:
        raise ValueError("no recognizable requirement nodes")

    # Reconcile parent/child links declared either way, then order the tree pre-order.
    for node in found:
        if node["parent_id"] not in by_id or node["parent_id"] == node["id"]:
            node["parent_id"] = None
    for node in found:
        for child_id in node["children_ids"]:
            child = by_id.get(child_id)
            if child is not None and child["parent_id"] is None and child_id != node["id"]:
                child["parent_id"] = node["id"]
    for node in found:
        node["children_ids"] = [c for c in _unique(node["children_ids"])
                                if c in by_id and by_id[c]["parent_id"] == node["id"]]
    for node in found:
        parent = by_id.get(node["parent_id"]) if node["parent_id"] else None
        if parent is not None and node["id"] not in parent["children_ids"]:
            parent["children_ids"].append(node["id"])

    ordered: list[dict] = []
    placed: set[str] = set()

    def place(node: dict, depth: int) -> None:
        if node["id"] in placed:
            return
        placed.add(node["id"])
        node["depth"] = depth
        ordered.append(node)
        for child_id in node["children_ids"]:
            place(by_id[child_id], depth + 1)

    for node in found:
        if node["parent_id"] is None:
            place(node, 0)
    for node in found:  # parent cycles: keep them rather than lose them
        if node["id"] not in placed:
            node["parent_id"] = None
            place(node, 0)
    return ordered


# --------------------------------------------------------------------------- tree index

class _Index:
    def __init__(self, reqs: list[dict]):
        self.reqs = reqs
        self.by_id = {str(r["id"]): r for r in reqs}
        self.order = {str(r["id"]): i for i, r in enumerate(reqs)}
        self.children: dict[str, list[str]] = {rid: [] for rid in self.by_id}
        for r in reqs:
            parent = r.get("parent_id")
            if parent in self.children and r["id"] != parent:
                self.children[parent].append(str(r["id"]))
        for r in reqs:
            for child in r.get("children_ids") or []:
                if child in self.by_id and child not in self.children[str(r["id"])]:
                    self.children[str(r["id"])].append(child)

    def ancestors(self, node: dict) -> list[dict]:
        """Root first, excluding the node itself."""
        chain: list[dict] = []
        seen = {str(node["id"])}
        parent = node.get("parent_id")
        while parent in self.by_id and parent not in seen:
            seen.add(parent)
            chain.append(self.by_id[parent])
            parent = self.by_id[parent].get("parent_id")
        return list(reversed(chain))

    def depth(self, node: dict) -> int:
        value = node.get("depth")
        return value if isinstance(value, int) else len(self.ancestors(node))

    def level1(self, node: dict) -> str:
        chain = self.ancestors(node) + [node]
        return str(chain[1]["id"] if len(chain) > 1 else chain[0]["id"])

    def is_atomic(self, node: dict) -> bool:
        return str(node.get("type") or "").upper() == "ATOMIC"


# --------------------------------------------------------------------------- units

def _unit(idx: _Index, folder_ids: list[str], atomic_ids: list[str]) -> dict:
    folder_ids = _unique(folder_ids)
    names = [str(idx.by_id[f]["name"]) if f in idx.by_id else f for f in folder_ids]
    return {"id": folder_ids[0], "title": " + ".join(names), "folder_ids": folder_ids,
            "atomic_ids": sorted(_unique(atomic_ids), key=lambda a: idx.order.get(a, 0))}


def _dependency_ids(idx: _Index, node: dict) -> list[str]:
    """Declared dependencies; a folder stands for its leaf requirements (own ancestors skipped)."""
    ancestors = {str(a["id"]) for a in idx.ancestors(node)}
    found: list[str] = []
    visited: set[str] = set()
    for raw in node.get("dependencies") or []:
        if not isinstance(raw, (str, int)) or str(raw).strip() in ancestors:
            continue
        stack = [str(raw).strip()]
        while stack:
            current = stack.pop(0)
            if current in visited:
                continue
            visited.add(current)
            if idx.children.get(current):
                stack = idx.children[current] + stack
            else:
                found.append(current)
    return found


def _dependency_order(idx: _Index, groups: dict[str, list[str]]) -> dict[str, list[str]]:
    """Atomics that depend on an atomic of a later group in the same top-level module move to
    a new group right after the latest such group (all movers of one group together, keyed by
    the first mover's id). Cross-module dependencies never reorder. Repeated until stable; an
    atomic moves at most once, so dependency cycles terminate."""
    moved_once: set[str] = set()
    for _ in range(sum(len(ids) for ids in groups.values())):
        keys = list(groups)
        rank = {key: number for number, key in enumerate(keys)}
        home = {a: key for key, ids in groups.items() for a in ids}
        moved: dict[str, list[str]] = {}
        for key in keys:
            movers: list[str] = []
            anchors: list[str] = []
            for atomic_id in groups[key]:
                if atomic_id in moved_once:
                    continue
                level1 = idx.level1(idx.by_id[atomic_id])
                later = [home[d] for d in _dependency_ids(idx, idx.by_id[atomic_id])
                         if d in home and rank[home[d]] > rank[key]
                         and idx.level1(idx.by_id[d]) == level1]
                if later:
                    movers.append(atomic_id)
                    anchors.extend(later)
            if movers:
                groups[key] = [a for a in groups[key] if a not in movers]
                moved.setdefault(max(anchors, key=rank.get), []).extend(movers)
                moved_once.update(movers)
        if not moved:
            break
        rebuilt: dict[str, list[str]] = {}
        for key in keys:
            if groups[key]:
                rebuilt[key] = groups[key]
            if key in moved:
                ids = sorted(moved[key], key=lambda a: idx.order.get(a, 0))
                new_key = ids[0]
                while new_key in rebuilt or groups.get(new_key):  # unit ids must stay unique
                    new_key += "-after"
                rebuilt[new_key] = ids
        groups = rebuilt
    return groups


def build_units(reqs: list[dict], max_atomics: int = 5) -> list[dict]:
    """Group ATOMIC requirements by direct parent into implementation units (document order;
    an atomic needing a later group of its module is moved after that group)."""
    idx = _Index(reqs)
    max_atomics = max(1, int(max_atomics))
    atomics = [r for r in reqs if idx.is_atomic(r)]
    if not atomics:
        atomics = [r for r in reqs if not idx.children.get(str(r["id"]))]
    groups: dict[str, list[str]] = {}
    for atomic in atomics:
        parent = atomic.get("parent_id")
        folder = parent if parent in idx.by_id else str(atomic["id"])
        groups.setdefault(folder, []).append(str(atomic["id"]))
    groups = _dependency_order(idx, groups)

    pending = [(_unit(idx, [folder], ids), idx.level1(idx.by_id.get(folder) or idx.by_id[ids[0]]))
               for folder, ids in groups.items()]
    limit = min(MERGE_LIMIT, max_atomics)
    merged: list[tuple[dict, str]] = []
    position = 0
    while position < len(pending):
        unit, level1 = pending[position]
        if len(unit["atomic_ids"]) == 1:
            if position + 1 < len(pending):
                following, following_level1 = pending[position + 1]
                if following_level1 == level1 and len(following["atomic_ids"]) + 1 <= limit:
                    pending[position + 1] = (_unit(idx, unit["folder_ids"] + following["folder_ids"],
                                                   unit["atomic_ids"] + following["atomic_ids"]), level1)
                    position += 1
                    continue
            if merged and merged[-1][1] == level1 and len(merged[-1][0]["atomic_ids"]) + 1 <= limit:
                previous = merged[-1][0]
                merged[-1] = (_unit(idx, previous["folder_ids"] + unit["folder_ids"],
                                    previous["atomic_ids"] + unit["atomic_ids"]), level1)
                position += 1
                continue
        merged.append((unit, level1))
        position += 1

    units: list[dict] = []
    for unit, _level1 in merged:
        atomic_ids = unit["atomic_ids"]
        if len(atomic_ids) <= max_atomics:
            units.append(unit)
            continue
        parts = -(-len(atomic_ids) // max_atomics)
        sizes = [len(atomic_ids) // parts + (1 if i < len(atomic_ids) % parts else 0) for i in range(parts)]
        start = 0
        for number, size in enumerate(sizes, 1):
            chunk = atomic_ids[start:start + size]
            start += size
            parents = {idx.by_id[a].get("parent_id") or a for a in chunk}
            folders = [f for f in unit["folder_ids"] if f in parents] or unit["folder_ids"][:1]
            part = _unit(idx, folders, chunk)
            part["id"] = f"{unit['id']}-part{number}"
            part["title"] = f"{part['title']} (part {number}/{parts})"
            units.append(part)
    return units


def _unit_label(number: int) -> str:
    return f"U{number:02d}"


# --------------------------------------------------------------------------- overview

def _truncate_head(text: str, limit: int, marker: str) -> str:
    if len(text) <= limit:
        return text
    if limit <= 0:
        return marker.strip()
    head = text[:limit]
    cut = max(head.rfind(". "), head.rfind(".\n"))
    if cut < limit * 0.6:
        cut = head.rfind(" ")
    else:
        cut += 1
    if cut <= 0:
        cut = limit
    return head[:cut].rstrip() + marker


def _overview(reqs: list[dict]) -> tuple[str, set[str]]:
    """Overview text plus the ids whose descriptions were truncated in it."""
    idx = _Index(reqs)
    units = build_units(reqs)
    sections: list[tuple[str, str, str, int]] = []  # header, description, id, depth
    for node in reqs:
        depth = idx.depth(node)
        if depth == 0 or (depth == 1 and idx.children.get(str(node["id"]))):
            description = _clean_text(node.get("description"))
            if description.strip() == str(node.get("name", "")).strip():
                description = ""
            header = f"{'##' if depth == 0 else '###'} {node['id']} {node.get('name', '')}".rstrip()
            sections.append((header, description, str(node["id"]), depth))
    outline = ["## Work units (implemented in this order)"]
    for number, unit in enumerate(units, 1):
        names = ", ".join(f"{a} {idx.by_id[a].get('name', '')}".rstrip()
                          for a in unit["atomic_ids"] if a in idx.by_id)
        outline.append(f"- {_unit_label(number)} {unit['id']} {unit['title']}: {names}")
    outline_text = "\n".join(outline)

    def render(descriptions: list[str]) -> str:
        blocks = [f"{header}\n{text}" if text else header
                  for (header, _d, _i, _depth), text in zip(sections, descriptions)]
        return "\n\n".join(blocks + [outline_text])

    original = [description for _h, description, _i, _d in sections]
    original_text = render(original)
    if len(original_text) <= OVERVIEW_BUDGET:
        return original_text, set()
    marker = " […truncated here; the full text is repeated in the unit specs]"
    # Truncate depth-1 descriptions first (units repeat them in full); roots only if unavoidable.
    text, truncated = original_text, set()
    for eligible_depths in ({1}, {0, 1}):
        eligible = {i for i, s in enumerate(sections) if s[3] in eligible_depths and original[i]}
        if not eligible:
            continue

        def attempt(ratio: float) -> list[str]:
            return [(_truncate_head(d, int(len(d) * ratio), marker) if i in eligible else d)
                    for i, d in enumerate(original)]

        best = attempt(0.0)
        low, high = 0.0, 1.0
        for _ in range(24):  # largest proportional share that still fits the budget
            middle = (low + high) / 2
            candidate = attempt(middle)
            if len(render(candidate)) <= OVERVIEW_BUDGET:
                best, low = candidate, middle
            else:
                high = middle
        text = render(best)
        truncated = {sections[i][2] for i, d in enumerate(best) if d != original[i]}
        if len(text) <= OVERVIEW_BUDGET:
            return text, truncated
    return text, truncated


def overview_markdown(reqs: list[dict]) -> str:
    """ROOT + depth-1 folder descriptions (verbatim) followed by the unit outline."""
    return _overview(reqs)[0]


# --------------------------------------------------------------------------- unit text

def _scenario_steps(scenario: Any) -> list[tuple[str, str]]:
    if not isinstance(scenario, dict):
        return [("", _as_text(scenario))]
    steps: list[tuple[str, str]] = []
    for step in scenario.get("steps") or []:
        if isinstance(step, dict):
            keyword = str(step.get("keyword") or step.get("type") or "").strip().upper()
            steps.append((keyword, _as_text(step.get("content") or step.get("text") or "")))
        else:
            steps.append(("", _as_text(step)))
    for key in ("given", "when", "then", "and", "but"):
        for field in (key, key.upper(), key.capitalize()):
            if field in scenario:
                values = scenario[field] if isinstance(scenario[field], list) else [scenario[field]]
                steps.extend((key.upper(), _as_text(value)) for value in values)
                break
    if not steps and scenario.get("name"):
        steps.append(("", _as_text(scenario.get("name"))))
    return steps


def _scenario_lines(scenarios: list | None, seen: set[str]) -> tuple[list[str], list[int]]:
    lines: list[str] = []
    repeated: list[int] = []
    for number, scenario in enumerate(scenarios or [], 1):
        emitted = False
        for keyword, content in _scenario_steps(scenario):
            kept = []
            for sentence in _split_sentences(_clean_text(content)):
                if _SEED_VALUES.match(sentence):
                    continue
                key = _sentence_key(sentence)
                if not key or key in seen:
                    continue
                seen.add(key)
                kept.append(sentence)
            if kept:
                label = f"S{number} {keyword}".rstrip()
                lines.append(f"- {label}: {' '.join(kept)}")
                emitted = True
        if not emitted:
            repeated.append(number)
    return lines, repeated


def _mark_seen(text: str, seen: set[str]) -> None:
    for sentence in _split_sentences(text):
        key = _sentence_key(sentence)
        if key:
            seen.add(key)


_NOTE_LIMIT = 1_200


def _dependents_note(reqs: list[dict], idx: _Index, unit: dict) -> str:
    """Atomics of earlier units whose dependencies point into this unit (cross-module
    dependencies are not reordered, so those atomics must be revisited here)."""
    own = [a for a in unit.get("atomic_ids", []) if a in idx.by_id]
    units = build_units(reqs)
    position = next((n for n, u in enumerate(units) if set(u["atomic_ids"]) & set(own)), 0)
    entries: list[str] = []
    for earlier in units[:position]:
        for atomic_id in earlier["atomic_ids"]:
            if atomic_id in own or atomic_id not in idx.by_id:
                continue
            targets = [d for d in _dependency_ids(idx, idx.by_id[atomic_id]) if d in own]
            if targets:
                name = idx.by_id[atomic_id].get("name", "")
                entries.append(f"- {atomic_id} {name} (depends on {', '.join(targets)})")
    if not entries:
        return ""
    lines = ["Earlier requirements that depend on this unit (re-check them now):"]
    for number, entry in enumerate(entries):
        if len("\n".join(lines + [entry])) > _NOTE_LIMIT:
            lines.append(f"- ({len(entries) - number} more)")
            break
        lines.append(entry)
    return "\n".join(lines)


def unit_markdown(reqs: list[dict], unit: dict, seen_sentences: set[str] | None = None) -> str:
    """Spec text of one unit. `seen_sentences` (updated in place) holds sentence keys the
    reader already has (e.g. from the overview); scenario sentences in it are dropped."""
    idx = _Index(reqs)
    seen = seen_sentences if seen_sentences is not None else set()
    _overview_text, truncated_in_overview = _overview(reqs)
    atomics = [idx.by_id[a] for a in unit.get("atomic_ids", []) if a in idx.by_id]

    modules = []
    for atomic in atomics:
        chain = idx.ancestors(atomic)
        module = next((n for n in chain if idx.depth(n) == 1), None)
        if module is not None and module not in modules:
            modules.append(module)
    header = [f"# Unit {unit.get('id', '')}: {unit.get('title', '')}".rstrip()]
    for module in modules:
        where = ("full description below" if module["id"] in truncated_in_overview
                 else "its description is in the product overview")
        header.append(f"Module: {module['id']} {module.get('name', '')} ({where})")
    header.append("Requirements in this unit: " + ", ".join(str(a["id"]) for a in atomics))

    blocks: list[Any] = ["\n".join(header)]  # str blocks or dict blocks for atomics
    emitted_folders: set[str] = set()
    for atomic in atomics:
        for ancestor in idx.ancestors(atomic):
            ancestor_id = str(ancestor["id"])
            depth = idx.depth(ancestor)
            if ancestor_id in emitted_folders:
                continue
            if depth >= 2 or ancestor_id in truncated_in_overview:
                emitted_folders.add(ancestor_id)
                description = _clean_text(ancestor.get("description"))
                _mark_seen(description, seen)
                blocks.append(f"## {ancestor_id} {ancestor.get('name', '')}\n{description}".rstrip())
        head = [f"### {atomic['id']} {atomic.get('name', '')}".rstrip()]
        dependencies = [str(d) for d in atomic.get("dependencies") or [] if isinstance(d, (str, int))]
        if dependencies:
            head.append("Depends on: " + ", ".join(
                f"{d} ({idx.by_id[d].get('name', '')})" if d in idx.by_id else d for d in dependencies))
        description = _clean_text(atomic.get("description"))
        if description:
            head.append(description)
        _mark_seen(description, seen)
        lines, repeated = _scenario_lines(atomic.get("scenarios"), seen)
        blocks.append({"head": "\n".join(head), "lines": lines, "repeated": repeated, "omitted": 0})
    note = _dependents_note(reqs, idx, unit)
    if note:
        blocks.append(note)

    def render_atomic(block: dict) -> str:
        parts = [block["head"]]
        if block["lines"] or block["repeated"] or block["omitted"]:
            parts.append("")
            parts.append("Scenarios:")
            parts.extend(block["lines"])
            if block["omitted"]:
                parts.append(f"({block['omitted']} further scenario lines omitted for length)")
            if block["repeated"]:
                numbers = ", ".join(str(n) for n in block["repeated"])
                noun = "Scenario" if len(block["repeated"]) == 1 else "Scenarios"
                verb = "repeats" if len(block["repeated"]) == 1 else "repeat"
                parts.append(f"({noun} {numbers} {verb} the text above.)")
        return "\n".join(parts)

    def render() -> str:
        return "\n\n".join(render_atomic(b) if isinstance(b, dict) else b for b in blocks).strip() + "\n"

    text = render()
    while len(text) > UNIT_BUDGET:
        candidates = [b for b in blocks if isinstance(b, dict) and b["lines"]]
        if not candidates:
            break
        longest = max(candidates, key=lambda b: len(render_atomic(b)))
        longest["lines"].pop()
        longest["omitted"] += 1
        text = render()
    return text


# --------------------------------------------------------------------------- seed facts

_SEED_MARKERS = re.compile(
    r"seed|pre-?existing|\bexisting\b[^.;:]{0,60}?\b(?:named|called|titled)\b"
    r"|\b(?:contains?|containing|includes?|has|have)\b[^.;:]{0,60}?\b(?:named|called|titled)\s+`"
    r"|\binitially (?:contains?|has|have|holds?|includes?|lists?)\b"
    r"|\b(?:is|are|was|were) signed in as\b|\bsigns? in as\b|\bpredefined\b"
    r"|\bpre-?populated\b|\bpre-?loaded\b|\b(?:system|database) (?:already )?contains\b", re.I)
_ALREADY_EXISTS = re.compile(r"\balready[ -]exist", re.I)
_CONDITIONAL = re.compile(r"\b(?:if|when|unless|whether|whenever)\b", re.I)
_QUOTED_SPAN = re.compile(r"“[^“”]*”|\"[^\"\n]*\"")
_NOT_PRE_EXISTING = re.compile(
    r"\b(?:does|do|did|must|should|will|may) not(?: yet)? (?:exist|be used|appear)|\bdoesn't exist"
    r"|\bnot yet\b|\bunused\b|\babsent\b|\bcandidate\b|\bno such\b|\bunknown\b|\binvalid\b"
    r"|\benters?\b|\btypes?\b|\bwill be created\b", re.I)


def _is_seed_sentence(sentence: str) -> bool:
    if _SEED_VALUES.match(sentence):
        return True
    plain = _QUOTED_SPAN.sub("“”", sentence)  # UI messages such as “Name already exists” are not facts
    if _SEED_MARKERS.search(plain):
        return True
    for match in _ALREADY_EXISTS.finditer(plain):
        if not _CONDITIONAL.search(plain[:match.start()]):
            return True
    return False


def _seed_candidates(reqs: list[dict]) -> list[tuple[str, str, str, str]]:
    """(group id, source req id, sentence, origin) in document order.
    origin: "description", "scenario", or "given" (a GIVEN-step sentence that only names values)."""
    idx = _Index(reqs)
    out: list[tuple[str, str, str, str]] = []
    for node in reqs:
        group = idx.level1(node)
        texts = [(_clean_text(node.get("description")), "description")]
        for scenario in node.get("scenarios") or []:
            main = ""
            for keyword, content in _scenario_steps(scenario):
                if keyword not in ("AND", "BUT", ""):
                    main = keyword
                texts.append((_clean_text(content), "given" if main == "GIVEN" else "scenario"))
        for text, origin in texts:
            for sentence in _split_sentences(text):
                if _is_seed_sentence(sentence):
                    out.append((group, str(node["id"]), sentence, "scenario" if origin == "given" else origin))
                elif origin == "given" and _backticked(sentence) and not _NOT_PRE_EXISTING.search(sentence):
                    out.append((group, str(node["id"]), sentence, "given"))
    return out


def seed_facts(reqs: list[dict]) -> str:
    """Verbatim, deduplicated sentences about pre-existing data grouped by top-level module."""
    idx = _Index(reqs)
    seen_keys: set[str] = set()
    seen_values: set[str] = set()
    kept: list[tuple[str, str, str]] = []
    for group, source, sentence, origin in _seed_candidates(reqs):
        key = _sentence_key(sentence)
        if not key or key in seen_keys:
            continue
        values = [v for v in (_backticked(sentence) or _quoted(sentence)) if "<" not in v]
        if origin != "description" and values and all(v in seen_values for v in values):
            continue  # a repeated scenario template restating already listed values
        if origin == "given" and not values:
            continue
        seen_keys.add(key)
        seen_values.update(_backticked(sentence))
        seen_values.update(_quoted(sentence))
        kept.append((group, f"{source} GIVEN" if origin == "given" else source, sentence))
    if not kept:
        return "No requirement sentence describes pre-existing data.\n"

    intro = ("Verbatim requirement sentences about pre-existing data, grouped by module "
             "([id] = source requirement; [id GIVEN] = a scenario precondition naming data that "
             "must already exist). Seed every record they state exists, with exactly these names "
             "and values.")

    def render(count: int) -> str:
        lines = [intro]
        listed: set[str] = set()
        current = None
        group_values: list[str] = []

        def flush() -> None:
            if group_values:
                lines.append("Values: " + ", ".join(f"`{v}`" for v in group_values))

        for group, source, sentence in kept[:count]:
            if group != current:
                flush()
                group_values = []
                current = group
                node = idx.by_id.get(group, {})
                lines.append("")
                lines.append(f"## {group} {node.get('name', '')}".rstrip())
            lines.append(f"- [{source}] {sentence}")
            for value in _backticked(sentence):
                if value not in listed:
                    listed.add(value)
                    group_values.append(value)
        flush()
        if count < len(kept):
            lines.append("(truncated)")
        return "\n".join(lines) + "\n"

    count = len(kept)
    text = render(count)
    while len(text) > SEED_BUDGET and count > 0:
        count -= 1
        text = render(count)
    return text


# --------------------------------------------------------------------------- UI strings

_UI_KEYWORDS = re.compile(
    r"\b(?:named|labeled|labelled|button|buttons|link|links|heading|headings|tab|tabs|menu|menus"
    r"|menuitem|option|options|title|titled|text|message|messages|displays|display|displayed|shows"
    r"|show|shown|reads|column|columns|header|headers|placeholder|label|labels|checkbox|dialog"
    r"|status|alert|region|caption|badge|prompt|aria-label|called|contains|contain"
    r"|click|clicks|clicking|clicked|activate|activates|activating|press|presses|choose|chooses"
    r"|select|selects|check|checks|uncheck|unchecks|toggle|toggles|textbox|searchbox|combobox"
    r"|field|error|errors|tooltip|toast|notice|reject|rejects|rejected|warning|warns"
    r"|notification|marker|icon|entry|selector)\b", re.I)
_UI_NOUN_AFTER = re.compile(
    r"^\s*(?:button|link|tab|page|dialog|menu|menu item|menuitem|option|heading|checkbox|field|textbox"
    r"|searchbox|combobox|column|section|panel|label|toggle|message|error|region|toolbar|badge"
    r"|control|entry point|filter|radio|marker|icon|input|selector"
    r"|(?:is |are )?(?:clicked|pressed|activated|selected|shown|displayed|visible|enabled|disabled))\b",
    re.I)
_LIST_GAP = re.compile(r"^(?:[\s,;/→>+&-]|\bor\b|\band\b|\bnor\b|\beither\b|\bthen\b)*$", re.I)
_CELL_REF = re.compile(r"^\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?$")
_EMAIL = re.compile(r"(?:^|[\s<(])[\w.+-]*@[\w-]+(?:\.[\w-]+)+")
_IMAGE_FILE = re.compile(r"\.(?:png|jpe?g|gif|svg|webp|ico|bmp)$", re.I)


def _acceptable_ui_string(value: str) -> bool:
    if not value or not re.search(r"[^\W_]", value):
        return False
    if "<" in value or ">" in value or len(value) > 60 or len(value.split()) > 8:
        return False
    if _EMAIL.search(value) or value.startswith("@"):
        return False
    if re.match(r"(?:https?://|www\.)", value, re.I) or "://" in value:
        return False
    if re.fullmatch(r"[\d\s.,:%+\-/$€£()]+", value):
        return False
    if _CELL_REF.match(value) or (value.startswith("=") and len(value) > 1):
        return False
    if _IMAGE_FILE.search(value):
        return False
    return True


def _strings_in_text(text: str) -> list[str]:
    found: list[str] = []
    previous_end = -1
    previous_ok = False
    for match in _QUOTED.finditer(text):
        value = re.sub(r"\s+", " ", next(g for g in match.groups() if g is not None)).strip()
        start = match.start()
        window_start = max(start - 48, previous_end if previous_end >= 0 else 0)
        window = text[window_start:start]
        boundary = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
        if boundary >= 0:
            window = window[boundary + 2:]
        attribute = text[max(0, start - 1):start] == "="
        continued = (previous_end >= 0 and start - previous_end <= 48 and previous_ok
                     and _LIST_GAP.match(text[previous_end:start]) is not None)
        accepted = not attribute and (continued or bool(_UI_KEYWORDS.search(window))
                                      or bool(_UI_NOUN_AFTER.match(text[match.end():match.end() + 24])))
        previous_end = match.end()
        previous_ok = accepted
        if accepted and _acceptable_ui_string(value):
            found.append(value)
    return found


def ui_strings(reqs: list[dict], atomic_ids: list[str]) -> list[str]:
    """Exact quoted UI strings (labels, button names, messages) of the given atomics."""
    idx = _Index(reqs)
    texts: list[str] = []
    emitted_folders: set[str] = set()
    for atomic_id in atomic_ids:
        node = idx.by_id.get(atomic_id)
        if node is None:
            continue
        for ancestor in idx.ancestors(node):  # unit-level folder text (below the module level)
            if idx.depth(ancestor) >= 2 and ancestor["id"] not in emitted_folders:
                emitted_folders.add(ancestor["id"])
                texts.append(_clean_text(ancestor.get("description")))
        texts.append(_clean_text(node.get("description")))
        for scenario in node.get("scenarios") or []:
            texts.extend(_clean_text(content) for _k, content in _scenario_steps(scenario))
    strings: list[str] = []
    for text in texts:
        for line in text.split("\n"):
            strings.extend(_strings_in_text(line))
    return _unique(strings)


# --------------------------------------------------------------------------- digest

_SPREADSHEET = re.compile(r"spreadsheet|worksheet|gridcell|formula", re.I)
_AUTH = re.compile(r"sign in|sign-in|password|log in|login", re.I)


def _all_text(reqs: list[dict]) -> str:
    parts: list[str] = []
    for node in reqs:
        parts.append(str(node.get("name", "")))
        parts.append(_as_text(node.get("description")))
        for scenario in node.get("scenarios") or []:
            if isinstance(scenario, dict):
                parts.append(_as_text(scenario.get("name")))
            parts.extend(content for _k, content in _scenario_steps(scenario))
    return "\n".join(parts)


def _safe_name(value: str) -> str:
    return re.sub(r"[^\w.-]+", "_", value).strip("_") or "unit"


def build_digest(requirements_dir: Path, arc_dir: Path) -> dict:
    """Load the requirements and write arc_dir/spec/{overview.md, seed.md, units.json,
    units/<NN>-<unit id>.md, ui-strings.json}."""
    reqs = load_requirements(Path(requirements_dir))
    units = build_units(reqs)
    overview = overview_markdown(reqs)
    seed = seed_facts(reqs)
    overview_seen: set[str] = set()
    for line in overview.split("\n"):
        if not line.startswith(("#", "- U")):
            _mark_seen(line, overview_seen)
    unit_text: dict[str, str] = {}
    unit_strings: dict[str, list[str]] = {}
    for unit in units:
        unit_text[unit["id"]] = unit_markdown(reqs, unit, set(overview_seen))
        unit_strings[unit["id"]] = ui_strings(reqs, unit["atomic_ids"])
    text = _all_text(reqs)
    domain = {"spreadsheet": bool(_SPREADSHEET.search(text)), "auth": bool(_AUTH.search(text))}

    spec_dir = Path(arc_dir) / "spec"
    units_dir = spec_dir / "units"
    units_dir.mkdir(parents=True, exist_ok=True)
    for stale in units_dir.glob("*.md"):
        stale.unlink()
    (spec_dir / "overview.md").write_text(overview, encoding="utf-8")
    (spec_dir / "seed.md").write_text(seed, encoding="utf-8")
    (spec_dir / "units.json").write_text(json.dumps(units, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    for number, unit in enumerate(units, 1):
        (units_dir / f"{number:02d}-{_safe_name(unit['id'])}.md").write_text(
            unit_text[unit["id"]], encoding="utf-8")
    (spec_dir / "ui-strings.json").write_text(
        json.dumps(unit_strings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"reqs": reqs, "units": units, "overview": overview, "seed": seed,
            "unit_text": unit_text, "unit_strings": unit_strings, "domain": domain}
