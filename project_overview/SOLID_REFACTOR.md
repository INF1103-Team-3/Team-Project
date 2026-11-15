# SOLID cleanup: migration and verification

Work branch: `SOLID-PEP8-Cleanup`, based on `main` at `4e529e1`.
This work keeps the four-manager architecture and the current CLI/web entry
points. Supporting policies, transports and workflows do not introduce a fifth
manager role. All commits use `xinop <2603049@sit.singaporetech.edu.sg>`.

## Migration map

| Previous implementation | Current owner | Preserved boundary / checks |
| --- | --- | --- |
| Chatbot filter normalization, update/reconciliation and onboarding decisions | `BIS/classes/logic/chat/chat_filter_policy.py`: `ChatFilterPolicy` | Existing web chat payload/results; negation, limits, onboarding and confirmation tests |
| Chatbot deterministic interpretation | `BIS/classes/logic/chat/deterministic_chat_parser.py`: `DeterministicChatParser` | Same fallback intents and updates; existing web tests |
| Chatbot summaries, prompts, edit questions and quick replies | `BIS/classes/io/web/chat/chat_presenter.py`: `ChatPresenter` | Same wording, filters and actions; chat characterization and web tests |
| `BISChatbotService` monolithic implementation | Existing `BIS/classes/services/web/bis_chatbot_service.py` | Conversation orchestration still connects AI, Logic and profile persistence |
| BRNS IO radius, fallback and spatial-selection decisions | `BRNS/classes/logic/discovery/discovery_policy.py`: `DiscoveryPolicy` | Generator yields the same ordered search requests; quota/query tests and mocked Google tests |
| BRNS IO Places/geocoding HTTP and response mapping | `BRNS/classes/io/gateways/google/google_places_gateway.py`: `GooglePlacesGateway` | Same request shapes, timeouts, retries and result fields |
| Candidate orchestration under IO gateways | `BRNS/classes/services/workflows/candidate_search.py`: `CandidateSearch` | Existing `find_candidates` / `build_candidates` callers remain usable |
| Profile ownership/email verification checks in Data and Logic | `BIS/classes/logic/security/profile_access_policy.py`: `ProfileAccessPolicy` | Web keeps permission errors; CLI keeps value errors; shared authorization tests |
| Live location lookup through Data | Injected `LocationGateway` in `BISApplicationService` | Same origin/profile validation; Data retains persistence responsibilities |
| Search-derived preference recording under Data | `BIS/classes/services/cli/search_preference_recorder.py` | Same explicitly approved wishes and cuisines; CLI tests |
| BIS procedural AI task bodies and reverse class-to-module imports | `BIS/classes/ai/tasks/bis_interpreter.py`: `BISInterpreter` | Existing module entry points delegate; prompts, schema handling and fallback remain |
| BIS/BRNS procedural provider transport bodies | Each subsystem's `classes/ai/providers/clients/provider_transport.py` | Injected HTTP operations; existing controlled-service and provider tests |
| Duplicate BRNS provider availability checks | `AIProviderFactoryRegistry.is_configured()` | Availability extends through registration; fake-provider capability test |
| BRC AI-folder jobs coordinating Logic/cache/save checkpoints | `BRC/classes/services/workflows/` | Existing build/check behavior and partial-failure/checkpoint tests |
| BRC `HalalDatabase` in caches | `BRC/classes/data/models/muis/halal_database.py` | Same aggregate and model re-export |
| BRNS coordinator's evidence-to-certification decisions | `BRNS/classes/logic/evaluation/halal_evidence_policy.py`: `HalalEvidencePolicy` | Both official certification and verified MUIS status are required |

Existing module functions are retained where they are active compatibility or
integration entry points; they delegate to one implementation. The unused BRC
AI whole-job methods `tag_cuisines` and `match_outlets` were removed: production
workflows use the focused AI operations `tag_batch` and `propose_match`.

## Deliberate failure-contract corrections

These changes are separate from the behavior-preserving responsibility moves:

- **BRNS JSON safety:** read-only queries retain the legacy empty fallback.
  Missing files can be created, but updates refuse to overwrite corrupt files
  or existing documents with the wrong top-level shape. Completed writes use a
  same-directory temporary file, flush/fsync and atomic replacement. Failed
  replacement retains the old file and removes the temporary file.
- **BIS bulk-load parity:** JSON and Mongo user stores return `[]` and expose
  `last_error` after malformed/unavailable reads. Successful loads clear that
  error. Direct user lookups and saves still raise validation/backend errors.
  There is no automatic switch from Mongo to JSON.
