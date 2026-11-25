import pytest

from bfa.report.export import ExportBlocked, export
from bfa.report.render import build_doc
from bfa.schemas import CheckResult


@pytest.mark.parametrize("fmt", ["md", "docx", "pptx", "pdf", "xlsx"])
def test_every_format_writes(demo_run, tmp_path, fmt):
    p = export(demo_run.report, demo_run.store, fmt, tmp_path / f"r.{fmt}")
    assert p.exists() and p.stat().st_size > 2000


def test_word_has_sources_and_citations(demo_run, tmp_path):
    import docx

    p = export(demo_run.report, demo_run.store, "docx", tmp_path / "r.docx", scope="decision_brief")
    text = "\n".join(x.text for x in docx.Document(str(p)).paragraphs)
    assert "Sources" in text and "[1" in text and "Primary only" in text


def test_citations_are_numbered_once(demo_run):
    doc = build_doc(demo_run.report, demo_run.store)
    ids = [r.fact_id for r in doc.refs]
    assert len(ids) == len(set(ids)) and [r.n for r in doc.refs] == list(range(1, len(ids) + 1))


def test_confidential_uploads_can_be_left_out(demo_run):
    marked = build_doc(demo_run.report, demo_run.store, confidential="mark")
    removed = build_doc(demo_run.report, demo_run.store, confidential="remove")
    assert any(ln.confidential for s in marked.sections for b in s.blocks for ln in b.lines)
    assert not any(ln.confidential for s in removed.sections for b in s.blocks for ln in b.lines)


def test_export_refused_when_locked_check_fails(demo_run, tmp_path):
    bad = demo_run.report.model_copy(deep=True)
    bad.checks = [CheckResult(rule=1, name="citations", passed=False, detail="seeded")]
    with pytest.raises(ExportBlocked):
        export(bad, demo_run.store, "md", tmp_path / "x.md")
