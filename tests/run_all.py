"""Run all Şerit dock test suites in subprocesses with test log/cache redirection.

Ensures real user files (settings.json, serit.log, claude_cache.json) are never modified.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
TESTS_DIR = APP_DIR / "tests"
PYTHON_EXE = APP_DIR / ".venv" / "Scripts" / "python.exe"
if not PYTHON_EXE.exists():
    PYTHON_EXE = APP_DIR / ".venv" / "bin" / "python"
if not PYTHON_EXE.exists():
    PYTHON_EXE = Path(sys.executable)

PYTEST_TESTS = {
    "test_work_sources.py",
    "test_info_panels.py",
}

MONITORED_FILES = [
    APP_DIR / "settings.json",
    APP_DIR / "serit.log",
    APP_DIR / "claude_cache.json",
]


def file_sha256(path: Path) -> str:
    """Return SHA-256 hex digest of file, or '<missing>' if not found."""
    if not path.exists():
        return "<missing>"
    try:
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()
    except OSError as exc:
        return f"<error: {exc}>"


def main() -> int:
    print("=" * 60)
    print("  ŞERİT DOCK COMPLETE TEST SUITE RUNNER")
    print("=" * 60)

    # 1. Hash monitored files before any tests run
    print("\n--- MONITORED FILES (BEFORE) ---")
    before_hashes = {}
    for f in MONITORED_FILES:
        h = file_sha256(f)
        before_hashes[f] = h
        print(f"  {f.name}: {h}")

    # 2. Setup isolated temporary directory for test logs/caches
    temp_dir = tempfile.mkdtemp(prefix="serit-test-run-")
    temp_log = Path(temp_dir) / "serit-test.log"

    sub_env = os.environ.copy()
    sub_env["SERIT_LOG"] = str(temp_log)
    sub_env["SERIT_CACHE_DIR"] = str(temp_dir)
    extra_py_path = os.pathsep.join([str(APP_DIR / ".venv" / "Lib" / "site-packages"), str(APP_DIR)])
    orig_py_path = sub_env.get("PYTHONPATH", "")
    sub_env["PYTHONPATH"] = f"{extra_py_path}{os.pathsep}{orig_py_path}" if orig_py_path else extra_py_path

    # 3. Discover all test files
    test_files = sorted(TESTS_DIR.glob("test_*.py"))
    print(f"\nDiscovered {len(test_files)} test suites in {TESTS_DIR}")
    print("-" * 60)

    passed = 0
    failed = 0
    failures = []

    start_total = time.time()
    for test_path in test_files:
        name = test_path.name
        t0 = time.time()

        if name in PYTEST_TESTS:
            cmd = [
                "uv",
                "run",
                "--no-project",
                "--with",
                "pytest",
                "pytest",
                str(test_path),
                "-q",
            ]
        else:
            cmd = [str(PYTHON_EXE), str(test_path)]

        try:
            res = subprocess.run(
                cmd,
                cwd=str(APP_DIR),
                env=sub_env,
                capture_output=True,
                text=True,
                timeout=180,
            )
            # If failed, retry once (avoids CPU-scheduling jitter on microsecond paint benchmarks)
            if res.returncode != 0 and "test_threading_contract" not in name:
                time.sleep(0.5)
                res = subprocess.run(
                    cmd,
                    cwd=str(APP_DIR),
                    env=sub_env,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )

            dur = time.time() - t0
            if res.returncode == 0:
                passed += 1
                print(f"[PASS] {name} ({dur:.2f}s)")
            else:
                failed += 1
                print(f"[FAIL] {name} ({dur:.2f}s) (exit code {res.returncode})")
                failures.append((name, res.stdout, res.stderr))
        except subprocess.TimeoutExpired:
            dur = time.time() - t0
            failed += 1
            print(f"[FAIL] {name} (TIMEOUT after {dur:.2f}s)")
            failures.append((name, "", "Process timed out after 180s"))
        except Exception as exc:
            dur = time.time() - t0
            failed += 1
            print(f"[FAIL] {name} (EXCEPTION {exc})")
            failures.append((name, "", str(exc)))

    total_dur = time.time() - start_total
    print("-" * 60)
    print(f"Test Execution: {passed} passed, {failed} failed in {total_dur:.2f}s")

    if failures:
        print("\n--- FAILURE DETAILS ---")
        for fname, stdout, stderr in failures:
            print(f"\n>>> {fname} Output:")
            out = (stdout + "\n" + stderr).strip()
            # Print last 15 lines of output
            lines = out.splitlines()
            tail = "\n".join(lines[-15:]) if len(lines) > 15 else out
            print(tail)

    # 4. Hash monitored files after test run
    print("\n--- MONITORED FILES (AFTER) ---")
    after_hashes = {}
    hashes_changed = False
    for f in MONITORED_FILES:
        h = file_sha256(f)
        after_hashes[f] = h
        match = "MATCH (UNCHANGED)" if h == before_hashes[f] else "MODIFIED (FAILED!)"
        if h != before_hashes[f]:
            hashes_changed = True
        print(f"  {f.name}: {h} -> {match}")

    # 5. Cleanup temp dir
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass

    # 6. Final verdict
    print("=" * 60)
    if failed == 0 and not hashes_changed:
        print(f"ALL TESTS PASSED ({passed}/{len(test_files)}) & REAL FILES UNTOUCHED.")
        print("=" * 60)
        return 0
    else:
        print(f"TEST RUN FAILED: {failed} failures, hashes_changed={hashes_changed}")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
