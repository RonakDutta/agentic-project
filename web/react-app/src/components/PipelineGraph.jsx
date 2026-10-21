import { nodeStates } from '../pipelines.js'
import { seconds } from './ui.jsx'

const W = 150
const H = 60
const COL = 178
const ROW = 80
const PAD = 14

const STATE_TEXT = { waiting: 'waiting', running: 'working now', done: 'done', fallback: 'fallback used' }

export default function PipelineGraph({ pipeline, events, phase, hidden = [] }) {
  const nodes = pipeline.nodes.filter((n) => !hidden.includes(n.id))
  const states = nodeStates(pipeline, events, phase)
  const cols = Math.max(...nodes.map((n) => n.col)) + 1
  const width = PAD * 2 + (cols - 1) * COL + W
  const height = PAD * 2 + (pipeline.rows - 1) * ROW + H
  const pos = {}
  nodes.forEach((n) => { pos[n.id] = { x: PAD + n.col * COL, y: PAD + n.row * ROW } })

  const edges = []
  nodes.forEach((n) => n.deps.forEach((d) => { if (pos[d]) edges.push([d, n.id]) }))

  return (
    <div className="graph-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Agent pipeline with live status">
        {edges.map(([from, to]) => {
          const a = pos[from]
          const b = pos[to]
          const x1 = a.x + W
          const y1 = a.y + H / 2
          const x2 = b.x
          const y2 = b.y + H / 2
          const mid = (x1 + x2) / 2
          const target = states[to]?.state
          const cls = target === 'running' ? 'active' : target === 'done' || target === 'fallback' ? 'done' : ''
          return <path key={`${from}-${to}`} className={`gedge ${cls}`} d={`M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`} />
        })}
        {nodes.map((n) => {
          const st = states[n.id] || { state: 'waiting' }
          const { x, y } = pos[n.id]
          const sub = st.state === 'done' && st.step ? `finished at ${seconds(st.step.elapsed_ms)}` : st.state === 'waiting' ? n.sub : STATE_TEXT[st.state]
          return (
            <g key={n.id} className={`gnode ${st.state} ${n.star ? 'star' : ''}`} transform={`translate(${x},${y})`}>
              <title>{`${n.label}: ${STATE_TEXT[st.state]}`}</title>
              <rect width={W} height={H} rx="4" />
              <text className="lbl" x="13" y="26">{n.label}</text>
              <text className="sub" x="13" y="45">{sub}</text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
