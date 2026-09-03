# Meridian demo script, by tab

Talk from it; the numbers are exact, the rest is yours.

## Before you record

Terminal, its own window, large font:

    cd ~/extraction-demo
    source venv/bin/activate
    echo ${GEMINI_API_KEY:-no key set}      # must print: no key set
    clear

If the echo prints a key, run `unset GEMINI_API_KEY` and echo again. Type `meridian-evaluate` but do not press return.

Browser tabs, open in this order:

1. Briefing: file:///Users/vaughnnahapetian_llm/extraction-demo/docs/BRIEFING.html. Open at the top; zoom 125%.
2. GitHub repo: https://github.com/vaughnalec04-ui/extraction-demo. README top visible.
3. Degraded page: file:///Users/vaughnnahapetian_llm/extraction-demo/data/docs/degr-012.jpg. Click once so it fits; find the total (4,804.39) and the policy number before recording.
4. Utility bill: file:///Users/vaughnnahapetian_llm/extraction-demo/data/docs/ood-006.jpg. Find the Amount Due line.
5. The double-key rule: https://github.com/vaughnalec04-ui/extraction-demo/blob/main/src/meridian/harness/configs.py#L86-L96. Lines highlighted on load.
6. Friction log: https://github.com/vaughnalec04-ui/extraction-demo/blob/main/FRICTION.md#f-007-self-reported-confidence-is-a-constant-self-consistency-too. Opens at F-007; F-010 is two entries below.

Notifications off. Close every other window. Put this script on a second screen or phone.

## TAB 1: Briefing

Link: file:///Users/vaughnnahapetian_llm/extraction-demo/docs/BRIEFING.html

Do: Start at the top of the page. Look at the camera for the first three sentences.

Thank you for joining me here today. My name is Vaughn Nahapetian, and I'm interviewing to join the DeepMind team as a Forward Deployed Engineer.

What I built for you is a small pipeline that reads six fields off scanned claims documents with the Gemini API, together with the part I'd most like to draw your attention to, which is a harness that tells you whether the pipeline knows when it's wrong.

The partner, which I'm calling Meridian Claims Group, is of course made up, and its documents and domain logic are notional. The situation is real, though. It's one your organization probably encounters often, and from my experience at Palantir it's going to keep coming up for a long time: someone is paying out claims from a scanner, and they care a lot more about a wrong payment than about a page going to a human for review. The whole build is organized around that fact, because getting the fields out of the page is the easy half of the job.

Two more things before I start. Claude wrote most of the code, with me directing what got built and in what order, and the two documents were drafted with Claude and Gemini and then argued over. The decisions were mine, and I'll show you the ones that matter. On time, the implementation took about three and a half hours, with agents running alongside me, spread over a couple of sittings, and it would have been shorter in one. The rest of the calendar went to waiting on quota, generating documents, and writing.

Do: Point at the BLUF box, then scroll to Context.

So here's the problem. Meridian receives about forty thousand scanned claims a month, and they want six fields pulled off every page: the claim id, the policy number, the claimant, the provider, the date of service, and the total. They need ninety-seven percent field accuracy at under two cents a document, and when the system isn't sure, it has to say so instead of guessing, because a wrong payout costs a lot more than a human review.

That last requirement is the hard one. Reading fields off a scan mostly works now, but catching your own mistakes doesn't, so I built the harness around that.

Do: Scroll to 1.1 Flow. Run your finger along the arrow line as you talk.

Here's how it's put together. I write the labels first, from a fixed seed, and then I render each page from its label, so no label ever depends on a model. The extractor sends each page to Gemini with a response schema and gets back one value and one confidence per field, and the value is allowed to be empty. Every raw response goes into a cache that's committed to the repo, and the harness scores that cache without ever touching the API.

That split is the main decision: extraction is one program and scoring is another. Once the responses are cached, every threshold sweep is free, tuning is repeatable, and the demo you're about to see runs offline and gives the same numbers every time. The cache key is the model, the prompt version, the schema, and the bytes of the image, and both programs recompute it when they read. If you regenerate a page and try to score it against an old response, the harness refuses, because that failure wouldn't crash; it would hand you plausible wrong numbers.

