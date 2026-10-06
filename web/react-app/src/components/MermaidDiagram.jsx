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
    let isCancelled = false
    setSvg(null)

    let definition = (chart || '').trim()
    if (!definition) {
      setSvg('empty')
      return
    }

    // Strip markdown code fences if present (e.g. ```mermaid ... ```)
    definition = definition
      .replace(/^```(?:mermaid)?\s*/i, '')
      .replace(/```\s*$/i, '')
      .trim()

    const renderId = `mermaid_diag_${Math.random().toString(36).substring(2, 9)}_${Date.now()}`

    const renderChart = async () => {
      try {
        const { svg: rendered } = await mermaid.render(renderId, definition)
        if (!isCancelled) {
          setSvg(rendered)
        }
      } catch (e) {
        console.warn('Mermaid SVG render failed, displaying structured definition:', e)
        // Clean up any stray error elements inserted into document.body by Mermaid v10
        document.getElementById(renderId)?.remove()
        document.getElementById('d' + renderId)?.remove()
        if (!isCancelled) {
          setSvg('')
        }
      }
    }

    renderChart()

    return () => {
      isCancelled = true
      document.getElementById(renderId)?.remove()
      document.getElementById('d' + renderId)?.remove()
    }
  }, [chart])

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
    <div className="mermaid overflow-x-auto p-4 flex justify-center bg-white/[0.02] rounded-lg w-full" dangerouslySetInnerHTML={{ __html: svg }} />
  )
}
