# Prompt iteration log

Every version of the Answer Call's prompt template, newest last. The template lives in [`backend/src/edgar_rag/_prompt.py`](../backend/src/edgar_rag/_prompt.py), and its `PROMPT_VERSION` constant is logged with every Answer Call (`data/derived/logs/answer_calls.jsonl`), so each logged answer can be traced to the template that produced it.

A change to the template bumps `PROMPT_VERSION` and adds an entry here: what changed, why, and the dev-split scores before and after (retrieval and generation harnesses, on the Golden Set's dev cases only). The holdout split is scored once, at the end, on the final version.

## v1: the tracer bullet

**What.** The first complete template, in this order:

1. System rules: use only the Sources, cite every claim `[Sn]`, earlier turns are not evidence, give form type and fiscal period, quote figures exactly, and the PE-analyst structure of assumption 8.
2. The Sources, grouped by Company under `## Company (TICKER)` headings. Each opens with its tag and label, e.g. `[S1] AAPL 10-K FY2025, Risk Factors (Item 1A). Filing ID AAPL_10-K_2025-09-27, Report Period 2025-09-27.`
3. The earlier conversation: the last 10 turns, capped at about 6k tokens by dropping the oldest. Earlier answers lose their `[Sn]` tags, which pointed at that turn's Sources.
4. The latest question.

The rules go in a system message; everything else goes in one user message.

**Why.** It is the thinnest prompt that makes a grounded, cited answer possible from the tracer-bullet retrieval, so the harnesses have something to score. Coverage Gaps and the Financial Facts table are not computed yet; they join the template between the rules and the Sources when the Query Scope parser and the Financial Facts store reach the Answer Context.

**Known gaps.** Earlier Source tags are dropped rather than rewritten as Filing IDs, because the browser does not send the earlier turns' Sources yet. There are no fixed Coverage Gap wordings, so the model writes its own coverage note.

**Scores.** Not measured yet: the retrieval and generation harnesses come next. Hand check on the brief's first example (`make ask`, `gpt-6-luna`): every point cites Sources from Apple, Tesla and JPMorgan, it says the Companies' periods differ, and it says JPMorgan's Item 1A risk factors were not among the Sources. About 26k input and 900 output tokens, 9 seconds.

### The v1 system rules

```text
You are a research assistant for private equity analysts. You answer business questions about public companies using only the excerpts from their SEC 10-K and 10-Q filings given to you as numbered Sources.

Rules:
1. Use only the Sources. Never use general knowledge, memory or any outside data, even for well-known facts. If the Sources do not answer part of the question, say so plainly.
2. Cite every claim with the tag of the Source it comes from, e.g. [S3], placed right after the claim. Use several tags when a claim rests on several Sources. Cite only tags listed in this turn's Sources.
3. The earlier conversation is there to help you understand the question. It is not evidence: never repeat a claim from an earlier answer unless a Source in this turn supports it, and then cite that Source.
4. When you use a Company's filings, give the filing's form type and fiscal period, and say so when the Companies you compare report for different periods.
5. Quote figures exactly as the Sources give them, with their units and periods.

Structure the answer for a PE analyst, in Markdown:
- Open with a direct answer in two or three sentences.
- Then give the points for each Company under its own heading, or a comparison table when several Companies are compared on the same dimensions.
- End with a short "Coverage" note saying what the Sources could not answer.
- Aim for 300 to 600 words.
```

### The v1 user message

```text
# Sources

## Apple Inc (AAPL)

[S1] AAPL 10-K FY2025, Risk Factors (Item 1A). Filing ID AAPL_10-K_2025-09-27, Report Period 2025-09-27.
<the retrieved chunks of that Section, in body order, separated by […]>

[S2] ...

## Tesla Inc (TSLA)

...

# Earlier conversation (context only, not evidence)

User: <earlier question>

Assistant: <earlier answer, Source tags removed>

# Question

<the latest user message>
```

The earlier-conversation block is left out when there is no history.
