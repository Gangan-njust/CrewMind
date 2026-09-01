import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { renderTextWithCitationSuperscript } from './writingCitations'
import { shouldIndentParagraph } from './writingParagraphIndent'

function CitationText({ children }: { children?: React.ReactNode }) {
  const text = String(children ?? '')
  if (!/\[\d+\]/.test(text)) return <>{children}</>
  const parts = renderTextWithCitationSuperscript(text)
  return (
    <>
      {parts.map((part, i) =>
        typeof part === 'string'
          ? part
          : <sup key={i} className="citation-sup">{part.sup}</sup>,
      )}
    </>
  )
}

function WritingParagraph({ children, ...props }: React.ComponentPropsWithoutRef<'p'>) {
  const text = String(children ?? '').trim()
  const className = shouldIndentParagraph(text) ? 'writing-para-indent' : undefined
  return <p className={className} {...props}>{children}</p>
}

export function WritingMarkdownPreview({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{ p: WritingParagraph, text: CitationText }}
    >
      {content}
    </ReactMarkdown>
  )
}
