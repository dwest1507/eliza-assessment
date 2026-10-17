import type { Metadata } from 'next'
import HowItWorks from '@/components/HowItWorks'
import evalExport from '@/data/eval-export.json'
import type { EvalExport } from '@/lib/evalExport'

export const metadata: Metadata = {
  title: 'How it works · SEC Filings Research',
  description:
    'How the research workspace answers, what it covers and how far to trust it, with the architecture, evaluation scoreboard and Corpus coverage behind it.',
}

// Written by `make eval-export`; typed here so a change to its shape fails the type check.
const data: EvalExport = evalExport

export default function HowItWorksPage() {
  return <HowItWorks data={data} />
}
