# Project Overview and Function Graphs

This directory contains maintainers' documentation and scripts that turn the
BiteFinder source or a real command line session into workflow images. It is
for understanding and presenting the project; it is not part of the runtime
search path.

## Contents

| Path | Purpose |
| --- | --- |
| `test_uml.py`, `uml_analysis.py`, `uml_rendering.py` | Source-derived class analysis, diagram generation and analyzer tests. |
| `visualise_functions.py` | Reads Python source with the AST and generates static architecture and function call diagrams. |
| `visualise_live_functions.py` | Starts BIS with a Python profiler and renders only calls observed during that interactive session. |
| `function_graphs/all_functions.png` | Static view of functions discovered throughout the project. |
| `function_graphs/bis_to_brns.png` | High level BIS to BRNS manager flow. |
| `function_graphs/bis_to_brns_functions.png` | Detailed function level path across BIS and BRNS. |
| `function_graphs/project_workflow.png` | Whole project view including BIS, BRNS, BRC, and common code. |
| `function_graphs/live_sessions/` | Locally generated timestamped runtime traces; ignored by Git. |

The authoritative text workflow is [ProjectFlow.md](../ProjectFlow.md), with
record/storage details in [DataFlowDiagram.md](../DataFlowDiagram.md). Regenerate
and inspect images after architecture changes; previously generated artifacts
are not evidence that the current source has been diagrammed.

## Install visualization dependencies

From the project root:

```bash
python -m pip install -r requirements-dev.txt
```

The static renderer uses Pillow. The optional legacy trace mode also uses
`python-call-graph`. Both are development dependencies and are intentionally
separate from normal application requirements.

## Generate static graphs

### UML class diagrams for Word

```bash
python project_overview/test_uml.py
```

Runs analyzer/diagram tests and generates a presentation set under
`../bitefinder-workfiles/uml/document/`, outside the repository. Set
`BITEFINDER_WORKFILES` to choose a different external workfiles directory.
Application code is read with Python's AST; providers, databases and application
modules are never imported or called.

Regenerate after pulling application changes or refactoring collaborators. The
current graph includes `PreferenceReviewService`, the Logic-owned
`PreferenceValidationPolicy` and BRC `DatabaseRefreshService`; old rendered
class counts and stored evidence do not certify the updated working tree.
The authoritative runtime and data diagrams are `ProjectFlow.md` and
`DataFlowDiagram.md` in the repository root.

Generated formats are separated within `bitefinder-workfiles/uml/document/`:

```text
png/       rendered PNGs
svg/       matching vector diagrams
mmd/       Mermaid sources
json/      models, evidence, sidecars and verification data

Each format folder contains:
  Appendix/   supporting class sheets (A_*)
  Functions/  function/module sheets (F_*)
  Managers/   four-manager class sheets (M_*)

INDEX.md   local navigation, with links into png/
```

Overview figures, preview/notation files and general metadata stay at the
root of their format folder. Categories are retained even when a format has
no exports for that category; currently Mermaid has only the overview source.

Models/evidence are in `json/`; companion Markdown/text source exports
remain under `sources/`. Regeneration keeps this layout, including
optional diagnostic images.

Start with `INDEX.md` and the four main images in `png/`:

- `01_overview.png`: real class collaborations across BIS, BRNS and BRC.
- `02_BIS_core.png`, `03_BRNS_core.png`, `04_BRC_core.png`: the four managers and
  their actual coordinating workflows. The IO → AI → Logic → Data sequence is
  workflow order; it does not imply that sibling managers own one another.

Every image is standalone and contains class members and annotations. Overview
boxes show selected attributes and operations; `(...)` explicitly indicates
omitted parameters, and generic container arguments are shortened. Full members
remain on the class sheets. No image references `INDEX.md`, JSON sidecars or
lookup IDs. The index remains available for local navigation:

- `M_*`: complete manager members, with numbered continuation sheets when needed.
- `A_*`: supporting class appendices grouped by real source package. Related
  small classes share a sheet; long classes use individual continuation sheets.
- `F_*`: standalone function signatures in module boxes, clearly distinguished
  from class diagrams. `json/module_dependencies.json` records their imports.

