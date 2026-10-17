interface FollowUpsProps {
  questions: string[]
  onPick: (question: string) => void
}

/**
 * Suggested follow-up questions under the latest completed answer, each sent as soon as
 * it is clicked, as a starter prompt is. They come from fixed templates (`lib/followUps.ts`),
 * never from a model.
 */
export default function FollowUps({ questions, onPick }: FollowUpsProps) {
  return (
    <section aria-labelledby="follow-ups-heading" className="flex flex-col gap-2">
      <h3 id="follow-ups-heading" className="text-[12.5px] font-medium text-muted">
        Ask next
      </h3>
      <ul aria-label="Suggested follow-ups" className="flex flex-wrap gap-2">
        {questions.map((question) => (
          <li key={question}>
            <button
              type="button"
              onClick={() => onPick(question)}
              className="rounded-lg border border-line bg-surface px-3 py-1.5 text-left text-[13.5px] text-ink transition-colors duration-200 hover:border-accent/40 hover:bg-raised"
            >
              {question}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
