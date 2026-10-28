"""Central path resolution for Şerit dock logs and caches.

Avoids polluting user data files during test runs or when environment
variables override destinations.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

DEFAULT_LOG_PATH = Path("D:/Apps/serit/serit.log")
DEFAULT_CACHE_DIR = Path("D:/Apps/serit")
# Gerçek log ve önbelleğe yalnız kurulu barın kendisi ve bekçisi yazar. Deneme betikleri, ajan
# kopyaları (worktree) ve "python -c" yoklamaları geçici dosyaya yazar (v23: bir ajan betiği gerçek
# log'a hata satırı düşürmüştü).
PRODUCTION_ENTRY_POINTS = frozenset({"serit_v5.pyw", "serit_bekci.pyw"})


def is_running_under_test() -> bool:
    """Return True if running inside pytest or a test script."""
    if "pytest" in sys.modules:
        return True
    main_mod = sys.modules.get("__main__")
    if main_mod:
        main_file = getattr(main_mod, "__file__", None)
        if isinstance(main_file, str):
            main_path = Path(main_file).resolve()
            if "tests" in main_path.parts:
                return True
    return False


def is_production_process(main_file: Optional[str] = None) -> bool:
    """D:/Apps/serit içindeki serit_v5.pyw ya da serit_bekci.pyw olarak mı çalışıyoruz?"""
    if main_file is None:
        main_mod = sys.modules.get("__main__")
        main_file = getattr(main_mod, "__file__", None) if main_mod else None
    if not isinstance(main_file, str) or not main_file:
        return False
    try:
        mp = Path(main_file).resolve()
        return mp.name.lower() in PRODUCTION_ENTRY_POINTS and mp.parent == DEFAULT_CACHE_DIR.resolve()
    except Exception:
        return False


def get_log_path() -> Path:
    """Return path to serit.log (or test / dev redirect)."""
    env_log = os.environ.get("SERIT_LOG")
    if env_log:
        return Path(env_log)
    if is_running_under_test():
        return Path(tempfile.gettempdir()) / "serit-test.log"
    if not is_production_process():
        return Path(tempfile.gettempdir()) / "serit-dev.log"
    return DEFAULT_LOG_PATH


def get_claude_cache_path() -> Path:
    """Return path to claude_cache.json (or test redirect)."""
    env_dir = os.environ.get("SERIT_CACHE_DIR")
    if env_dir:
        return Path(env_dir) / "claude_cache.json"
    if is_running_under_test():
        return Path(tempfile.gettempdir()) / "claude_cache.json"
    if not is_production_process():
        return Path(tempfile.gettempdir()) / "serit-dev-claude_cache.json"
    return DEFAULT_CACHE_DIR / "claude_cache.json"


LOG_PATH: Path = get_log_path()
CLAUDE_CACHE: Path = get_claude_cache_path()
CLAUDE_CACHE_PATH: Path = CLAUDE_CACHE
