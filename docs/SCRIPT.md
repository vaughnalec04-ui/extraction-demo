## 1. Open (0:00 to 1:29)

[Tab 1, top of the briefing. Look at the camera for the first three sentences.]

## 2. The problem (1:29 to 2:10)

[Point at the BLUF box, then scroll to Context.]

## 3. Architecture (2:10 to 5:42)

[Scroll to 1.1 Flow. Run your finger along the arrow line as you talk.]

Here's how it's put together. I write the labels first, from a fixed seed. Then I render each page from its label. So no label ever depends on a model. The extractor sends each page to Gemini with a response schema and gets back one value and one confidence per field, and the value's allowed to be empty. Every raw response goes into a cache that's committed to the repo. The harness scores that cache. It never touches the API.

That split is the main decision. Extraction is one program, scoring is another. Once the responses are cached, every threshold sweep is free, tuning is repeatable, and the demo you're about to see runs offline and gives the same numbers every time. The cache key is the model, the prompt version, the schema, and the bytes of the image, and both programs recompute it when they read. Regenerate a page and try to score it against an old response, and it refuses, because that failure wouldn't crash. It'd hand you plausible wrong numbers.

Four configurations come out of the same cached calls. One reader on its own. The second reader on its own. A cascade, where a page goes to the second reader when the first one's confidence is low. And double-keying, where both readers read every page and any field they disagree on goes to a human. That idea comes straight from how claims shops already work. Two people key the same document and a supervisor settles the differences.

[Scroll to 1.3, the trade-offs table.]

## 4. Live run (5:42 to 6:59)

[Switch to the terminal. Press return on meridian-evaluate. Scroll to the frontier table, then the paired table right under it.]

## 5. Two documents (6:59 to 8:47)

[Tab 3. Point at the total, then the policy number.]

Two pages surprised me, for opposite reasons. This is a degraded repair estimate. The total is four thousand eight hundred and four dollars. The primary reader read forty-one thousand eight hundred and four. One extra digit on a faded scan, and that's exactly the mistake that pays out. What got me was that its confidence on that field was point nine, the lowest it gave anywhere, so the model half knew. It got the policy number wrong too, at point nine five, and those are its only two mistakes on the whole test split, both on this one page. The second reader had the total right and the policy number wrong in a different way. So under double-keying both fields went to review. On a real claim that's a thirty-seven thousand dollar overpayment that didn't go out.

[Tab 4. Point at Amount Due.]

## 6. The rule in code (8:47 to 9:24)

[Tab 5. The highlighted lines are the double-key branch.]

## 7. What we found (9:24 to 11:22)

[Terminal. Scroll to the primary block and the line that says DEGENERATE. Then Tab 1, the Cascade paragraph.]

## 8. From an eval to a benchmark (11:22 to 12:39)

[Tab 2. Scroll the README to the dataset table with the five strata.]

## 9. Friction, for the Gemini teams (12:39 to 14:01)

[Tab 6. It opens at F-007. Read the counts, then scroll down to F-010.]

## 10. Close (14:01 to 14:38)

[Tab 1, section 4. Back to the camera for the last two sentences.]
