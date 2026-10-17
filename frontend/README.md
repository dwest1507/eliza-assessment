# Research workspace (front-end)

The Next.js research workspace: an analyst asks a question, or clicks a starter prompt, watches the answer stream in, and clicks any `[Sn]` citation to open that Source's passage in a side panel. It sits on the stack of the developer's portfolio: Next.js (App Router), Tailwind CSS and the AI SDK's `useChat`. It shares the portfolio's look as well: a dark canvas with a faint grid and an ambient glow, glass cards, Inter with monospaced labels and a sky-blue accent, all defined as theme tokens and a few component classes in [`app/globals.css`](app/globals.css).

Run it from the repo root with `make dev`, which starts the chat API and this app together (see the root [README](../README.md#running-the-full-stack)).

## How it talks to the backend

The browser never calls the chat API directly. `useChat` posts the conversation to this app's own route, [`app/api/chat/route.ts`](app/api/chat/route.ts), which forwards the last messages the prompt uses (the question and the 10 before it, the backend's `HISTORY_TURNS`; older ones are dropped, so a long conversation keeps working), each with its role and text (and, for an earlier answer, the Filing ID each of its Source tags cited, never the passages) to the API's `POST /api/chat` (it reads them with the same helpers in [`lib/chat.ts`](lib/chat.ts) that the workspace uses to read a message's text, Sources and data parts) and streams the API's [AI SDK UI message stream](https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol) back unchanged. The API's URL therefore stays on the server. It comes from `BACKEND_URL` (copy [`.env.example`](.env.example) to `.env`); when unset it is `http://127.0.0.1:8000`, where `make api` listens. `make dev` sets it to the API it starts.

The stream carries the Query Scope and the numbered Sources as data parts before the answer text, so every citation is clickable while the answer is still arriving. The Query Scope shows as chips above each answer, so the analyst sees what the system answered and can dispute it: each Sector phrase with the Companies it resolved to (hover for the Sector table rows it used), the other Companies, the time window, any Section hints and the metric.

An empty conversation shows the starter prompts and, below them, a line saying how many Companies are covered and how many have two or more years of quarterly Filings, linking to the "What's covered" list on "How it works". The workspace page builds those counts with [`lib/coverage.ts`](lib/coverage.ts) from the committed evaluation export's coverage grid, the data "How it works" reads, so the two pages never disagree; without that summary the workspace shows no coverage line.

The conversation is kept in the browser's session storage ([`lib/conversation.ts`](lib/conversation.ts)), so a refresh keeps it and a new browser session starts empty; the backend keeps nothing. It is saved once each answer is complete. "New conversation" in the header clears it, so an old Query Scope can't leak into a new topic.

## Layout

| Path                               | What it is                                                                                            |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `app/page.tsx`                     | The workspace page, given the Corpus coverage summary from the evaluation export                      |
| `app/api/chat/route.ts`            | The server-side proxy to the chat API                                                                 |
| `app/how-it-works/page.tsx`        | The "How it works" page, rendered from the evaluation export                                          |
| `components/Workspace.tsx`         | The conversation thread, starter prompts and question box                                             |
| `components/AnswerMessage.tsx`     | One answer: Markdown with `[Sn]` citations as links, and its Sources                                  |
| `components/QueryScopeChips.tsx`   | The Query Scope chips above an answer                                                                 |
| `components/SourcesPanel.tsx`      | The side panel showing one Source's Filing metadata and passage, or a Facts Source's table of figures |
| `components/AmbientBackground.tsx` | The portfolio's fixed, blurred background glow                                                        |
| `lib/chat.ts`                      | The stream's data part types, the shared message readers, the turn limit and the citation helpers     |
| `lib/starters.ts`                  | The six starter prompts, copied from the Brief Suite and the Golden Set                               |
| `lib/conversation.ts`              | Keeps the conversation in session storage                                                             |
| `components/HowItWorks.tsx`        | The architecture, the evaluation scoreboard and the coverage grid                                     |
| `components/WhatsCovered.tsx`      | "What's covered": every Company, grouped by Tracked and Snapshot in plain words                       |
| `lib/coverage.ts`                  | The Corpus coverage summary (Company counts and list) built from the export's coverage grid           |
| `lib/evalExport.ts`                | The evaluation export's types and number formats                                                      |
| `data/eval-export.json`            | The evaluation export, written by `make eval-export` (committed)                                      |
| `__tests__/`                       | Vitest and React Testing Library tests                                                                |

The starter prompts are the labelled cases that carry a `starter` object, so every demo prompt is measured: the brief's three questions from the Brief Suite (`data/eval/brief_suite.json`), each taking over the starter of the Golden Set version 1 case it replaces, and three Golden Set cases (`data/eval/golden_set.json`). `__tests__/starters.test.ts` reads both files and fails if the copy in `lib/starters.ts` drifts from them.

## The "How it works" page

`/how-it-works`, linked from the workspace's header, puts the evidence inside the product: "What's covered" at the top (every Company, grouped in plain words into those with two or more years of history, the Tracked Companies, and those with only a few Filings, the Snapshot Companies, under the `#whats-covered` anchor the workspace's coverage line links to), the architecture (from the Corpus to the one Answer Call, and how it is measured), the evaluation scoreboard on Golden Set version 2 (each retrieval Arm against the Shipped Arm on Evidence Reached, with whether it can ship and the free screen's result; the shipped run beside its Control Run and each generator's scores, cost and latency; and the generator comparison: the Control Run's and each challenger's one-sided sign tests and bootstrap intervals against the shipped generator, and the generator chosen, worded as directional), the Brief Suite (each case's pass or fail, its missed must-state facts and how many never reached the Answer Context), the holdout run (its retrieval and answer scores, shown beside dev's with the small-sample caveat) and the Corpus coverage grid (each Company's Filings by Report Period, Tracked and Snapshot). It is a static page built from [`data/eval-export.json`](data/eval-export.json), which `make eval-export` writes from the harnesses' latest reports (see the root [README](../README.md#showing-the-results-in-the-workspace)). The file is committed and generated, never edited by hand; Prettier skips it.

## Commands

From the repo root, `make install`, `make test`, `make lint` and `make format` cover this app as well as the backend. Inside `frontend/`:

| Command                                                       | What it does                                                    |
| ------------------------------------------------------------- | --------------------------------------------------------------- |
| `npm run dev`                                                 | The dev server on http://localhost:3000 (needs the API running) |
| `npm test`                                                    | The Vitest suite                                                |
| `npm run lint` / `npm run typecheck` / `npm run format:check` | ESLint, TypeScript and Prettier checks                          |
| `npm run build`                                               | A production build                                              |

The tests run against a mocked stream: `fetch` returns the API's UI message stream, so the real `useChat` parses it. They cover a starter sending on click, Markdown rendering, a citation opening its Source in the panel, a Facts Source shown as a table, the Query Scope chips, the conversation surviving a refresh, the "New conversation" control, the API's reason shown when it rejects a request, the empty workspace's coverage line and its link (and no line without the coverage summary), the proxy route (which sends only the turns the prompt uses), and the shared message readers and turn limit (`__tests__/chat.test.ts`, which also checks the front-end's copy of the prompt's `HISTORY_TURNS` against the backend's). The "How it works" page, including the grouped "What's covered" list, is rendered from a fixture export (`__tests__/fixtures/eval-export.json`).
