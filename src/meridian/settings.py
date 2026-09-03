"""Every constant and path in one place.

ROOT is the repository checkout, because the data, cache, config and results
live beside the code. Override with MERIDIAN_ROOT if they live elsewhere.
"""
from __future__ import annotations

import os

ROOT = os.environ.get(
    "MERIDIAN_ROOT",
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA = os.path.join(ROOT, "data")
DOCS = os.path.join(DATA, "docs")
CACHE = os.path.join(ROOT, "cache")
CONFIG = os.path.join(ROOT, "config")
RESULTS = os.path.join(ROOT, "results")

# The two readers. Both lite-class: free-tier quota on every Flash-tier model
# runs out after about twenty requests a day (FRICTION F-010).
PRIMARY = "gemini-3.5-flash-lite"
VERIFIER = "gemini-3.1-flash-lite"

# Meridian's field-level accuracy target, and their monthly document volume.
MERIDIAN_BAR = 0.97
MONTHLY_VOLUME = 40_000

# Dataset generation. The seed fixes every label and every rendered pixel.
SEED = 20260902
CORPUS_VERSION = 3
DOC_EXT = ".jpg"                                   # scans arrive as JPEG
FONT_DIR = "/System/Library/Fonts/Supplemental"    # macOS; see README

# Bump when the prompt text changes so old cache entries miss instead of
# scoring a new prompt against old responses.
PROMPT_VERSION = "v2-reconciliation"

# Free-tier pacing. Not a retry library. The published rate-limit tables no
# longer give per-model numbers and a 429 does not say what the limit is, so
# the interval is found by backing off until calls succeed.
MIN_INTERVAL_S = 2.0
MAX_INTERVAL_S = 30.0
RATE_LIMIT_ATTEMPTS = 6
