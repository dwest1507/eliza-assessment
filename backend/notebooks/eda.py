# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # EDA: characterise the Corpus
#
# Exploratory data analysis of the SEC EDGAR Corpus supplied with the assessment.
# Every analysis loads Filings through the `edgar_rag` Corpus seam, the same code the
# indexer and API will use, and ends with a **so the design does X** conclusion.
# Findings are collected in [`docs/findings.md`](../../docs/findings.md).
#
# This file is the source of truth (jupytext percent format). The paired `.ipynb`
# is generated with `make eda` and is never edited by hand.

# %%
import json
import re
from collections import Counter

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

from edgar_rag.corpus import DEFAULT_CORPUS_DIR, check_manifest, load_corpus

filings = load_corpus()
print(f"{len(filings)} Filings from {len({f.ticker for f in filings})} Companies")

# %% [markdown]
# ## 1. Inventory and coverage
#
# How many Filings does each Company have, of which Form Type, and in which Calendar
# Quarters? Calendar Quarter is taken from the header as written. Filings whose header
# has no Calendar Quarter are counted in a separate column; deriving their Report
# Period is a later analysis.

# %%
df = pd.DataFrame(
    {
        "ticker": f.ticker,
        "company": f.company,
        "form_type": f.form_type,
        "calendar_quarter": f.calendar_quarter,
        "report_period": f.report_period,
        "filing_date": f.filing_date,
    }
    for f in filings
)

per_company = (
    df.pivot_table(index="ticker", columns="form_type", values="company", aggfunc="count")
    .fillna(0)
    .astype(int)
)
per_company["total"] = per_company.sum(axis=1)
per_company = per_company.sort_values(["total", "10-Q"], ascending=False)
per_company.T

# %%
filings_per_company = Counter(per_company["total"])
pd.DataFrame(
    sorted(filings_per_company.items(), reverse=True),
    columns=["Filings per Company", "Companies"],
).set_index("Filings per Company").T

# %%
NO_QUARTER = "none in header"

known_quarters = df["calendar_quarter"].dropna()
quarters = [str(q) for q in pd.period_range(known_quarters.min(), known_quarters.max(), freq="Q")]
columns = quarters + [NO_QUARTER]
tickers = list(per_company.index)

# Cell code: 0 = no Filing, 1 = 10-Q only, 2 = 10-K only, 3 = both.
codes = np.zeros((len(tickers), len(columns)), dtype=int)
counts = np.zeros_like(codes)
for f in filings:
    row = tickers.index(f.ticker)
    col = columns.index(f.calendar_quarter or NO_QUARTER)
    codes[row, col] |= 2 if f.form_type == "10-K" else 1
    counts[row, col] += 1

colours = ["#f2f2f2", "#6baed6", "#fd8d3c", "#8c6bb1"]
fig, ax = plt.subplots(figsize=(11, 15))
ax.imshow(codes, cmap=ListedColormap(colours), vmin=0, vmax=3, aspect="auto")
for r, c in zip(*np.nonzero(counts > 1), strict=True):
    ax.text(c, r, counts[r, c], ha="center", va="center", fontsize=8, color="white")

ax.set_xticks(range(len(columns)), columns, rotation=90)
ax.set_yticks(range(len(tickers)), [f"{t} ({per_company.loc[t, 'total']})" for t in tickers])
ax.set_xticks(np.arange(-0.5, len(columns)), minor=True)
ax.set_yticks(np.arange(-0.5, len(tickers)), minor=True)
ax.grid(which="minor", color="white", linewidth=1)
ax.tick_params(which="minor", length=0)
ax.axvline(len(quarters) - 0.5, color="black", linewidth=1.5)
ax.set_xlabel("Calendar Quarter (from the Filing header)")
ax.set_ylabel("Company (total Filings)")
ax.set_title("Coverage: Company × Calendar Quarter × Form Type\n(number = Filings sharing a cell)")
ax.legend(
    handles=[
        Patch(color=colour, label=label)
        for colour, label in zip(colours[1:], ["10-Q", "10-K", "10-K and 10-Q"], strict=True)
    ],
    loc="upper left",
    bbox_to_anchor=(1.01, 1.0),
)
fig.tight_layout()
plt.show()

