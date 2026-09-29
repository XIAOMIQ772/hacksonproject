"""Read the supplied public requirements and preserve their source structure."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any
import yaml


def read_requirements_data(requirements_dir: Path) -> Any:
    yaml_path = requirements_dir / "requirements.yaml"
    if yaml_path.is_file():
        return yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    json_path = requirements_dir / "requirement.txt"
    if json_path.is_file():
        payload = yaml.safe_load(json_path.read_text(encoding="utf-8"))
        embedded = payload.get("requirements_yaml") if isinstance(payload, dict) else None
        return yaml.safe_load(embedded) if embedded else payload

    raise FileNotFoundError(f"no requirements.yaml or requirement.txt in {requirements_dir}")


def load_requirements(requirements_dir: Path) -> list[dict[str, Any]]:
    data = read_requirements_data(requirements_dir)

    requirements: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(value: Any, parent_id: str | None = None, key_hint: str = "") -> None:
        if isinstance(value, list):
            for item in value:
                visit(item, parent_id)
            return
        if not isinstance(value, dict):
            return

        hinted_id = key_hint if key_hint.upper().startswith("REQ-") else ""
        raw_id = value.get("req_id") or value.get("requirement_id") or value.get("id") or hinted_id
        node_id = str(raw_id or "").strip()
        looks_like_requirement = bool(
            value.get("req_id")
            or value.get("requirement_id")
            or node_id.upper().startswith("REQ-")
            or str(value.get("type", "")).upper() in {"ATOMIC", "COMPOSITE", "FOLDER"}
        )

        current_parent = parent_id
        if looks_like_requirement:
            if not node_id:
                node_id = f"REQ-{len(requirements) + 1}"
            name = str(value.get("name") or value.get("title") or value.get("label") or node_id)
            description = str(
                value.get("description") or value.get("desc")
                or value.get("content") or value.get("requirement") or name
            )
            scenarios = value.get("scenarios")
            dependencies = value.get("dependencies")
            children = value.get("children") or value.get("children_ids")
            child_ids = [
                str(child.get("req_id") or child.get("requirement_id") or child.get("id"))
                for child in children
                if isinstance(child, dict) and (child.get("req_id") or child.get("requirement_id") or child.get("id"))
            ] if isinstance(children, list) else []
            if node_id not in seen:
                requirements.append({
                    "id": node_id,
                    "name": name,
                    "description": description,
                    "scenarios": scenarios if isinstance(scenarios, list) else None,
                    "parent_id": parent_id,
                    "children_ids": child_ids,
                    "dependencies": dependencies if isinstance(dependencies, list) else [],
                    "type": value.get("type", ""),
                    "details": {key: child for key, child in value.items()
                                if key not in {"children", "children_ids"}},
                })
                seen.add(node_id)
            current_parent = node_id

        for key, child in value.items():
            if key in {"scenarios", "steps", "dependencies", "visual_reference"}:
                continue
            if isinstance(child, (dict, list)):
                visit(child, current_parent, str(key))

    visit(data)
    if not requirements:
        raise ValueError("no recognizable requirement nodes")
    return requirements


def build_fixture_inventory(requirements: list[dict[str, Any]]) -> str:
    """Preserve source context and distinguish preconditions from actions/results.

    This is a review aid, not an entity extractor or a database schema. Quoted
    buttons, newly created names, and requirement parents are not seed records.
    """
    rows = [
        '# Data preconditions and scenario transitions', '',
        'Review source passages below. Only explicitly pre-existing records belong '
        'in seed data. Descriptions may mix initial state and actions; interpret them '
        'in context. Never seed action inputs, expected new records, or UI labels. '
        'Requirement hierarchy does not imply a database relationship.', '',
    ]
    for req in requirements:
        rows.extend([f"## {req['id']} {req['name']}",
                     '### Description (review in context)',
                     str(req.get('description', ''))])
        scenarios = req.get('scenarios') or req.get('details', {}).get('scenarios') or []
        for scenario in scenarios:
            if not isinstance(scenario, dict):
                rows.extend(['### Scenario (unclassified)', str(scenario)])
                continue
            rows.append('### Scenario: ' + str(scenario.get('name', '')))
            phase = ''
            for step in scenario.get('steps') or []:
                if not isinstance(step, dict):
                    rows.append('Unclassified: ' + str(step))
                    continue
                keyword = str(step.get('keyword', '')).upper()
                if keyword in {'GIVEN', 'WHEN', 'THEN'}:
                    phase = keyword
                elif keyword not in {'AND', 'BUT'}:
                    phase = ''
                label = {'GIVEN': 'Precondition (classify data vs UI state)',
                         'WHEN': 'Action/input (not a seed instruction)',
                         'THEN': 'Expected result (not a seed instruction)'}.get(phase, 'Unclassified')
                rows.append(label + ': ' + yaml.safe_dump(step, allow_unicode=True, sort_keys=False).strip())
            other = {k: v for k, v in scenario.items() if k not in {'name', 'steps'}}
            if other:
                rows.append('Additional scenario fields (review in context):\n' +
                            yaml.safe_dump(other, allow_unicode=True, sort_keys=False))
        rows.append('')
    return '\n'.join(rows) + '\n'


def extract_fixture_manifest(requirements: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Extract a reviewable checklist for explicitly pre-existing records.

    This is deliberately limited to phrases that state existence. It does not
    turn every quoted UI label or action input into seed data.
    """
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    patterns = [
        re.compile(r"(?:system|database)\s+contains\s+(?:an?\s+)?([^,.;]+?)\s+named\s+[\"'`]([^\"'`]+)[\"'`]", re.I),
        re.compile(r"(?:existing|pre-existing|already\s+exists?)\s+(?:an?\s+)?([^,.;]+?)\s+named\s+[\"'`]([^\"'`]+)[\"'`]", re.I),
        re.compile(r"verified\s+account\s+with\s+nickname\s+[\"'`]([^\"'`]+)[\"'`]", re.I),
    ]
    for req in requirements:
        details = req.get('details', req)
        passages = [str(req.get('description', ''))]
        for scenario in details.get('scenarios') or []:
            if isinstance(scenario, dict):
                passages.extend(str(step.get('content', '')) for step in scenario.get('steps') or []
                                if isinstance(step, dict))
        for passage in passages:
            for index, pattern in enumerate(patterns):
                for match in pattern.finditer(passage):
                    if index == 2:
                        entity, name = 'account nickname', match.group(1)
                    else:
                        entity, name = match.group(1).strip(), match.group(2).strip()
                    key = (entity.lower(), name, req['id'])
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({'req_id': req['id'], 'entity': entity, 'name': name,
                                 'source': passage})
    return rows
