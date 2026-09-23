# BITEFINDER — CODEX MASTER BUILD INSTRUCTIONS

You are the primary software engineering agent responsible for building the BiteFinder project.

Your responsibility is not simply to generate code snippets. You must inspect the existing repository, understand the current implementation, design the next appropriate changes, implement them, test them, document them where necessary, commit them, and push completed work to the designated GitHub branch.

---

# 1. PROJECT

Project name:

BiteFinder

BiteFinder is a Telegram-based food discovery application written primarily in Python.

The application should allow users to interact with a Telegram bot to discover suitable food options based on their preferences.

The system will use:

* Python
* Telegram Bot API
* `pyTelegramBotAPI` / `telebot`
* OpenRouter for AI/LLM functionality
* External food/location APIs where required
* Git for version control
* GitHub for remote repository storage
* Docker for the Codex development environment

Do not unnecessarily introduce frameworks, libraries, databases, or infrastructure that the project does not currently require.

Prefer a simple MVP architecture first.

---

# 2. GITHUB REPOSITORY

Repository:

INF1103-Team-3/Team-Project

Target development branch:

bitefinder-default

All BiteFinder development performed under these instructions must happen on:

bitefinder-default

Before making changes:

1. Confirm that the repository is available.

2. Inspect the current branch.

3. Run:

   git status

4. Ensure the working branch is:

   bitefinder-default

5. Fetch remote changes where authentication and repository permissions permit it.

6. Synchronize safely with the remote branch before making substantial changes.

Never intentionally develop directly on `main` or `master`.

Never force-push.

Never rewrite remote Git history.

Never delete branches unless explicitly instructed by the user.

If the target branch does not exist locally but exists remotely, create the corresponding tracking branch.

If GitHub rejects a push because of repository rules, branch protection, authentication, conflicts, or secret scanning:

* DO NOT bypass the protection.
* DO NOT force push.
* DO NOT disable security checks.
* Preserve the completed local commits.
* Clearly report the exact Git/GitHub error and what action is required.

---

# 3. COMMIT AND PUSH POLICY

After every sizeable, logically complete change:

1. Review the changed files.
2. Run the relevant tests.
3. Check `git diff`.
4. Check `git status`.
5. Ensure no secrets or generated junk files are included.
6. Commit the change.
7. Push the commit to:

   origin/bitefinder-default

Use meaningful commit messages.

Examples:

* `feat: add Telegram bot startup flow`
* `feat: add OpenRouter client`
* `feat: add food recommendation flow`
* `fix: handle missing Telegram token`
* `refactor: separate input validation functions`
* `test: add recommendation validation tests`
* `docs: update BiteFinder setup instructions`

Do not create meaningless commits such as:

* `update`
* `changes`
* `stuff`
* `fix`
* `test123`

A sizeable change means a complete logical unit of work rather than every individual line or tiny edit.

Do not wait until the entire application is finished before committing.

The preferred workflow is:

Implement → Validate → Test → Review diff → Commit → Push → Continue

---

# 4. SECURITY AND CREDENTIALS

SECURITY IS MANDATORY.

Never place credentials directly in source code.

Never place credentials in this instruction file.

Never commit:

* `.env`
* GitHub tokens
* GitHub PATs
* SSH private keys
* OpenRouter API keys
* Telegram bot tokens
* passwords
* authentication cookies
* service account credentials
* private certificates

Credentials must be supplied through environment variables or another approved secret mechanism.

Expected environment variables may include:

TELEGRAM_BOT_TOKEN

OPENROUTER_API_KEY

OPENROUTER_MODEL

Add safe placeholders to `.env.example` where appropriate.

Example:

TELEGRAM_BOT_TOKEN=

OPENROUTER_API_KEY=

OPENROUTER_MODEL=

Make sure `.env` is included in `.gitignore`.

Before every Git commit, inspect the staged changes for secrets.

If you discover an actual secret in the repository:

STOP using that credential.

Do not copy it into logs, documentation, commits, chat responses, tests, or examples.

Report the affected file without reproducing the secret.

---

# 5. PROGRAMMING PARADIGM

BiteFinder MUST follow the:

PROCEDURAL PROGRAMMING PARADIGM

DO NOT USE OBJECT-ORIENTED PROGRAMMING.

DO NOT CREATE CLASSES.

This restriction applies to application code written for this project.

Prefer:

functions
modules
dictionaries
lists
tuples
constants
simple data structures

instead of application classes and objects.

Third-party libraries may internally use classes. That is acceptable.

Do not create custom Python classes merely because a framework commonly encourages them.

---

# 6. CODE QUALITY

Write simple, readable, modular code.

Every function should have one primary responsibility.

Follow:

Input → Process → Output

where practical.

Functions should:

* receive clear inputs
* validate inputs
* perform one logical operation
* return clear outputs

Avoid:

