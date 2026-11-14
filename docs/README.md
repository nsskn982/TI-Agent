# TI Agent documentation

| Document | Contents |
|---|---|
| [progress.md](progress.md) | Current status of every phase, the website and the app: what's done, gate progress, next steps, known limitations |
| [security.md](security.md) | What is protected and how, the 2026-11-11 security review and its fixes, and the setup steps you must do yourself |
| [architecture.md](architecture.md) | How modules M1–M6, M8, M9 (Telegram, website, app) and M10 (evaluation) work and why they are built this way, with citations; the no-lookahead rule; plans for later phases |
| [report/](report/) | Technical report (`main.tex`, 18 pages): the whole build, phase by phase, with TikZ diagrams and screenshots. Build: `latexmk -pdf main.tex` (biber) |
| [paper/](paper/) | Journal-style paper (`paper.tex`, elsarticle): system, pre-registered evaluation protocol, first-week results, limitations. Build: `latexmk -pdf paper.tex` (bibtex) |
| [references.md](references.md) | Bibliography: 22 arXiv papers (each checked against the arXiv API) and 2 other sources |
| [references.bib](references.bib) | The same references in BibTeX |
| [../app/README.md](../app/README.md) | The Flutter app: setup, configuration, how it reads the encrypted data file |
| [../reports/evaluation.md](../reports/evaluation.md) | The latest M10 evaluation report, rewritten by every weekly screen |

New to the project? Read the [main README](../README.md) first, then [architecture.md](architecture.md).

Disclaimer: TI Agent is a research and learning project. Its output is not financial advice, and it never places trades.
