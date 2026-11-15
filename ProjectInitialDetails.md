# BiteFinder — Project Scope, Team 3

Repository: [INF1103-Team-3/Team-Project](https://github.com/INF1103-Team-3/Team-Project)

This describes the current `WEB-OOP` application, including the CLI and web
interface. Operational instructions are in [README.md](README.md), process
branches in [ProjectFlow.md](ProjectFlow.md), and record/storage details in
[DataFlowDiagram.md](DataFlowDiagram.md).

## Problem and users

Choosing a restaurant requires comparing dietary needs, budget, cuisines,
opening hours, ratings and travel limits across several services. BiteFinder
combines Singapore restaurant and route facts with AI-assisted interpretation
and ranking, and distinguishes MUIS-verified halal evidence from unofficial
Google indications.

The intended users include students, staff, office workers, visitors,
budget-conscious diners, halal/vegetarian diners and public-transport users.

## User inputs and interfaces

- **Accounts:** email, username, password (8–128 characters for new credentials),
  and a six-digit code when email verification is enabled.
- **Profiles:** saved Singapore locations, travel distance/time, budget, dietary
  requirements, liked/disliked cuisines and reusable special wishes.
- **CLI search:** one confirmed origin and cuisine, walk/drive/transit mode,
  one active travel limit, optional driving traffic, budget and special requests.
- **Web search:** filter form or guided chatbot, multiple origins with a
  midpoint search, multiple/custom cuisine terms and follow-up clarification.
- **Result actions:** details, sorting, maps/routes, CLI Maps-link email, web
  favorites/history, and comparison of up to three restaurants.

## Architecture and AI use

BIS owns interaction, accounts, profiles and requests. BRNS owns candidate
retrieval, recommendation decisions, ranking and navigation. BRC independently
manages official MUIS evidence and outlet verification. Four identifiable
manager responsibilities remain in each subsystem: IO, AI, Logic and Data.

The browser calls nginx and a thin FastAPI `http_gateway`, which delegates to
BIS. BIS calls `BRNSService`; BRNS alone coordinates BRC. Production classes
are grouped by layer beneath each subsystem's `classes/` directory.

BIS AI interprets free text and proposes structured updates/searches. BRNS AI
ranks current candidate IDs using controlled reason codes. BRC can use AI for
uncached cuisine tags and ambiguous outlet proposals, but cached/keyword/exact
paths skip it, and Compose disables AI cuisine building by default. Chatbot
parsing has deterministic fallbacks. These are current implementation details,
not a claim of complete Part 2 compliance.

## Business rules and outputs

- Inputs and AI responses are validated before domain use; confirmed search
  values are protected from silent AI changes.
- Candidate IDs must be valid and complete. AI reasons must be grounded in
  available restaurant facts.
- Logic checks opening evidence, disliked cuisines, dietary evidence, selected
  cuisine, rating, price and travel limits. Missing facts remain unknown.
- Hard wishes can change how budget/travel cautions are handled. Results stay
  separated into matches, alternatives and exclusions; advisories explain
  relaxed conditions rather than inventing supporting facts.
- Only validated MUIS outlet/certificate evidence can become official halal
  certification. Google indications remain labelled unofficial.
- Web multi-cuisine searches merge/deduplicate existing BRNS results; browser
  comparison and sorting do not override eligibility or verification rules.

Outputs include restaurant identity, rating/review count, available price and
hours, dietary/halal status, route information, reasons and cautions.

## Persistence and operation

MongoDB is the normal shared CLI/web store for accounts, credentials, user
state, favorites, restaurant facts, history and geocode aliases. Explicit JSON
mode remains available for CLI/tests. BRC retains its own JSON files and caches.
Credentials and raw bearer tokens are not public profile fields.

Docker Compose runs MongoDB, BRC, API, nginx and a CLI container. The optional
`dev` profile supplies mongo-express. Local testing can bypass SMTP in **both**
interfaces; that does not establish real email ownership. Regression suites
use mocks/sample AI and temporary data, with separate live-service checks.
