import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { Source } from '@/lib/chat'
import { GAP, passageBlocks, sourceHeading } from '@/lib/source'

const nvidiaSource: Source = {
  tag: 'S3',
  filingId: 'NVDA_10-Q_2024-07-28',
  company: 'NVIDIA Corporation',
  ticker: 'NVDA',
  formType: '10-Q',
  reportPeriod: '2024-07-28',
  fiscalPeriod: 'Q2 FY2025',
  calendarMonths: 'May–Jul 2024',
  section: 'MD&A',
  item: 'Item 2',
  label: 'NVDA 10-Q Q2 FY2025 (May–Jul 2024), MD&A (Item 2).',
  text: 'a passage',
}

describe('sourceHeading', () => {
  it('names the Company, form type, Fiscal Period with its calendar months, and Section', () => {
    expect(sourceHeading(nvidiaSource)).toBe('NVIDIA 10-Q, Q2 FY2025 (May–Jul 2024) · MD&A')
  })

  it('leaves the months out for a Source sent before they were', () => {
    const earlier = { ...nvidiaSource, calendarMonths: undefined }
    expect(sourceHeading(earlier)).toBe('NVIDIA 10-Q, Q2 FY2025 · MD&A')
  })

  it('drops a corporate suffix from the Company name', () => {
    const name = (company: string) => sourceHeading({ ...nvidiaSource, company }).split(' 10-Q')[0]
    expect(name('Apple Inc')).toBe('Apple')
    expect(name('Tesla, Inc.')).toBe('Tesla')
    expect(name('International Business Machines Corp')).toBe('International Business Machines')
    expect(name('The Walt Disney Company')).toBe('The Walt Disney Company')
  })

  it('reads the Report Period as a date when there is no Fiscal Period', () => {
    const quarter = { ...nvidiaSource, fiscalPeriod: null }
    expect(sourceHeading(quarter)).toBe('NVIDIA 10-Q, quarter ended Jul 28, 2024 · MD&A')
    const year = {
      ...nvidiaSource,
      formType: '10-K',
      fiscalPeriod: null,
      reportPeriod: '2025-01-26',
    }
    expect(sourceHeading(year)).toBe('NVIDIA 10-K, year ended Jan 26, 2025 · MD&A')
  })

  it('keeps a Report Period it cannot read as a date', () => {
    const odd = { ...nvidiaSource, fiscalPeriod: null, reportPeriod: 'unknown' }
    expect(sourceHeading(odd)).toBe('NVIDIA 10-Q, quarter ended unknown · MD&A')
  })
})

