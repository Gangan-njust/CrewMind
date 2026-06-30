import { useMemo } from 'react'
import katex from 'katex'
import type { LiteratureFormula } from '../api'

interface Props {
  formula: LiteratureFormula
}

export function FormulaBlock({ formula }: Props) {
  const html = useMemo(() => {
    const latex = formula.latex?.trim()
    if (!latex) return ''
    try {
      return katex.renderToString(latex, {
        throwOnError: false,
        displayMode: true,
        strict: 'ignore',
      })
    } catch {
      return latex
    }
  }, [formula.latex])

  return (
    <div className="formula-card">
      <div className="formula-card-header">
        <h5>{formula.name || '公式'}</h5>
        {formula.context && <span className="formula-context">{formula.context}</span>}
      </div>
      {html ? (
        <div
          className="formula-latex"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      ) : (
        <pre className="formula-latex-fallback">{formula.latex}</pre>
      )}
      {formula.variables && formula.variables.length > 0 && (
        <div className="formula-variables">
          <strong>变量说明</strong>
          <ul>
            {formula.variables.map((v, i) => (
              <li key={i}>{v}</li>
            ))}
          </ul>
        </div>
      )}
      {formula.explanation && (
        <div className="formula-explanation">
          <strong>详细解释</strong>
          <p>{formula.explanation}</p>
        </div>
      )}
    </div>
  )
}
