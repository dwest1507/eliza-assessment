import Workspace from '@/components/Workspace'
import evalExport from '@/data/eval-export.json'
import { coverageSummary } from '@/lib/coverage'
import type { EvalExport } from '@/lib/evalExport'

// The same committed export "How it works" reads, so the two pages never disagree.
const data: EvalExport = evalExport

export default function Home() {
  return <Workspace coverage={coverageSummary(data.companies)} calendars={data.companies} />
}