# %%
missing_quarter = df[df["calendar_quarter"].isna()]
shared_cells = int((counts[:, : len(quarters)] > 1).sum())
print(f"Filings with no Calendar Quarter in the header: {len(missing_quarter)}")
print(f"Companies with exactly one Filing: {(per_company['total'] == 1).sum()}")
print(f"Companies with 4 or more Filings: {(per_company['total'] >= 4).sum()}")
print(f"Company × Calendar Quarter cells holding more than one Filing: {shared_cells}")

# %% [markdown]
# **What the grid shows**
#
# - Coverage is very uneven. 12 Companies have 14–17 Filings spread over 2022Q1–2025Q4,
#   META has 8, JPM and BAC have 4, MCD and PEP have 2, and the remaining 37 Companies
#   have a single 10-K.
# - Every Company has exactly one Filing with no Calendar Quarter (or Report Period) in
#   its header: its most recent 10-K (filed between 2024 and 2026, plus GE's from 2015).
#   For the 37 single-Filing Companies that is their only Filing, so they cannot be
#   placed on the time axis from the header alone.
# - Several Company × Calendar Quarter cells hold two Filings (e.g. Coca-Cola's two
#   2022Q3 Filings), so Calendar Quarter cannot be a unique key.
# - Coverage starts in 2022Q1, a year before the brief's "2023–2025".
#
# **So the design does:**
#
# - Treat Company coverage as first-class metadata: classify each Company as a Tracked
#   Company (quarterly Filings across years, trend questions answerable) or a Snapshot
#   Company (point-in-time only), and have the Answer Call state plainly when coverage
#   limits an answer.
# - Filter retrieval on Company and Report Period metadata instead of relying on
#   similarity alone, so a trend question about a Tracked Company is not crowded out by
#   one-off 10-Ks, and a comparison across Snapshot Companies retrieves each of them.
# - Derive a Report Period for every Filing whose header lacks one (next analysis), and
#   never use Calendar Quarter as a key.

# %% [markdown]
# ## 2. Metadata integrity
#
# Can every Filing be placed on the time axis and identified unambiguously? This
# analysis checks the metadata from every angle available: the header, the file name,
# the manifest, the source URL and the cover-page sentence ("For the fiscal year ended
# ..." / "For the quarterly period ended ...").
#
# The Corpus seam resolves each Filing's Report Period from the header, else the date
# in the source URL, else the cover-page sentence. It cross-checks every source that is
# present and records disagreements as diagnostics on the Filing.

# %% [markdown]
# ### 2.1 Manifest vs files on disk, and header vs file name

