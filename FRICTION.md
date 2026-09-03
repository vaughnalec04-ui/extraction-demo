# Friction Log

Written at the time each issue happened, with the error text as it appeared.
Nothing here was reconstructed afterwards. Anything I could not confirm was
real was left out.

Buckets: **core modeling** / **API surface** / **documentation** /
**environment**. Environment issues are not Google's surface and are kept
separate.

---

## F-001: `gh` installed but not on `PATH`

- **Bucket:** environment (not a Google surface)
- **Severity:** low
- **Attempting:** confirm the GitHub CLI was installed and authenticated before
  creating the repo.
- **Error:**
  ```
  $ which gh
  gh not found
  $ gh auth status
  (eval):1: command not found: gh
  ```
- **What was actually going on:** the binary was at `~/bin/gh` (v2.98.0) and
  already authenticated. `~/bin` was not on the shell `PATH`.
- **Time lost:** about 5 minutes, and one wrong conclusion that the tool was
  missing.
- **Workaround:** `export PATH="$HOME/bin:$PATH"`.
- **What would help:** a negative `which` is weak evidence. Probe the common
  install locations before concluding a tool is absent.

---

## F-002: `models.list()` advertises models that `generateContent` refuses

- **Bucket:** API surface
- **Severity:** high
- **Attempting:** confirm the planned cascade pair (`gemini-2.5-flash-lite` →
  `gemini-2.5-pro`) was callable before building on it.
- **Error:**
  ```
  ClientError: 404 NOT_FOUND. {'error': {'code': 404, 'message': 'This model
  models/gemini-2.5-flash-lite is no longer available to new users. Please update
  your code to use models/gemini-3.5-flash-lite for the latest features and
  improvements. We recommend you to use the Interactions API.', 'status': 'NOT_FOUND'}}
  ```
  Same shape for `gemini-2.5-pro`, pointing at `models/gemini-3.1-pro-preview`.
- **Contradiction:** `client.models.list()` on the same key returns both
  `models/gemini-2.5-flash-lite` and `models/gemini-2.5-pro` with
  `generateContent` in `supported_actions`. The discovery endpoint and the
  inference endpoint disagree about what the key can call.
- **Time lost:** about 10 minutes, and a model-tier decision already agreed
  with the customer had to be redone.
- **Workaround:** ignore `models.list()` for capability. Probe each candidate
  with a one-token `generate_content` call.
- **What would help:** `models.list()` reflecting per-key availability, or an
  `available_to_caller` flag. A model I cannot call should not be in my list.

## F-003: Pro tier returns 429 on the first call

- **Bucket:** API surface
- **Severity:** high
- **Attempting:** first request to `gemini-3.1-pro-preview`, the model the 404
  in F-002 said to migrate to.
- **Error:**
  ```
  ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You
  exceeded your current quota, please check your plan and billing details. ...
  ```
  Reproduced on retry and on the `gemini-pro-latest` alias. Zero Pro requests
  had been made on this key.
- **Time lost:** about 10 minutes telling this apart from a transient rate limit.
- **Workaround:** none. The cascade had to be re-planned around Flash tiers.
- **What would help:** "you exceeded your current quota" is misleading when
  the real state is "your tier has no quota for this model". A 403 with
  `reason: TIER_NOT_ENTITLED` would have settled it in one call.

## F-004: Transient 503 on a healthy model

- **Bucket:** API surface
- **Severity:** low
- **Attempting:** a trivial `generate_content` against `gemini-3.8-flash`.
- **Error:**
  ```
  ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is
  currently experiencing high demand. Spikes in demand are usually temporary.
  Please try again later.', 'status': 'UNAVAILABLE'}}
  ```
- **What was actually going on:** it succeeded on the next attempt a few
  seconds later. For a moment it was indistinguishable from F-002/F-003.
- **Time lost:** about 3 minutes.
- **Workaround:** retry once before concluding a model is unavailable.
- **What would help:** a `Retry-After` header, or a status distinct from the
  entitlement failures.

## F-005: Warning noise on every run

- **Bucket:** documentation / packaging
- **Severity:** low
- **Attempting:** any `from google import genai` on the system Python (3.9.6).
- **Output**, on every invocation, twice:
  ```
  .../google/auth/__init__.py:54: FutureWarning: You are using a Python version
  3.9 past its end of life. ...
  .../google/oauth2/__init__.py:40: FutureWarning: ... (same message again)
  .../urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports
  OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'.
  ```
