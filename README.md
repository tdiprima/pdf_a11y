# pdf-a11y

Batch accessibility remediation for untagged PDFs, for the case where the
original Word/InDesign source is gone and re-exporting is not an option.

It repairs the defects that can be fixed deterministically from the PDF alone,
generates a heuristic structure tree, and reports honestly on what still needs
a human.

## Usage

```sh
cd pdf_a11y
```

1. Put your PDFs somewhere, then audit:  
`python3 main.py /path/to/your/pdfs --recursive --audit-only`.  
Open reports/audit.csv. Any row saying `no_text_layer` → needs OCR first.  

2. Fix them:  
`python3 main.py /path/to/your/pdfs --recursive --out-dir /path/to/fixed`.  

3. Check the results:  
`verapdf --flavour ua1 --format text /path/to/fixed/*.pdf`  
Want PASS. Anything that says FAIL, send Claude the filename.

4. Read reports/remediation.csv, column `manual_work` — those files need you.

<br>