Four configurations come out of the same cached calls: one reader on its own, the second reader on its own, a cascade where a page goes to the second reader when the first one's confidence is low, and double-keying, where both readers read every page and any field they disagree on goes to a human. That last idea comes straight from how claims shops already work, where two people key the same document and a supervisor settles the differences.

Do: Scroll to 1.3, the trade-offs table.

Now, the free tier, because this is where the plan changed. The very first thing that broke was trivial: the GitHub CLI wasn't on my path, and I spent five minutes thinking it wasn't installed. The first real break was the model list. I had planned the cascade as 2.5 Flash Lite escalating to 2.5 Pro, and the API's own model list said both were callable, but the first real call came back 404, no longer available to new users, with an instruction to use 3.5 instead. Then the Pro model it pointed me at returned a 429 on the very first request, with a message about exceeding my quota when I hadn't made a single call. So I stopped trusting the list, probed every candidate with a one-token call, wrote down what answered, and re-planned around the Flash tier. That held for about twenty requests per model before the Flash quota ran out too, which cost me about ninety minutes and four model changes.

Honestly, swapping to a second lite model felt like a compromise at first. The design was a cheap model with a stronger one behind it, and the stronger one was the part I had lost, so I remember asking whether I should just start over. What changed my mind was noticing that the interesting signal was never whether the second model was smarter; it was whether two independent readers agreed. For that you want two models that fail differently, and a second lite model from a different generation gives you exactly that. So I kept everything and swapped the second reader. The cost is that the cascade has nothing stronger to escalate to, and you'll see that in the results.

## TERMINAL: Live run

Do: Have ready before recording: meridian-evaluate typed and not run, and the no-key echo already shown. Now press return. Scroll to the frontier table, then to the paired table right under it.

Let me run it. There's no API key in this shell, as you saw from the echo, so I'll press enter.

That's the whole evaluation, in about a quarter of a second, straight from the cache. Here's the frontier. The primary reader alone gets ninety-nine point two percent of fields right, with an interval from ninety-seven point oh to ninety-nine point eight, at about a tenth of a cent a document. Look at that lower bound: ninety-seven point oh is Meridian's bar exactly, so the bar is met with no margin at all.

Double-keying gets a hundred percent on the fields the two readers agree on, which is ninety-six point seven percent of them, at two tenths of a cent, and that looks better. But look at the paired table underneath. On the same forty documents, the two systems differ on two fields out of two hundred forty, and the p-value is point five. What this data actually shows is the cost, which is that three point three points of coverage go to review. The accuracy gain is inside the noise, and I'd rather tell you that than sell you the bigger number.

## TAB 3: Degraded page

Link: file:///Users/vaughnnahapetian_llm/extraction-demo/data/docs/degr-012.jpg

Do: Point at the total, then at the policy number.

Two pages surprised me, for opposite reasons. This one is a degraded repair estimate. The total on the page is four thousand eight hundred and four dollars, and the primary reader read forty-one thousand eight hundred and four. That's one extra digit on a faded scan, and it's exactly the kind of mistake that pays out. What got me was that its confidence on that field was point nine, the lowest it gave anywhere, so the model half knew. It got the policy number wrong too, at point nine five, and those are its only two mistakes on the whole test split, both on this one page. The second reader had the total right and the policy number wrong in a different way, so under double-keying both fields went to review. On a real claim, that's a thirty-seven thousand dollar overpayment that didn't go out.

On the total field specifically, which is the payment field, the primary alone gets ninety-seven and a half percent, and double-keyed it gets a hundred. That's a small sample with wide intervals, but it's the field where the money is.

## TAB 4: Utility bill

Link: file:///Users/vaughnnahapetian_llm/extraction-demo/data/docs/ood-006.jpg

Do: Point at the Amount Due line.