Every focal class shows all locally declared attributes and operations, including
constructors, protocol methods, class/static members and private helpers. A
property appears once as an attribute with its read-only status. Parent sheets
cover inherited project members; external parent names are recorded in the
index/model, and base names are printed in full-class headers.
`uml_types.py` reconstructs unannotated types from constructor
wiring, call sites, returns and reviewed response validators. `AppConfig`,
`ChatDecision` and other documented aliases describe existing dictionaries,
not additional application classes. Full-class images expand these aliases
to Python types directly; the local index retains the alias glossary.
`json/type_evidence.json` records declared/reconstructed contracts and their evidence.
Genuinely unresolved dynamic contracts use `DynamicValue` in the evidence ledger
and `object` in images, with an on-image explanation. They remain listed for
review. Heterogeneous JSON values retain `Any`.
Dynamic attribute allowlists and tuple-assigned fields are included.

All figures have matching SVGs and 3200 × 2200 PNGs at 300 DPI. Insert at about
10.5 inches wide in a landscape Word section. Keep continuation sheets together;
do not shrink a whole subsystem's full member inventory onto one portrait page.
`class_boxes.txt` supplies unwrapped, compartment-style text boxes.

Relationships use solid hollow triangles pointing at parents for
generalisation, dashed hollow triangles for interfaces, dotted associations
without arrowheads (the requested coursework convention), open arrows for
reviewed navigability, hollow aggregation diamonds and filled black composition
diamonds at the whole end. Standard UML normally uses solid associations;
this generator follows the requested dotted-line convention. Relationship
semantics follow the [Creately guide](https://creately.com/guides/class-diagram-relationships/).
A reflexive association requires a stored relationship to another instance of
the same class; recursive calls alone do not qualify. Relationships are drawn
only where supported by code, not to demonstrate every possible symbol.
`00_relationship_notation.png` is the visual key. Only reviewed ownership cases receive
diamonds. Optional injected defaults are not automatically composition. Inferred
collaborations with uncertain cardinality omit multiplicities. Generalisation,
realisation and temporary/HTTP dependencies never carry multiplicities.

`json/class_model.json` contains every class, member, indexed sheet, reviewed relation
and source-line evidence. Detail sheets show up to three important neighbors;
the model retains further links. Each main image has a `.relations.json` key.
`json/analysis.json` retains unresolved calls and static-inference limitations. Neither
member visibility nor a diagram proves HTTP caller authentication.

`document_uml.py`, `uml_members.py` and `uml_document_rendering.py` implement the
presentation views. The older giant diagnostic views remain opt-in with
`BITEFINDER_UML_FULL=1`; they are supplementary, not the Word report figures.
The renderer needs Pillow. For repeatable typography, optionally set
`BITEFINDER_UML_FONT` to a local monospace TrueType font; the local workfiles font
is used when available. No external rendering service receives project code.

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


## Current architecture coverage

Classes now live under subsystem layer packages such as `classes/io/`,
`classes/ai/`, `classes/logic/`, `classes/data/` and `classes/services/`.
The analyzers recursively inspect BIS, BRNS, BRC and `common`. The HTTP gateway
and JavaScript frontend are not included in those Python source sets; use the
maintained root flow/data diagrams for browser/nginx/HTTP deployment boundaries.

The live tracer starts the BIS CLI/Web selection menu. Choose CLI when tracing
an in-process interaction. Calls performed by separate API/BRC containers or
browser JavaScript are not observed by that Python process; an absent trace
edge does not prove that a service was not involved.

Visualization scripts can write ignored output and live tracing executes the
real application. Use controlled data/providers for demonstrations; static UML
analysis itself does not import application modules or call paid services.
The generators are development tools excluded from the Docker build context.

## SOLID cleanup migration

The full generator resolves the new chat, discovery, AI transport and BRC workflow
locations without hand-maintained class lists. Unresolved dynamic relationships
remain explicitly reported in `../bitefinder-workfiles/uml/document/json/analysis.json`.

The document presentation set and its reviewed model live in the external
workfiles directory. They complement the source analysis and do not claim complete
runtime inference. Generated artifacts are not staged or committed.
