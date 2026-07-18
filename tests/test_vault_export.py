from paper_digest.vault_export import GENERATOR_MARKER, export_to_vault


def test_export_writes_preview_and_state(tmp_path):
    (tmp_path / "AGENTS.md").write_text("vault", encoding="utf-8")
    (tmp_path / "99_System").mkdir()
    report = {"date": "2026-07-18", "focus": [], "explore": [], "xhs": []}
    state, preview = export_to_vault(report, f"<html><head>{GENERATOR_MARKER}</head></html>", tmp_path)
    assert state.name == "2026-07-18-daily-digest.json"
    assert preview.name == "2026-07-18.html"
    assert preview.is_file()
