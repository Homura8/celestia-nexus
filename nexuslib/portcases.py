"""Validate and inspect sanitised, source-pinned physical-port case records.

No device access, network requests, external dependencies or executable hooks.
This is an evidence index, NOT a physical-device runner or driver framework.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "docs" / "port-cases"
ID = re.compile(r"[a-z][a-z0-9-]{1,79}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
PATH = re.compile(r"docs/[A-Za-z0-9_./-]+\.md\Z")
STATUSES = {"owner-observed", "host-verified", "upstream-reported",
            "hypothesis", "not-tested"}
SCOPES = {"general", "conditional", "device-specific"}


def validate(case: object) -> list[str]:
    """Return actionable problems without executing or contacting source repos."""
    problems: list[str] = []
    if not isinstance(case, dict):
        return ["root must be an object"]
    if type(case.get("schema")) is not int or case["schema"] != 1:
        problems.append("schema must be 1")
    if not isinstance(case.get("id"), str) or not ID.fullmatch(case["id"]):
        problems.append("id must be lowercase hyphenated")
    source = case.get("source")
    if not isinstance(source, dict):
        problems.append("source must be an object")
        source = {}
    repository, commit = source.get("repository"), source.get("commit")
    if not isinstance(repository, str) or not REPO.fullmatch(repository):
        problems.append("source.repository must be owner/name")
    if not isinstance(commit, str) or not SHA.fullmatch(commit):
        problems.append("source.commit must be a full lowercase Git SHA")
    review = source.get("review")
    if not isinstance(review, str) or not re.fullmatch(
        r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/\d+", review
    ):
        problems.append("source.review must be a GitHub PR URL")
    try:
        date.fromisoformat(source["as_of_utc"])
    except (KeyError, TypeError, ValueError):
        problems.append("source.as_of_utc must be an ISO date")
    target = case.get("target")
    if not isinstance(target, dict):
        problems.append("target must be an object")
        target = {}
    for key in ("device", "soc", "architecture", "os"):
        value = target.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"target.{key} must be a nonempty string")

    seen: set[str] = set()
    for section in ("milestones", "lessons", "open_questions"):
        records = case.get(section)
        if not isinstance(records, list) or not records:
            problems.append(f"{section} must be a nonempty array")
            continue
        for index, item in enumerate(records):
            prefix = f"{section}[{index}]"
            if not isinstance(item, dict):
                problems.append(f"{prefix} must be an object")
                continue
            item_id = item.get("id")
            if not isinstance(item_id, str) or not ID.fullmatch(item_id):
                problems.append(f"{prefix}.id must be lowercase hyphenated")
            elif item_id in seen:
                problems.append(f"{prefix}.id duplicated: {item_id}")
            else:
                seen.add(item_id)
            fields = {
                "milestones": ("claim",),
                "lessons": ("title", "finding", "application", "caveat"),
                "open_questions": ("question", "next_test"),
            }[section]
            for field in fields:
                value = item.get(field)
                if not isinstance(value, str) or not value.strip():
                    problems.append(f"{prefix}.{field} must be a nonempty string")
            status = item.get("status")
            if status not in STATUSES:
                problems.append(f"{prefix}.status must be one of {sorted(STATUSES)}")
            if section == "milestones" and status in {"hypothesis", "not-tested"}:
                problems.append(f"{prefix}: proposed/unverified work is not a milestone")
            if section == "lessons" and item.get("scope") not in SCOPES:
                problems.append(f"{prefix}.scope must be one of {sorted(SCOPES)}")
            evidence = item.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                problems.append(f"{prefix}.evidence needs at least one source path")
                continue
            for path in evidence:
                if (not isinstance(path, str) or not PATH.fullmatch(path)
                        or ".." in Path(path).parts or "//" in path):
                    problems.append(f"{prefix}: unsafe or malformed evidence path {path!r}")
    return problems


def load_cases(directory: Path = CASES) -> list[dict]:
    files = sorted(directory.glob("*.json"))
    if not files:
        raise ValueError(f"No case JSON files found in {directory}")
    cases = []
    identifiers = set()
    for file in files:
        try:
            case = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{file}: {exc}") from exc
        problems = validate(case)
        if problems:
            raise ValueError(f"{file}:\n  " + "\n  ".join(problems))
        if case["id"] in identifiers:
            raise ValueError(f"{file}: duplicate case id {case['id']}")
        identifiers.add(case["id"])
        cases.append(case)
    return cases


def source_url(case: dict, evidence: str) -> str:
    """A permalink at the recorded source commit, never a moving branch."""
    source = case["source"]
    return (f"https://github.com/{source['repository']}/blob/"
            f"{source['commit']}/{evidence}")


def summary(case: dict) -> str:
    source = case["source"]
    lines = [
        f"{case['id']} — {case['target']['device']} / {case['target']['os']}",
        f"Source: https://github.com/{source['repository']}/tree/{source['commit']}",
        f"Review: {source['review']} (mutable; pinned tree above is authoritative)",
        f"As of: {source['as_of_utc']} UTC",
        "Milestones (source observations, not Nexus reproductions):",
    ]
    for item in case["milestones"]:
        lines.append(f"  [{item['status']}] {item['claim']}")
        lines.append(f"    {source_url(case, item['evidence'][0])}")
    lines.append("Transferable findings:")
    for item in case["lessons"]:
        lines.append(f"  [{item['scope']}; {item['status']}] {item['title']}")
        lines.append(f"    {item['application']}")
    lines.append("Open investigations:")
    for item in case["open_questions"]:
        lines.append(f"  [{item['status']}] {item['question']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "show"))
    parser.add_argument("--directory", type=Path, default=CASES)
    parser.add_argument("--id", help="case id to show (required if multiple cases)")
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.directory)
        if args.action == "check":
            print(f"port cases: OK ({len(cases)} pinned, sanitised record(s))")
        else:
            selected = [c for c in cases if args.id is None or c["id"] == args.id]
            if len(selected) != 1:
                raise ValueError("Select exactly one existing case with --id")
            print(summary(selected[0]))
    except ValueError as exc:
        print(f"port cases: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
