"""ag_quota.py - Standalone helper for Şerit dock Antigravity quota retrieval.

Executes within Hermes Python environment to access hermes-overview plugin API.
Outputs strictly sanitized JSON to stdout: {available, reason, windows}.
Never exposes tokens, auth files, or sensitive error traces.
"""

import importlib.util
import json
import os
from pathlib import Path
import sys


def main() -> None:
    try:
        # Resolve Hermes home directory
        base_h = Path(os.environ.get("HERMES_BASE", r"C:\Users\Emre Karatasli\AppData\Local\hermes"))
        hermes_agent_dir = str(base_h / "hermes-agent")
        if hermes_agent_dir not in sys.path:
            sys.path.insert(0, hermes_agent_dir)

        plugin_api_path = base_h / "plugins" / "hermes-overview" / "dashboard" / "plugin_api.py"
        if not plugin_api_path.is_file():
            sys.stdout.write(json.dumps({"available": False, "reason": "plugin_missing", "windows": []}) + "\n")
            return

        spec = importlib.util.spec_from_file_location("plugin_api", str(plugin_api_path))
        if spec is None or spec.loader is None:
            sys.stdout.write(json.dumps({"available": False, "reason": "loader_missing", "windows": []}) + "\n")
            return

        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        if not hasattr(mod, "_fetch_antigravity"):
            sys.stdout.write(json.dumps({"available": False, "reason": "func_missing", "windows": []}) + "\n")
            return

        raw_res = mod._fetch_antigravity()
        if not isinstance(raw_res, dict):
            sys.stdout.write(json.dumps({"available": False, "reason": "invalid_response", "windows": []}) + "\n")
            return

        available = bool(raw_res.get("available"))
        raw_reason = raw_res.get("reason")
        # Generic reasons only - never expose sensitive exception or account strings
        if raw_reason in ("oauth_required", "unavailable"):
            safe_reason = raw_reason
        else:
            safe_reason = "unavailable" if not available else None

        raw_windows = raw_res.get("windows") or []
        windows = []
        for w in raw_windows:
            if isinstance(w, dict):
                label = str(w.get("label") or "").strip()
                try:
                    used_pct = float(w.get("used_percent") or 0.0)
                except (ValueError, TypeError):
                    used_pct = 0.0
                reset_at = w.get("reset_at")
                if reset_at is not None:
                    reset_at = str(reset_at).strip()
                windows.append({
                    "label": label,
                    "used_percent": max(0.0, min(100.0, used_pct)),
                    "reset_at": reset_at,
                })

        output = {
            "available": available,
            "reason": safe_reason,
            "windows": windows,
        }
        sys.stdout.write(json.dumps(output) + "\n")

    except Exception:
        # Strictly never print stack traces or raw exceptions
        sys.stdout.write(json.dumps({"available": False, "reason": "error", "windows": []}) + "\n")


if __name__ == "__main__":
    main()