describe('passageBlocks', () => {
  it('keeps plain text as one paragraph, whitespace and all', () => {
    expect(passageBlocks('First line.\n  Second line.')).toEqual([
      { kind: 'paragraph', text: 'First line.\n  Second line.' },
    ])
  })

  it('turns a run of lines starting with a pipe into a table, with no header row', () => {
    expect(passageBlocks('| Revenue | $ | 30,040 |\n| Cost of revenue | 7,466 |')).toEqual([
      {
        kind: 'table',
        rows: [
          ['Revenue', '$', '30,040'],
          ['Cost of revenue', '7,466'],
        ],
      },
    ])
  })

  it('drops the empty edge cells of a row and keeps the empty cells inside it', () => {
    expect(passageBlocks('| Three Months Ended |  |\n|  | Jul 28, 2024 |  |  |')).toEqual([
      {
        kind: 'table',
        rows: [['Three Months Ended'], ['', 'Jul 28, 2024']],
      },
    ])
    expect(passageBlocks('| Revenue | $ |  | 30,040 |  |  |')).toEqual([
      { kind: 'table', rows: [['Revenue', '$', '', '30,040']] },
    ])
  })

  it("keeps a flattened table's rows that open with their label in the table", () => {
    // The Corpus flattens a table's header rows with a leading pipe and its data rows
    // without one.
    const text = '| Three Months Ended\nRevenue | $ | 30,040 |  |\nGross profit | 22,574 |'
    expect(passageBlocks(text)).toEqual([
      {
        kind: 'table',
        rows: [['Three Months Ended'], ['Revenue', '$', '30,040'], ['Gross profit', '22,574']],
      },
    ])
  })

  it('turns a line that is just [...] into an elision', () => {
    expect(passageBlocks('Before.\n[...]\nAfter.')).toEqual([
      { kind: 'paragraph', text: 'Before.' },
      { kind: 'elision', label: 'passage skipped' },
      { kind: 'paragraph', text: 'After.' },
    ])
  })

  it('reads the gap the retrieval writes, [ followed by an ellipsis character ], as an elision', () => {
    expect(passageBlocks('Before.\n[…]\nAfter.')).toEqual([
      { kind: 'paragraph', text: 'Before.' },
      { kind: 'elision', label: 'passage skipped' },
      { kind: 'paragraph', text: 'After.' },
    ])
  })

  it('splits mixed text into paragraphs, tables and elisions in order', () => {
    const text = [
      'Fiscal Year 2025 Summary',
      '| Year Ended',
      'Revenue | $ | 130,497 |',
      'Revenue grew on Data Center demand.',
      'It was led by Hopper.',
      '[...]',
      '| Net income | 72,880 |',
    ].join('\n')
    expect(passageBlocks(text)).toEqual([
      { kind: 'paragraph', text: 'Fiscal Year 2025 Summary' },
      { kind: 'table', rows: [['Year Ended'], ['Revenue', '$', '130,497']] },
      { kind: 'paragraph', text: 'Revenue grew on Data Center demand.\nIt was led by Hopper.' },
      { kind: 'elision', label: 'passage skipped' },
      { kind: 'table', rows: [['Net income', '72,880']] },
    ])
  })

  it('labels the marker "passage skipped"', () => {
    expect(passageBlocks(`Before.${GAP}After.`)).toContainEqual({
      kind: 'elision',
      label: 'passage skipped',
    })
  })

  it('spaces sentences the Corpus glued together, on display only', () => {
    expect(passageBlocks('Revenue rose on earnings.Summary of results follows.')).toEqual([
      { kind: 'paragraph', text: 'Revenue rose on earnings. Summary of results follows.' },
    ])
    expect(passageBlocks('Net sales grew 9%.Services led (see Note 2).Margins held!Why?')).toEqual([
      {
        kind: 'paragraph',
        text: 'Net sales grew 9%. Services led (see Note 2). Margins held! Why?',
      },
    ])
    expect(passageBlocks('It said “we grew.”The board agreed.')).toEqual([
      { kind: 'paragraph', text: 'It said “we grew.” The board agreed.' },
    ])
  })

  it('spaces a heading glued to the sentence after it', () => {
    expect(passageBlocks('Fiscal 2025 earnings.SummaryThe Company grew.')).toEqual([
      { kind: 'paragraph', text: 'Fiscal 2025 earnings. Summary The Company grew.' },
    ])
    expect(passageBlocks('Results of OperationsWe sell iPhone.')).toEqual([
      { kind: 'paragraph', text: 'Results of Operations We sell iPhone.' },
    ])
  })

  it('leaves names, decimals, abbreviations, web addresses and tables unspaced', () => {
    const text =
      'PepsiCo and JPMorgan use iPhone, WeChat and LinkedIn. Revenue was 3.5 billion in the U.S. per investor.apple.com.'
    expect(passageBlocks(text)).toEqual([{ kind: 'paragraph', text }])
    expect(passageBlocks('| Change.Better | 3.5 |')).toEqual([
      { kind: 'table', rows: [['Change.Better', '3.5']] },
    ])
  })

  it('reads Windows line breaks and drops blank runs between blocks', () => {
    expect(passageBlocks('Intro.\r\n\r\n| a | b |\r\n\r\nOutro.')).toEqual([
      { kind: 'paragraph', text: 'Intro.' },
      { kind: 'table', rows: [['a', 'b']] },
      { kind: 'paragraph', text: 'Outro.' },
    ])
    expect(passageBlocks('')).toEqual([])
  })
})

describe("the copy of the retrieval's gap marker", () => {
  it('is GAP in _repeats.py, read from the backend', () => {
    const repeats = readFileSync(
      join(__dirname, '../../backend/src/edgar_rag/_repeats.py'),
      'utf-8'
    )
    const match = repeats.match(/^GAP = ("[^"\n]*")$/m)

    expect(match).not.toBeNull()
    // A plain Python string literal escapes "\n" as JSON does.
    expect(GAP).toBe(JSON.parse(match![1]))
  })

  it('shows as an elision between the two runs it joins', () => {
    expect(passageBlocks(`Before.${GAP}After.`)).toEqual([
      { kind: 'paragraph', text: 'Before.' },
      { kind: 'elision', label: 'passage skipped' },
      { kind: 'paragraph', text: 'After.' },
    ])
  })
})
