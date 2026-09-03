## 1. Open (0:00 to 1:00)

[Tab 1, top of the briefing. Look at the camera for the first three sentences.]

The accuracy bar is met. The cost bar is met. The third one, knowing when it's wrong, isn't. That's what the next twelve minutes are about, and I'll show you the numbers behind each of those.

What I built is a small pipeline that reads six fields off scanned claims documents with Gemini, plus the part I actually care about, which is a harness that tells you whether the pipeline knows when it's wrong. The partner, Meridian Claims Group, is made up, but the situation isn't: someone paying out claims from a scanner, who cares a lot more about a wrong payment than about a page going to a human. So the whole build is organized around that. Getting the fields out is the easy half.

Two more things before I start. Claude wrote most of the code, with me directing what got built and in what order, and the two documents were drafted with Claude and Gemini and then argued over. The decisions were mine, and I'll show you the ones that matter. And on time: about three and a half hours of implementation, with agents running alongside me, spread over a couple of sittings. It would've been shorter in one. The rest of the calendar was waiting on quota, generating documents, and writing.

## 2. The problem (1:00 to 1:45)

[Point at the BLUF box, then scroll to Context.]

So here's the problem. Meridian gets about forty thousand scanned claims a month. They want six fields pulled off every page: claim id, policy number, claimant, provider, date of service, and the total. Ninety-seven percent field accuracy. Under two cents a document. And when the system isn't sure, it has to say so instead of guessing, because a wrong payout costs a lot more than a human review.

That last one is the hard one. Reading fields off a scan mostly works now. Catching your own mistakes doesn't. So I built the harness around that.

## 3. Architecture (1:45 to 4:15)

[Scroll to 1.1 Flow. Run your finger along the arrow line as you talk.]

Here's how it's put together. I write the labels first, from a fixed seed. Then I render each page from its label. So no label ever depends on a model. The extractor sends each page to Gemini with a response schema and gets back one value and one confidence per field, and the value's allowed to be empty. Every raw response goes into a cache that's committed to the repo. The harness scores that cache. It never touches the API.

That split is the main decision. Extraction is one program, scoring is another. Once the responses are cached, every threshold sweep is free, tuning is repeatable, and the demo you're about to see runs offline and gives the same numbers every time. The cache key is the model, the prompt version, the schema, and the bytes of the image, and both programs recompute it when they read. Regenerate a page and try to score it against an old response, and it refuses, because that failure wouldn't crash. It'd hand you plausible wrong numbers.

Four configurations come out of the same cached calls. One reader on its own. The second reader on its own. A cascade, where a page goes to the second reader when the first one's confidence is low. And double-keying, where both readers read every page and any field they disagree on goes to a human. That idea comes straight from how claims shops already work. Two people key the same document and a supervisor settles the differences.

[Scroll to 1.3, the trade-offs table.]

Now, the free tier, because this is where the plan changed. The very first thing that broke was dumb: the GitHub CLI wasn't on my path and I spent five minutes thinking it wasn't installed. The first real break was the model list. I'd planned the cascade as 2.5 Flash Lite escalating to 2.5 Pro. The API's own model list said both were callable, and the first real call came back 404, no longer available to new users, go use 3.5. Then the Pro model it pointed me at returned a 429 on the very first request, with a message about exceeding my quota when I hadn't made a single call. So I stopped trusting the list, probed every candidate with a one-token call, wrote down what answered, and re-planned around the Flash tier. That held for about twenty requests per model before the Flash quota ran out too. About ninety minutes and four model changes.

Honestly, swapping to a second lite model felt like a compromise at first. The design was a cheap model with a stronger one behind it, and the stronger one was the part I'd lost. I remember asking whether I should just start over. What changed my mind was noticing that the interesting signal was never whether the second model was smarter. It was whether two independent readers agreed. For that you want two models that fail differently, and a second lite model from a different generation gives you that. So I kept everything and swapped the second reader. The cost is that the cascade has nothing stronger to escalate to, and you'll see that in the results.

## 4. Live run (4:15 to 5:25)

[Switch to the terminal. Press return on meridian-evaluate. Scroll to the frontier table, then the paired table right under it.]

Let me run it. No API key in this shell, you saw the echo. Enter.

That's the whole evaluation. About a quarter of a second, straight from the cache. Here's the frontier. The primary reader alone gets ninety-nine point two percent of fields right, and the interval runs from ninety-seven point oh to ninety-nine point eight, at about a tenth of a cent a document. Look at that lower bound. Ninety-seven point oh. That's Meridian's bar exactly. Met, with no margin.

Double-keying gets a hundred percent on the fields the two readers agree on, which is ninety-six point seven percent of them, at two tenths of a cent. Looks better. Now look at the paired table underneath. Same forty documents, and the two systems differ on two fields out of two hundred forty. P is point five. What this data actually shows is the cost: three point three points of coverage go to review. The accuracy gain is inside the noise. I'd rather tell you that than sell you the bigger number.

## 5. Two documents (5:25 to 7:25)

[Tab 3. Point at the total, then the policy number.]

Two pages surprised me, for opposite reasons. This is a degraded repair estimate. The total is four thousand eight hundred and four dollars. The primary reader read forty-one thousand eight hundred and four. One extra digit on a faded scan, and that's exactly the mistake that pays out. What got me was that its confidence on that field was point nine, the lowest it gave anywhere, so the model half knew. It got the policy number wrong too, at point nine five, and those are its only two mistakes on the whole test split, both on this one page. The second reader had the total right and the policy number wrong in a different way. So under double-keying both fields went to review. On a real claim that's a thirty-seven thousand dollar overpayment that didn't go out.

