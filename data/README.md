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

## Sector reference table (`reference/sectors.csv`)

Filings carry no sector, so each Company is mapped to one in a small curated table, the only outside reference data that can affect answers. One row per Company (54 rows):

| Column | Meaning |
|---|---|
| `ticker`, `company` | As in the Filing headers |
| `sector`, `industry` | GICS-style sector and industry |
| `sic_code`, `sic_description` | The Company's SEC Standard Industrial Classification |
| `sic_agrees` | `yes` when the SIC code points to the same sector and industry as the GICS-style label, else `no` |
| `note` | Why they disagree (required when `sic_agrees` is `no`), or another caveat |

Sources:

- **Sector and industry** were curated by hand from the GICS structure (11 sectors, as revised in March 2023) and the Companies' publicly reported S&P 500 GICS assignments. This is a GICS-style label, not a licensed GICS data feed.
- **SIC code and description** come from the SEC EDGAR submissions API (`https://data.sec.gov/submissions/CIK##########.json`, fields `sic` and `sicDescription`), retrieved 2026-10-15 for each Company's CIK in the Corpus.

The GE row describes the Filing in the Corpus, GE Capital's FY2014 10-K, not today's General Electric. Unlike the Corpus, this table is ours to edit; a test checks it has exactly one row per Company and an explanation for every disagreement.

## Derived files

Anything built from the Corpus (cleaned Sections, a Financial Facts database, indexes) is written to `data/derived/`, which is gitignored and rebuilt by Makefile targets.

## SEC company-facts reference (`derived/sec_companyfacts/`)

To measure how accurately Financial Facts are extracted, the EDA compares them with the SEC's XBRL company-facts data (`https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`), one JSON file per Tracked Company plus an `index.json` recording the retrieval date. **It is an evaluation reference only, never an answer source:** nothing that answers questions reads it.

`make sec-facts` fetches it into `data/derived/sec_companyfacts/` (gitignored). `make eda` fetches it first if the cache is missing, and otherwise works from the cache.

The SEC requires every automated request to carry a User-Agent naming the requester and a contact email. Fetching reads it from the `SEC_USER_AGENT` environment variable and refuses to run without it:

```sh
cp backend/.env.example backend/.env   # then edit SEC_USER_AGENT (unquoted)
make sec-facts
```

`backend/.env` is gitignored, so the contact address stays out of the repository.
