# Meridian Claims: field extraction and evaluation

This repository contains a structured-extraction prototype and an evaluation
harness for six payment-critical fields on scanned claims documents. The
extractor returns a value and a confidence for each field and can route a field
to an exception queue instead of answering. The harness exists to answer one
question: does the system know when it is unsure?

The design follows the cost asymmetry of the task. A wrong payout is far more
expensive than a flagged exception, so the system abstains rather than guesses,
and the harness measures whether those abstentions are worth anything.

The code was written with Claude (Opus 5), and the briefing and walkthrough
script were drafted with Claude and Gemini. The corpus comes from a seeded
generator. No model produced a document or a label, and every label was written
before its document existed.

---

## How to run it

Install the package once, on Python 3.9 or newer, and then run two commands.
The second command needs no API key.

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install --upgrade pip && pip install -e ".[test]"
```

```bash
export GEMINI_API_KEY=... && meridian-extract --split test --all-models
```

```bash
meridian-evaluate
```

The `meridian-evaluate` command scores the committed response cache. It is
deterministic, it needs no network, and two consecutive runs produce a
byte-identical `results/results.json`. The `meridian-extract` command is needed
only to rebuild that cache. If more repeat runs are requested than the cache
holds, the harness scores the runs that exist and says so.

The tests run in under a second and need no API key. They cover the scoring
primitives, the cache-freshness guard, and an end-to-end check that the
committed cache reproduces the committed `results.json`.

```bash
pytest
```

The corpus can be rebuilt deterministically from its seed.

```bash
meridian-generate
```

Rendering uses the macOS system fonts in `/System/Library/Fonts/Supplemental`.
On another platform, use the committed corpus in `data/`, because the response
cache is keyed on the image bytes and a different font changes them.

Throughput is measured with live calls.

```bash
meridian-throughput --split test --levels 1,2,4,8,16
```

---

## The partner briefing

The architecture, the evaluation plan, and the friction log for the GDM core
modeling and product teams are in [`docs/BRIEFING.html`](docs/BRIEFING.html).
GitHub displays the file as source, so download it and open it in a browser.
The script for the recorded walkthrough is in
[`docs/RUNOFSHOW.html`](docs/RUNOFSHOW.html).

---

## Architecture

```
 data/labels.jsonl ──────┐   authored first, from a fixed seed
                         │
                         ▼
 meridian.dataset ── renders ──▶ data/docs/*.jpg     (labels -> documents, never the reverse)
                         │
                         ▼
 meridian.extract ──▶ meridian.client ──▶ Gemini (structured output, per-field confidence)
                         │                     │
                         │                     ▼
                         │              cache/<model>/<split>-run<n>/<doc>.json   [committed]
                         ▼
 meridian.harness.run ── scores the cache; never calls the API
      ├── configs.py   four configurations resolved from the same cached calls
      ├── metrics.py   match, error taxonomy, Wilson, calibration, ECE
      └── report.py    terminal table
                         │
                         ▼
              results/results.json      every headline figure and chart series
```

The package lives in `src/meridian/`. The `settings.py` module holds every
constant and path. The `throughput.py` and `batch.py` modules are the two
execution modes measured in the results, and the `dataset/` package is split
into label authoring, rendering, degradation, and the spot-check manifest.

Extraction and scoring are separate programs. The extractor fetches and caches
raw responses, and every later decision, including the abstention threshold,
the escalation threshold, and the choice of configuration, is computed from the
cached confidences. This arrangement gives three things: threshold sweeps cost
no API calls, tuning is reproducible against a fixed set of responses, and the
demo runs offline with identical numbers each time.

Cache entries are keyed on a hash of the model, the prompt version, the schema,
a fixed temperature tag, the run index, and the image bytes. Both the extractor
and the harness recompute the key on read. The extractor treats a mismatch as a
cache miss, and the harness refuses to score one. Without that check,
regenerating the corpus would score new documents against old responses, a
failure that does not crash and instead produces plausible wrong numbers.

The key has two limits. It carries the prompt version rather than the prompt
text, so a test pins the hash of the prompt and fails when the text changes
without a version bump. Generation settings other than temperature are left at
the service defaults and are not part of the key, and the model name is an
alias, so a service-side model update between two runs would not be detected.

### The four configurations

| Configuration | Calls per document | Uncertainty signal | Question it answers |
|---|---|---|---|
| `primary_solo` | 1 | Self-reported confidence | Is the cheapest configuration good enough? |
| `verifier_solo` | 1 | Self-reported confidence | Can the second reader stand on its own? |
| `cascade` | 1, plus 1 when unsure | Self-reported confidence | Does the standard cost-saving pattern work here? |
| `double_key` | 2 on every document | Disagreement between readers | Can uncertainty be measured without self-assessment? |

`cascade` bets that self-reported confidence carries information, and
`double_key` assumes that it does not and uses disagreement between two readers
instead. Both are measured. The cascade escalates per document on the lowest
field confidence and takes all six of the verifier's values when it does,
because the API cannot re-read one field for less than the cost of the page.

---

## Dataset

Every ground-truth record is authored as JSON by `meridian.dataset.labels` from
a fixed seed, and each document image is rendered from its record. Labels are
written to disk before any document exists, so nothing downstream can affect
the ground truth.

The corpus holds 80 documents, 40 in the tune split and 40 in the test split,
stratified as shown below. The split is frozen in `data/splits.json` and was
set before the first API call. The test split was scored once.

| Stratum | n | Tune | Test | What it tests |
|---|---|---|---|---|
| clean | 24 | 12 | 12 | Baseline accuracy on legible intake. |
| ambiguous | 16 | 8 | 8 | Two plausible totals on one page. |
| degraded | 16 | 8 | 8 | Skew, noise, faded toner, stamps, and handwriting. |
| incomplete | 16 | 8 | 8 | A required field that is absent. |
| out-of-distribution | 8 | 4 | 4 | A page of the wrong document type. |

Every stratum carries scanner noise and JPEG loss; there is no clean digital
page in the corpus.

Ambiguity uses three mechanisms so that no single heuristic solves the stratum:
a second total under a different label (`AMOUNT BILLED` against `TOTAL DUE`), a
subtotal that differs from the true total by one transposed digit, and a
printed total struck through and corrected by hand. The distractor sits above
or below the true total, so a rule that takes the last figure on the page does
not work.

Incompleteness uses two mechanisms: either the row is dropped, or the field
label is printed above an empty rule. The second invites a guess. The hardest
item is a page on which `total_amount` is blank while the line items still sum
to a plausible number.

Out-of-distribution pages carry no marker saying that they are not claims. One
utility bill shows an "Amount Due" line to bait the payment field.

### Difficulty ceiling

The degraded stratum was pulled back during development. The first version was
illegible on inspection, and if a human keyer cannot recover a value, the
ground truth is not derivable from the document and the item tests nothing. The
degradation bounds were set by reading rendered pages rather than by looking at
model scores.

### Corpus v1

The first corpus was too easy. `primary_solo` scored 240 of 240 field-instances
with no errors, so the calibration curve had a single bucket and abstention
precision was 0/0. Most of the headline metrics measured nothing. That result is
preserved in `results/v1_corpus_saturation.json`, produced by the same harness.
The hardening described above was specified before anything was rescored.

### Spot check

The file `data/spot_check.md` flags 10 of the 80 records for manual label
verification. They were chosen for difficulty rather than at random and cover
all five strata and both splits. Each entry links to the image and lists the
expected values.

---

## Metric definitions

A field-instance is one pair of a document and a field. Rates are computed over
field-instances because Meridian pays per field.

- **Exact match** requires the prediction to be byte-identical to the label.
- **Normalized match** requires equality after type-aware canonicalization:
  money is reduced to decimal cents, dates to ISO format, names are folded for
  case, accents, and punctuation, and identifiers are stripped of separators.
  Both measures are reported, and they are never merged. Name normalization
  keeps token order, so `Ferraro, Dolores` and `Dolores Ferraro` remain
  different.
- **The error taxonomy** has three mutually exclusive kinds, reported
  separately because their costs differ. A `wrong_value` means that a value was
  emitted, the label has a value, and they differ; this is a wrong payout. A
  `missed_field` means that the model said the field was absent when the label
  has a value; this is a rekey. A `hallucinated_field` means that a value was
  emitted where the label has none; it is measurable only because the
  incomplete and out-of-distribution strata exist.
- **Coverage** is the share of field-instances that were not routed to the
  exception queue.
- **Accuracy on covered** is accuracy over the field-instances that were
  processed automatically. The 97% bar applies to this number. It is never
  shown without coverage, because a system that abstains on everything reports
  100%.
- **Abstention precision** is the share of flagged instances that would have
  been wrong. It requires every instance to record what the outcome would have
  been without abstention. It is shown as `n/a` when nothing was flagged, since
  0/0 is undefined.
- **Abstention recall** is the share of instances that would have been wrong
  and were caught by a flag.
- **Calibration** buckets predictions into ten bins by stated confidence and
  compares observed accuracy with mean stated confidence in each bin. The
  expected calibration error (ECE) is the count-weighted mean gap; a model that
  says 1.0 while being right 90% of the time scores 0.10. A bin counts toward
  the curve only when it holds at least five predictions, and the harness marks
  a curve `degenerate: true` when fewer than two bins qualify, so a lone
  prediction in a second bin does not make a curve. Bins are right-closed, so a
  stated 0.9 falls in the 0.8 to 0.9 bin; the ECE does not depend on that
  convention.
- **Wilson 95% intervals** are reported on every proportion. These proportions
  sit near 1.0 at sample sizes between 40 and 240, where the normal
  approximation produces intervals above 1.0.
- The **paired comparison** treats every configuration as scored on the same
  documents, so the difference between two configurations is a paired quantity
  and its interval is tighter than two overlapping one-sample intervals
  suggest. Each configuration is compared with `primary_solo` on two quantities
  that remain defined when coverage differs: wrong emissions, meaning a
  `wrong_value` or a `hallucinated_field` that left the system, and coverage.
  Discordant instances are tested with McNemar's exact test, and the bootstrap
  resamples documents rather than field-instances because the six fields on one
  page share one scan.
- **Run-to-run variance** is measured by running the full evaluation repeatedly
  at temperature 0 and reporting the spread.
- **Cost** is computed from the `usage_metadata` token counts against the
  prices in `config/pricing.json`. Thinking tokens are added to output tokens
  because they are billed at the output rate.
- **Latency** is the measured serial wall-clock time at the 50th and 95th
  percentiles. Back-off sleeps are excluded.

---

## Results

All figures below are for the test split of corpus v3: 40 documents, 240
field-instances, and one run at temperature 0. Thresholds were tuned on the
tune split only, and the test split was scored once. Every number traces to
`results/results.json`, and every interval is a Wilson 95% interval.

### The frontier

| Configuration | Accuracy on covered | Coverage | Bad-claim recall | Abstention precision | Cost per document | Cost per month at 40,000 documents | p50 latency |
|---|---|---|---|---|---|---|---|
| `primary_solo` | 99.17% [97.0–99.8] | 100% | 100% [75.8–100] | n/a | $0.00132 | $52.8 | 2.17 s |
| `cascade` | 99.17% [97.0–99.8] | 100% | 100% [75.8–100] | n/a | $0.00132 | $52.8 | 2.17 s |
| `double_key` | 100.00% [98.4–100.0] | 96.7% | 100% [75.8–100] | 25.0% [7.1–59.1] | $0.00221 | $88.3 | 5.58 s |
| `verifier_solo` | 97.08% [94.1–98.6] | 100% | 91.7% [64.6–98.5] | n/a | $0.00089 | $35.6 | 3.24 s |

Tuning chose an abstention threshold of 0.0 for every configuration that uses
self-reported confidence, so none of them abstains; full coverage already
cleared the bar on the tune split, and the objective maximizes coverage. Only
`double_key` abstains, and it does so on disagreement. The objective encodes
the cost asymmetry through the 97% bar rather than through a price per error;
with a price per wrong payout, the thresholds would move.

Against the bar, `primary_solo` clears 97% with its lower bound at exactly
97.0%, which leaves no margin. `double_key` clears it with a lower bound of
98.4% at about a ninth of the $0.02 budget. The interval for `verifier_solo`
crosses the bar. Cost is not the binding constraint anywhere in this table.

### The cascade escalated nothing

`cascade` is identical to `primary_solo` on every metric, and on the test split
that is true by construction: tuning set the escalation threshold to 0.0, so no
page was sent to the verifier. The cascade was tested on the tune split, where
the sweep tried every observed confidence as a threshold.

| Escalate when any field is below | Pages escalated | Accuracy on covered | Cost per document |
|---|---|---|---|
| Never (the chosen setting) | 0% | 98.75% | $0.00132 |
| 0.95 | 10% | 98.75% | $0.00141 |
| 0.99 | 15% | 98.75% | $0.00146 |
| 1.00 | 100% | 97.92% | $0.00221 |

No threshold raised accuracy, and sending every page lowered it, because the
verifier is not a stronger reader. That is the first reason the cascade fails
here: the design escalated to a Flash-tier model, quota removed that model
(F-010), and nothing better remained to escalate to. The second reason is the
signal. The verifier's confidence is 1.0 on all 240 instances, and the primary's
is nearly constant as well. On the tune split its three errors all carried a
confidence of 1.0, while on the test split its two errors were its two lowest
confidences, 0.90 and 0.95, both on one degraded page. A threshold below 0.95
would have sent that page to the verifier, which read the total correctly and
the policy number wrong. Five errors across both splits decide nothing about
the signal. They do show that a cascade needs a stronger second reader before
the trigger matters.

### Reconciliation

Reading fields is a transcription task that these models have mostly solved.
Reconciliation, meaning whether the line items sum to the stated total, is the
adjudication task beneath it, and it is where Meridian loses money. Of the 40
test documents, 34 have an itemization and a stated total, and 12 are
inconsistent by construction. `double_key` scores 33 of them, because on one
document the readers disagreed on the total, so the field and its verdict went
to review together.

| | Primary | Verifier | `double_key` |
|---|---|---|---|
| Documents scored | 34 | 34 | 33 |
| Verdict accuracy | 100% [89.8–100] | 97.1% [85.1–99.5] | 100% [89.6–100] |
| Bad-claim recall | 100% [75.8–100] | 91.7% [64.6–98.5] | 100% [74.1–100] |
| False passes (wrong payouts) | 0 | 1 | 0 |
| False flags (review cost) | 0 | 0 | 0 |
| Model arithmetic correct | 100% | 100% | 100% |
| Line items read correctly | 91.2% [77.0–97.0] | 91.2% | 93.9% |

The interval is wide. The primary reader caught all 12 inconsistent claims on
the test split and 12 of 13 on the tune split. With 12 inconsistent claims the
recall interval runs from 76% to 100%, so the miss rate is somewhere under one
in four and cannot be pinned tighter with this many bad claims. The verifier's
one false pass is a claim that would have been paid.

The arithmetic result went against the hypothesis the test was built for. The
model sums its own line items and gives a verdict, and Python sums the same
line items the model extracted and gives its own verdict. Because the inputs
are the same and only the adder differs, any gap between the two verdicts would
be arithmetic. There was no gap. Model arithmetic is 100% on every reader, both
verdict paths fail on the same documents, and every failure is a misread digit
on a degraded scan; line items were read correctly 91.2% of the time. The rule
of thumb that a model should never do arithmetic does not apply here. The
arithmetic was free and correct, and the errors came from reading four digits
off a stamped, faded page, which is an image-quality problem.

### Errors, unpooled

| Kind | Primary | Verifier | `double_key` | Business cost |
|---|---|---|---|---|
| `wrong_value` | 2 | 2 | 0 | A wrong payout. |
| `missed_field` | 0 | 0 | 0 | A rekey. |
| `hallucinated_field` | 0 | 5 | 0 | Measurable only because the out-of-distribution and incomplete strata exist. |

The verifier hallucinated five fields on out-of-distribution documents. It read
a utility bill's "Amount Due" as a claim total and an account number as a
policy number, which those pages were built to invite. The primary reader did
not. On its own, the verifier would have emitted five invented values. Under
`double_key` none of them reached the output, because the primary said the
fields were absent, the readers disagreed, and the five instances went to
review. That is the mechanism the second reader exists for: it catches one
reader's confident invention on a page that should have been rejected. On this
sample the invention was the verifier's, so the five flags were review cost
rather than saved payouts. Had the roles been reversed, they would have been
saved payouts.

On `total_amount`, the payment-critical field, either reader alone scored
97.5% [87.1–99.6], and `double_key` scored 100% [90.8–100].

### Normalization

| Field | Exact match | Normalized match |
|---|---|---|
| `total_amount` | 15.0% | 97.5% |
| `date_of_service` | 32.5% | 100% |
| overall | 74.2% | 99.2% |

Exact match compares the prediction with the canonical label rather than with
the printed string, so the 25-point gap measures the size of the formatting
problem that a downstream system would have to solve, for example `$7,374.71`
against `7374.71` or `1 Jun 2026` against `2026-06-01`; it is not a model error
rate. A consumer that skipped normalization would see this pipeline 23 points
under the bar.

### What double-keying costs

`double_key` flags 3.3% of field-instances and reaches 100% on the rest. Of the
8 flags, 2 would have been wrong, which gives a precision of 25.0% [7.1–59.1].
Those two were both of the primary's errors, so recall is 100% [34.2–100] on a
denominator of two. The other six flags are the verifier's five hallucinations
and one disagreement on a degraded policy number, all of them places where the
primary was already right. At Meridian's volume that is roughly 8,000
field-instances a month to the exception queue, on about 4,000 documents, since
4 of the 40 pages carried a flag, against zero wrong payouts in this sample.
With 8 flags, neither number is tight.

### Paired against the primary alone

The separate intervals in the frontier table overstate how different these
systems are. The comparison below scores each configuration against
`primary_solo` on the same 240 field-instances.

| Against `primary_solo` | Wrong emissions | Discordant instances (configuration / primary) | Exact p | Coverage change |
|---|---|---|---|---|
| `double_key` | 0 vs 2 | 0 / 2 | 0.50 | −3.3 pts [−7.5, −0.4] |
| `cascade` | 2 vs 2 | 0 / 0 | 1.00 | 0 |
| `verifier_solo` | 7 vs 2 | 6 / 1 | 0.125 | 0 |

`double_key` removed both wrong emissions and added none, but two discordant
instances cannot separate two systems (p = 0.50). The one difference this
sample establishes is the cost: 3.3 points of coverage, with an interval clear
of zero. `verifier_solo` added six wrong emissions and removed one, which falls
short of significance at this sample size. `cascade` is identical to
`primary_solo`.

### Variance

Run-to-run variance at temperature 0 was measured on the corpus v2 test split
over three runs, before reconciliation was added, and that results file is
preserved as `results/v2_variance.json`. Accuracy on covered moved 0.4 points
across the three runs (0.9958, 0.9958, 0.9917), and ECE ranged from 0.0019 to
0.0069. The v3 test split has one complete run: the verifier has three runs
cached and the primary has one, and every paired configuration needs both. The
verifier's three runs return identical values on all 40 documents. Two more
primary runs would cost about $0.10 after a quota reset. Any single v3 figure
should be read as ±0.4 points.

### Throughput at 40,000 documents a month

Throughput was measured on the corpus v2 test split with one full pass per
concurrency level.

| Workers | Documents per minute | Documents per hour | Hours for 40,000 documents | Throttle events | Failed calls |
|---|---|---|---|---|---|
| 1 | 8.0 | 479 | 83.4 | 8 | 1 |
| 2 | 8.3 | 499 | 80.1 | 9 | 1 |
| 4 | 8.2 | 490 | 81.7 | 9 | 0 |
| 8 | 8.0 | 479 | 83.5 | 9 | 0 |
| 16 | 7.0 | 423 | 94.7 | 10 | 0 |

Throughput is bound by quota. It is flat from 1 to 8 workers and drops at 16,
where sixteen workers are 12% slower than one. The ceiling is the account-level
request rate, so extra client parallelism turns into back-off, and past the
knee it costs throughput. Four workers are enough. Processing 40,000 documents
takes about 83 hours of continuous running with no headroom, and the lever is
quota rather than client code. The limiter is one shared gate rather than
per-worker back-off, because N workers backing off independently still put N
times the load on one quota.

### Two levers measured and not used

- Context caching produced no saving. `cached_tokens` was 0 across all 200
  sweep calls, for two reasons. The request places the per-document image
  before the shared prompt, so no two requests share a prefix, and even with
  the prompt first, the shared part is about 350 tokens against a 4,096-token
  minimum on this model family, out of about 1,400 input tokens per document.
  Prompt-first ordering is the change to try; it alters every cache key, so it
  was not made after scoring.
- The Batch API is the right mode for the overnight bulk at 50% of the
  interactive price. It is implemented against the SDK contract in
  `src/meridian/batch.py` and was never successfully submitted, because every
  `batches.create` call returns `400 FAILED_PRECONDITION` while `batches.list`
  succeeds (F-011). No cost figure is claimed for it.

### Corpus history

- Corpus v1 saturated: `primary_solo` scored 240 of 240 with no errors, so
  calibration collapsed to one bucket and abstention precision was 0/0. The
  result is preserved in `results/v1_corpus_saturation.json`.
- Corpus v2 hardened the scans and still produced one error in 240, which
  showed that extraction alone was the wrong task.
- Corpus v3 added itemization and the reconciliation verdict. It is the corpus
  in `data/` and the one every figure above describes.

## Trade-offs

| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| Label provenance | Labels are authored first and documents are rendered from them. | Labels taken from model output, or hand-labeling of generated documents. | A harness whose labels come from a model measures agreement with that model rather than accuracy. |
| Output format | A response schema with a `{value, confidence}` pair per field. | Prompting and parsing free text. | A nullable value makes "absent" a real answer instead of a parse failure. |
| Uncertainty signal | Disagreement between two readers. | Self-reported confidence, log probabilities, and self-consistency. | Log probabilities are disabled (F-006), self-reported confidence is nearly constant, and self-consistency showed 5 of 5 agreement (F-007). |
| Second reader | An independent lite-class peer. | A stronger Flash-tier model. | Free-tier quota stopped each Flash model run toward evaluation volume after about 20 requests (F-010), and for a disagreement signal independence matters more than capability. |
| Escalation | Kept, and expected to fail. | Dropped, or tuned until it helped. | The negative result is the finding, and making the cascade win would have meant tuning on the test split. |
| Thresholds | Swept on the tune split, frozen, and the test split scored once. | Sweeping on the test split. | Tuning on the test split would invalidate every reported number. |
| Scoring | From cached responses, never live. | Live calls during scoring. | Cached scoring gives free sweeps, reproducible tuning, and an offline demo. |
| Intervals | Wilson intervals. | The normal approximation. | The proportions sit near 1.0 at sample sizes of 40 to 240, where the normal approximation exceeds 1.0. |
| Difficulty ceiling | Human legibility. | Whatever made the score interesting. | An illegible page has no derivable ground truth. |

The following were deliberately not built, because the brief asked for
architecture and evaluation rather than production hardening: authentication,
Docker, CI, a web framework, a database, a job queue, a UI, retry libraries,
and additional document types.

---

## Next step

The next step is to ingest 500 real Meridian documents, weighted toward the
exceptions their contractors already flag, and to run this harness on them
unchanged. Everything measured here can be measured again on those documents
without touching the code.
