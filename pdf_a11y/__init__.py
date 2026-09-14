"""Batch accessibility remediation for untagged PDFs.

Fixes the deterministic WCAG / PDF-UA failures that can be repaired without
the original authoring source: document language, title metadata, viewer
title display, URI link annotations, artifact marking and a heuristic
structure tree.

Structural tagging produced here is machine-generated. It is a large
improvement over an untagged file but it is not a substitute for human
review of the resulting reading order.
"""

# Keep in step with [project] version in pyproject.toml.
__version__ = "1.0.0"
