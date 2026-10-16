# Data

## Corpus (`edgar_corpus/`)

The Corpus is the set of SEC EDGAR Filings supplied with the assessment brief, committed here exactly as extracted from the source zip.

| | |
|---|---|
| Source URL (from the brief) | <https://eliza-fde-assessment.s3.us-east-2.amazonaws.com/sec-filings/edgar_corpus.zip> |
| Downloaded | 2026-10-15 |
| SHA-256 of `edgar_corpus.zip` | `ed41deb84abde08834ce9084a43c5b74a67be0105ac6dcaea61ce33201f14746` |
| Zip size | 19,514,720 bytes (S3 `Last-Modified: Fri, 20 Feb 2026 02:08:25 GMT`) |
| Contents | 246 Filing `.txt` files plus `manifest.json` (247 files, about 79 MB uncompressed) |

The committed `edgar_corpus/` directory was checked against a fresh download of the zip on the date above (`diff -r` against the extracted files reported no differences).

To verify it yourself:

```sh
curl -sSfLO https://eliza-fde-assessment.s3.us-east-2.amazonaws.com/sec-filings/edgar_corpus.zip
sha256sum edgar_corpus.zip   # expect ed41deb8...f14746
unzip -q edgar_corpus.zip -d /tmp/edgar_corpus_check && diff -r /tmp/edgar_corpus_check data/edgar_corpus
```

**The Corpus is read-only.** Never edit, rename, add or delete files in `edgar_corpus/`. Every cleaning and derivation step happens in code (`backend/src/edgar_rag`), so the analysis always runs on the data the Client provided, unmodified.

## Derived files

Anything built from the Corpus (cleaned Sections, a Financial Facts database, indexes) is written to `data/derived/`, which is gitignored and rebuilt by Makefile targets.
