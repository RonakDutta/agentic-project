# AGENTS.md

All agent instructions for this repository live in **[CLAUDE.md](CLAUDE.md)**. Read it before making changes.

The five rules that matter most:

1. **Honesty:** never add fake results, papers, citations or fixes. Label every fallback. Scores are computed in code.
2. **Research papers are the headline feature:** keep the paper check prominent and linked in the UI.
3. **UI style:** flat and plain. No pills, status dots, pulsing, gradients, uppercase labels, fancy fonts or arrows. Little text, plain but not childish language.
4. **No external-API wording in the UI:** no "Groq", "free tier", "API key" or token-budget mentions.
5. **Keep it working end to end:** `GROQ_API_KEY= pytest -q` must pass, rebuild `web/react-app` (`npm run build`) after UI changes and commit `dist/`, then update CLAUDE.md and push.