- **What was actually going on:** `google-genai` installs and works on 3.9.
  The warning is advisory, fires twice per process, and buries real stderr.
- **Time lost:** about 2 minutes, plus every command since needs `2>/dev/null`,
  which is how a real error gets missed.
- **Workaround:** route stderr to `/dev/null` on demo commands.
- **What would help:** emit the EOL warning once per process, and state the
  supported Python floor in the install docs.

## F-006: Logprobs unavailable

- **Bucket:** core modeling / API surface
- **Severity:** high for this engagement
- **Attempting:** get a token-level probability for each extracted field
  instead of asking the model to self-report confidence.
- **Error:**
  ```
  ClientError: 400 INVALID_ARGUMENT. {'error': {'code': 400, 'message':
  'Logprobs is not enabled for this model', 'status': 'INVALID_ARGUMENT'}}
  ```
  Reproduced with `response_logprobs=True, logprobs=3` and with
  `response_logprobs=True` alone, on `gemini-3.5-flash-lite`.
- **Why it matters here:** Meridian's requirement is that the system knows when
  it is unsure. Logprobs are the one uncertainty signal that does not depend on
  the model assessing itself. Without them, self-report is what is left, and
  F-007 shows it carries no information.
- **Time lost:** about 8 minutes, and a design option gone.
- **Workaround:** none found. Self-consistency was tried as a substitute and
  gave no signal either (F-007).
- **What would help:** logprobs on the lite tiers, or any calibrated scalar the
  model does not have to introspect to produce. Failing that, the model card
  should state logprob availability so this is a documentation lookup.

## F-007: Self-reported confidence is a constant; self-consistency too

- **Bucket:** core modeling
- **Severity:** high for this engagement
- **Attempting:** build a calibration curve from per-field self-reported
  confidence on the 40-document tune split.
- **Observed**, 240 field-instances from `gemini-3.5-flash-lite`:
  ```
  conf=1.00 :  239  (99.6%)
  conf=0.95 :    1  ( 0.4%)
  ```
  The schema told the model to use the full 0.0 to 1.0 range and not default
  high. It defaulted high.
- **Also tried:** self-consistency, 5 samples at temperature 1.0 on the three
  hardest documents (a two-total page, a skewed noisy scan with a handwritten
  amount, a page with no total). All three came back 5/5 identical. No
  disagreement to turn into a confidence.
- **Time lost:** about 20 minutes across both attempts.
- **Workaround:** none. This is an open gap and is reported as one.
- **What would help:** a documented, calibrated confidence primitive. Asking a
  model for a probability produces a number that looks like one and behaves
  like a constant. For a customer whose requirement is "know when you are
  unsure", this is the biggest missing piece.
- **Addendum, corpus v3:** the counts above were logged on corpus v1. On the
  committed v3 tune cache the primary reports 214 x 1.00, 22 x 0.99 and
  4 x 0.95; the verifier reports 1.00 on all 240. The primary's three tune
  errors all carried 1.00. On test its two errors were its two lowest
  confidences, 0.90 and 0.95, on one degraded page. The verifier's confidence
  is a constant; the primary's is nearly one, and five errors decide nothing.

## F-008: One 429 message for two different conditions

- **Bucket:** API surface
- **Severity:** medium
- **Attempting:** extract 80 documents across two model tiers in one pass.
- **Error**, on 23 of 40 lite-tier calls and 33 of 40 Flash-tier calls:
  ```
  ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You
  exceeded your current quota, please check your plan and billing details. ...
  ```
- **The problem:** this is byte-for-byte the message from F-003, where the
  condition was "your tier has no entitlement to this model". Here it is "you
  are sending too fast, wait a moment". One is permanent and needs billing; the
  other clears in seconds. Nothing in the status, message or headers tells
  them apart.
- **Time lost:** about 15 minutes, mostly re-checking that `gemini-3.5-flash`
  had not become entitlement-blocked mid-run.
- **Workaround:** back off and retry. If it eventually succeeds it was a rate
  limit; if it never does it was an entitlement wall.
- **What would help:** distinct `status` or `reason` values for quota-exhausted
  versus not-entitled, and a `Retry-After` header on the transient one. The
  cheapest fix on this list.

## F-009: Rate-limit numbers are no longer in the rate-limit documentation

- **Bucket:** documentation
- **Severity:** medium
- **Attempting:** find the free-tier requests-per-minute ceiling to pace the
  extraction run, after hitting F-008.
