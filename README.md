# Quantum Swarm

Hierarchical multi-agent workflows (Hamiltonian swarm) plus an optional **software company** pipeline that turns a brief into architecture, design, implementation, and QA artifacts.

## Software company CLI

Run from the repo root (with dependencies installed and `GEMINI_API_KEY` / other keys set as needed):

```bash
python -m software_company
python -m software_company "Your project brief here"
python -m software_company "Brief" --sprints 3
```

Outputs default to `company_output/` (override via the `software_company` package / `OUTPUT_DIR` where supported).

Implementation lives mainly in the `software_company` package: leaf modules (`config`, `contracts`, `dashboard`, `browser`, `state`, `rag`) plus `software_company/_monolith.py` for tools, LLM loops, teams, and orchestration.

## Hamiltonian swarm

See `hamiltonian_swarm/README.md` for library usage and examples.
