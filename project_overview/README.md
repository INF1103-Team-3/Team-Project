# Project Overview and Function Graphs

This directory contains maintainers' documentation and scripts that turn the
BiteFinder source or a real command line session into workflow images. It is
for understanding and presenting the project; it is not part of the runtime
search path.

## Contents

| Path | Purpose |
| --- | --- |
| `visualise_functions.py` | Reads Python source with the AST and generates static architecture and function call diagrams. |
| `visualise_live_functions.py` | Starts BIS with a Python profiler and renders only calls observed during that interactive session. |
| `function_graphs/all_functions.png` | Static view of functions discovered throughout the project. |
| `function_graphs/bis_to_brns.png` | High level BIS to BRNS manager flow. |
| `function_graphs/bis_to_brns_functions.png` | Detailed function level path across BIS and BRNS. |
| `function_graphs/project_workflow.png` | Whole project view including BIS, BRNS, BRC, and common code. |
| `function_graphs/live_sessions/` | Locally generated timestamped runtime traces; ignored by Git. |

The authoritative text workflow is [ProjectFlow.md](../ProjectFlow.md). The
images here provide a presentation view of the same architecture.

## Install visualization dependencies

From the project root:

```bash
python -m pip install -r requirements-dev.txt
```

The static renderer uses Pillow. The optional legacy trace mode also uses
`python-call-graph`. Both are development dependencies and are intentionally
separate from normal application requirements.

## Generate static graphs

### UML class diagrams

```bash
python project_overview/test_uml.py
```

Runs source-analysis tests and then generates:

- `uml/bitefinder.png` and `.svg`: the full UML class diagram.
- `uml/BIS.png`, `uml/BRNS.png`, `uml/BRC.png` (and SVG): subsystem detail.
- `uml/bitefinder_flow.png` and `.svg`: compact class/method dependencies.
- `.puml` and `.dot` sources for editing or rendering with external tools.
- `uml/analysis.json`: class locations, relationships with source-line evidence,
  unresolved calls, and whether type inference converged.
- `.edges.json` beside each view: numbered edges and their full details.

The analysis reads Python ASTs without importing or executing application code.
It resolves imports, aliases/re-exports, factory returns, constructor wiring,
registered lambda factories, tuple unpacking, inherited methods, annotations,
and calls through compatibility functions. It follows injected collaborators
into stored attributes before drawing their relationships.

Boxes show class names, inferred/declared attributes, and method signatures in
separate compartments. `+`, `#`, and `-` indicate Python visibility conventions;
`?` means no type was resolved. Abstract classes/interfaces are marked. Colors
identify BIS, BRNS, and BRC.

Relationships distinguish inheritance, interfaces, stored construction
(composition), injected collections (aggregation), injected references
(association), construction dependencies, and method calls. Default construction
is labeled `(default)` when an injected override is also possible. These ownership
labels reflect source construction/storage, not a proof of runtime lifetimes.
HTTP service edges are conditional matches between configured client routes and
handler routes; they do not prove a service is currently running.

Graphviz's optional `dot` executable provides automatic graph layout. Otherwise
Pillow uses connected neighborhoods in multiple rows and columns, with A* edge
routing around class boxes. SVG files support zoom and full edge tooltips;
numbered PNG labels refer to `.edges.json`. Dense graphs may lack space for every
text label, so consult SVG tooltips or the edge inventory for complete details.

This is static dependency analysis, not runtime sequence tracing. It explicitly
reports unresolved dynamic calls instead of guessing from class names. It cannot
prove arbitrary Python behavior or resolve every callback/reflection pattern.
Use the existing live tracer when observed execution order is needed.

Run:

```bash
python project_overview/visualise_functions.py
```

The script inspects BIS, BRNS, BRC, and `common` Python files and writes four PNG
files into `project_overview/function_graphs`. Functions are grouped below
their program and, where applicable, below Main, IO, AI, Logic, and Data. The
whole project graph shows the main data flow from account interaction through
restaurant search and official halal checking.

Static analysis is useful even when providers are unavailable because the
program does not have to run. It cannot always resolve callbacks, imports
selected at runtime, or a function stored in a variable, so the graph describes
source relationships rather than proving a particular execution path.

## Record a live interactive trace

Run:

```bash
python project_overview/visualise_live_functions.py
```

The script starts the real BIS entry point. Use the application normally and
choose `/quit` when the scenario is complete. The profiler records project
function calls and saves a new folder under
`project_overview/function_graphs/live_sessions/` containing:

- `calls.json`, with exact caller, callee, and call counts;
- `overview.png`, with the observed flow across programs;
- `bis_functions.png`, grouped by BIS manager;
- `brns_functions.png`, when BRNS was reached;
- `brc_functions.png`, when official halal checking was reached; and
- `common_functions.png`, for common cache, UI, logging, and model helpers.

Programs that were not reached in the chosen session are marked accordingly.
For example, BRC normally appears only when a halal constrained search checks
candidates. A short login and quit session will naturally produce a smaller
graph than a completed search.

The tracer uses `sys.setprofile`; it does not replace application functions or
change provider selection. Pressing Ctrl+C still writes calls captured before
the interruption when Python can handle the signal normally.

## Optional legacy call graph

`visualise_functions.py` also retains an optional `python-call-graph` mode:

```bash
python project_overview/visualise_functions.py --trace
```

This produces `bis_live_trace.png` when the legacy dependency and its Graphviz
requirements work in the local environment. The dedicated live visualizer is
preferred for the grouped BiteFinder diagrams.

## Windows commands

When using the repository virtual environment in PowerShell:

```powershell
.\.venv\Scripts\python.exe project_overview\visualise_functions.py
.\.venv\Scripts\python.exe project_overview\visualise_live_functions.py
```

## Generated file policy

Live sessions and newly generated graph outputs are local diagnostic artifacts
and are ignored by Git. Existing example PNGs may remain tracked as project
documentation. Regenerate them after a meaningful architecture change and
inspect the images before intentionally updating a tracked example.

Do not place application state, credentials, restaurant data, or copied log
contents in this directory.

