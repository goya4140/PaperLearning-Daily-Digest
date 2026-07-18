from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def canonical_payload(report: dict[str, Any]) -> bytes:
    payload = {key: value for key, value in report.items() if key != "content_sha256"}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def seal_report(report: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(report)
    sealed["schema_version"] = 1
    sealed["content_sha256"] = hashlib.sha256(canonical_payload(sealed)).hexdigest()
    return sealed


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def archive_report(report: dict[str, Any], docs_root: Path) -> tuple[Path, Path]:
    date = str(report["date"])
    data_path = Path("data") / date[:4] / date[5:7] / f"{date}.json"
    latest_path = Path("data/latest.json")
    report_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    latest = {
        "schema_version": 1,
        "digest_date": date,
        "data_path": data_path.as_posix(),
        "preview_path": f"daily/{date[:4]}/{date[5:7]}/{date}.html",
        "content_sha256": report["content_sha256"],
        "generated_at": report["generated_at"],
    }
    atomic_write(docs_root / data_path, report_text)
    current_latest = docs_root / latest_path
    should_advance = True
    if current_latest.is_file():
        try:
            current = json.loads(current_latest.read_text(encoding="utf-8"))
            should_advance = str(current.get("digest_date", "")) <= date
        except (OSError, ValueError):
            pass
    if should_advance:
        atomic_write(current_latest, json.dumps(latest, ensure_ascii=False, indent=2) + "\n")
    return docs_root / data_path, docs_root / latest_path