[Tab 4. Point at Amount Due.]

This one's a utility bill. It's in the corpus because it isn't a claim, so the right answer for every field is "nothing here." The primary said nothing here on all six. The second reader, working alone, simply made things up. The account number became a policy number. The billing period became a date of service. The utility became the provider. And this amount due, a hundred sixty-eight dollars forty-four, became a claim total. All at confidence one point oh. Under double-keying none of that got out, because the readers disagreed. On this sample the primary happened to be right, so those flags cost a review each. Flip the roles and they're saved payouts.

## 6. The rule in code (7:25 to 8:10)

[Tab 5. The highlighted lines are the double-key branch.]

Here's the whole idea in ten lines. For each field, take the primary's value and the verifier's value. Normalize both, so a dollar sign or a comma doesn't count as a disagreement. Compare. If they agree, the primary's value goes out. If they don't, the field is marked abstained and goes to the queue. We keep the lower of the two confidences for the record, but nothing depends on it. That's the point. This configuration never asks either model how sure it is.

## 7. What we found (8:10 to 9:50)

[Terminal. Scroll to the primary block and the line that says DEGENERATE. Then Tab 1, the Cascade paragraph.]

Okay, so what did we actually find? Three things.

First, the confidence numbers. They're not probabilities. The second reader said one point oh on every single field, two hundred forty out of two hundred forty, after I told it in the schema to use the whole range. The primary said one point oh on two hundred fourteen. The harness flags the calibration curve as degenerate, meaning there's only one bin with enough points in it to count. You can't gate on that. The frustrating part is there's a hint of something real in there, because the two lowest numbers the primary gave were on its two mistakes. But that's two data points, and I couldn't get log probabilities to check. So until the API gives you something calibrated, treat the number as decoration.

Second, the cascade. On the tuning split, no escalation threshold improved accuracy, and sending every page to the second reader made things worse. Ninety-eight point seven five down to ninety-seven point nine two, at one point seven times the cost. The second reader isn't stronger. So tuning set the threshold to zero, and the cascade is just the primary. That's a result about these two readers, and it traces straight back to the quota problem. Give me a Flash-class second reader and I'd rerun it.

Third, the abstention signal itself. Eight flags in two hundred forty fields. Two were real errors. That's twenty-five percent precision, and the interval runs from seven to fifty-nine. So I can't tell you yet whether double-keying pays for itself. What would settle it is about five hundred of Meridian's real documents, weighted toward the exceptions their contractors already flag, through this harness unchanged. The pass-fail gates are in the briefing.

## 8. From an eval to a benchmark (9:50 to 10:50)

[Tab 2. Scroll the README to the dataset table with the five strata.]

I built it this way because most of it turns into a benchmark for extraction with abstention. Here's what carries over. A label-first generator with named strata, so the difficulty is designed instead of discovered. A committed response cache, so anyone can reproduce the scoring without spending a cent. A fixed set of metrics: accuracy always shown next to coverage, three kinds of error kept apart, abstention precision from the recorded counterfactual, and an interval on everything. Paired comparison between systems on the same documents, so nobody's comparing overlapping error bars. And reconciliation, does the itemization add up to the total, because adjudication is the job underneath the transcription.

The findings tell you what a benchmark like that has to contain. Out-of-distribution pages that bait a hallucination, because that's where the two readers split. Degraded scans, because that's the only stratum with errors in it. And the thing you report should be the whole cost-accuracy frontier rather than one number, because Meridian's decision is a trade between coverage and review load. What's missing is real documents. The synthetic failure distribution is my guess at theirs.

## 9. Friction, for the Gemini teams (10:50 to 12:05)

[Tab 6. It opens at F-007. Read the counts, then scroll down to F-010.]

If I could get Google to fix one thing, it's this. Give structured output a real confidence signal. Log probabilities on schema fields, or any calibrated number the model doesn't have to introspect to produce. Every customer whose requirement is "tell me when you're not sure" hits this wall, and right now the answer is to pay for a second model. That's F-007 in the log, with F-006 next to it for the missing log probabilities.

If I get a second one, it's the free tier, F-010. It stopped every Flash model I pushed toward volume after about twenty requests. The whole evaluation costs about a dollar at list price. That's the tier people use to decide whether Gemini fits, and it can't support an evaluation. A per-project evaluation allowance would fix it.

The log has eleven entries, written as things happened, with the error text as it appeared. Two smaller ones are worth a sentence. The same four-twenty-nine message covers a rate limit and an exhausted entitlement, so a client can't tell whether to wait or stop. And batch create returns a failed precondition without saying which one, so I never got to measure the half-price batch mode.

## 10. Close (12:05 to 12:45)

[Tab 1, section 4. Back to the camera for the last two sentences.]

So if Meridian asked me whether they should buy this, I'd say not yet, and not because of accuracy or cost, since both clear the bar. Run five hundred of your real documents through it first, especially the ones your contractors already flag, and then we'll know whether the second reader is worth the three points of coverage it costs. The harness is built for exactly that. It reproduces from a clean clone in one command, and everything you saw is in the repo. Thanks.