# %%
manifest = json.loads((DEFAULT_CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
print("Manifest problems:", check_manifest() or "none")
print("Manifest Form Type counts:", manifest["filing_types"])
print("Header Form Type counts:  ", dict(Counter(f.form_type for f in filings)))

FILE_NAME = re.compile(r"^([A-Z]+)_(10K|10Q)_(?:(\d{4}Q[1-4])_)?(\d{4}-\d{2}-\d{2})_full\.txt$")
name_mismatches = []
for f in filings:
    ticker, form, quarter, filed = FILE_NAME.match(f.path.name).groups()
    expected = (f.ticker, f.form_type.replace("-", ""), f.calendar_quarter, str(f.filing_date))
    if (ticker, form, quarter, filed) != expected:
        name_mismatches.append(f.path.name)
print("File names disagreeing with their header (ticker, Form Type, Quarter, Filing Date):")
print("  ", name_mismatches or "none")

# %% [markdown]
# ### 2.2 Missing header fields and where each Report Period came from

# %%
header_fields = pd.DataFrame(
    {
        "Report Period in header": sum(f.report_period_source == "header" for f in filings),
        "Calendar Quarter in header": sum(f.calendar_quarter is not None for f in filings),
    },
    index=["Filings"],
)
header_fields["Filings in Corpus"] = len(filings)
header_fields

# %%
sources = pd.crosstab(
    pd.Series([f.report_period_source for f in filings], name="Report Period source"),
    pd.Series([f.form_type for f in filings], name="Form Type"),
    margins=True,
)
sources

# %%
diagnostics = [(f.filing_id, d.code, d.detail) for f in filings for d in f.diagnostics]
print(f"Filings with a Report Period: {sum(f.report_period is not None for f in filings)}")
print(f"Diagnostics (source disagreements, missing cover-page sentence, ...): {len(diagnostics)}")
pd.DataFrame(diagnostics, columns=["filing_id", "code", "detail"])

# %% [markdown]
# The 54 Filings with no Report Period in the header are exactly the 54 most recent
# 10-Ks, one per Company. 53 have a dated source URL; the cover-page sentence agrees
# with it in every case. For the 192 Filings that do have a header Report Period, the
# URL date and the cover-page sentence agree with it too. Two kinds of flattening
# quirk had to be handled to find the sentence: the date glued to the phrase
# (`endedDecember 31, 2025`) and a table cell between them
# (`For the quarterly period ended | Commission file |\nMarch 31, 2025`).
#
# ### 2.3 The GE Filing

# %%
ge = next(f for f in filings if f.ticker == "GE")
ge_text = ge.path.read_text(encoding="utf-8")
registrant = re.search(r"([A-Z][A-Za-z ]+?)\s*\(Exact name of registrant", ge_text).group(1)
print(f"Header Company:      {ge.company} (CIK {ge.cik})")
print(f"Cover-page registrant: {registrant}")
print(f"Source URL:          {ge.source_url}")
print(f"Report Period:       {ge.report_period} (from {ge.report_period_source})")
print(f"Fiscal Period:       {ge.fiscal_period}, filed {ge.filing_date}")

# %% [markdown]
# The GE Filing is **not** a General Electric Company report. Its header says "General
# Electric Company", but the cover page names **General Electric Capital Corporation**
# (GE Capital) as the registrant, the document is `gecc10k2014.htm`, and the CIK it is
# filed under (0000040554) is GE Capital's EDGAR folder. It is GE Capital's 10-K for
# the **fiscal year ended 31 December 2014**, filed on 27 February 2015. Its URL has no
# date, so its Report Period comes from the cover-page sentence.
#
# ### 2.4 Calendar Quarter clashes


# %%
def calendar_quarter_of(d):
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


inconsistent = [
    f.filing_id
    for f in filings
    if f.calendar_quarter and f.calendar_quarter != calendar_quarter_of(f.report_period)
]
print("Calendar Quarter not the quarter its Report Period ends in:", inconsistent or "none")

by_cell = df.assign(filing=filings).dropna(subset=["calendar_quarter"])
clashes = pd.DataFrame(
    {
        "ticker": f.ticker,
        "calendar_quarter": f.calendar_quarter,
        "form_type": f.form_type,
        "report_period": f.report_period,
        "fiscal_period": f.fiscal_period,
        "filing_id": f.filing_id,
    }
    for _, group in by_cell.groupby(["ticker", "calendar_quarter"])
    if len(group) > 1
    for f in group["filing"]
)
clashes

# %%
ids = [f.filing_id for f in filings]
cells = by_cell.groupby(["ticker", "calendar_quarter"]).ngroups
print(f"Company × Calendar Quarter cells with a Filing: {cells}")
print(f"Filings with a Calendar Quarter:                {len(by_cell)}")
print(f"Distinct Filing identifiers:                   {len(set(ids))} of {len(ids)}")

# %% [markdown]
# Every Calendar Quarter label is correct by its own definition (the calendar quarter
# in which the Report Period ends), yet seven Company × Calendar Quarter cells hold two
# Filings. All seven come from 52/53-week fiscal calendars whose periods end a day or
# two into the next calendar quarter. Coca-Cola's second quarter of 2022 ended on
# 1 July, so it shares 2022Q3 with its third quarter (30 September). Apple's and
# Disney's third quarters of 2023 also ended on 1 July. Disney's FY2022 and Pfizer's
# and J&J's third quarters ended on 1–2 October. The identifier
# `ticker_FormType_ReportPeriod` keeps all 246 Filings distinct.
#
# ### 2.5 CIK and Company name consistency

# %%
ciks_per_ticker = df.assign(cik=[f.cik for f in filings]).groupby("ticker")["cik"].nunique()
tickers_per_cik = df.assign(cik=[f.cik for f in filings]).groupby("cik")["ticker"].nunique()
names_per_ticker = df.groupby("ticker")["company"].nunique()
url_not_under_cik = [f.filing_id for f in filings if f"/data/{int(f.cik)}/" not in f.source_url]
print(f"Tickers with more than one CIK:  {(ciks_per_ticker > 1).sum()}")
print(f"CIKs with more than one ticker:  {(tickers_per_cik > 1).sum()}")
print(f"Tickers with more than one name: {(names_per_ticker > 1).sum()}")
print(f"Filings whose URL is not under their CIK: {url_not_under_cik or 'none'}")

# %% [markdown]
# ### 2.6 Fiscal year ends and Fiscal Periods
#
# Each Company's fiscal year end is derived from its 10-K Report Periods. A period end
# within the first seven days of a month counts as the end of the previous month, so
# 52/53-week years (Deere's 2 November, J&J's 2 January) map to the right month. Each
# Filing's Fiscal Period is then counted from that month, and the fiscal year is named
# after the calendar year in which it ends.

# %%
fiscal_year_ends = (
    pd.Series({f.ticker: f.fiscal_year_end_month for f in filings}, name="fiscal year end month")
    .map(lambda m: pd.Timestamp(2000, m, 1).strftime("%B"))
    .rename_axis("ticker")
)
fiscal_year_ends.value_counts().to_frame("Companies").T

# %%
fiscal_year_ends[fiscal_year_ends != "December"].to_frame().T

# %%
example = next(f for f in filings if f.ticker == "NVDA" and str(f.report_period) == "2025-07-27")
print(f"{example.filing_id}: {example.fiscal_period}")
print(f"Filings without a Fiscal Period: {sum(f.fiscal_period is None for f in filings)}")

# %% [markdown]
# 17 of 54 Companies do not have a December year end. The Fiscal Period rule reproduces
# each Company's own label where we checked it (NVIDIA's quarter ending 27 July 2025 is
# Q2 FY2026; Apple, Microsoft, Walmart and Salesforce match their reports). It does
# **not** match retailers that name a fiscal year after the year it starts in: Home
# Depot calls the year ended 2 February 2025 "fiscal 2024", and Target likewise, while
# the rule labels it FY2025. Both are Snapshot Companies with one 10-K each, and the
# Fiscal Period is a secondary label, so this is recorded rather than special-cased.
#
# ### 2.7 Filings outside the brief's "2023–2025" window

# %%
out_of_window = sorted(
    (f for f in filings if not 2023 <= f.report_period.year <= 2025),
    key=lambda f: (f.report_period, f.ticker),
)
print(f"Filings with a Report Period outside 2023–2025: {len(out_of_window)}")
pd.DataFrame(
    {
        "ticker": f.ticker,
        "form_type": f.form_type,
        "report_period": f.report_period,
        "fiscal_period": f.fiscal_period,
        "filing_date": f.filing_date,
    }
    for f in out_of_window
).groupby("ticker").agg(
    filings=("form_type", "size"),
    first=("report_period", "min"),
    last=("report_period", "max"),
    forms=("form_type", lambda s: ", ".join(f"{n} {t}" for t, n in Counter(s).items())),
)

# %%
filed_after = [f for f in filings if f.filing_date.year > 2025]
print(f"Filings inside the window by Report Period but filed in 2026: {len(filed_after)}")
print("By Form Type:", dict(Counter(f.form_type for f in filed_after)))

# %% [markdown]
# **What the integrity checks show**
#
# - The metadata is internally consistent: the manifest matches the files on disk, every
#   file name agrees with its header, each ticker has one CIK and one name, and every
#   source URL sits under the Filing's CIK.
# - Every Filing now has a Report Period: 192 from the header, 53 from the source URL
#   and 1 (GE Capital) from the cover-page sentence. Where more than one source exists
#   they agree, so there are no diagnostics to review by hand.
# - The "GE" Filing is GE Capital's FY2014 10-K, filed in 2015, under GE's ticker.
# - Seven Company × Calendar Quarter cells hold two Filings, all caused by 52/53-week
#   fiscal calendars. The identifier `ticker_FormType_ReportPeriod` is unique.
# - 17 Companies have a non-December fiscal year end.
# - 48 Filings have a Report Period outside 2023–2025: GE Capital's FY2014 10-K and 47
#   Filings from 12 Companies in 2022 (including J&J's FY2021 10-K, whose year
#   ended 2 January 2022). A further 27 Filings fall inside the window but were filed
#   in 2026: 24 FY2025 10-Ks and 3 10-Qs for quarters ending in December 2025.
#
# **So the design does:**
#
# - Use the Report Period as the time axis and `ticker_FormType_ReportPeriod` as the
#   Filing key everywhere (chunk metadata, citations, Financial Facts). Never key on
#   Calendar Quarter or Filing Date.
# - Keep the Report Period source on every Filing and keep cross-checking it, so a new
#   Filing whose sources disagree is surfaced, not silently trusted.
# - Show both the Report Period and the Fiscal Period in citations ("NVIDIA 10-Q, Q2
#   FY2026, period ended 2025-07-27"), and resolve relative questions ("last two
#   years", "latest") on Report Period.
# - Keep all 48 out-of-window Filings, but flag GE Capital's FY2014 10-K as stale and
#   attribute it to GE Capital, not General Electric, in any answer that uses it.

# %% [markdown]
# ## 3. Text anatomy
#
# What is each Filing actually made of? Every character of the raw body (the text
# after the header) is put in one of five classes:
#
# - **XBRL noise**: the machine-readable residue in front of the cover page, which the
#   Corpus seam removes (`Filing.xbrl_noise_chars`).
# - **TOC**: the table of contents the seam locates (`Filing.toc`).
# - **Exhibits and signatures**: exhibit-index rows ("31.1 | Certification of ...") and
#   signature lines ("/s/ ...", "SIGNATURES", "duly caused this report to be signed").
# - **Flattened tables**: any other line made of `|`-separated cells, the remains of
#   HTML tables. A line counts only if none of its cells is longer than 500
#   characters: some Filings glue whole pages of prose into one line around a page
#   footer such as "Apple Inc. | 2024 Form 10-K | 20", and that prose is not a table.
# - **Prose**: everything else.
#
# The last three are line-level heuristics written for this analysis, not part of the
# core package; they are good enough to size cleaning priorities, not to cut text.

# %%
EXHIBIT_ROW = re.compile(
    r"^\s*\|?\s*(?:\d{1,3}(?:\.[0-9A-Z]{1,4}){1,2}|10[14])\s*[*†‡#+^]*\s*(?:\(\w\))?\s*\|"
)
SIGNATURE_LINE = re.compile(
    r"/s/|^\s*SIGNATURES?\s*$|duly caused this report to be signed", re.IGNORECASE
)
RUNNING_HEADER = re.compile(r"Table of Contents", re.IGNORECASE)
MAX_TABLE_CELL = 500
CLASSES = ["XBRL noise", "TOC", "Exhibits and signatures", "Flattened tables", "Prose"]


def anatomy(filing):
    """Characters of the raw body in each class."""
    chars = dict.fromkeys(CLASSES, 0)
    chars["XBRL noise"] = filing.xbrl_noise_chars
    toc_start, toc_end = (filing.toc.start, filing.toc.end) if filing.toc else (0, 0)
    pos = 0
    for line in filing.body.split("\n"):
        size = len(line) + 1
        if toc_start <= pos < toc_end:
            chars["TOC"] += size
        elif EXHIBIT_ROW.match(line) or SIGNATURE_LINE.search(line):
            chars["Exhibits and signatures"] += size
        elif "|" in line and max(len(cell) for cell in line.split("|")) <= MAX_TABLE_CELL:
            chars["Flattened tables"] += size
        else:
            chars["Prose"] += size
        pos += size
    return chars


def running_headers(filing):
    """'Table of Contents' page headers left in the text outside the TOC itself."""
    toc_text = filing.body[filing.toc.start : filing.toc.end] if filing.toc else ""
    return len(RUNNING_HEADER.findall(filing.body)) - len(RUNNING_HEADER.findall(toc_text))


anat = pd.DataFrame(
    {
        "ticker": f.ticker,
        "form_type": f.form_type,
        "file": f.path.name,
        "raw_chars": f.xbrl_noise_chars + len(f.body),
        "has_toc": f.toc is not None,
        "running_headers": running_headers(f),
        "longest_line": max(len(line) for line in f.body.split("\n")),
        **anatomy(f),
    }
    for f in filings
)
assert (anat[CLASSES].sum(axis=1) == anat["raw_chars"] + 1).all()  # +1: the final newline


def shares(frame):
    """Character-weighted share of each class, in percent."""
    return (frame[CLASSES].sum() / frame[CLASSES].sum().sum() * 100).round(1)


by_form = pd.DataFrame(
    {
        "Corpus": shares(anat),
        "10-K": shares(anat[anat["form_type"] == "10-K"]),
        "10-Q": shares(anat[anat["form_type"] == "10-Q"]),
    }
).T
by_form

# %%
size_bins = [0, 200_000, 400_000, 800_000, float("inf")]
size_labels = ["< 200k chars", "200k–400k", "400k–800k", "≥ 800k"]
anat["size_bin"] = pd.cut(anat["raw_chars"], size_bins, labels=size_labels, right=False)
by_size = anat.groupby("size_bin", observed=True)[CLASSES].sum()
by_size = by_size.div(by_size.sum(axis=1), axis=0) * 100
filings_per_bin = anat["size_bin"].value_counts().reindex(size_labels)

class_colours = ["#bdbdbd", "#fd8d3c", "#8c6bb1", "#6baed6", "#31a354"]
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.5), sharex=True)
for ax, frame, title, ylabels in [
    (ax1, by_form, "By Form Type", by_form.index),
    (
        ax2,
        by_size,
        "By Filing size (raw body characters)",
        [f"{b} ({filings_per_bin[b]} Filings)" for b in by_size.index],
    ),
]:
    left = np.zeros(len(frame))
    for cls, colour in zip(CLASSES, class_colours, strict=True):
        ax.barh(range(len(frame)), frame[cls], left=left, color=colour, label=cls)
        left += frame[cls].to_numpy()
    ax.set_yticks(range(len(frame)), ylabels)
    ax.invert_yaxis()
    ax.set_title(title)
    ax.set_xlabel("Share of raw body characters (%)")
