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

**Scores.** Retrieval on dev, from the retrieval harness: hit@10 0.71, recall@10 0.52, MRR 0.39 over 17 scored cases ([evaluation notes](evaluation.md#first-fts5-numbers-on-dev)). The generation harness comes next. Hand check on the brief's first example (`make ask`, `gpt-6-luna`): every point cites Sources from Apple, Tesla and JPMorgan, it says the Companies' periods differ, and it says JPMorgan's Item 1A risk factors were not among the Sources. About 26k input and 900 output tokens, 9 seconds.

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

## v2: Companies a Sector phrase resolved to

**What.** When the question uses a Sector phrase, a `# Companies in scope` block goes before the Sources, one line per phrase:

```text
# Companies in scope

"pharmaceutical companies" was resolved through the Sector table (industry: Pharmaceuticals or Biotechnology) to: Johnson & Johnson (JNJ), Eli Lilly and Company (LLY), Merck & Co Inc (MRK), Pfizer Inc (PFE), AbbVie Inc (ABBV).
```

A sixth system rule tells the model what the block means:

```text
6. When the question names a group of companies ("the major banks"), it was resolved through a curated Sector table to the Companies listed under "Companies in scope". Name those Companies near the start of the answer, say they come from the Sector table, and cover no other company for that group.
```

Everything else is unchanged from v1. A question with no Sector phrase gets no block.

**Why.** The analyst must be able to dispute a mapping (user story 15, assumption 5), so the answer has to say which Companies "the major pharmaceutical companies" meant. Under v1 the model saw only Sources grouped by Company and could name some Companies and skip the ones whose Sources said little, or add a company it remembered as a drug maker.

**Scores.** Retrieval on dev, from the retrieval harness: hit@10 0.71 → 0.71, recall@10 0.58 → 0.65, MRR 0.56 → 0.59; the two sector cases go from recall@10 0.47 to 1.00 ([evaluation notes](evaluation.md#after-sector-phrases)). The retrieval gain comes from resolving the phrase, not from the template. The generation harness is not built yet, so there are no answer scores before and after. Hand check on the brief's third example ("What regulatory risks do the major pharmaceutical companies face?", `make ask`, `gpt-6-luna`): the answer opens "The Sector table defines the companies in scope as Johnson & Johnson (JNJ), Eli Lilly and Company (LLY), Merck & Co. (MRK), Pfizer (PFE), and AbbVie (ABBV)", covers those five and no other company, and cites a Source from each. About 21.5k input and 1,000 output tokens, 13.5 seconds.
