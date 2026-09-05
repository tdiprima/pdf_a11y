# pdf-a11y

Batch accessibility remediation for untagged PDFs, for the case where the
original Word/InDesign source is gone and re-exporting is not an option.

It repairs the defects that can be fixed deterministically from the PDF alone,
generates a heuristic structure tree, and reports honestly on what still needs
a human.

## What it fixes automatically

| Defect | Standard | How |
|---|---|---|
| No `/StructTreeRoot` (untagged) | WCAG 1.3.1 (A) | Injects marked content and builds a structure tree of headings, paragraphs and lists |
| `/MarkInfo /Marked` missing | PDF/UA (ISO 14289-1) | Set as part of tagging |
| No document language | WCAG 3.1.1 (A) | Writes catalog `/Lang` |
| Filename announced instead of title | WCAG 2.4.2 (A) | Writes XMP `dc:title` + docinfo `/Title`, sets `/ViewerPreferences /DisplayDocTitle` |
| URLs and emails as dead plain text | WCAG 2.4.4 (A) | Adds `/Link` annotations with URI actions |
| Links announced as raw URLs | WCAG 2.4.4 (A) | Adds `/Contents` descriptions ("Link to py4e.com") |
| Decorative graphics in the reading order | WCAG 1.3.1 (A) | Wraps painted paths as `/Artifact` |
| Skipped heading levels (H1 straight to H3) | PDF/UA 7.4.2 | Remaps the levels used onto a contiguous run from H1 |
| Missing tab order on annotated pages | PDF/UA 7.18.3 | Sets `/Tabs` to `/S` |
| No PDF/UA identifier | PDF/UA 5 | Adds XMP `pdfuaid:part`, but only when every page was tagged |

Link annotations are nested inside the paragraph they appear in, with an
`OBJR` reference, so they are announced in reading order rather than collected
at the end of the document.

## What it cannot fix

These are reported, never guessed at:

- **Alternative text for images.** Requires a human who can see the image.
- **Scanned pages with no text layer.** Requires OCR first.
- **Table header cells.** Row/column header semantics cannot be inferred safely.
- **Heading levels.** Generated from font size and weight, then flattened to
  a gap-free outline. Correct on consistent Word exports, worth spot-checking
  on anything unusual. The remap assumes the shallowest heading appears first;
  a document that opens with a subheading may still report a level jump.
- **Whether the text actually reads correctly.** Machine tagging passes the
  validator; it does not guarantee a good listening experience.

## Safety model

The tool fails closed. A page is left untagged rather than tagged wrongly when
it contains:

- XObjects, shadings or inline images (`Do`, `sh`, `BI`)
- existing marked content
- unbalanced `BT`/`ET` nesting
- a mismatch between the content stream's text runs and the extracted text
  lines, or under 90% agreement on their vertical ordering

Input files are never modified in place; repaired copies are written to
`--out-dir`, mirroring the input tree.

Text and rendering are preserved exactly. On the reference document, extracted
text is byte-identical and rendered pages are pixel-identical at 150 dpi.

## Install

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On RHEL/Rocky, `python3.11` or newer from AppStream works:

```bash
sudo dnf install python3.11 python3.11-pip
```

## Usage

Audit a tree first, to see the size of the problem:

```bash
python3 main.py /srv/syllabi --recursive --audit-only --report-dir reports
```

Repair everything:

```bash
python3 main.py /srv/syllabi --recursive \
  --out-dir /srv/syllabi-fixed \
  --report-dir reports
```

Deterministic fixes only, skipping the heuristic structure tree:

```bash
python3 main.py /srv/syllabi --recursive --out-dir /srv/syllabi-fixed --no-tagging
```

### Options

| Flag | Purpose |
|---|---|
| `--out-dir` | Where repaired PDFs go. Required unless `--audit-only`. |
| `--report-dir` | JSON and CSV reports. Default `./reports`. |
| `--recursive` | Descend into subdirectories. |
| `--audit-only` | Report findings, write no files. |
| `--no-tagging` | Skip the structure tree; apply only deterministic fixes. |
| `--dry-run` | List what would be processed, then stop. |
| `--lang` | BCP 47 language tag. Default `en-US`. |
| `--title` | Force one title on every file. |
| `--workers` | Parallel processes. Default 4. |

### Configuration

Command line flags win over environment variables.

| Variable | Default | Meaning |
|---|---|---|
| `PDF_A11Y_LANG` | `en-US` | Document language |
| `PDF_A11Y_LOG_LEVEL` | `INFO` | Log verbosity |
| `PDF_A11Y_WORKERS` | `4` | Parallel processes |
| `PDF_A11Y_MAX_FILE_MB` | `200` | Per-file size ceiling |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | All files processed |
| 2 | Usage error |
| 3 | Some files failed; see the report |
| 4 | Invalid configuration |

## Reports

`remediation.csv` is the triage sheet: one row per file, with the manual work
each still needs. `remediation.json` carries the full findings, including the
pre-repair audit. Logs are JSON on stderr; reports are files, so stdout stays
clean for piping.

## Recommended workflow for a large corpus

1. `--audit-only` across everything. Sort `audit.csv` by blocker count.
2. Pull out files flagged `no_text_layer` — they need OCR (`ocrmypdf`) before
   this tool is any use.
3. Run the repair on the rest.
4. Validate a sample. See "Validating the output" below.
5. Hand-remediate the files whose reports list skipped pages or images.

## Validating the output

Validate against a real PDF/UA checker, not this tool's own audit — a checker
written by the same author as the fixer will agree with itself.

**veraPDF** — cross-platform, scriptable, and the right choice for a large
corpus. Java, GPLv3+/MPLv2+, runs on Linux and macOS, and validates PDF/UA-1
(ISO 14289-1) from the command line.

- <https://verapdf.org/software/>
- macOS: `brew install verapdf`
- Linux: download the installer from the link above (needs a JRE)

```bash
verapdf --flavour ua1 --format text /srv/syllabi-fixed/*.pdf
```

The reference document validates clean after remediation:

```
PASS out/BMI503_Syllabus_Fall2022.pdf ua1
106 rules passed, 0 failed / 10228 checks passed, 0 failed
```

Before remediation the same file failed 532 checks across 6 rules.

`--flavour ua1` must be given explicitly. Without it veraPDF autodetects from
metadata and will check PDF/A instead.

**PAC** — the reference PDF/UA checker, free and no registration, published by
the PDF/UA Foundation. Best per-file report, including a screen-reader preview.
**Windows only** (Windows 10/11, .NET Framework 4.8+), so it will not run on
your Mac or on a Linux batch host.

- <https://pac.pdf-accessibility.org/en/download>

The current release is **PAC 2026.1**, not PAC 2024 — the name changes with the
year, so search results for older versions are stale.

**Adobe Acrobat Pro** — its Accessibility Checker is a reasonable third opinion
if you already have a licence.

## Verification

```bash
python3 -m pytest tests/ -q
```

The suite covers empty input, blank lines, degenerate font sizes, page
boundaries, oversized input and adversarial text. Mutating any of the five
core heuristics causes at least one test to fail.

https://verapdf.org/software/

<br>

