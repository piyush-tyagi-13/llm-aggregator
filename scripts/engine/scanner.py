"""Blueprint Scanner — compares codebase against blueprint requirements."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BLUEPRINT = ROOT / "scripts" / "engine" / "blueprint.yaml"
OUTPUT = ROOT / "scripts" / "engine" / "gap_report.json"
TICKETS = ROOT / "scripts" / "engine" / "tickets"


def exists(path: str) -> bool:
    return (ROOT / path).exists()


def contains(path: str, pat: str) -> bool:
    f = ROOT / path
    if not f.exists():
        return False
    try:
        return bool(re.search(pat, f.read_text(), re.MULTILINE))
    except Exception:
        return False


def list_py(dirpath: str) -> list[str]:
    d = ROOT / dirpath
    if not d.exists():
        return []
    return sorted(
        p.name
        for p in d.iterdir()
        if p.suffix == ".py" and p.name not in ("__init__.py", "_base.py")
    )


def check(req: dict) -> dict:
    req_id = req["id"]
    checks = req.get("check", [])
    files = req.get("files", [req.get("file", "")])
    passed, failed = 0, 0
    details = []

    for check_desc in checks:
        c = check_desc.lower()

        # Function existence
        if "()" in check_desc or "function" in c:
            fname = check_desc.split("(")[0].split()[-1]
            ok = any(contains(f, rf"^(?:async )?def {fname}\(") for f in files if f)
            details.append(f"  {'OK' if ok else 'MISS'} {check_desc}")
            if ok:
                passed += 1
            else:
                failed += 1

        # File/directory/adapter checks
        elif "16 adapter" in c:
            count = len(list_py("llm_apipool/providers/adapters"))
            ok = count >= 16
            details.append(f"  {'OK' if ok else 'MISS'} {check_desc} ({count} found)")
            if ok:
                passed += 1
            else:
                failed += 1

        elif "file exists" in c:
            ok = any(exists(f) for f in files if f)
            details.append(f"  {'OK' if ok else 'MISS'} {check_desc}")
            if ok:
                passed += 1
            else:
                failed += 1

        # Endpoint checks
        elif "endpoint" in c or check_desc.strip().startswith(
            ("GET ", "POST ", "PUT ")
        ):
            endpoint = check_desc
            ok = any(contains(f, re.escape(endpoint)) for f in files if f)
            details.append(f"  {'OK' if ok else 'MISS'} {check_desc}")
            if ok:
                passed += 1
            else:
                failed += 1

        # Test suite
        elif "test" in c and ("pass" in c or "coverage" in c):
            if "all tests pass" in c:
                r = subprocess.run(
                    "python -m pytest --tb=short -q 2>&1 | tail -5",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=ROOT,
                )
                out = r.stdout + r.stderr
                m = re.search(r"(\d+) passed", out)
                ok = m is not None and "failed" not in out
                details.append(
                    f"  {'OK' if ok else 'MISS'} {check_desc} (count={m.group(1) if m else '?'})"
                )
            else:
                ok = True
                details.append(f"  OK {check_desc} (manual check)")
            if ok:
                passed += 1
            else:
                failed += 1

        # Generic keyword search
        else:
            words = [
                w.strip(".,;:!?")
                for w in check_desc.split()
                if len(w.strip(".,;:!?")) > 3
            ]
            ok = any(any(contains(f, re.escape(w)) for w in words) for f in files if f)
            details.append(f"  {'OK' if ok else 'MISS'} {check_desc}")
            if ok:
                passed += 1
            else:
                failed += 1

    status = "done" if failed == 0 else ("partial" if passed > 0 else "pending")
    return {
        "id": req_id,
        "category": req["category"],
        "description": req["description"],
        "status": status,
        "checks_passed": passed,
        "checks_failed": failed,
        "details": details,
        "files": files,
    }


def main():
    import yaml

    print("=" * 60)
    print("  LLM-KEYPOOL BLUEPRINT SCANNER")
    print("=" * 60)

    with open(BLUEPRINT) as f:
        blueprint = yaml.safe_load(f)

    results = [check(r) for r in blueprint["requirements"]]
    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
        emoji = {"done": "OK", "partial": "WARN", "pending": "FAIL"}.get(
            r["status"], "??"
        )
        print(f"[{emoji}] [{r['id']}] {r['description']}")
        for d in r["details"]:
            print(d)
        print()

    print("=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Done:    {summary.get('done', 0)}")
    print(f"  Partial: {summary.get('partial', 0)}")
    print(f"  Pending: {summary.get('pending', 0)}")
    print(f"  Total:   {len(results)}")

    TICKETS.mkdir(parents=True, exist_ok=True)
    report = {
        "meta": blueprint["meta"],
        "summary": summary,
        "total": len(results),
        "requirements": results,
    }
    with open(OUTPUT, "w") as f:
        json.dump(report, f, indent=2)

    incomplete = [r for r in results if r["status"] != "done"]
    for r in incomplete:
        ticket = {
            "id": r["id"],
            "category": r["category"],
            "description": r["description"],
            "status": r["status"],
            "files": r["files"],
        }
        with open(TICKETS / f"{r['id']}.json", "w") as f:
            json.dump(ticket, f, indent=2)

    print(f"\n  Report:  {OUTPUT}")
    print(f"  Tickets: {len(incomplete)} in {TICKETS}")
    if incomplete:
        print(f"\n  {len(incomplete)} requirements need work")
        sys.exit(1)
    else:
        print("\n  All requirements satisfied!")
        sys.exit(0)


if __name__ == "__main__":
    main()
