"""Trusted image entrypoint. Never execute commands supplied by candidate code."""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

POLICY = "1"
PREFIX = "ASHVANE_SANDBOX_RESULT="


def main() -> int:
    result = {"policy": POLICY, "tests": 0, "failures": 0, "errors": 0,
              "skipped": 0, "exit_code": 1, "error": ""}
    try:
        threads = max(1, math.ceil(float(sys.argv[2])))
        if hasattr(os, "sched_getaffinity"):
            allowed = sorted(os.sched_getaffinity(0))
            os.sched_setaffinity(0, set(allowed[:threads]))
        # The host composes candidate code + protected baseline tests, then Docker
        # mounts the entire tree read-only. Candidate imports cannot rewrite tests.
        work = Path("/workspace")
        home = Path("/tmp/synthetic-home")
        home.mkdir()
        env = {"PATH": os.environ["PATH"], "HOME": str(home), "CLIPBOT_HOME": str(home),
               "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
               "LANG": "C.UTF-8", "TMPDIR": "/tmp"}
        for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            env[variable] = str(threads)
        phases = [("baseline", work / "tests")]
        if (work / "_additional_tests").is_dir():
            phases.append(("additional", work / "_additional_tests"))
        result["phases"] = []
        with Path("/tmp/pytest.log").open("wb") as output:
            for phase, location in phases:
                junit = Path("/tmp/" + phase + ".xml")
                child = subprocess.run([str(Path(sys.executable).resolve()), "-I", "-m", "pytest", "-q", "-c", str(work / "pytest.ini"),
                                        "--rootdir", str(work), "-p", "no:cacheprovider", "-p", "anyio.pytest_plugin", "--junitxml", str(junit),
                                        str(location)], cwd=work, env=env, stdout=output, stderr=subprocess.STDOUT)
                result["exit_code"] = child.returncode
                if not junit.is_file() or junit.is_symlink():
                    raise ValueError("Pytest produced no regular JUnit result")
                cases = ET.parse(junit).getroot().findall(".//testcase")
                measured = {"name": phase, "tests": len(cases), "exit_code": child.returncode}
                for kind in ("failure", "error", "skipped"):
                    key = {"failure": "failures", "error": "errors", "skipped": "skipped"}[kind]
                    measured[key] = sum(case.find(kind) is not None for case in cases)
                    result[key] += measured[key]
                result["tests"] += measured["tests"]
                result["phases"].append(measured)
                if len(cases) <= measured["skipped"]:
                    result["error"] = phase + ": no tests were executed"
                if child.returncode or result["error"]:
                    break
        # Output is evidence only. Never parse candidate stdout as an evaluator result.
        with Path("/tmp/pytest.log").open("rb") as output:
            # JSON escaping can expand each byte into six ASCII characters.
            result["output"] = output.read(int(sys.argv[1]) // len("\\u0000") // 2).decode("utf-8", errors="replace")
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
    print(PREFIX + json.dumps(result, ensure_ascii=True), flush=True)
    return 0 if result["exit_code"] == 0 and result["tests"] > result["skipped"] and not result["failures"] and not result["errors"] and not result["error"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
