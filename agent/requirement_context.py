"""Lossless, per-requirement reading aids derived only from supplied requirements.

These files organize source evidence. They do not infer fixtures, routes, roles,
or relationships, and are not an independently authored test oracle.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import yaml


_REQ_REFERENCE = re.compile(r"(?<![\w-])REQ-\d+(?:[.-]\d+)*(?![\w-]|\.\d)")
_PLACEHOLDERS = (
    ("requested workflow", re.compile(r"\bthe requested workflow\b", re.I)),
    ("generic workflow action", re.compile(r"follows? the visible controls for .+? workflow", re.I)),
    ("generic observable result", re.compile(r"required headings, controls, values, and status", re.I)),
)


def _details(req: dict[str, Any]) -> dict[str, Any]:
    details = req.get("details")
    return details if isinstance(details, dict) else req


def _description(req: dict[str, Any]) -> str:
    return str(req.get("description", _details(req).get("description", "")) or "")


def _atomic(req: dict[str, Any]) -> bool:
    return str(req.get("type", "")).upper() == "ATOMIC" or (
        not req.get("children_ids") and not req.get("children")
        and bool(req.get("scenarios") or _details(req).get("scenarios")))


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def _references(value: Any) -> list[str]:
    """List cited resources without opening them or treating source paths as data."""
    files = []
    for text in _strings(value):
        files.extend(match.group(1).strip().split(" ", 1)[0].strip("<>")
                     for match in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", text))
        files.extend(re.findall(r"(?:\./)?reference/[^\s`\"'<>\])]+", text))
    if isinstance(value, dict):
        for key in ("visual_reference", "reference", "references"):
            if key in value:
                files.extend(_strings(value[key]))
    return _unique(path for path in files if path and not path.startswith(("#", "http:", "https:", "data:")))


def _source_block(value: Any) -> str:
    text = yaml.safe_dump(value, allow_unicode=True, sort_keys=False).rstrip()
    fence = "`" * max(3, max((len(m.group()) + 1 for m in re.finditer(r"`+", text)), default=3))
    return f"{fence}yaml\n{text}\n{fence}"


def _text(value: Any) -> str:
    return value if isinstance(value, str) else yaml.safe_dump(value, allow_unicode=True, sort_keys=False).rstrip()


def _scenario_steps(scenario: Any) -> list[dict[str, Any]]:
    if not isinstance(scenario, dict):
        return [{"phase": "UNCLASSIFIED", "keyword": "", "content": _text(scenario), "source": scenario}]
    result = []
    phase = "UNCLASSIFIED"
    for step in scenario.get("steps") or []:
        if not isinstance(step, dict):
            phase = "UNCLASSIFIED"
            result.append({"phase": phase, "keyword": "", "content": _text(step), "source": step})
            continue
        keyword = str(step.get("keyword", "")).upper().strip()
        if keyword in {"GIVEN", "WHEN", "THEN"}:
            phase = keyword
        elif keyword not in {"AND", "BUT"}:
            phase = "UNCLASSIFIED"
        result.append({"phase": phase, "keyword": keyword,
                       "content": _text(step.get("content", "")), "source": step})
    # Some requirement sources use direct scenario fields instead of Gherkin steps.
    # Retain the original field and value; never discard it because steps also exist.
    for key, value in scenario.items():
        direct_phase = {"given": "GIVEN", "when": "WHEN", "then": "THEN"}.get(key.lower())
        if direct_phase:
            for item in value if isinstance(value, list) else [value]:
                result.append({"phase": direct_phase, "keyword": key,
                               "content": _text(item), "source": {key: item}})
    return result


def build_requirement_context(requirements: list[dict[str, Any]], output_dir: Path) -> Path:
    """Write indexed source dossiers and scenario context; return the index path.

    IDs and scenario ordering are preserved. Scenario IDs are ``req_id::ordinal``
    (one-based), even when names or fixtures are repeated across scenarios.
    """
    folder = Path(output_dir) / ".arc" / "requirements"
    folder.mkdir(parents=True, exist_ok=True)
    by_id = {str(req["id"]): req for req in requirements}
    leaves = [req for req in requirements if _atomic(req)]
    filenames = {str(req["id"]): quote(str(req["id"]), safe="-_") + ".md" for req in leaves}
    scenarios = []
    index_rows = []
    explicit_users: dict[str, list[str]] = defaultdict(list)
    mentioned_users: dict[str, list[str]] = defaultdict(list)
    issues = []

    def ancestors(req: dict[str, Any]) -> list[dict[str, Any]]:
        parents = []
        visited = {str(req["id"])}
        parent_id = req.get("parent_id")
        while parent_id:
            parent_id = str(parent_id)
            if parent_id in visited:
                issues.append(f"{req['id']}: parent cycle at {parent_id}; review original hierarchy.")
                break
            visited.add(parent_id)
            if parent_id not in by_id:
                issues.append(f"{req['id']}: parent {parent_id} is not present in supplied records.")
                break
            parent = by_id[parent_id]
            parents.append(parent)
            parent_id = parent.get("parent_id")
        return list(reversed(parents))

    for req in leaves:
        req_id = str(req["id"])
        parents = ancestors(req)
        details = _details(req)
        dependencies = req.get("dependencies", details.get("dependencies", [])) or []
        dependency_ids = _unique(value for value in dependencies if isinstance(value, str))
        references = _unique(_REQ_REFERENCE.findall(_description(req)))
        for dependency in dependency_ids:
            explicit_users[dependency].append(req_id)
        for reference in references:
            if reference != req_id:
                mentioned_users[reference].append(req_id)
        resources = _unique(path for source in [details] + [_details(parent) for parent in parents]
                            for path in _references({key: value for key, value in source.items()
                                                    if key not in {"children", "children_ids"}}))
        raw_scenarios = req.get("scenarios") or details.get("scenarios") or []
        placeholder_count = 0
        for ordinal, scenario in enumerate(raw_scenarios, 1):
            steps = _scenario_steps(scenario)
            placeholder_reasons = [name for name, pattern in _PLACEHOLDERS
                                   if any(pattern.search(text) for text in _strings(scenario))]
            placeholder_count += bool(placeholder_reasons)
            scenarios.append({
                "scenario_id": f"{req_id}::{ordinal}", "req_id": req_id, "ordinal": ordinal,
                "name": str(scenario.get("name", "")) if isinstance(scenario, dict) else "",
                "placeholder": bool(placeholder_reasons), "placeholder_reasons": placeholder_reasons,
                "requirement_file": f".arc/requirements/{filenames[req_id]}",
                "preconditions": [step["content"] for step in steps if step["phase"] == "GIVEN"],
                "actions": [step["content"] for step in steps if step["phase"] == "WHEN"],
                "expected_results": [step["content"] for step in steps if step["phase"] == "THEN"],
                "steps": steps, "reference_files": resources, "source": scenario,
            })
        dossier = [f"# {req_id} {req.get('name', '')}",
                   "Read the inherited descriptions and complete atomic source together. "
                   "Explicit dependencies and textual references below are separate source evidence; "
                   "neither invents a data relationship or an unstated implementation rule.",
                   "## Inherited parent descriptions"]
        for parent in parents:
            dossier.extend([f"### {parent['id']} {parent.get('name', '')}", _description(parent)])
        if not parents:
            dossier.append("No parent description supplied.")
        dossier.extend(["## Explicit dependencies (verbatim)", _source_block(dependencies),
                        "## Requirement IDs mentioned in the atomic description",
                        ", ".join(references) or "None.",
                        "## Reference files (source citations only)",
                        "\n".join(f"- {path}" for path in resources) or "None.",
                        "## Complete atomic source", _source_block(details)])
        (folder / filenames[req_id]).write_text("\n\n".join(dossier) + "\n", encoding="utf-8")
        title = str(req.get("name", "")).replace("|", "\\|").replace("\n", " ")
        index_rows.append(f"| [{req_id}]({filenames[req_id]}) | {title} | {len(raw_scenarios)} | "
                          f"{placeholder_count} | {', '.join(dependency_ids) or '—'} |")

    (folder.parent / "scenario-inventory.json").write_text(
        json.dumps(scenarios, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review = ["# Source review and shared workflow priorities",
              "These are reading aids, not generated fixtures or a correctness verdict.",
              "## Scenario boundaries and source authority",
              "Preserve every scenario's original preconditions independently. Identical names do not "
              "prove identical accounts, objects, permissions, or initial states. Reuse records only when "
              "the source explicitly identifies them as the same entity. Keep action inputs and failed "
              "results separate from pre-existing data; never automatically seed quoted text. Do not "
              "reset persisted user changes during ordinary application startup.",
              "Read each leaf's inherited parent constraints, explicit dependencies, and complete "
              "description before interpreting its steps. Where a generic scenario is underspecified, "
              "expand it using the atomic description. Retain negative actions, permission refusals, "
              "and failure results. Apply an explicitly stated source precedence rule when text conflicts; "
              "record unresolved conflicts instead of silently inventing behavior.",
              "## Placeholder workflows requiring description-based expansion"]
    placeholders = [scenario for scenario in scenarios if scenario["placeholder"]]
    review.extend(f"- {scenario['scenario_id']}: {', '.join(scenario['placeholder_reasons'])}; "
                  f"read [{scenario['req_id']}]({filenames[scenario['req_id']]}) and replace the generic "
                  "workflow in the implementation/test plan with the description's concrete actions and outcomes."
                  for scenario in placeholders)
    if not placeholders:
        review.append("No known placeholder phrase detected. This does not certify scenario completeness.")
    review.extend(["## Shared explicit dependencies",
                   "Prioritize real end-to-end checks for dependencies used by many atomic requirements. "
                   "Counts below reflect explicit source dependency lists only; they do not infer edges."])
    for dependency, users in sorted(explicit_users.items(), key=lambda pair: (-len(set(pair[1])), pair[0])):
        name = str(by_id.get(dependency, {}).get("name", "not supplied"))
        review.append(f"- {dependency} {name}: {len(set(users))} atomic dependents — {', '.join(_unique(users))}")
    review.extend(["## Description references (not inferred dependencies)",
                   "Textual mentions can explain shared rules; read them in context before treating them as prerequisites."])
    for reference, users in sorted(mentioned_users.items(), key=lambda pair: (-len(set(pair[1])), pair[0])):
        review.append(f"- {reference}: mentioned by {', '.join(_unique(users))}")
    missing = [str(req["id"]) for req in leaves if not (req.get("scenarios") or _details(req).get("scenarios"))]
    if missing or issues:
        review.append("## Source gaps to review")
        review.extend(f"- {req_id}: no scenario supplied; derive the plan from the complete description." for req_id in missing)
        review.extend(f"- {issue}" for issue in _unique(issues))
    (folder / "review.md").write_text("\n\n".join(review) + "\n", encoding="utf-8")
    index = ["# Atomic requirement reading index",
             f"{len(requirements)} requirement nodes; {len(leaves)} atomic requirements; "
             f"{len(scenarios)} scenarios; {len(placeholders)} scenarios with known placeholder wording.",
             "Start with [source review and shared dependency priorities](review.md). Read each linked "
             "atomic dossier in full before implementation: it contains inherited descriptions, explicit "
             "dependencies, textual references, and the unabridged leaf source. "
             "[Scenario inventory](../scenario-inventory.json) preserves original steps and independent "
             "preconditions; AND/BUT inherit the preceding GIVEN/WHEN/THEN phase.",
             "| Requirement | Name | Scenarios | Placeholder flags | Explicit dependencies |\n"
             "| --- | --- | ---: | ---: | --- |\n" + "\n".join(index_rows)]
    index_path = folder / "index.md"
    index_path.write_text("\n\n".join(index) + "\n", encoding="utf-8")
    return index_path