This one is a utility bill. It's in the corpus because it isn't a claim, so the right answer for every field is that there's nothing there. The primary said exactly that on all six fields. The second reader, working alone, simply made things up: the account number became a policy number, the billing period became a date of service, the utility became the provider, and this amount due of a hundred sixty-eight dollars and forty-four cents became a claim total, all at a confidence of one point oh. Under double-keying, none of that got out, because the readers disagreed. On this sample the primary happened to be right, so those flags cost a review each, but flip the roles and they're saved payouts.

## TAB 5: The double-key rule, configs.py lines 86 to 96

Link: https://github.com/vaughnalec04-ui/extraction-demo/blob/main/src/meridian/harness/configs.py#L86-L96

Do: The highlighted lines are the double-key branch.

Here's the whole idea in ten lines. For each field, you take the primary's value and the verifier's value, normalize both so that a dollar sign or a comma doesn't count as a disagreement, and compare them. If they agree, the primary's value goes out; if they don't, the field is marked abstained and goes to the queue. We keep the lower of the two confidences for the record, but nothing depends on it, and that's the point: this configuration never asks either model how sure it is.

## TERMINAL, then TAB 1: What we found

Link: file:///Users/vaughnnahapetian_llm/extraction-demo/docs/BRIEFING.html

Do: In the terminal, scroll to the primary_solo block and the line that says DEGENERATE. Then switch to Tab 1 and scroll to the Cascade paragraph in section 2.3.

So what did we actually find? There are four things.

First, the confidence numbers, which are not probabilities. The second reader said one point oh on every single field, two hundred forty out of two hundred forty, after I had told it in the schema to use the whole range, and the primary said one point oh on two hundred fourteen. The harness flags the calibration curve as degenerate, meaning there's only one bin with enough points in it to count, and you can't gate on that. The frustrating part is that there's a hint of something real in there, because the two lowest numbers the primary gave were on its two mistakes. But that's two data points, and I couldn't get log probabilities to check, so until the API gives you something calibrated, the number is decoration.

Second, the cascade. On the tuning split, no escalation threshold improved accuracy, and sending every page to the second reader made things worse, from ninety-eight point seven five down to ninety-seven point nine two, at one point seven times the cost. The second reader simply isn't stronger, so tuning set the threshold to zero and the cascade is just the primary. That's a result about these two readers, and it traces straight back to the quota problem; give me a Flash-class second reader and I'd rerun it.

Third, the abstention signal itself. There were eight flags in two hundred forty fields, and two of them were real errors, which is twenty-five percent precision with an interval that runs from seven to fifty-nine. So I can't tell you yet whether double-keying pays for itself. What would settle it is about five hundred of Meridian's real documents, weighted toward the exceptions their contractors already flag, run through this harness unchanged, and the pass-fail gates for that are in the briefing.

Do: Still on Tab 1, scroll down one paragraph to Reconciliation.

And fourth, the finding I'd most want a claims person to hear. Reading the fields is transcription, and the job underneath it is adjudication: do the line items actually add up to the total the provider wrote down? Thirty-four of the forty test documents have an itemization and a stated total, and twelve of them don't add up, by construction. The primary caught all twelve. The verifier missed one, and that one is a claim that would have been paid. The part that went against my own hypothesis is the arithmetic. I had assumed the model would get the sums wrong and that I'd have Python check them, but the model's arithmetic was right on every single document. Every verdict failure traces back to a misread digit on a degraded scan, and the line items were read correctly about ninety-one percent of the time. So the rule of thumb that you never let a model do arithmetic didn't apply here: the adding was free and correct, and the reading is the problem, which makes it an image-quality problem.

## TAB 2: GitHub repo

Link: https://github.com/vaughnalec04-ui/extraction-demo

Do: Scroll the README to the dataset table with the five strata and stop there.

