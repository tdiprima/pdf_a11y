"""Batch boundary behaviour: one bad file must not sink the batch, and the
output directory must never sit inside the input tree."""

from __future__ import annotations

from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pytest

from pdf_a11y import cli
from pdf_a11y.audit import AuditResult
from pdf_a11y.cli import (
    EXIT_OK,
    EXIT_USAGE,
    _audit_error,
    _collect_result,
    _output_dir_is_safe,
    _remediation_error,
)
from pdf_a11y.pipeline import RemediationResult


class TestOutputDirIsSafe:
    def test_same_directory_is_unsafe(self, tmp_path):
        assert not _output_dir_is_safe(tmp_path, tmp_path)

    def test_subdirectory_is_unsafe(self, tmp_path):
        assert not _output_dir_is_safe(tmp_path / "in" / "out", tmp_path / "in")

    def test_relative_alias_of_same_directory_is_unsafe(self, tmp_path, monkeypatch):
        (tmp_path / "docs").mkdir()
        monkeypatch.chdir(tmp_path)
        assert not _output_dir_is_safe(Path("docs"), tmp_path / "docs")

    def test_sibling_is_safe(self, tmp_path):
        assert _output_dir_is_safe(tmp_path / "out", tmp_path / "in")

    def test_parent_is_safe(self, tmp_path):
        assert _output_dir_is_safe(tmp_path, tmp_path / "in")

    def test_prefix_match_is_not_containment(self, tmp_path):
        # "in-fixed" starts with "in" but is a sibling, not a child.
        assert _output_dir_is_safe(tmp_path / "in-fixed", tmp_path / "in")


class TestCollectResult:
    def test_returns_the_worker_result(self):
        future: Future[AuditResult] = Future()
        expected = AuditResult(path="a.pdf", pages=3)
        future.set_result(expected)
        assert _collect_result(future, Path("a.pdf"), _audit_error) is expected

    @pytest.mark.parametrize("error", [KeyError("/Annots"), TypeError("bad"), MemoryError()])
    def test_unexpected_exception_becomes_error_result(self, error):
        future: Future[RemediationResult] = Future()
        future.set_exception(error)
        result = _collect_result(future, Path("bad.pdf"), _remediation_error)
        assert result.source == "bad.pdf"
        assert not result.succeeded
        assert type(error).__name__ in result.error

    def test_broken_pool_is_not_swallowed(self):
        future: Future[AuditResult] = Future()
        future.set_exception(BrokenProcessPool("worker died"))
        with pytest.raises(BrokenProcessPool):
            _collect_result(future, Path("a.pdf"), _audit_error)


class TestMain:
    def test_out_dir_inside_input_is_rejected_before_any_work(self, pdf_factory, tmp_path):
        pdf_factory("in/doc.pdf", text="hello")
        code = cli.main(
            [str(tmp_path / "in"), "--out-dir", str(tmp_path / "in"), "--report-dir", str(tmp_path / "r")]
        )
        assert code == EXIT_USAGE
        assert not (tmp_path / "r").exists()

    def test_missing_out_dir_is_usage_error(self, pdf_factory, tmp_path):
        pdf_factory("in/doc.pdf", text="hello")
        assert cli.main([str(tmp_path / "in")]) == EXIT_USAGE

    def test_batch_writes_report_and_unresolved_column(self, pdf_factory, tmp_path):
        pdf_factory("in/doc.pdf", text="Visit https://example.com/p now")
        code = cli.main(
            [
                str(tmp_path / "in"),
                "--out-dir", str(tmp_path / "out"),
                "--report-dir", str(tmp_path / "r"),
                "--workers", "1",
                "--no-tagging",
            ]
        )
        assert code == EXIT_OK
        header = (tmp_path / "r" / "remediation.csv").read_text().splitlines()[0]
        assert "unresolved_addresses" in header.split(",")
        assert (tmp_path / "out" / "doc.pdf").is_file()
