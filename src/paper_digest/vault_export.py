from __future__ import annotations

import json
from pathlib import Path
from typing import Any


GENERATOR_MARKER = '<meta name="generator" content="PaperLearning-Daily-Digest">'


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def export_to_vault(report: dict[str, Any], html: str, vault: Path) -> tuple[Path, Path]:
    vault = vault.expanduser().resolve()
    if not (vault / "AGENTS.md").is_file() or not (vault / "99_System").is_dir():
        raise ValueError(f"not a PaperLearning Vault: {vault}")
    if GENERATOR_MARKER not in html:
        raise ValueError("preview HTML is missing the generator marker")
    preview = vault / "03_Daily_Digests" / f"{report['date']}.html"
    if preview.exists() and GENERATOR_MARKER not in preview.read_text(encoding="utf-8", errors="replace"):
        raise FileExistsError(f"refusing to overwrite a non-generated preview: {preview}")
    state = vault / "99_System" / "state" / f"{report['date']}-daily-digest.json"
    _atomic_write(state, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _atomic_write(preview, html)
    return state, preview
