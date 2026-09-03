"""This module keeps every constant and path in one place.

ROOT is the repository checkout, because the data, cache, config and results
live beside the code. Setting MERIDIAN_ROOT overrides ROOT if they live elsewhere.
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

# These are the two readers, and both are lite-class. The free-tier quota on each
# Flash model run toward evaluation volume ran out after about twenty requests
# and did not recover during the build (FRICTION F-010).
PRIMARY = "gemini-3.5-flash-lite"
VERIFIER = "gemini-3.1-flash-lite"

# These are Meridian's field-level accuracy target and their monthly document volume.
MERIDIAN_BAR = 0.97
MONTHLY_VOLUME = 40_000

# These values control dataset generation. The seed fixes every label and every
# rendered pixel.
SEED = 20260902
CORPUS_VERSION = 3
DOC_EXT = ".jpg"                                   # Scans arrive as JPEG.
FONT_DIR = "/System/Library/Fonts/Supplemental"    # The README covers this macOS path.

# A calibration bin needs this many predictions before it counts as a point on
# the curve. One prediction in a second bin is not a curve.
MIN_BUCKET_N = 5

# These values configure the paired comparison between configurations scored on
# the same documents.
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = SEED

# This is bumped when the prompt text changes so that old cache entries miss
# instead of scoring a new prompt against old responses.
PROMPT_VERSION = "v2-reconciliation"

# This is free-tier pacing, and it is not a retry library. The published
# rate-limit tables no longer give per-model numbers and a 429 does not say what
# the limit is, so the interval is found by backing off until calls succeed.
MIN_INTERVAL_S = 2.0
MAX_INTERVAL_S = 30.0
RATE_LIMIT_ATTEMPTS = 6
