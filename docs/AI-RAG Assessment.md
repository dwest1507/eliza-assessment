# Forward Deployed Engineer
## AI Engineering Assessment- RAG

---

## Context

<mark>You will build a presentation that displays technical capabilities while defending business value for a fictitious company Private Equity firm.</mark>

<mark>The presentation should be a working demo that answers a business question about SEC financial filings using a single LLM API call with retrieval-augmented generation and also includes information on how this creates value for the business.</mark>

**Timebox:** ~4 hours

## The Task

Build a retrieval index over the provided corpus and a prompt template that injects retrieved context into a single LLM call. The system should accept a natural-language business question as input and return a well-structured answer grounded in the filing data.

The final answer must be produced in **one API request**. Your indexing and retrieval pipeline can run beforehand, but the answer itself must come from a single LLM call. Beyond that constraint, the design is yours.

Document your assumptions and the decisions you make along the way.

## Dataset

The corpus is a collection of SEC EDGAR filings — annual reports (10-K) and quarterly reports (10-Q) from major US public companies spanning 2023–2025.

Download the corpus here:

[edgar_corpus.zip](https://eliza-fde-assessment.s3.us-east-2.amazonaws.com/sec-filings/edgar_corpus.zip)

The zip contains `.txt` filings and a `manifest.json`.

## Business Question

During the demo, we will enter a business question into your system's input field. Examples of what we might ask:

- *"What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?"*
- *"How has NVIDIA's revenue and growth outlook changed over the last two years?"*
- *"What regulatory risks do the major pharmaceutical companies face, and how are they addressing them?"*

## Deliverables

Submit a repo or notebook containing:

- A README with setup and run instructions
- Your indexing and retrieval code
- A log of your prompt iterations (what changed, why)
- Your final prompt template
- A front-end
- An example request ready to execute
- Notes on how you evaluated quality

## Demo Format

You will set up your environment, talk your interview panel through it as if this were a real client meeting, and run a question through your system. In addition to the repo, we want to see a front-end to the system.

<mark>Be prepared to walk through your design decisions as well as defend the value creation. Additionally, assume the client would want to understand future state and capabilities if they are sold on this RAG solution.</mark>

## Questions

If anything is unclear, ask. We'd rather answer a good question now than review a set of wrong assumptions later.