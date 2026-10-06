import React, { useEffect, useId, useRef, useState } from 'react'
import mermaid from 'mermaid'

// Unique per render attempt: StrictMode double-invokes effects in dev, and
// mermaid v10 collides when two concurrent renders share one diagram id.
let renderSeq = 0

export default function MermaidDiagram({ chart }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, '')
  const [svg, setSvg] = useState(null) // null = loading, '' = failed
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    setSvg(null)
    const definition = (chart || '').trim()
    if (!definition) {
      setSvg('empty')
      return () => { alive.current = false }
    }
    const renderId = `mermaid_diag_${id}_${++renderSeq}`
    mermaid.render(renderId, definition)
      .then(({ svg: rendered }) => { if (alive.current) setSvg(rendered) })
      .catch((e) => {
        console.warn('Mermaid SVG render failed, displaying structured definition:', e)
        if (alive.current) setSvg('')
      })
    return () => { alive.current = false }
  }, [chart, id])

  if (!chart || !chart.trim()) {
    return <div className="text-xs text-zinc-500 p-6 text-center">No diagram on this tab.</div>
  }
  if (svg === null) {
    return (
      <div className="flex items-center justify-center p-8 text-xs text-zinc-400">
        <span>Drawing the diagram...</span>
      </div>
    )
  }
  if (!svg || svg === 'empty') {
    return (
      <div className="p-4 bg-white/[0.02] rounded-lg w-full">
        <div className="text-[11px] font-mono text-zinc-500 mb-2">Mermaid Definition:</div>
        <pre className="text-xs font-mono text-blue-300 overflow-x-auto leading-relaxed whitespace-pre">{chart.trim()}</pre>
      </div>
    )
  }
  return (
    <div className="overflow-x-auto p-4 flex justify-center bg-white/[0.02] rounded-lg w-full" dangerouslySetInnerHTML={{ __html: svg }} />
  )
}