fig.legend(*ax1.get_legend_handles_labels(), loc="lower center", ncol=5, frameon=False)
fig.suptitle("Text anatomy: what the Filings are made of")
fig.tight_layout(rect=(0, 0.07, 1, 1))
plt.show()

by_size.round(1).assign(Filings=filings_per_bin)

# %%
per_filing = anat.assign(
    **{f"{c} %": (anat[c] / anat["raw_chars"] * 100).round(1) for c in CLASSES}
)
pct = [f"{c} %" for c in CLASSES]
fig, ax = plt.subplots(figsize=(11, 4))
ax.boxplot([per_filing[c] for c in pct], orientation="horizontal", tick_labels=CLASSES)
ax.invert_yaxis()
ax.set_xlabel("Share of the Filing's raw body (%)")
ax.set_title("Spread of each class across the 246 Filings")
fig.tight_layout()
plt.show()

per_filing.sort_values("XBRL noise %", ascending=False)[["file", "raw_chars", *pct]].head(8)

# %%
print(f"XBRL noise removed: {anat['XBRL noise'].sum() / 1e6:.1f}M characters in total")
print(
    "Filings where XBRL noise is over 20% of the raw body: "
    f"{(per_filing['XBRL noise %'] > 20).sum()}"
)
print(f"Filings without a table of contents: {(~anat['has_toc']).sum()}")
print(", ".join(anat.loc[~anat["has_toc"], "file"]))
print(
    "Filings with 'Table of Contents' running page headers left in the text: "
    f"{(anat['running_headers'] > 0).sum()} "
    f"({anat['running_headers'].sum()} headers in total)"
)
print(
    "Filings with a single line over 20,000 characters: "
    f"{(anat['longest_line'] > 20_000).sum()} "
    f"(longest: {anat['longest_line'].max():,} characters, "
    f"{anat.loc[anat['longest_line'].idxmax(), 'file']})"
)

