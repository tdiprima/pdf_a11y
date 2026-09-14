"""Command line interface for batch PDF accessibility remediation."""

from __future__ import annotations

import argparse
import logging
import os
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from typing import Callable, TypeVar
from pathlib import Path

from .audit import AuditResult, audit_file
from .config import Config, ConfigError, load_config, validate_lang
from .logging_setup import configure_logging
from .pipeline import RemediationResult, remediate_file
from .report import write_audit_report, write_remediation_report

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_PARTIAL_FAILURE = 3
EXIT_CONFIG = 4
EXIT_WORKER_POOL_BROKEN = 5

ResultT = TypeVar("ResultT", AuditResult, RemediationResult)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-a11y",
        description=(
            "Batch-repair the accessibility defects in untagged PDFs that can be "
            "fixed without the original authoring source."
        ),
    )
    parser.add_argument(
        "input", type=Path, help="A PDF file, or a directory of PDFs."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Directory for repaired PDFs. Required unless --audit-only is used.",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("reports"),
        help="Directory for the JSON and CSV reports. Default: ./reports",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search subdirectories when the input is a directory.",
    )
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="Report findings without writing any repaired files.",
    )
    parser.add_argument(
        "--no-tagging",
        action="store_true",
        help=(
            "Apply only the deterministic fixes (language, title, links). "
            "Skips the heuristic structure tree."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the files that would be processed, then stop.",
    )
    parser.add_argument("--lang", help="BCP 47 language tag. Default: en-US.")
    parser.add_argument(
        "--title",
        help="Force this title on every file. Omit to derive it from each document.",
    )
    parser.add_argument(
        "--workers", type=int, help="Parallel worker processes. Default: 4."
    )
    return parser


def find_pdfs(root: Path, recursive: bool) -> list[Path]:
    """Return the PDFs to process, sorted for a repeatable run order."""
    if root.is_file():
        return [root]
    pattern = "**/*.pdf" if recursive else "*.pdf"
    return sorted(path for path in root.glob(pattern) if path.is_file())


def _resolve_config(arguments: argparse.Namespace) -> Config:
    """Layer command line arguments over environment configuration."""
    config = load_config()
    lang = validate_lang(arguments.lang) if arguments.lang else config.lang
    workers = config.workers

    if arguments.workers is not None:
        if not 1 <= arguments.workers <= 32:
            raise ConfigError(f"--workers must be between 1 and 32, got {arguments.workers}")
        workers = arguments.workers

    return Config(
        lang=lang,
        log_level=config.log_level,
        workers=workers,
        max_file_mb=config.max_file_mb,
    )


def _output_dir_is_safe(output_dir: Path, input_root: Path) -> bool:
    """False when the output directory sits inside the input tree.

    Writing repaired files into the tree being read would overwrite sources
    on this run or feed already-repaired files back in on the next one.
    """
    resolved_output = output_dir.resolve()
    resolved_input = input_root.resolve()
    return resolved_output != resolved_input and not resolved_output.is_relative_to(
        resolved_input
    )


def _collect_result(
    future: Future[ResultT],
    path: Path,
    error_result: Callable[[Path, str], ResultT],
) -> ResultT:
    """Turn an unexpected worker exception into an error result for its file.

    The per-file handlers catch the expected failures; anything else must not
    abort the whole batch and lose the report for every finished file. A dead
    pool is a different problem and is left to the caller.
    """
    try:
        return future.result()
    except BrokenProcessPool:
        raise
    except Exception as error:  # noqa: BLE001 - worker boundary, logged and surfaced
        reason = f"{type(error).__name__}: {error}"
        logger.error("worker_failed", extra={"path": str(path), "reason": reason})
        return error_result(path, reason)


def _audit_error(path: Path, reason: str) -> AuditResult:
    return AuditResult(path=str(path), error=reason)


def _remediation_error(path: Path, reason: str) -> RemediationResult:
    return RemediationResult(source=str(path), error=reason)


def _run_audit(paths: list[Path], config: Config) -> list[AuditResult]:
    """Audit every file in parallel.

    Worker processes are started fresh under spawn and forkserver, so each one
    configures logging itself; without this their output bypasses the
    structured formatter.
    """
    results: list[AuditResult] = []
    with ProcessPoolExecutor(
        max_workers=config.workers,
        initializer=configure_logging,
        initargs=(config.log_level,),
    ) as pool:
        futures = {pool.submit(audit_file, path): path for path in paths}
        for future in as_completed(futures):
            results.append(_collect_result(future, futures[future], _audit_error))
    return sorted(results, key=lambda item: item.path)


def _run_remediation(
    paths: list[Path],
    output_dir: Path,
    input_root: Path,
    config: Config,
    enable_tagging: bool,
    title: str | None,
    language_override: bool,
) -> list[RemediationResult]:
    results: list[RemediationResult] = []
    with ProcessPoolExecutor(
        max_workers=config.workers,
        initializer=configure_logging,
        initargs=(config.log_level,),
    ) as pool:
        futures = {
            pool.submit(
                remediate_file,
                path,
                output_dir,
                input_root,
                config,
                enable_tagging,
                title,
                language_override,
            ): path
            for path in paths
        }
        for future in as_completed(futures):
            results.append(
                _collect_result(future, futures[future], _remediation_error)
            )
    return sorted(results, key=lambda item: item.source)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    arguments = build_parser().parse_args(argv)

    try:
        config = _resolve_config(arguments)
    except ConfigError as error:
        logging.basicConfig()
        logging.getLogger(__name__).error("invalid_configuration", extra={"reason": str(error)})
        return EXIT_CONFIG

    configure_logging(config.log_level)

    if not arguments.input.exists():
        logger.error("input_not_found", extra={"path": str(arguments.input)})
        return EXIT_USAGE

    if not arguments.audit_only and not arguments.dry_run and arguments.out_dir is None:
        logger.error("missing_out_dir", extra={"hint": "pass --out-dir or --audit-only"})
        return EXIT_USAGE

    paths = find_pdfs(arguments.input, arguments.recursive)
    if not paths:
        logger.warning("no_pdfs_found", extra={"path": str(arguments.input)})
        return EXIT_OK

    logger.info("batch_start", extra={"files": len(paths), "workers": config.workers})

    if arguments.dry_run:
        for path in paths:
            logger.info("would_process", extra={"path": str(path)})
        return EXIT_OK

    input_root = arguments.input if arguments.input.is_dir() else arguments.input.parent

    try:
        if arguments.audit_only:
            return _audit_batch(arguments, paths, config)
        return _remediate_batch(arguments, paths, input_root, config)
    except BrokenProcessPool as error:
        logger.error("worker_pool_broken", extra={"reason": str(error)})
        return EXIT_WORKER_POOL_BROKEN


def _audit_batch(arguments: argparse.Namespace, paths: list[Path], config: Config) -> int:
    results = _run_audit(paths, config)
    write_audit_report(arguments.report_dir, results)
    failed = sum(1 for item in results if item.error)
    logger.info(
        "audit_complete",
        extra={
            "files": len(results),
            "unreadable": failed,
            "total_blockers": sum(item.blockers for item in results),
            "report_dir": str(arguments.report_dir),
        },
    )
    return EXIT_PARTIAL_FAILURE if failed else EXIT_OK


def _remediate_batch(
    arguments: argparse.Namespace, paths: list[Path], input_root: Path, config: Config
) -> int:
    if not _output_dir_is_safe(arguments.out_dir, input_root):
        logger.error(
            "out_dir_inside_input",
            extra={"out_dir": str(arguments.out_dir), "input": str(input_root)},
        )
        return EXIT_USAGE

    arguments.out_dir.mkdir(parents=True, exist_ok=True)
    results = _run_remediation(
        paths,
        arguments.out_dir,
        input_root,
        config,
        enable_tagging=not arguments.no_tagging,
        title=arguments.title,
        language_override=(
            arguments.lang is not None or "PDF_A11Y_LANG" in os.environ
        ),
    )
    write_remediation_report(arguments.report_dir, results)

    failed = sum(1 for item in results if not item.succeeded)
    tagged = sum(int(item.changes.get("tagged_pages", 0) or 0) for item in results)
    logger.info(
        "remediation_complete",
        extra={
            "files": len(results),
            "failed": failed,
            "pages_tagged": tagged,
            "out_dir": str(arguments.out_dir),
            "report_dir": str(arguments.report_dir),
        },
    )
    return EXIT_PARTIAL_FAILURE if failed else EXIT_OK
