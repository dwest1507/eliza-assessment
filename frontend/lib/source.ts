import type { Source } from '@/lib/chat'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** A corporate suffix the heading leaves off: "NVIDIA Corporation" reads "NVIDIA". */
const COMPANY_SUFFIX = /,?\s+(?:Inc\.?|Incorporated|Corporation|Corp\.?)$/i

/** "2024-07-28" as "Jul 28, 2024", or the text unchanged when it is not such a date. */
function readableDate(isoDate: string): string {
  const match = isoDate.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  const month = match ? MONTHS[Number(match[2]) - 1] : undefined
  return match && month ? `${month} ${Number(match[3])}, ${match[1]}` : isoDate
}

/** The period a Source covers: its Fiscal Period, or the Report Period as a date. */
function readablePeriod(source: Source): string {
  if (source.fiscalPeriod) return source.fiscalPeriod
  const span = source.formType.startsWith('10-K')
    ? 'year'
    : source.formType.startsWith('10-Q')
      ? 'quarter'
      : 'period'
  return `${span} ended ${readableDate(source.reportPeriod)}`
}

/**
 * The one line that tells a reader what a Source is, naming its Company, Form Type,
 * period and Section: "NVIDIA 10-Q, Q2 FY2025 · MD&A".
 */
export function sourceHeading(source: Source): string {
  const company = source.company.replace(COMPANY_SUFFIX, '')
  return `${company} ${source.formType}, ${readablePeriod(source)} · ${source.section}`
}

/** One block of a passage as the Sources panel shows it. */
export type PassageBlock =
  | { kind: 'paragraph'; text: string }
  | { kind: 'table'; rows: string[][] }
  | { kind: 'elision'; label: string }

/** How the Sources panel names the break where the retrieval skipped text. */
const SKIPPED = 'passage skipped'

/**
 * A sentence end glued straight onto the next sentence ("earnings.Summary"): a lower-case
 * letter, digit, `)` or `%`, then `.`, `!` or `?` and any closing quote or bracket, then a
 * capital. The same rule the chunker splits sentences on (`_SENTENCE_END` in
 * `backend/src/edgar_rag/_chunks.py`), so "U.S.", "3.5" and "investor.apple.com" stay.
 */
const GLUED_SENTENCE = /([a-z0-9)%][.!?]["”’)]?)(?=[A-Z])/g

/**
 * A heading glued to the sentence after it ("SummaryThe Company", "OperationsWe sell"):
 * a lower-case letter, then a capitalised word that opens sentences in the Filings and
 * is followed by a space, so "WeChat" and "LinkedIn" stay.
 */
const GLUED_HEADING = /([a-z])(?=(?:The|We|Our|This|These|During) )/g

/**
 * Prose as the Sources panel shows it: sentences and headings the Corpus glued together
 * are spaced. Display only; the indexed text, and what the Answer Call reads, keep them.
 */
function spaced(text: string): string {
  return text.replace(GLUED_SENTENCE, '$1 ').replace(GLUED_HEADING, '$1 ')
}

/**
 * A line of a flattened table. The Corpus writes a table's rows as cells joined by
 * `|`: its header rows start with the pipe, and its data rows start with their label
 * ("Revenue | $ | 30,040 |"), so both count.
 */
function isTableLine(line: string): boolean {
  return /(?:^|\s)\|(?:\s|$)/.test(line.trim())
}

/**
 * What the retrieval writes where it skipped text: between two chunks of a Source that
 * are not next to each other in the Filing, or beside a chunk cut down to its new
 * paragraphs (chunks next to each other join as one passage). A copy of `GAP` in
 * `backend/src/edgar_rag/_repeats.py`, which a test keeps in sync.
 */
export const GAP = '\n[…]\n'

/**
 * A line that marks text left out between two passages: the retrieval's own gap
 * (`GAP`'s line), or `[...]` written with three dots.
 */
function isElision(line: string): boolean {
  const trimmed = line.trim()
  return trimmed === GAP.trim() || trimmed === '[...]'
}

/**
 * A table row's cells: split on `|`, trimmed, with the empty cells at its edges
 * dropped. An empty cell inside the row stays, since it holds a column's place.
 */
function rowCells(line: string): string[] {
  const cells = line
    .trim()
    .split('|')
    .map((cell) => cell.trim())
  if (cells[0] === '') cells.shift()
  while (cells.length > 0 && cells.at(-1) === '') cells.pop()
  return cells
}

/**
 * A passage's text as the blocks the Sources panel shows: a run of table lines becomes
 * a table (no header row is assumed, since the Corpus's flattened tables mark none), a
 * line that is just `[...]` an elision labelled "passage skipped", and the rest
 * paragraphs, their whitespace kept and their glued sentences spaced.
 */
export function passageBlocks(text: string): PassageBlock[] {
  const blocks: PassageBlock[] = []
  let paragraph: string[] = []
  let rows: string[][] | null = null

  const flush = () => {
    const joined = paragraph.join('\n').replace(/^\s*\n|\n\s*$/g, '')
    if (joined.trim()) blocks.push({ kind: 'paragraph', text: spaced(joined) })
    paragraph = []
    if (rows && rows.length > 0) blocks.push({ kind: 'table', rows })
    rows = null
  }

  for (const line of text.split(/\r?\n/)) {
    if (isElision(line)) {
      flush()
      blocks.push({ kind: 'elision', label: SKIPPED })
    } else if (isTableLine(line)) {
      if (!rows) flush()
      const cells = rowCells(line)
      rows ??= []
      if (cells.length > 0) rows.push(cells)
    } else {
      if (rows) flush()
      paragraph.push(line)
    }
  }
  flush()
  return blocks
}
