import { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { renderTextWithCitationSuperscript } from './writingCitations'
import { shouldIndentParagraph } from './writingParagraphIndent'
import {
  isPlaceholderImageSrc,
  resolveCmassetSrc,
  withInlineFigureHints,
  type FigureHintItem,
} from './writingFigureHints'

function CitationText({ children }: { children?: React.ReactNode }) {
  const text = String(children ?? '')
  if (!/\[\d+\]/.test(text)) return <>{children}</>
  const parts = renderTextWithCitationSuperscript(text)
  return (
    <>
      {parts.map((part, i) =>
        typeof part === 'string'
          ? <span key={`t-${i}`}>{part}</span>
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

function WritingImage({
  src,
  alt,
  assetUrlFor,
}: React.ComponentPropsWithoutRef<'img'> & {
  assetUrlFor?: (assetId: string) => string | null
}) {
  if (!src) return null
  // 待插入占位图 → 醒目占位卡片
  if (isPlaceholderImageSrc(src)) {
    return (
      <div className="writing-figure-placeholder">
        <span className="writing-figure-placeholder-title">📊 {alt || '图位占位'}</span>
        <span className="writing-figure-placeholder-hint">
          此处已预留图表位：请插入真实图表，或在正文中替换图片路径
        </span>
      </div>
    )
  }
  // cmasset:// 项目内嵌资产 → 解析为带鉴权的真实 URL
  if (src.startsWith('cmasset://')) {
    const resolved = resolveCmassetSrc(src, assetUrlFor)
    if (!resolved) {
      return (
        <div className="writing-figure-placeholder">
          <span className="writing-figure-placeholder-title">🔒 图表已插入</span>
          <span className="writing-figure-placeholder-hint">请保持登录状态预览，或导出后查看</span>
        </div>
      )
    }
    return (
      <figure className="writing-figure-embedded">
        <img src={resolved} alt={alt || ''} loading="lazy" />
        {alt ? <figcaption>{alt}</figcaption> : null}
      </figure>
    )
  }
  return <img src={src} alt={alt || ''} loading="lazy" />
}

export function WritingMarkdownPreview({
  content,
  hints,
  assetUrlFor,
}: {
  content: string
  hints?: FigureHintItem[] | null
  assetUrlFor?: (assetId: string) => string | null
}) {
  const display = useMemo(
    () => withInlineFigureHints(content, hints),
    [content, hints],
  )
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]}
      components={{
        p: WritingParagraph,
        text: CitationText,
        img: (props) => <WritingImage {...props} assetUrlFor={assetUrlFor} />,
      }}
    >
      {display}
    </ReactMarkdown>
  )
}

