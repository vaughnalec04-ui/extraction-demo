# Meridian Claims: field extraction and evaluation

Structured extraction of six payment-critical fields from scanned claims
documents, with per-field confidence, an abstention path to an exception queue,
and an evaluation harness built to answer one question: does the system know
when it is unsure?

The cost asymmetry drives the design. A wrong payout is far more expensive than
a flagged exception, so the system abstains rather than guesses, and the
harness measures whether the abstentions are worth anything.

The code was written with Claude (Opus 5); the briefing and walkthrough script
were drafted with Claude and Gemini. The corpus comes from a seeded generator:
no model produced a document or a label, and every label was written before
its document existed.

---

## Run it

Install once (Python 3.9 or newer), then two commands. The second needs no
API key.

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install --upgrade pip && pip install -e ".[test]"
```

```bash
export GEMINI_API_KEY=... && meridian-extract --split test --all-models
```

```bash
meridian-evaluate
```

`meridian-evaluate` scores the committed response cache. It is deterministic,
needs no network, and two consecutive runs produce a byte-identical
`results/results.json`. `meridian-extract` is only needed to rebuild that
cache. Asking for more repeat runs than the cache holds scores what exists and
says so.

Tests (no API key, under a second) cover the scoring primitives, the
cache-freshness guard, and an end-to-end check that the committed cache
reproduces the committed `results.json`:

```bash
pytest
```

To rebuild the corpus (deterministic, seeded):

```bash
meridian-generate
```

Rendering uses macOS system fonts from `/System/Library/Fonts/Supplemental`. On
another platform, use the committed corpus in `data/`. The response cache is
keyed on the image bytes, and a different font changes them.

To measure throughput (live calls):

```bash
meridian-throughput --split test --levels 1,2,4,8,16
```

---

## Partner briefing

Architecture, evaluation plan, and the friction log for GDM core modeling and
product are in [`docs/BRIEFING.html`](docs/BRIEFING.html). GitHub shows the
source; download it and open it in a browser. The script for the recorded
walkthrough is [`docs/RUNOFSHOW.html`](docs/RUNOFSHOW.html).

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

The package lives in `src/meridian/`. `settings.py` holds every constant and
path. `throughput.py` and `batch.py` are the two execution modes measured in
the results. `dataset/` is split into labels, render, degrade and the
spot-check manifest.

Extraction and scoring are separate programs. The extractor fetches and caches
raw responses. Every later decision (abstention threshold, escalation
threshold, which configuration) is computed from the cached confidences. That
gives three things: threshold sweeps cost no API calls, tuning is reproducible
against a fixed set of responses, and the demo runs offline with identical
numbers each time.

Cache entries are keyed on a hash of model, prompt version, schema, a fixed
temperature tag, run index and the image bytes. Both the extractor and the
harness recompute the key on read; the extractor treats a mismatch as a miss
and the harness refuses to score it. Without that, regenerating the corpus
would score new documents against old responses, which does not crash and
produces plausible wrong numbers.

Two limits of the key. It carries the prompt version rather than the prompt
text, so a test pins the prompt's hash and fails when the text changes without
a version bump. Generation settings other than temperature are left at service
defaults and are not in the key, and the model name is an alias, so a
service-side model update between two runs would not be detected.

### The four configurations

| config | calls/doc | uncertainty signal | question |
|---|---|---|---|
| `primary_solo` | 1 | self-reported confidence | cheapest thing that could work |
| `verifier_solo` | 1 | self-reported confidence | does the second reader stand alone |
| `cascade` | 1, +1 when unsure | self-reported confidence | the standard cost saver |
| `double_key` | 2, always | cross-reader disagreement | uncertainty without self-assessment |

`cascade` bets that self-reported confidence carries information. `double_key`
assumes it does not and uses disagreement between two readers instead. Both
are measured. `cascade` escalates per document, on the lowest field confidence,
and takes all six of the verifier's values when it does; the API cannot re-read
one field for less than the page.

---

## Dataset

Every ground-truth record is authored as JSON by `meridian.dataset.labels`
from a fixed seed, and each document image is rendered from its record. Labels
are written to disk before any document exists, so nothing downstream can
affect ground truth.

80 documents, 40 tune and 40 test, stratified. The split is frozen in
`data/splits.json` and was set before the first API call. Test was scored once.

| stratum | n | tune | test | what it tests |
|---|---|---|---|---|
| clean | 24 | 12 | 12 | baseline on legible intake |
| ambiguous | 16 | 8 | 8 | two plausible totals on one page |
| degraded | 16 | 8 | 8 | skew, noise, faded toner, stamps, handwriting |
| incomplete | 16 | 8 | 8 | a required field absent |
| out-of-distribution | 8 | 4 | 4 | wrong document type |

Every stratum carries scanner noise and JPEG loss. There is no clean digital
page in the corpus.

Ambiguity uses three mechanisms so no single heuristic solves the stratum: a
differently labelled second total (`AMOUNT BILLED` against `TOTAL DUE`); a
subtotal off from the true total by one transposed digit; and a printed total
struck through and corrected by hand. The distractor sits above or below the
true total, so "last figure on the page" does not work.

Incompleteness uses two mechanisms: the row is dropped, or the field label is
printed above an empty rule. The second invites a guess. The hardest item is a
page where `total_amount` is blank and the line items still sum to a plausible
number.

OOD pages carry no marker saying they are not claims. One utility bill shows an
"Amount Due" to bait the payment field.

### Difficulty ceiling

The degraded stratum was pulled back during development. The first version was
illegible on inspection, and if a keyer cannot recover the value the ground
truth is not derivable from the document, so the item tests nothing.
Degradation bounds were set by reading rendered pages, not by looking at model
scores.

### Corpus v1

The first corpus was too easy. `primary_solo` scored 240 of 240 field-instances
with no errors, so the calibration curve had one bucket and abstention
precision was 0/0. Most of the headline metrics measured nothing. That result
is in `results/v1_corpus_saturation.json`, produced by the same harness. The
hardening described above was specified before anything was rescored.

### Spot check

`data/spot_check.md` flags 10 of the 80 records for manual label verification,
chosen for difficulty rather than at random, across all five strata and both
splits. Each entry links the image and lists the expected values.

---

## Metric definitions

A field-instance is one (document, field) pair. Rates are over field-instances
because Meridian pays per field.

- **Exact match**: byte-identical to the label.
- **Normalized match**: equal after type-aware canonicalization. Money to
  decimal cents, dates to ISO, names case/accent/punctuation-folded,
  identifiers stripped of separators. Both are reported and never merged. Name
  normalization keeps token order: `Ferraro, Dolores` and `Dolores Ferraro`
  stay different.
- **Error taxonomy**, mutually exclusive, reported separately because the costs
  differ:
  - `wrong_value`: a value was emitted, the label has one, they differ. A
    wrong payout.
  - `missed_field`: said absent, the label has a value. A rekey.
  - `hallucinated_field`: emitted a value where the label has none. Only
    measurable because the incomplete and OOD strata exist.
- **Coverage**: share of field-instances not routed to the exception queue.
- **Accuracy on covered**: accuracy over what was auto-processed. The 97% bar
  applies to this number. It is never shown without coverage, since a
  system that abstains on everything reports 100%.
- **Abstention precision**: of the instances flagged, the share that would have
  been wrong. Needs every instance to record what the outcome would have been
  without abstention. Shown as `n/a` when nothing was flagged; 0/0 is
  undefined.
- **Abstention recall**: of everything that would have been wrong, the share
  caught.
- **Calibration**: predictions bucketed into 10 bins by stated confidence;
  observed accuracy against mean stated confidence per bin. ECE is the
  count-weighted mean gap. A model that says 1.0 while being right 90% of the
  time scores 0.10. The harness marks a curve `degenerate: true` when one or
  zero buckets are occupied. Bins are right-closed, so a stated 0.9 sits in the
  0.8–0.9 bin. ECE does not depend on that convention; the occupied-bin count
  does, and on this data it decides whether the curve has two bins or one.
- **Wilson 95% intervals** on every accuracy figure. These proportions sit near
  1.0 at n = 40 to 240, where the normal approximation gives intervals above
  1.0.
- **Paired comparison**: every configuration is scored on the same documents,
  so a difference between two configurations is a paired quantity and its
  interval is tighter than two overlapping one-sample intervals suggest. Each
  configuration is compared with `primary_solo` on two quantities that stay
  defined when coverage differs: wrong emissions (a `wrong_value` or
  `hallucinated_field` that left the system) and coverage. Discordant instances
  get McNemar's exact test. The bootstrap resamples documents, not
  field-instances, because six fields on one page share one scan.
- **Run-to-run variance**: the full evaluation run repeatedly at temperature 0,
  spread reported.
- **Cost**: from `usage_metadata` token counts against the pricing in
  `config/pricing.json`. Thinking tokens are added to output tokens because
  they bill at the output rate.
- **Latency**: p50/p95 serial wall-clock, measured. Back-off sleeps are
  excluded.

---

## Results

Test split, corpus v3, 40 documents / 240 field-instances, one run at
temperature 0. Thresholds were tuned on the tune split only and test was
scored once. Every number traces to `results/results.json`. Intervals are
Wilson 95%.

### Frontier

| config | accuracy on covered | coverage | bad-claim recall | abstention precision | $/doc | $/mo @ 40k | p50 |
|---|---|---|---|---|---|---|---|
| `primary_solo` | 99.17% [97.0–99.8] | 100% | 100% [75.8–100] | n/a | $0.00132 | $52.8 | 2.17s |
| `cascade` | 99.17% [97.0–99.8] | 100% | 100% [75.8–100] | n/a | $0.00132 | $52.8 | 2.17s |
| `double_key` | 100.00% [98.4–100.0] | 96.7% | 100% [75.8–100] | 25.0% [7.1–59.1] | $0.00221 | $88.3 | 5.58s |
| `verifier_solo` | 97.08% [94.1–98.6] | 100% | 91.7% [64.6–98.5] | n/a | $0.00089 | $35.6 | 3.24s |

Tuning chose an abstention threshold of 0.0 for every configuration that uses
self-reported confidence, so none of them abstains: full coverage already
cleared the bar on tune, and the objective maximises coverage. Only
`double_key` abstains, on disagreement. The objective encodes the cost
asymmetry through the 97% bar rather than a price per error; with a price per
wrong payout, the thresholds would move.

Against the bar: `primary_solo` clears 97% with its lower bound at 97.0%, which
is no margin. `double_key` clears it with a 98.4% lower bound at about a ninth
of the $0.02 budget. `verifier_solo`'s interval crosses the bar. Cost is not
the constraint anywhere in this table.

### The cascade escalated nothing

`cascade` is identical to `primary_solo` on every metric, and on test that is
by construction: tuning set the escalation threshold to 0.0, so no page was
sent on. The cascade was tested on tune, where the sweep tried every observed
confidence as a threshold:

| escalate when any field is below | pages escalated | accuracy on covered | $/doc |
|---|---|---|---|
| never (chosen) | 0% | 98.75% | $0.00132 |
| 0.95 | 10% | 98.75% | $0.00141 |
| 0.99 | 15% | 98.75% | $0.00146 |
| 1.00 | 100% | 97.92% | $0.00221 |

No threshold raised accuracy, and sending everything lowered it, because the
verifier is not a stronger reader. That is the first reason the cascade fails
here: the design escalated to a Flash-tier model and quota removed it (F-010),
so there is nothing better to escalate to. The second is the signal. The
verifier's confidence is 1.0 on all 240 instances. The primary's is nearly so:
on tune its three errors all carried 1.0, while on test its two errors were its
two lowest confidences, 0.90 and 0.95, on one degraded page. A threshold under
0.95 would have sent that page to the verifier, which read the total correctly
and the policy number wrong. Five errors across both splits decide nothing
about the signal; they do show that a cascade needs a stronger second reader
before the trigger matters.

### Reconciliation

Reading fields is a transcription task these models mostly have solved.
Reconciliation, whether the line items sum to the stated total, is the
adjudication task under it and is where Meridian loses money. 34 of the 40 test
documents have an itemisation and a stated total; 12 are inconsistent by
construction.
`double_key` scores 33 of them: on 1 the readers disagreed on the total, so
the field and its verdict went to review together.

| | primary | verifier | double_key |
|---|---|---|---|
| documents scored | 34 | 34 | 33 |
| verdict accuracy | 100% [89.8–100] | 97.1% [85.1–99.5] | 100% [89.6–100] |
| bad-claim recall | 100% [75.8–100] | 91.7% [64.6–98.5] | 100% [74.1–100] |
| false pass (wrong payout) | 0 | 1 | 0 |
| false flag (review cost) | 0 | 0 | 0 |
| model arithmetic correct | 100% | 100% | 100% |
| line items read correctly | 91.2% [77.0–97.0] | 91.2% | 93.9% |

The interval is wide. The primary reader caught all 12
inconsistent claims on test and 12 of 13 on tune. With n=12 the recall interval
runs from 76% to 100%. The miss rate is somewhere under one in four and cannot
be pinned tighter with this many bad claims. The verifier's one false pass is a
claim that would have been paid.

The arithmetic result went against the hypothesis the test was built for. The
model sums its own line items and gives a verdict; Python sums the same line
items the model extracted and gives its own verdict. Same inputs, two adders,
so any gap is arithmetic. There was no gap. Model arithmetic is 100% on every
reader, both verdict paths fail on the same documents, and every failure is a
misread digit on a degraded scan (line items read correctly: 91.2%). "Never let
a model do arithmetic" is the wrong lesson here. The arithmetic is free and
correct. The errors come from reading four digits off a stamped, faded page,
which is an image-quality problem.

### Errors, unpooled

| kind | primary | verifier | double_key | business cost |
|---|---|---|---|---|
| `wrong_value` | 2 | 2 | 0 | a wrong payout |
| `missed_field` | 0 | 0 | 0 | a rekey |
| `hallucinated_field` | 0 | 5 | 0 | measurable only because the OOD and incomplete strata exist |

The verifier hallucinated five fields on out-of-distribution documents. It read
a utility bill's "Amount Due" as a claim total and an account number as a
policy number, which those pages were built to invite. The primary reader did
not.
Alone, the verifier would have emitted five invented values. Under `double_key`
none reached output: the primary said absent, the readers disagreed, and the
five instances went to review. That is the mechanism the second reader is for,
catching one reader's confident invention on a page it should have rejected.
On this sample the invention was the verifier's, so the five flags were review
cost rather than saved payouts. Had the roles been reversed, they would have
been saved payouts.

`total_amount` was 97.5% [87.1–99.6] on either reader alone and 100% [90.8–100]
under `double_key`.

### Normalization

| field | exact | normalized |
|---|---|---|
| `total_amount` | 15.0% | 97.5% |
| `date_of_service` | 32.5% | 100% |
| overall | 74.2% | 99.2% |

Exact match compares against the canonical label, not the printed string, so
the 25-point gap is the size of the formatting problem a downstream system has
to solve (`$7,374.71` against `7374.71`, `1 Jun 2026` against `2026-06-01`),
not a model error rate. A consumer that skipped normalization would see this
pipeline 23 points under the bar.

### What double-keying costs

`double_key` flags 3.3% of field-instances and reaches 100% on the rest. Of 8
flags, 2 would have been wrong (precision 25.0% [7.1–59.1]): both of the
primary's errors, so recall is 100% [34.2–100] on a denominator of two. The
other six flags are the verifier's five hallucinations and one disagreement on
a degraded policy number, all places where the primary was already right. At
Meridian's volume that is roughly 8,000 field-instances a month to the
exception queue, on about 4,000 documents (4 of 40 pages carried a flag),
against zero wrong payouts in this sample. With 8 flags, neither number is
tight.

### Paired against the primary alone

The frontier table's separate intervals overstate how different these systems
are. Scored on the same 240 field-instances:

| against `primary_solo` | wrong emissions | discordant (config / primary) | exact p | coverage change |
|---|---|---|---|---|
| `double_key` | 0 vs 2 | 0 / 2 | 0.50 | −3.3 pts [−7.5, −0.4] |
| `cascade` | 2 vs 2 | 0 / 0 | 1.00 | 0 |
| `verifier_solo` | 7 vs 2 | 6 / 1 | 0.125 | 0 |

`double_key` removed both wrong emissions and added none, but two discordant
instances cannot separate two systems (p = 0.50). The one difference this
sample establishes is the cost: 3.3 points of coverage, interval clear of zero.
`verifier_solo` added six wrong emissions and removed one, short of
significance at this size. `cascade` is `primary_solo`.

### Variance

Run-to-run variance at temperature 0 was measured on the corpus v2 test split,
3 runs, before reconciliation was added; that results file is preserved as
`results/v2_variance.json`. Accuracy on covered moved 0.4 points across the
three runs (0.9958, 0.9958, 0.9917) and ECE ranged 0.0019 to 0.0069. The v3
test split has one complete run: the verifier has three cached, the primary
one, and every paired configuration needs both. The verifier's three runs
return identical values on all 40 documents. Two more primary runs would cost
about $0.10 after a quota reset. Treat any single v3 figure as ±0.4 points.

### Throughput at 40,000 documents a month

Measured on the corpus v2 test split, one full pass per concurrency level:

| workers | docs/min | docs/hour | hours for 40k | throttle events | failed calls |
|---|---|---|---|---|---|
| 1 | 8.0 | 479 | 83.4 | 8 | 1 |
| 2 | 8.3 | 499 | 80.1 | 9 | 1 |
| 4 | 8.2 | 490 | 81.7 | 9 | 0 |
| 8 | 8.0 | 479 | 83.5 | 9 | 0 |
| 16 | 7.0 | 423 | 94.7 | 10 | 0 |

Throughput is quota-bound. It is flat from 1 to 8 workers and drops at 16;
sixteen workers is 12% slower than one. The ceiling is account-level
requests-per-minute. Extra client parallelism turns into back-off, and past
the knee it costs throughput. Four workers is enough. 40,000 documents is
about 83 hours of continuous running with no headroom, and the lever is quota,
not client code. The limiter is one shared gate rather than per-worker
back-off, since N workers backing off on their own still put N times the load
on one quota.

### Two levers measured and not used

- Context caching: `cached_tokens` was 0 across all 200 sweep calls. Two
  reasons. The request puts the per-document image before the shared prompt,
  so no two requests share a prefix; and even prompt-first, the shared part is
  about 350 tokens against a 4,096-token minimum on this model family, with
  about 1,400 input tokens per document in total. Prompt-first ordering is the
  change to try; it alters every cache key, so it was not made after scoring.
- Batch API: the right mode for the overnight bulk at 50% of interactive cost.
  Implemented against the SDK contract in `src/meridian/batch.py` and never
  successfully submitted. Every `batches.create` returns `400
  FAILED_PRECONDITION` while `batches.list` succeeds (F-011). No cost figure is
  claimed for it.

### Corpus history

- v1 saturated: `primary_solo` scored 240/240 with no errors, so calibration
  collapsed to one bucket and abstention precision was 0/0. Preserved in
  `results/v1_corpus_saturation.json`.
- v2 hardened the scans and still produced one error in 240. Extraction was
  the wrong task.
- v3 added itemisation and the reconciliation verdict. That is the corpus in
  `data/` and the one every figure above describes.

## Trade-offs

| decision | chosen | rejected | why |
|---|---|---|---|
| Label provenance | Authored first; documents rendered from labels | Labels from model output, or hand-labelling generated docs | A harness whose labels come from a model measures agreement, not accuracy |
| Output format | Response schema with per-field `{value, confidence}` | Prompt-and-parse | Nullable value makes "absent" a real answer instead of a parse failure |
| Uncertainty signal | Cross-reader disagreement | Self-reported confidence; logprobs; self-consistency | Logprobs are disabled (F-006); self-report is constant and self-consistency showed 5/5 agreement (F-007) |
| Second reader | Independent lite-class peer | Stronger Flash tier | Free-tier quota stopped each Flash model run toward evaluation volume after about 20 requests (F-010). For a disagreement signal, independence matters more than capability |
| Escalation | Kept, expected to fail | Dropped, or tuned until it helped | The negative result is the finding. Making it win would have meant tuning on test |
| Thresholds | Swept on tune, frozen, test scored once | Sweeping on test | Not negotiable |
| Scoring | Cached responses, never live | Live | Free sweeps, reproducible tuning, offline demo |
| Intervals | Wilson | Normal approximation | Proportions near 1.0 at n=40 to 240, where the normal approximation exceeds 1.0 |
| Difficulty ceiling | Human legibility | Whatever made the score interesting | An illegible page has no derivable ground truth |

Not built, because the brief is architecture and evaluation rather than
production hardening: auth, Docker, CI, web framework, database, job queue, UI,
retry libraries, additional document types.

---

## Where it falls short

The accuracy bar is met with zero margin and the cost bar with room to spare.
The third requirement, that the system knows when it is unsure, is not met.

1. **Calibration cannot be demonstrated.** 239 of 240 predictions fall in one
   confidence bucket. The ECE of 0.0064 is what a model gets for saying ~1.0
   and being right ~99.2% of the time, not evidence that confidence tracks
   correctness. Closing this needs a calibrated confidence primitive from the
   model: logprobs, or any scalar it does not have to introspect to produce.

2. **Abstention precision is 25% with a CI of [7.1–59.1].** That runs from
   "mostly noise" to "mostly real". With 8 flags on 240 instances they cannot
   be told apart. Closing this needs more errors to observe, which means
   Meridian's own rejected documents.

3. **Too few errors to characterize a failure mode.** The primary reader made
   two wrong-value errors in 240 field-instances; the verifier made two plus
   five hallucinations on OOD pages. Enough to show that double-keying catches
   the hallucinations, not enough to say when either reader fails. Paired
   against the primary alone, `double_key` differs on two instances
   (p = 0.50). Closing this needs real partner documents; the synthetic
   failure distribution is a guess about theirs.

4. **Bad-claim recall is 100% on 12 claims, which is [75.8–100].** Tune showed
   12 of 13. The miss rate is under one in four and cannot be pinned tighter
   with this many inconsistent claims. One false pass on the verifier is a
   claim that would have been paid.

5. **Zero margin on the bar.** `primary_solo`'s lower bound is 97.0% against
   97%, and run-to-run spread on v2 was 0.4 points. It passes on paper and
   should not be presented as comfortable. n≈500 tightens the interval about
   3.5× for about $1.10 of inference across both readers. The v3 test split also has one complete
   run; two more primary runs cost about $0.10 after a quota reset.

6. **The capability-tier comparison never ran.** Free-tier quota blocked it.
   Unknown, not negative.

Next step: ingest 500 real Meridian documents, weighted toward the exceptions
their contractors already flag, and re-run this harness unchanged. The
instrumentation is built; it needs harder inputs.
