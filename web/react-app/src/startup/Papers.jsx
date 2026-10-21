import { Bar, More, SafeLink, Source, Tag, downloadText } from '../components/ui.jsx'

const SOURCE_NAMES = { arxiv: 'arXiv', semantic_scholar: 'Semantic Scholar', openalex: 'OpenAlex' }
const sourceName = (s) => SOURCE_NAMES[s] || s
const LEVEL_TONE = { high: 'risk', medium: 'warn', low: '' }

function authors(list, n = 3) {
  const a = (list || []).filter(Boolean)
  return a.slice(0, n).join(', ') + (a.length > n ? ' et al.' : '')
}

function PaperLinks({ p }) {
  return (
    <div className="paper-links">
      <SafeLink href={p.url}>Open paper</SafeLink>
      {p.pdf_url && <SafeLink href={p.pdf_url}>PDF</SafeLink>}
      {p.doi && <SafeLink href={`https://doi.org/${p.doi}`}>DOI</SafeLink>}
    </div>
  )
}

export function NoveltyCard({ pa }) {
  const nov = pa.novelty_index
  const tone = nov === null || nov === undefined ? '' : nov >= 50 ? 'good' : nov >= 35 ? 'warn' : 'risk'
  return (
    <div className="card pad stack">
      <div className="eyebrow">Novelty index</div>
      <div className="row" style={{ alignItems: 'baseline', gap: 6 }}>
        <span className="display" style={{ fontSize: 56, lineHeight: 0.9 }}>{nov ?? 'n/a'}</span>
        <span className="muted">/ 100</span>
      </div>
      <Bar value={nov || 0} tone={tone} />
      <div style={{ fontWeight: 600 }}>{pa.novelty_band}</div>
      <div className="row tiny">
        <Tag>Evidence: {pa.evidence_confidence}</Tag>
        <Tag>{pa.similarity_backend}</Tag>
      </div>
      <More label="How is this computed?">
        <p className="small muted" style={{ margin: 0 }}>
          Calculated in code, not written by the AI: 100 x (1 - (0.6 x closest similarity + 0.4 x average of the top 3)).
          Similarity compares the meaning of your idea with each paper's title and abstract. The bands
          (very close / closely related / related / little) are fixed cut-offs, not a judgement by the AI.
        </p>
      </More>
    </div>
  )
}

export function SimilarityMap({ points, papers }) {
  if (!points || points.length < 2) return <div className="empty">Not enough papers for a map.</div>
  const W = 560
  const H = 300
  const pad = 34
  const byRef = Object.fromEntries((papers || []).map((p) => [p.ref_id, p]))
  const idea = points.find((p) => p.is_idea)
  const px = (p) => pad + p.x * (W - 2 * pad)
  const py = (p) => pad + (1 - p.y) * (H - 2 * pad)
  const others = points.filter((p) => !p.is_idea)
  return (
    <div className="map">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Map of your idea and the papers: closer means more similar">
        {others.map((p) => (
          <line key={`l${p.label}`} x1={px(idea)} y1={py(idea)} x2={px(p)} y2={py(p)}
            stroke="var(--line-strong)" strokeWidth={0.6 + 3 * Math.max(0, p.similarity)} strokeOpacity="0.7" />
        ))}
        {others.map((p) => {
          const r = 6 + 12 * Math.max(0, p.similarity)
          const paper = byRef[p.label]
          return (
            <a key={p.label} href={paper?.url || undefined} target="_blank" rel="noopener noreferrer">
              <g>
                <title>{`${p.label}: ${paper ? paper.title : ''} (similarity ${p.similarity.toFixed(2)})`}</title>
                <circle cx={px(p)} cy={py(p)} r={r} fill="var(--info)" fillOpacity={0.15 + 0.6 * Math.max(0, p.similarity)} stroke="var(--info)" />
                <text x={px(p)} y={py(p) - r - 5} textAnchor="middle">{p.label}</text>
              </g>
            </a>
          )
        })}
        <circle cx={px(idea)} cy={py(idea)} r="11" fill="var(--accent)" stroke="var(--surface)" strokeWidth="3" />
        <text x={px(idea)} y={py(idea) + 27} textAnchor="middle" style={{ fontWeight: 700, fill: 'var(--accent-ink)', fontFamily: 'var(--font)', fontSize: 12.5 }}>Your idea</text>
      </svg>
      <div className="tiny muted">Closer and bigger = more similar to your idea. Click a dot to open the paper.</div>
    </div>
  )
}

