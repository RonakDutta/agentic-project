import PipelineGraph from './components/PipelineGraph.jsx'
import { CODE_PIPELINE, STARTUP_PIPELINE } from './pipelines.js'

// Facts about how the system is built. Keep them true: if the code changes, change these.
const SHEET = [
  ['Tools', 'Startup Assistance, Codebase Evaluation'],
  ['AI calls per idea run', '7, plus 1 or 2 for a prototype'],
  ['Paper sources', 'arXiv, Semantic Scholar, OpenAlex (live)'],
  ['Idea score', '7-category rubric, computed in code'],
  ['Code search', 'BM25 keywords + MiniLM embeddings'],
  ['Prototype', 'FastAPI + one page, tested with pytest'],
  ['Runs on', 'One Python server on this computer'],
]

const TOOLS = [
  {
    id: 'startup',
    n: '1',
    name: 'Startup Assistance',
    line: 'Is this idea worth building, and has someone already done it?',
    steps: [
      'Searches the market and live research papers',
      'A devil\'s advocate argues against it, a judge weighs both sides',
      'Scores it with a fixed rubric in code',
      'Writes the PRD and roadmap, then builds and tests a small prototype',
    ],
  },
  {
    id: 'code',
    n: '2',
    name: 'Codebase Evaluation',
    line: 'Where is the bug, and what breaks if I change this?',
    steps: [
      'Opens a local folder or a GitHub link',
      'Parses every file into functions and a call graph',
      'Finds the code behind a bug or a question',
      'A critic checks file, lines and quoted code against the disk',
    ],
  },
]

const COMPARE = [
  ['Research papers', 'Can name papers that do not exist', 'Fetched live; every link opens the real paper'],
  ['Scores', 'Change each time you ask', 'Same formula in code, same score'],
  ['Code questions', 'Sees only the snippet you paste', 'Reads the whole project and checks line numbers on disk'],
  ['Prototype', 'Gives code you still have to run', 'Writes it, runs the tests, starts it, watches it'],
  ['When the AI fails', 'Still answers confidently', 'Falls back to plain code and says so'],
]

export default function Landing({ onEnter, theme, setTheme }) {
  return (
    <div className="landing">
      <nav className="l-nav">
        <div className="l-wrap l-nav-inner">
          <button className="l-brand" onClick={() => window.scrollTo({ top: 0 })}>
            <span className="brand-mark" aria-hidden="true">AC</span>
            <span>Agentic Co-Pilot</span>
          </button>
          <div className="l-links">
            <a href="#tools">Tools</a>
            <a href="#how">How it works</a>
            <a href="#compare">Compared to a chatbot</a>
          </div>
          <button className="icon-btn" aria-label="Toggle dark mode" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
            {theme === 'dark' ? '☀' : '☾'}
          </button>
          <button className="btn primary" onClick={() => onEnter('startup')}>Open the app</button>
        </div>
      </nav>

      <header className="l-wrap l-hero">
        <div className="l-hero-text">
          <p className="l-kicker">B.Tech minor project, GGSIPU USAR</p>
          <h1>A second pair of eyes for your startup idea and your code.</h1>
          <p className="l-lead">
            It checks an idea against real research papers and builds a small working prototype.
            It reads a Python project and finds the lines behind a bug.
            Code checks every answer before you see it.
          </p>
          <div className="row" style={{ gap: 12 }}>
            <button className="btn primary l-big" onClick={() => onEnter('startup')}>Open the app</button>
            <a className="btn l-big" href="#how">How it works</a>
          </div>
        </div>
        <table className="l-sheet" aria-label="Project facts">
          <caption>Project sheet</caption>
          <tbody>
            {SHEET.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{v}</td></tr>)}
          </tbody>
        </table>
      </header>

      <section id="tools" className="l-section">
        <div className="l-wrap">
          <h2 className="l-h2">Two tools</h2>
          <div className="l-tools">
            {TOOLS.map((t) => (
              <article key={t.id} className="l-tool">
                <div className="l-num">{t.n}</div>
                <h3>{t.name}</h3>
                <p className="l-tool-line">{t.line}</p>
                <ol>{t.steps.map((s) => <li key={s}>{s}</li>)}</ol>
                <button className="btn" onClick={() => onEnter(t.id)}>Open {t.name}</button>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="how" className="l-section">
        <div className="l-wrap stack-lg">
          <div>
            <h2 className="l-h2">How a run works</h2>
            <p className="l-note">These are the real agent graphs the app lights up while it runs. Boxes marked AI call a language model; the rest is plain code.</p>
          </div>
          <figure className="l-figure">
            <figcaption>Startup Assistance</figcaption>
            <PipelineGraph pipeline={STARTUP_PIPELINE} events={[]} phase="idle" />
          </figure>
          <figure className="l-figure">
            <figcaption>Codebase Evaluation</figcaption>
            <PipelineGraph pipeline={CODE_PIPELINE} events={[]} phase="idle" />
          </figure>
        </div>
      </section>

      <section id="compare" className="l-band">
        <div className="l-wrap">
          <h2 className="l-h2">"Can't a chatbot do this?"</h2>
          <p className="l-note">Partly. This is what changes when agents, live sources and code checks work together.</p>
          <div className="l-table-wrap">
            <table className="l-compare">
              <thead><tr><th /><th>Plain chatbot</th><th>Agentic Co-Pilot</th></tr></thead>
              <tbody>
                {COMPARE.map(([k, a, b]) => <tr key={k}><th scope="row">{k}</th><td>{a}</td><td>{b}</td></tr>)}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="l-section l-end">
        <div className="l-wrap l-end-inner">
          <h2 className="l-h2">Try it with your own idea or project.</h2>
          <div className="row" style={{ gap: 12 }}>
            <button className="btn primary l-big" onClick={() => onEnter('startup')}>Check an idea</button>
            <button className="btn l-big" onClick={() => onEnter('code')}>Evaluate a codebase</button>
          </div>
        </div>
      </section>

      <footer className="l-wrap l-foot">
        <span>Agentic Co-Pilot</span>
        <span>B.Tech minor project, GGSIPU USAR</span>
      </footer>
    </div>
  )
}
