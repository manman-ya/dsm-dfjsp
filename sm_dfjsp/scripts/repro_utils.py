from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import yaml


def load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def current_git_commit(root: Path) -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True)
        return out.strip()
    except Exception:
        return "unknown"


def write_run_meta(out_dir: Path, config_path: Path | None, extra: Dict[str, Any] | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    payload: Dict[str, Any] = {
        "utc_time": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "git_commit": current_git_commit(root),
        "cwd": str(root),
    }
    if config_path is not None and config_path.exists():
        payload["config_path"] = str(config_path)
        payload["config_sha256"] = sha256_file(config_path)
    if extra:
        payload.update(extra)
    out_path = out_dir / "run_meta.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path

