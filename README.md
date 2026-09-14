# ♿📄 pdf-a11y

A batch tool that repairs the accessibility defects in untagged PDFs using only the PDF file itself — no InDesign, no Word doc, no original source required.

## The pile of PDFs nobody can fix anymore

Every department ends up with a folder of PDFs — old lecture slides, event flyers, posters, syllabi — that need to meet accessibility requirements (WCAG, PDF/UA) but whose source files are long gone. Without the original InDesign or Word document, "just re-export it properly" isn't an option. Fixing these by hand means opening each file in Acrobat, adding a language tag, retitling it, building a structure tree, and tagging every heading and link one at a time. For a handful of files that's tedious. For hundreds, it's not realistic — so the PDFs stay broken.

## What this tool actually does

pdf-a11y audits a PDF, then applies every fix that can be determined safely and automatically:

- Sets the document language and a real title (derived from the content, not the filename)
- Turns plain-text URLs and email addresses into real link annotations, with tab order set
- Adds descriptive alt text to link annotations
- Builds a heuristic structure tree — headings, paragraphs, lists — by comparing two independent PDF parses (PyMuPDF and pikepdf) and only tagging a page when their reading order agrees

It refuses to guess where guessing would be dangerous. If a page's content stream contains constructs it can't reason about (images, shading, nested marked content), or the two extraction passes disagree on reading order, that page — or the whole file — is left untouched rather than tagged incorrectly. A file that's still untagged is recoverable; one with a wrong reading order silently misleads a screen reader. What it can't fix (image alt text, table headers, OCR for scanned pages) is reported in a manual work-list per file, and it never claims PDF/UA conformance — that still requires a validator like veraPDF and human review.

## A concrete run

```sh
# See the size of the problem first
python3 main.py in/ --recursive --audit-only --report-dir reports

# Fix everything that can be fixed automatically
python3 main.py in/ --recursive --out-dir out
```

`reports/audit.csv` lists every file with its blocker and warning counts:

```
path,pages,blockers,warnings,codes,error
in/sample-doc-final4.pdf,12,3,1,untagged;no_lang;no_title;raw_url_link_text,
```

After remediation, `reports/remediation.csv` shows what changed and what's left for a human:

```
source,output,blockers_before,links_added,tagged_pages,skipped_pages,unresolved_addresses,manual_work,error
in/sample-doc-final4.pdf,out/sample-doc-final4.pdf,3,2,12,0,,Spot-check the generated heading levels and reading order in a validator. | Confirm tables, if any, have header cells; this tool cannot infer them.,
```

## Usage

Requires Python 3.13+. Install with [uv](https://docs.astral.sh/uv/) or pip:

```sh
uv sync
```

**Audit only** — report findings without writing anything:

```sh
python3 main.py /path/to/pdfs --recursive --audit-only
```

**Remediate** — write repaired copies to a separate directory:

```sh
python3 main.py /path/to/pdfs --recursive --out-dir /path/to/fixed
```

The output directory can't be inside the input tree — this stops a run from overwriting its own sources or re-processing already-fixed files.

Other flags:

| Flag | Purpose |
|---|---|
| `--report-dir DIR` | Where audit/remediation reports go (default `./reports`) |
| `--no-tagging` | Apply only the deterministic fixes (language, title, links); skip the structure tree |
| `--dry-run` | List the files that would be processed, then stop |
| `--lang TAG` | Force a BCP 47 language tag (default `en-US`) |
| `--title TEXT` | Force this title on every file, instead of deriving one per file |
| `--workers N` | Parallel worker processes (default 4) |

Configuration can also come from environment variables: `PDF_A11Y_LANG`, `PDF_A11Y_LOG_LEVEL`, `PDF_A11Y_WORKERS`, `PDF_A11Y_MAX_FILE_MB`.

Verify the result with a real validator:

```sh
verapdf --flavour ua1 --format text /path/to/fixed/*.pdf
```

Run the test suite with:

```sh
uv run python -m pytest -q
```

<br>