export function Spotlight({ pa }) {
  const p = (pa.papers || [])[0]
  if (!p) return null
  const cmp = (pa.comparisons || []).find((c) => c.ref === p.ref_id) || {}
  return (
    <div className="card pad-lg spotlight stack">
      <div className="row between">
        <span className="eyebrow accent">Closest published research</span>
        <span className="row tiny">
          <Tag tone="accent">similarity {p.similarity.toFixed(2)}</Tag>
          <Tag>{sourceName(p.source)}</Tag>
        </span>
      </div>
      <SafeLink href={p.url} style={{ color: 'var(--ink)' }}>
        <span className="display" style={{ fontSize: 24 }}>{p.title}</span>
      </SafeLink>
      <div className="small muted">{authors(p.authors, 6)} · {p.venue || sourceName(p.source)} · {p.year || 'n.d.'}{p.citation_count != null ? ` · ${p.citation_count} citations` : ''}</div>
      {p.abstract && <p className="small clamp-3" style={{ margin: 0, color: 'var(--ink-2)' }}>{p.abstract}</p>}
      {cmp.paper_is_stronger_at && (
        <div className="grid g2">
          <div className="soft" style={{ padding: 12 }}>
            <div className="eyebrow" style={{ color: 'var(--warn)' }}>Where the paper is stronger</div>
            <div className="small">{cmp.paper_is_stronger_at}</div>
          </div>
          <div className="soft" style={{ padding: 12 }}>
            <div className="eyebrow" style={{ color: 'var(--good)' }}>What your idea adds</div>
            <div className="small">{cmp.idea_adds}</div>
          </div>
        </div>
      )}
      <div className="row">
        <SafeLink href={p.url} className="btn sm dark">Open paper</SafeLink>
        {p.pdf_url && <SafeLink href={p.pdf_url} className="btn sm">Read PDF</SafeLink>}
        {p.doi && <SafeLink href={`https://doi.org/${p.doi}`} className="btn sm">DOI</SafeLink>}
      </div>
    </div>
  )
}

function PaperList({ papers }) {
  return (
    <div className="card pad">
      {papers.map((p) => (
        <div className="paper" key={p.ref_id}>
          <span className="ref">{p.ref_id}</span>
          <div style={{ minWidth: 0 }}>
            <SafeLink href={p.url} className="paper-title">{p.title}</SafeLink>
            <div className="tiny muted">{authors(p.authors)} · {p.year || 'n.d.'} · {[p.source, ...(p.also_found_in || [])].map(sourceName).join(', ')}</div>
            <PaperLinks p={p} />
            {p.abstract && <More label="Abstract"><p className="small muted" style={{ margin: 0 }}>{p.abstract}</p></More>}
          </div>
          <div className="sim">
            <div className="row between tiny"><span className="muted">similarity</span><span className="mono">{p.similarity.toFixed(2)}</span></div>
            <Bar value={p.similarity * 100} tone="info" />
          </div>
        </div>
      ))}
    </div>
  )
}

