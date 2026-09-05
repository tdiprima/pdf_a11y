#!/usr/bin/env python3
"""Entry point for the PDF accessibility remediation tool."""
# See the size of the problem first
# python3 main.py ../in --recursive --audit-only --report-dir ../reports
# Fix them
# python3 main.py ../in --recursive --out-dir ../out

import sys

from pdf_a11y.cli import main

if __name__ == "__main__":
    sys.exit(main())
