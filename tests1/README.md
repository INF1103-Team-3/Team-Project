# BiteFinder Test Strategy

For the shortest grader procedure, Docker commands, expected results and
manual application check, see [`../GRADER_TEST_GUIDE.md`](../GRADER_TEST_GUIDE.md).

BiteFinder uses layered automated testing to verify its input handling,
restaurant recommendation rules, BIS-to-BRNS data flow and Docker deployment.

The teacher-facing tests show:

- the function or workflow being tested;
- a short description of its purpose;
- the input supplied;
- the expected output;
- the actual output; and
- a clear PASS or FAIL result.

Core automated tests use hardcoded AI responses and do not require a live AI
API call.

## Test groups

| Group | What it verifies | Command |
| --- | --- | --- |
| BIS | User input validation, preferences, travel limits, cuisine handling and structured AI interpretation | `python tests/run_tests.py bis` |
| BRNS | Restaurant eligibility, budget, dietary rules, travel limits, opening hours, ranking and hardcoded AI recommendations | `python tests/run_tests.py brns` |
| Core | Runs BIS and BRNS function tests together | `python tests/run_tests.py core` |
| Black box | Runs the real BIS and BRNS command-line programs using controlled external-service fixtures | `python tests/run_tests.py blackbox` |
| Integration | Verifies the structured BIS → BRNS request boundary and shared business rules | `python tests/run_tests.py integration` |
| Deployment | Confirms the tests and BiteFinder services work inside Docker | `python tests/run_tests.py deployment` |
| All | Runs the complete teacher-facing automated suite | `python tests/run_tests.py all` |

## Recommended Docker run

Build and start BiteFinder:

```bash
docker compose up -d --build