function Comparisons({ pa }) {
  const papers = Object.fromEntries((pa.papers || []).map((p) => [p.ref_id, p]))
  const v = pa.verification || {}
  return (
    <div className="stack">
      <div className="row between">
        <h3>Your idea vs each paper</h3>
        <span className="tiny muted">
          Checked: {v.comparisons_kept || 0}/{v.comparisons_returned || v.comparisons_kept || 0} refer to a paper we found
          · {v.citations_removed || 0} wrong citations removed · {Math.round((v.avg_abstract_support || 0) * 100)}% backed by abstracts
        </span>
      </div>
      <div className="grid g2">
        {(pa.comparisons || []).map((c) => (
          <div className="card pad stack" key={c.ref} style={{ gap: 10 }}>
            <div className="row between" style={{ alignItems: 'flex-start' }}>
              <SafeLink href={papers[c.ref]?.url} className="paper-title" style={{ flex: 1, minWidth: 0 }}>
                <span className="mono" style={{ color: 'var(--accent-ink)', marginRight: 6 }}>{c.ref}</span>{c.title}
              </SafeLink>
              <Tag tone={LEVEL_TONE[c.overlap_level]}>{c.overlap_level} overlap</Tag>
            </div>
            <div className="small" style={{ color: 'var(--warn)' }}><strong>Stronger at:</strong> <span style={{ color: 'var(--ink-2)' }}>{c.paper_is_stronger_at}</span></div>
            <div className="small" style={{ color: 'var(--good)' }}><strong>You add:</strong> <span style={{ color: 'var(--ink-2)' }}>{c.idea_adds}</span></div>
            <More label="What it does and the overlap">
              <div className="small stack" style={{ gap: 6 }}>
                <div><strong>Does:</strong> {c.what_it_does}</div>
                <div><strong>Overlap:</strong> {c.overlap}</div>
                <div className="tiny muted">{Math.round(c.abstract_support * 100)}% of this summary's key words appear in the paper's abstract.</div>
              </div>
            </More>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Papers({ pa, title }) {
  if (!pa) return <div className="empty">The research paper check was switched off for this run.</div>
  const papers = pa.papers || []
  if (!papers.length) {
    return (
      <div className="card pad stack">
        <h3>No research papers could be retrieved right now</h3>
        <p className="small muted" style={{ margin: 0 }}>Nothing was made up in their place. Sources tried: arXiv, Semantic Scholar, OpenAlex.</p>
        <ul className="list small muted">{(pa.notes || []).map((n, i) => <li key={i}>{n}</li>)}</ul>
      </div>
    )
  }
  const slug = (title || 'idea').toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, 40)
  return (
    <div className="stack-lg">
      <div className="row between">
        <div className="row small muted">
          <span>{papers.length} papers found live on {pa.search_backend.split(' + ').map(sourceName).join(' + ')}</span>
          <Source value={pa.generation_source} />
        </div>
        <div className="row">
          <button className="btn sm" onClick={() => navigator.clipboard?.writeText(pa.bibtex || '')}>Copy BibTeX</button>
          <button className="btn sm" onClick={() => downloadText(`${slug}_related_work.bib`, pa.bibtex || '', 'application/x-bibtex')}>Download .bib</button>
        </div>
      </div>
      <Spotlight pa={pa} />
      <div className="grid split">
        <NoveltyCard pa={pa} />
        <div className="card pad stack">
          <div className="eyebrow">Where your idea sits</div>
          <SimilarityMap points={pa.similarity_map} papers={papers} />
        </div>
      </div>
      <div className="stack">
        <h3>All papers we compared against</h3>
        <PaperList papers={papers} />
      </div>
      {(pa.comparisons || []).length > 0 && <Comparisons pa={pa} />}
      {(pa.research_gap || pa.positioning) && (
        <div className="grid g2">
          <div className="card pad stack" style={{ gap: 6 }}>
            <div className="eyebrow" style={{ color: 'var(--good)' }}>The gap you can fill</div>
            <div>{pa.research_gap}</div>
          </div>
          <div className="card pad stack" style={{ gap: 6 }}>
            <div className="eyebrow accent">How to position it</div>
            <div>{pa.positioning}</div>
          </div>
        </div>
      )}
      <div className="card pad stack">
        <div className="row between">
          <h3>Related Work, ready for your report</h3>
          <Tag>IEEE style</Tag>
        </div>
        {pa.related_work ? <p style={{ margin: 0, color: 'var(--ink-2)' }}>{pa.related_work}</p> : <p className="small muted" style={{ margin: 0 }}>No draft paragraph (AI comparison unavailable). The references below are real and can be cited.</p>}
        <More label={`References (${(pa.ieee_references || []).length})`}>
          <ol className="list tiny mono" style={{ listStyle: 'none', paddingLeft: 0 }}>
            {(pa.ieee_references || []).map((r, i) => <li key={i} style={{ wordBreak: 'break-word' }}>{r}</li>)}
          </ol>
        </More>
      </div>
      {(pa.notes || []).length > 0 && <ul className="list tiny muted">{pa.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
    </div>
  )
}
