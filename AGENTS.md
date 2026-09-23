# BiteFinder Codex Instructions

You are working on the BiteFinder project.

## Required project instructions

Before making ANY code changes, read the following file completely:

`docs/BITEFINDER_SPEC.md`

Treat that file as the authoritative BiteFinder project specification and
development workflow.

All implementation decisions must follow both this AGENTS.md and the master
prompt.

## Git workflow

The development branch is:

`bitefinder-draft`

Before starting work:

1. Run `git status`.
2. Confirm the current branch is `bitefinder-draft`.
3. Fetch the latest remote state.
4. Use `git pull --ff-only origin bitefinder-draft` when safe.
5. Never work directly on `main` or `master`.

After every sizeable, logically complete change:

1. Run the relevant tests.
2. Run `git diff`.
3. Run `git status`.
4. Check that no secrets are staged.
5. Commit with a descriptive commit message.
6. Push to `origin/bitefinder-draft`.

Never force-push.

If GitHub rejects a push, report the error instead of bypassing repository
protections.

## Programming rules

BiteFinder uses procedural programming.

Do not create custom classes.
Do not introduce object-oriented application architecture.

Follow PEP 8.

Prefer:

Input -> Process -> Output

Functions should have one clear responsibility.

Keep code simple, readable, modular, and appropriate for a student project.

## Security

Never commit or print:

- GitHub private keys
- GitHub tokens
- Telegram bot tokens
- OpenRouter API keys
- `.env`
- passwords
- other secrets

Secrets must come from the container environment or mounted secrets.

Do not modify files under `/run/codex-secrets`.

## Completion

Do not stop after creating a plan when implementation is possible.

For each major task follow:

Inspect -> Plan -> Implement -> Test -> Review -> Commit -> Push

At the end report:

- functionality implemented
- files changed
- tests run
- test results
- commits created
- push status
- remaining work