I built it this way because most of it turns into a benchmark for extraction with abstention. Here's what carries over. There's a label-first generator with named strata, so the difficulty is designed instead of discovered, and a committed response cache, so anyone can reproduce the scoring without spending a cent. There's a fixed set of metrics, where accuracy is always shown next to coverage, the three kinds of error are kept apart, abstention precision comes from the recorded counterfactual, and everything carries an interval. There's paired comparison between systems on the same documents, so nobody is comparing overlapping error bars. And there's reconciliation, whether the itemization adds up to the total, because adjudication is the job underneath the transcription.

The findings tell you what a benchmark like that has to contain. It needs out-of-distribution pages that bait a hallucination, because that's where the two readers split, and degraded scans, because that's the only stratum with errors in it. And the thing you report should be the whole cost-accuracy frontier rather than one number, because Meridian's decision is a trade between coverage and review load. What's missing is real documents; the synthetic failure distribution is my guess at theirs.

## TAB 6: Friction log

Link: https://github.com/vaughnalec04-ui/extraction-demo/blob/main/FRICTION.md#f-007-self-reported-confidence-is-a-constant-self-consistency-too

Do: It opens at F-007. Read the confidence counts, then scroll down two entries to F-010.

If I could get Google to fix one thing, it would be this: give structured output a real confidence signal, either log probabilities on schema fields or any calibrated number the model doesn't have to introspect to produce. Every customer whose requirement is to be told when the model isn't sure hits this wall, and right now the answer is to pay for a second model. That's F-007 in the log, with F-006 next to it for the missing log probabilities.

If I get a second one, it's the free tier, which is F-010. It stopped every Flash model I pushed toward volume after about twenty requests, and the whole evaluation costs about a dollar at list price. That's the tier people use to decide whether Gemini fits, and it can't support an evaluation, so a per-project evaluation allowance would fix it.

The log has eleven entries, written as things happened, with the error text as it appeared, and two smaller ones are worth a sentence. The same four-twenty-nine message covers both a rate limit and an exhausted entitlement, so a client can't tell whether to wait or stop. And batch create returns a failed precondition without saying which one, so I never got to measure the half-price batch mode.

## TAB 1: Briefing, sections 2.4 and 2.5

Link: file:///Users/vaughnnahapetian_llm/extraction-demo/docs/BRIEFING.html

Do: Scroll to 2.4 Monitoring in production, then 2.5 Pilot gates.

One more thing before I wrap up, because a partner would ask it: what would I watch if this went live tomorrow? The pipeline already gives you the signals. Every document produces a disagreement rate between the two readers, by field and by stratum; every flagged item comes back from the adjudicator as right or wrong, which turns abstention precision into a live number instead of a one-time estimate; and every response carries a cost, a latency, and the model version string.

So the plan I'd propose to Meridian is this. Daily, compare the disagreement rate to its baseline, which is three point three percent of fields here, and if it goes above double that, page someone, because either the documents changed or a model did. Weekly, take two hundred documents, run them through this same harness with the adjudicators' final answers as the labels, and check two percent of the items the readers agreed on by hand, because two readers agreeing on a wrong value is the one failure this system can't see on its own. If the lower bound on accuracy drops under ninety-seven on that weekly sample, auto-pay stops until someone finds out why. And since the model name is an alias, any change in the version string coming back from the API means the harness runs on the committed corpus again before the next batch goes out.

For the five-hundred-document pilot, the gates are written down. I'd go ahead with double-keying if the lower bound on accuracy is at or above ninety-seven, coverage is at or above ninety, and at least one flag in three turns out to be a real error. If that last gate fails, the honest answer is the primary alone with a sampled audit rather than a second model.

## TAB 1: Briefing, section 4

Link: file:///Users/vaughnnahapetian_llm/extraction-demo/docs/BRIEFING.html

Do: Scroll to section 4, Next steps. Back to the camera for the last two sentences.

So if Meridian asked me whether they should buy this, I'd say not yet, and not because of accuracy or cost, since both clear the bar. I'd tell them to run five hundred of their real documents through it first, especially the ones their contractors already flag, and then we'd know whether the second reader is worth the three points of coverage it costs. The harness is built for exactly that: it reproduces from a clean clone in one command, and everything you saw is in the repo. Thank you.