- **Observed:** the rate-limits page documents the four tiers and their billing
  thresholds but has no per-model RPM/TPM/RPD figures. It says limits "can be
  viewed in Google AI Studio" and links to a dashboard.
- **Why it hurts:** the number is needed while writing a pacing constant, not
  while browsing a dashboard. With F-008 also declining to say what the limit
  is, there is no path from inside the program to the value that governs it.
- **Time lost:** about 10 minutes, then gave up and measured it.
- **Workaround:** adaptive back-off that finds the ceiling empirically.
- **What would help:** the numbers back in the docs, and exposed on the client
  so a program can pace itself.

## F-010: Free-tier per-model quota cannot fund a scored evaluation

- **Bucket:** API surface / product
- **Severity:** high
- **Attempting:** run a 3x-repeated evaluation over an 80-document corpus across
  two model tiers, roughly 320 calls. A small evaluation.
- **Observed:** each Flash model run toward evaluation volume stopped after
  about 20 successful requests and then returned 429 in about 0.2s without
  attempting inference. Across the four Flash models tried:
  ```
  gemini-3.5-flash     ok, then 429 permanently
  gemini-3.7-flash     17 ok, then 429 permanently
  gemini-3.8-flash     available, intermittent 503 under load
  gemini-3-flash-preview  available
  ```
  The two run toward volume hit the quota and did not recover for the rest of
  the build. `gemini-3.8-flash` returned 503 on 2 of 4 probe calls (F-004).
  `gemini-3-flash-preview` passed a 4-call probe (9.6s mean, about 1,500
  thinking tokens per call) and was not carried to evaluation volume, so its
  quota is untested. Lite-tier models were unaffected. `gemini-3.5-flash-lite` completed 89
  consecutive calls with no errors.
- **Why it matters:** the quota is not the cost. The whole evaluation at list
  price costs about a dollar. The free tier is enough to try a model and not
  enough to evaluate one, and evaluation is what a partner does before
  committing.
- **Consequence for this build:** the escalation tier was dropped for a second
  lite-class reader, because no Flash model was carried to the call volume:
  two stopped at the quota, one was unstable, and the preview model was not
  tested at volume. The evaluation survived; the capability-escalation design
  did not.
- **Time lost:** about 90 minutes across four model migrations.
- **Workaround:** none on the free tier. Enabling billing resolves it.
- **What would help:** a quota shaped for evaluation. A one-off allowance of a
  few thousand requests per project, or free-tier limits per project per day
  rather than per model so a fixed budget can be spent where the developer
  chooses. As it stands, the tier a partner uses to decide whether Gemini fits
  is the tier least able to answer that.

## F-011: `batches.create` fails an unnamed precondition; `batches.list` works

- **Bucket:** API surface / documentation
- **Severity:** high
- **Attempting:** submit the 40-document test split as a batch job. Batch is
  the right mode for Meridian's overnight bulk: 50% of the interactive rate
  with a 24h target turnaround at 40,000 documents a month.
- **Error**, on every attempt:
  ```
  ClientError: 400 FAILED_PRECONDITION. {'error': {'code': 400,
  'message': 'Precondition check failed.', 'status': 'FAILED_PRECONDITION'}}
  ```
- **Isolation**, to rule out our request shape:

  | probe | result |
  |---|---|
  | minimal text-only, one request, `gemini-3.5-flash-lite` | 400 FAILED_PRECONDITION |
  | same on `gemini-3.1-flash-lite` | 400 FAILED_PRECONDITION |
  | text + `response_schema` | 400 FAILED_PRECONDITION |
  | single inline image | 400 FAILED_PRECONDITION |
  | `client.batches.list()` | **succeeds**, 0 existing jobs |

  A one-part text request fails the same way as a 40-document multimodal
  batch, so the payload is not the cause. `batches.list` succeeding means the
  endpoint is reachable and the client is authenticated.
- **Documentation check:** the Batch API page states no tier restriction or
  precondition and does not document `FAILED_PRECONDITION`. Batch probably
  requires a billed project, but that is an inference, not something the API
  or the docs say.
- **Time lost:** about 25 minutes, mostly isolating a request-shape bug that
  did not exist.
- **Workaround:** none on this key. The batch path is implemented against the
  SDK contract in `src/meridian/batch.py` and is **unverified**. No throughput or
  cost figure is claimed for it.
- **What would help:** name the precondition. "Precondition check failed." says
  nothing about which precondition, which resource, or what to change. "Batch
  API requires a project with billing enabled" would have cost zero minutes,
  and belongs in the first paragraph of the Batch API page.
