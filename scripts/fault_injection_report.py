#!/usr/bin/env python3
"""Run the shared conformance suite under each injected fault and print a Markdown table.

    uv run python scripts/fault_injection_report.py > /tmp/table.md

For each fault in ``tests/faults.py``, runs ``TestSharedSuiteUnderInjectedFault`` (the shared
``CalendarServiceConformance`` suite over our real Google adapter) with ``FAULT_INJECTION`` set,
and reports each check as passed or failed. The exact error per operation and fault is
asserted separately, in ``test_each_operation_fails_the_documented_way``.
The table in ``docs/FAULT_INJECTION.md`` comes from this script.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.faults import FAULTS  # noqa: E402

TARGET = "tests/unit/test_fault_injection.py::TestSharedSuiteUnderInjectedFault"


def run(fault: str) -> dict[str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "junit.xml"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                TARGET,
                "-q",
                "-p",
                "no:cacheprovider",
                f"--junitxml={report}",
            ],
            cwd=ROOT,
            env={**os.environ, "FAULT_INJECTION": fault},
            capture_output=True,
            text=True,
            check=False,
        )
        # pytest can write two entries for one check (the check, then its teardown), so
        # combine them: any real failure wins over a cleanup-only error.
        seen: dict[str, set[str]] = {}
        for case in ET.parse(report).iter("testcase"):
            name = case.get("name", "").removeprefix("test_")
            kinds = seen.setdefault(name, set())
            for problem in [*case.findall("failure"), *case.findall("error")]:
                cleanup = problem.tag == "error" and "teardown" in problem.get("message", "")
                kinds.add("cleanup" if cleanup else "fail")
        results: dict[str, str] = {}
        for name, kinds in seen.items():
            if "fail" in kinds:
                results[name] = "fail"
            elif "cleanup" in kinds:
                # The check passed; the suite's cleanup (a delete) then met the fault.
                results[name] = "pass (cleanup hit the fault)"
            else:
                results[name] = "pass"
        return results


def main() -> None:
    faults = list(FAULTS)
    by_fault = {fault: run(fault) for fault in faults}
    checks = list(by_fault["none"])
    print("| Shared check | " + " | ".join(f"`{f}`" for f in faults) + " |")
    print("| --- |" + " --- |" * len(faults))
    for check in checks:
        cells = [by_fault[f].get(check, "?") for f in faults]
        print(f"| `{check}` | " + " | ".join(cells) + " |")
    print()
    passed = [sum(v.startswith("pass") for v in by_fault[f].values()) for f in faults]
    totals = [f"{n}/{len(by_fault[f])}" for n, f in zip(passed, faults, strict=True)]
    print("| Passed | " + " | ".join(totals) + " |")


if __name__ == "__main__":
    main()