- **BRC injection:** background warm-up uses the handler selected in the server
  constructor, including its database path, lock and application callback.
  Default service behavior is unchanged.

No restaurant eligibility/ranking weights, official verification rules, provider
order, AI prompts, CLI menus, endpoint schemas or stored record schemas were
intentionally changed. Formatting was checked against executable ASTs and
prompt/output string values; only documentation whitespace and top-level import
placement were excluded from that comparison.

## Design evidence

- **SRP:** chat policy, presentation, AI interpretation, network transport and
  conversation orchestration have distinct owners. Discovery planning lives in
  Logic and its HTTP executor in IO. Persistence performs storage work.
- **OCP:** provider availability and result sorting use existing registries;
  callers do not acquire a new provider-name switch for an added registration.
- **LSP:** JSON/Mongo behavior is tested with the same malformed-record and
  recovery cases; existing provider, sorter and manager contract tests remain.
- **ISP:** `ChatAIInterface` expresses the chat/review capability needed by the
  web workflow, separately from the profile/search AI contract. Broad public
  HTTP/subsystem facades remain where they intentionally expose that boundary.
- **DIP:** AI interpretation uses an injected request operation. Provider
  transport accepts HTTP collaborators, location IO is injected into the
  application workflow, and BRC warm-up honors the injected handler.
- **Composition:** chat orchestration creates its parser/presenter; Logic
  creates its authorization policy. Other collaborators can be supplied and
  referenced independently. Registries aggregate supplied provider/sorter
  behaviors; existing abstract bases remain genuine specializations.

One production class per module remains enforced by review. The final scan found
169 classes under owning subsystem class directories, with no classes in
`__init__.py` and no parent-after-interface declarations. Additional abstract
parents or persistence implementations were not manufactured for rubric points.

## Style policy

`setup.cfg` defines a 79-character code-line limit. GitHub Actions runs
`pycodestyle` separately from container tests. There is no global line-length
exemption. Narrow inline exceptions document script-path bootstrap imports,
unbreakable qualified import paths and descriptive test identifiers. Formatting
is kept in its own commit, separate from domain changes.

```bash
python -m pycodestyle BIS BRNS BRC common http_gateway main.py tests project_overview
```

## Executed verification

Tests used an isolated copy of tracked/new source files, external services were
mocked, credentials were removed from test subprocess environments, and the
local environment/secrets files were not copied into that test checkout.

| Command | Final result |
| --- | --- |
| `python3 tests/run_tests.py core` | Pass: BIS 14, BRNS 23, BRC 4, OOP 40, cleanup contracts 13, launcher 10: 104 cases |
| `python3 tests/run_tests.py integration` | Pass: 11 cases |
| `python3 tests/run_tests.py blackbox` | Pass: 18 BIS, 8 BRNS, 3 combined: 29 cases |
| `python3 tests/run_tests.py web` | Pass: 39 web API + 6 storage cases; one real-Mongo test skipped |
| `python3 project_overview/test_uml.py` | Pass: 11 tests; regenerated local PNG/SVG/source artifacts |
| `python3 -m pycodestyle BIS BRNS BRC common http_gateway main.py tests project_overview` | Pass: zero findings under the documented policy |
| `pyflakes` production scan | No undefined names; existing unused-import/re-export diagnostics are not claimed as a clean full pyflakes run |

Total: **200 passing reported cases, one skipped** including UML tests.
Temporary test dependencies were installed outside the repository. Native
extensions cannot execute from `/tmp` in this workspace, so existing web
dependencies and an external local Pillow directory were used for those checks.

Docker is unavailable here. Container builds, deployment smoke tests, live MongoDB
and paid/provider API checks were not run. CI definitions do not establish that
the remote CI checks passed, and this work has not been pushed.

## Diagram review and remaining limitations

Generated diagrams remain ignored under `project_overview/uml/`. The full static
analysis found 169 classes and 1,116 source-evidenced relationships, with 95
unresolved dynamic call sites. It is diagnostic and does not prove every runtime
lifetime or call. The existing subsystem PNG layout was visually inspected.
A reviewed subset is saved locally as `cleanup_reviewed.json`, `.txt`, `.mmd`
and `.md`; it distinguishes associations, owned parts and actual interfaces.

The existing deterministic chat fallback, BRC cache/exact-match AI short circuits
and optional in-process CLI BRC adapter are intentionally retained. These should
not be represented as proof of literal every-record AI processing or HTTP-only
operation in every configuration. No new feature, backend, data migration or
deployment architecture is included in this cleanup.