# %% [markdown]
# **What the anatomy shows**
#
# - XBRL noise is 13.6% of all raw text (11.1M characters), more in 10-Qs (16%) than
#   10-Ks (12%), over 20% in 31 Filings and 52% in IBM's 10-K. It is pure machine
#   residue (context IDs, taxonomy URLs, hidden facts) glued in front of the cover
#   page. The Corpus seam strips it, and a Corpus-level test checks that no cleaned
#   body contains an XBRL signature.
# - Flattened tables are about a fifth of the text (24% in 10-Qs, a quarter of the
#   largest Filings). They hold most of the numbers the Client will ask about, but as
#   rows of `|`-separated cells, so a value cut away from its row and column labels
#   means nothing.
# - The TOC is small (under 1%) but dangerous: its rows repeat every Item heading.
#   The seam locates it in all but nine Filings (Disney 10-Qs before 2025, which have
#   none), always in the first tenth of the body.
# - Exhibit indexes and signatures are about 3% (4% of 10-Ks) and carry no business
#   content.
# - Line breaks are not paragraph breaks. 135 Filings have a single line over 20,000
#   characters (META's longest is 287,855): whole pages of prose glued together, with
#   page footers ("Apple Inc. | 2024 Form 10-K | 20") and "Table of Contents" running
#   headers (7,813 of them, in 204 Filings) embedded mid-line.
#
# **So the design does:**
#
# - Index only the cleaned body: XBRL noise never reaches a chunk or a prompt.
# - Skip the TOC span in Section detection (next analysis) and leave it out of the
#   index, so a TOC row like "Item 1A. | Risk Factors | 5" is never retrieved as if it
#   were the Risk Factors.
# - Leave exhibit indexes and signatures out of the index.
# - Chunk tables as whole tables (or row groups that repeat the table's header rows),
#   never splitting a row from its labels, and tag them as table chunks so the Answer
#   Call knows it is reading a table. Their numbers are also the input to the Financial
#   Facts experiment (analysis 7).
# - Split prose on sentence boundaries within a token budget, not on line breaks, and
#   strip running page headers and page footers before chunking so they do not pollute
#   chunk text and embeddings.
