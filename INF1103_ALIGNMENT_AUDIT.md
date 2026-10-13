# INF1103 Part 1 Alignment Audit

Audit date: 13 October 2026  
Reference: `BIS/docs/INF1103_Part1_Consolidated_Requirements.md`

## Verification summary

| Area | Status | Evidence |
| --- | --- | --- |
| Production architecture | Pass | BIS, BRNS, and BRC each contain `io_manager.py`, `ai_manager.py`, `logic_manager.py`, and `data_manager.py`. Their normal processing path follows I/O → AI → logic → data. |
| Required manager functions | Pass | Each application exposes the required display, AI request/parse/validate, evaluate/score/route, and save/load/query functions. |
| Procedural production code | Pass | No class definitions remain in BIS, BRNS, BRC, or shared production modules. |
| Production I/O boundary | Pass | The automated compliance scan found no direct `input()` or `print()` calls outside production I/O managers. |
| AI JSON validation | Pass | BIS, BRNS, and BRC request structured results and validate model output before logic or persistence uses it. Invalid output and provider failure paths are tested. |
| Flat-file persistence | Pass | Saved application data uses JSON. Missing and corrupt file behavior is covered by tests. |
| Automated tests | Pass on host | `python -m unittest discover -s tests -v` completed 243 tests successfully, including BIS, BRNS, BIS-to-BRNS, BRC, SMTP, and manager tests. HTTP services are locally simulated in black box tests. |
| Root Docker deployment files | Present | The root `Dockerfile` comes from the `docker-deployment` branch, the main-only `docker-compose.yml` was removed, and the image context includes the offline tests required by the course. |
| Docker execution | Not verified here | Docker is unavailable in the current workspace, so image build, `docker run`, and tests inside the container still require verification on a team machine. |
| Git history | Partial | The repository has iterative history and feature merges, but several existing commit messages are vague (`update`, `In Progress`). Rewriting shared history shortly before submission is unsafe. |
| Engineering report and submission package | Missing from repository | No final five-page report, DFD, exception matrix, exported Docker image, Git-history artifact, or submission ZIP was found. These require team and submission metadata. |

## Changes made during this review

- Removed class-based helpers from the production modules and replaced them with procedural functions and dictionaries.
- Added the mandatory named manager functions where the existing implementation used differently named equivalents.
- Kept all production terminal interaction behind I/O manager functions.
- Made BRNS model calls deterministic at the request level by using temperature `0`.
- Made missing or corrupt BRNS/BRC JSON loads log the problem and return an empty result.
- Isolated Groq credentials in black box tests so tests never fall through to a live provider.
- Added `tests/inf1103_compliance_check.py` to check production classes, I/O boundaries, manager function names, requirements, and root Docker files.
- Restored `.dockerignore` and `Dockerfile` from `origin/docker-deployment`, removed the main-only Compose deployment, and retained the offline tests in the image context as required by the course.

## Remaining submission risks

### Classes outside production

The exact consolidated wording says there must be no class definitions anywhere in the codebase. The production application satisfies this, but the test harness uses `unittest.TestCase`, local HTTP server handlers, and custom test reporting classes. The project visualization utilities also use classes for AST traversal and tracing. An assessor who applies a literal repository-wide class search may count these as a C1 violation even though they are not application architecture.

Before packaging, the team should obtain a lecturer ruling or submit only a procedural test script and exclude development visualization tools. Converting the full 243-test harness to class-free procedural tests is possible, but should be treated as a deliberate submission change rather than deleting proven coverage at the last minute.

### Docker verification

The image context contains the standard-library `unittest` suite, so it can be invoked without `requirements-dev.txt`. Docker is unavailable in this workspace, so the team must still build the image and execute the tests in the resulting container on a Docker-capable machine.

### AI repeatability

Temperature is set to zero for ranking and processing calls, and schema checks constrain output. External model providers can still change output or model versions between runs, so exact cross-run equality cannot be guaranteed solely by temperature. Persisting validated AI decisions by stable input hash would provide stronger evidence for the stated deterministic-output requirement.

### Every-record AI rule

The main BIS-to-BRNS search path depends on validated AI output and fails safely when all configured models fail. BRC can reuse cached cuisine tags and exact MUIS outlet matches without spending a new AI request. This is useful operationally, but an assessor treating every cached BRC lookup as a newly processed record may consider it weaker than the literal “every processed record goes through AI” rule.

### Deliverables requiring manual completion

The team still needs to create and verify:

1. A maximum five-page engineering report with the BiteFinder data flow diagram, storage design, and exception handling matrix.
2. A Docker build and run on every team laptop, plus an offline test run inside the image.
3. The required Docker image artifact and Git repository history artifact.
4. The final ZIP using the lab group and team number naming convention.
5. One xSITE submission before 14 October 2026 at 23:59.

## Commands used for verification

```text
.venv/bin/python tests/inf1103_compliance_check.py
.venv/bin/python -m unittest discover -s tests -v
```

Observed result:

```text
INF1103 production-source check passed
Ran 243 tests in 41.922s
OK
```

