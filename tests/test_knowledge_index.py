from datetime import date
import importlib.util


def module():
    spec = importlib.util.spec_from_file_location("knowledge_index", "tools/knowledge_index.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_write_indexes_present_files_and_preserves_descriptions(tmp_path):
    mod = module()
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "projects").mkdir()
    (tmp_path / "knowledge" / "projects" / ".gitkeep").write_text("")
    (tmp_path / "knowledge" / "INDEX.md").write_text(
        "# Knowledge Index\n\nHeader.\n\n- `old.md` — retained description\n\nFooter.\n")
    (tmp_path / "knowledge" / "lessons.md").write_text("# Lessons\n")
    (tmp_path / "knowledge" / "projects" / "new.md").write_text("# New\n")
    rendered = mod.render_index(tmp_path)
    assert "Header." in rendered and "Footer." in rendered
    assert "`lessons.md`" in rendered and "`projects/new.md`" in rendered
    assert "projects/.gitkeep" not in rendered
    assert "old.md" not in rendered


def test_roll_is_verbatim_and_skips_undated_entries(tmp_path):
    mod = module()
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "docs" / "archive").mkdir(parents=True)
    (tmp_path / "knowledge" / "lessons.md").write_text(
        "# Lessons\n\n## 2020-01-01 — old\n\nKeep **exactly**.\n\n## Current note\n\nDo not move.\n")
    (tmp_path / "docs" / "archive" / "lessons-history.md").write_text("# Archived lessons\n")
    assert mod.roll_lessons(tmp_path, date(2026, 9, 11)) == ["2020-01-01"]
    assert "Keep **exactly**." not in (tmp_path / "knowledge/lessons.md").read_text()
    archive = (tmp_path / "docs/archive/lessons-history.md").read_text()
    assert "## 2020-01-01 — old\n\nKeep **exactly**." in archive
    assert "## Current note" in (tmp_path / "knowledge/lessons.md").read_text()
