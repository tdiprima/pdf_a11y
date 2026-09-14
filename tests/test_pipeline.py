"""Pipeline safety: never overwrite sources, never leak staged files, never
claim PDF/UA, always tell the operator about addresses left unlinked."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import fitz
import pikepdf
import pytest

from pdf_a11y import __version__
from pdf_a11y.audit import AuditResult
from pdf_a11y.config import Config
from pdf_a11y.pipeline import (
    UnreadablePdf,
    _collect_manual_work,
    _resolve_output,
    remediate_file,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestResolveOutput:
    def test_mirrors_the_input_tree(self, tmp_path):
        source = tmp_path / "in" / "sub" / "a.pdf"
        source.parent.mkdir(parents=True)
        source.touch()
        destination = _resolve_output(source, tmp_path / "out", tmp_path / "in")
        assert destination == tmp_path / "out" / "sub" / "a.pdf"
        assert destination.parent.is_dir()

    def test_source_outside_root_falls_back_to_name(self, tmp_path):
        source = tmp_path / "elsewhere" / "a.pdf"
        source.parent.mkdir()
        source.touch()
        destination = _resolve_output(source, tmp_path / "out", tmp_path / "in")
        assert destination == tmp_path / "out" / "a.pdf"

    def test_refuses_to_overwrite_the_source(self, tmp_path):
        source = tmp_path / "docs" / "a.pdf"
        source.parent.mkdir()
        source.touch()
        with pytest.raises(UnreadablePdf, match="overwrite the source"):
            _resolve_output(source, tmp_path / "docs", tmp_path / "docs")

    def test_refuses_overwrite_through_a_relative_alias(self, tmp_path, monkeypatch):
        source = tmp_path / "docs" / "a.pdf"
        source.parent.mkdir()
        source.touch()
        monkeypatch.chdir(tmp_path)
        with pytest.raises(UnreadablePdf):
            _resolve_output(source, Path("docs"), Path("docs"))


class TestCollectManualWork:
    def test_unresolved_addresses_become_a_task(self):
        audit = AuditResult(path="x.pdf")
        tasks = _collect_manual_work(audit, {}, ["https://wrapped.example/x"])
        assert any("https://wrapped.example/x" in task for task in tasks)

    def test_no_unresolved_addresses_no_task(self):
        tasks = _collect_manual_work(AuditResult(path="x.pdf"), {}, [])
        assert not any("could not be located" in task for task in tasks)

    def test_always_warns_against_claiming_conformance(self):
        tasks = _collect_manual_work(AuditResult(path="x.pdf"), {}, [])
        assert any("PDF/UA" in task for task in tasks)


class TestRemediateFile:
    def test_source_is_untouched_and_no_pdfua_claim(self, pdf_factory, tmp_path):
        source = pdf_factory("in/doc.pdf", text="Heading\nVisit https://example.com/p now")
        before = sha256(source)

        result = remediate_file(
            source, tmp_path / "out", tmp_path / "in", Config(), enable_tagging=True
        )

        assert result.succeeded, result.error
        assert sha256(source) == before
        output = Path(result.output)
        assert output == tmp_path / "out" / "doc.pdf"
        with pikepdf.open(output) as pdf:
            with pdf.open_metadata() as meta:
                assert "pdfuaid:part" not in meta
        assert "declared_pdfua" not in result.changes
        assert result.changes["links_added"] == 1

    def test_output_equal_to_source_is_an_error_not_an_overwrite(self, pdf_factory, tmp_path):
        source = pdf_factory("in/doc.pdf", text="hello")
        before = sha256(source)
        result = remediate_file(
            source, tmp_path / "in", tmp_path / "in", Config(), enable_tagging=False
        )
        assert not result.succeeded
        assert "overwrite" in result.error
        assert sha256(source) == before

    def test_staged_file_is_removed_when_first_save_fails(
        self, pdf_factory, tmp_path, monkeypatch
    ):
        source = pdf_factory("in/doc.pdf", text="hello")
        staging = tmp_path / "staging"
        staging.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(staging))

        def failing_save(self, *args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(fitz.Document, "save", failing_save)

        result = remediate_file(
            source, tmp_path / "out", tmp_path / "in", Config(), enable_tagging=False
        )

        assert not result.succeeded
        assert "disk full" in result.error
        assert list(staging.iterdir()) == []

    def test_staged_file_is_removed_on_success(self, pdf_factory, tmp_path, monkeypatch):
        source = pdf_factory("in/doc.pdf", text="hello")
        staging = tmp_path / "staging"
        staging.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(staging))

        result = remediate_file(
            source, tmp_path / "out", tmp_path / "in", Config(), enable_tagging=False
        )

        assert result.succeeded, result.error
        assert list(staging.iterdir()) == []

    def test_empty_file_is_rejected(self, tmp_path):
        source = tmp_path / "empty.pdf"
        source.touch()
        result = remediate_file(source, tmp_path / "out", tmp_path, Config(), True)
        assert "empty" in result.error

    def test_non_pdf_bytes_are_rejected(self, tmp_path):
        source = tmp_path / "fake.pdf"
        source.write_bytes(b"<html>not a pdf</html>")
        result = remediate_file(source, tmp_path / "out", tmp_path, Config(), True)
        assert "missing %PDF- header" in result.error

    def test_preserves_existing_title_and_language_by_default(
        self, pdf_factory, tmp_path
    ):
        source = pdf_factory("in/doc.pdf", text="Executive Summary")
        with pikepdf.open(source, allow_overwriting_input=True) as pdf:
            pdf.docinfo[pikepdf.Name.Title] = pikepdf.String("Annual Report 2025")
            pdf.Root.Lang = pikepdf.String("es-MX")
            pdf.save(source)

        result = remediate_file(
            source, tmp_path / "out", tmp_path / "in", Config(), enable_tagging=False
        )

        assert result.succeeded, result.error
        assert result.changes["title"] == "Annual Report 2025"
        assert result.changes["language"] == "es-MX"
        assert result.changes["title_changed"] is True  # XMP was synchronized.
        assert result.changes["lang"] is False
        with pikepdf.open(result.output) as pdf:
            assert str(pdf.docinfo[pikepdf.Name.Title]) == "Annual Report 2025"
            assert str(pdf.Root.Lang) == "es-MX"

    def test_explicit_title_and_language_replace_existing_values(
        self, pdf_factory, tmp_path
    ):
        source = pdf_factory("in/doc.pdf", text="Executive Summary")
        with pikepdf.open(source, allow_overwriting_input=True) as pdf:
            pdf.docinfo[pikepdf.Name.Title] = pikepdf.String("Old title")
            pdf.Root.Lang = pikepdf.String("es-MX")
            pdf.save(source)

        result = remediate_file(
            source,
            tmp_path / "out",
            tmp_path / "in",
            Config(lang="fr-FR"),
            enable_tagging=False,
            title_override="New title",
            language_override=True,
        )

        assert result.succeeded, result.error
        assert result.changes["title"] == "New title"
        assert result.changes["language"] == "fr-FR"
        assert result.changes["title_changed"] is True
        assert result.changes["lang"] is True


def test_package_version_matches_pyproject():
    import tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject.open("rb") as handle:
        declared = tomllib.load(handle)["project"]["version"]
    assert __version__ == declared