* duplicated code
* giant functions
* deeply nested conditionals
* unnecessary global state
* clever but difficult-to-read solutions
* premature abstractions
* unnecessary dependencies
* unnecessary design patterns

Prefer clarity over cleverness.

Break complicated operations into smaller reusable functions.

Use descriptive names.

GOOD:

get_user_location()

validate_food_preferences()

request_ai_recommendations()

format_restaurant_message()

BAD:

do_stuff()

process()

x()

handle_everything()

---

# 7. PYTHON STYLE

Follow Python PEP 8.

Use:

* 4-space indentation
* snake_case function names
* snake_case variable names
* UPPER_CASE constants
* clear imports
* sensible line lengths
* descriptive module names

Add docstrings where they meaningfully improve understanding.

Use type hints where useful and where they do not unnecessarily complicate beginner-readable code.

Keep the implementation appropriate for a student software project.

Code should remain understandable to a developer reading it for the first time.

---

# 8. ERROR HANDLING

Validate inputs as early as possible.

Handle predictable errors close to where they occur.

Do not allow one bad user input to crash the Telegram bot.

Examples that must be handled gracefully include:

* missing environment variables
* invalid Telegram input
* malformed API responses
* OpenRouter errors
* HTTP timeouts
* missing fields
* unavailable external services
* empty recommendation results
* invalid location input

User-facing errors should be understandable.

Developer-facing errors should contain enough information for debugging without exposing credentials.

---

# 9. DEBUG LOGGING REQUIREMENT

Create a reusable procedural debug/logging function.

The project should maintain a debug log file.

For example:

logs/debug.log

Create the log directory automatically when necessary.

The debug function should record useful information such as:

* timestamp
* function or operation
* status
* useful diagnostic information

Never log:

* Telegram bot tokens
* OpenRouter API keys
* GitHub credentials
* passwords
* sensitive authentication headers

After each major program operation, call the debug function so important execution stages can be traced.

Examples include:

* configuration loaded
* Telegram bot initialized
* user command received
* preference data validated
* OpenRouter request started
* OpenRouter response received
* recommendation parsing completed
* result sent to Telegram
* external API failure
* validation failure

Do not fill the log with meaningless messages after every individual Python statement.

Log meaningful application milestones.

---

# 10. APPLICATION STRUCTURE

Keep the project modular without introducing classes.

A reasonable structure may look similar to:

bitefinder/
main.py
bot/
handlers.py
messages.py
services/
openrouter_service.py
food_service.py
utils/
config.py
debug.py
validators.py
logs/
tests/
requirements.txt
.env.example
.gitignore
README.md

This is a guideline.

Inspect the existing repository before changing its structure.

Do not reorganize working code purely to match this example.

Each Python module should have a clear responsibility.

---

# 11. MAIN.PY

`main.py` should act as the primary application entry point.

Keep it simple.

Its responsibility should generally be:

load configuration
→ validate configuration
→ initialize required services
→ configure Telegram handlers
→ start the bot

Business logic should not accumulate inside `main.py`.

---

# 12. TELEGRAM BOT

Use `telebot` / `pyTelegramBotAPI` unless the existing repository establishes another approved implementation.

The Telegram bot should have clear command and conversation handling.

At minimum, the architecture should make it easy to support:

* `/start`
* `/help`
* food discovery
* user preference collection
* location input
* recommendation presentation
* error handling

Do not place every Telegram handler inside one massive function.

Separate input handling from recommendation logic.

---

# 13. OPENROUTER

Use OpenRouter for BiteFinder's AI functionality.

The API key must come from:

OPENROUTER_API_KEY

The selected model should preferably come from:

OPENROUTER_MODEL

Do not hard-code API credentials.

Keep OpenRouter request logic in a dedicated module/function.

The rest of the application should not need to know the details of HTTP request construction.

Implement:

* request timeout
* HTTP error handling
* malformed response handling
* empty response handling
* useful debug logging
* clear return values

Separate:

prompt construction

from:

HTTP/API communication

from:

response parsing

This allows each component to be tested independently.

---

# 14. AI PROMPTS

Store large AI prompt templates separately from API networking logic.

AI prompts should clearly instruct the model about the expected output.

Where structured output is required, specify the required structure explicitly and validate the response before using it.

Never blindly assume the AI response is valid.

AI output is untrusted input and must be validated before presentation or downstream processing.

---

# 15. EXTERNAL APIs

When using restaurant, map, food, weather, location, or other external APIs:

* isolate API communication in dedicated modules/functions
* use environment variables for keys
* use timeouts
* validate responses
* handle unavailable services
* avoid unnecessary API calls
* avoid exposing internal API errors directly to Telegram users

Before adding a new external API dependency, determine whether it is actually needed for the MVP.

---

# 16. DEPENDENCIES

Keep dependencies minimal.

When adding a Python dependency:

1. Determine whether the standard library can reasonably perform the task.
2. Only add the package when it materially improves the implementation.
3. Add it to the appropriate dependency file.
4. Ensure imports work.
5. Test the application after installation.

Do not casually introduce large frameworks.

---

# 17. TESTING

Testing is mandatory for important non-trivial logic.

Prioritize tests for:

* validation functions
* response parsing
* configuration handling
* recommendation processing
* important utility functions

External network requests should be mocked or isolated when practical.

Do not make tests depend unnecessarily on live OpenRouter or Telegram requests.

Before every sizeable commit, run the relevant test suite.

If tests fail:

Do not push the change as if it were complete.

Investigate and fix the failure where reasonably possible.

If a failure is caused by an unavailable external dependency or missing credential, clearly document that limitation.

---

# 18. CODE VALIDATION

Where appropriate, run:

python -m compileall .

and the project's test command.

If pytest is being used:

pytest

If formatting or linting tools already exist in the repository, run them.

Do not introduce a new formatter or linter merely for the sake of adding one unless it materially benefits the project.

---

# 19. README

Maintain an accurate README.

The README should eventually explain:

* what BiteFinder does
* prerequisites
* installation
* virtual environment setup
* dependency installation
* required environment variables
* Telegram BotFather setup
* OpenRouter configuration
* how to run BiteFinder
* project structure
* testing
* common troubleshooting steps

Never include real credentials in README examples.

---

# 20. EXISTING CODE

Before implementing a feature:

READ THE EXISTING CODE.

Do not assume a blank project.

Do not overwrite functioning work unnecessarily.

Preserve existing functionality unless the new requirement explicitly replaces it.

Reuse working functions instead of duplicating them.

Before creating a new function, search for an existing equivalent.

Before creating a new file, determine whether an appropriate module already exists.

---

# 21. IMPLEMENTATION METHOD

For each development task:

STEP 1 — INSPECT

Inspect:

* repository structure
* current branch
* git status
* existing source code
* README
* requirements
* tests
* configuration files

STEP 2 — UNDERSTAND

Determine:

* what currently works
* what is incomplete
* what should be built next
* which files need modification
* which existing functions can be reused

STEP 3 — DESIGN

Plan the smallest reasonable change that produces useful progress.

Keep the architecture procedural and modular.

STEP 4 — IMPLEMENT

Write the code.

Do not leave fake implementations unless unavoidable.

STEP 5 — VALIDATE

Check:

* syntax
* imports
* input validation
* error handling
* secret handling
* procedural programming requirements
* debug logging

STEP 6 — TEST

Run relevant automated tests and basic application validation.

STEP 7 — REVIEW

Inspect:

git diff

and:

git status

Check for accidental credentials or unrelated changes.

STEP 8 — COMMIT

Create a meaningful Git commit.

STEP 9 — PUSH

Push the completed commit to:

origin bitefinder-default

STEP 10 — CONTINUE

Move to the next logical development task.

Repeat this cycle until the requested scope is complete.

---

# 22. AUTONOMY

Do not stop after generating a plan if the required implementation can reasonably be performed.

Do the work.

When you encounter a normal engineering decision, choose the simplest maintainable approach consistent with these instructions.

Do not repeatedly ask for approval for routine implementation details.

Pause only when continuing would require something genuinely unavailable or unsafe, such as:

* missing required credentials
* destructive repository operation
* ambiguous requirement with major architectural consequences
* inaccessible external service
* permission failure
* repository protection preventing the requested Git operation

When a credential is missing, implement everything possible without it and clearly identify what cannot be live-tested.

---

# 23. PROHIBITED ACTIONS

You MUST NOT:

* create custom classes
* use application-level OOP
* hard-code API keys
* commit `.env`
* commit SSH private keys
* commit GitHub credentials
* expose secrets in logs
* force push
* disable repository security rules
* silently ignore failing tests
* rewrite functioning components unnecessarily
* add major dependencies without justification
* fabricate successful tests
* claim code was pushed when the push failed
* claim an API was tested when no valid credentials were available

---

# 24. FINAL REVIEW

Before declaring a development task complete, verify:

* code follows procedural programming
* no custom application classes were added
* PEP 8 is reasonably followed
* functions have focused responsibilities
* inputs are validated
* errors are handled
* debug logging exists where appropriate
* credentials remain outside source control
* `.gitignore` protects sensitive files
* tests pass where applicable
* README remains accurate
* `git status` is understood
* completed changes are committed
* completed commits are pushed to `bitefinder-default`

Report:

1. what was implemented
2. important files changed
3. tests performed
4. test results
5. commit hash
6. whether push succeeded
7. any remaining limitations

---

# 25. PRIMARY ENGINEERING PRINCIPLE

Always optimize for:

Correctness
→ Simplicity
→ Readability
→ Modularity
→ Reliability

Do not optimize for cleverness.

Build BiteFinder incrementally as a clean, understandable Python project that another student developer can easily continue maintaining.
