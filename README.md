# BiteFinder chatbot

A terminal chatbot that collects and saves user profiles and food preferences.
It supports multiple accounts. It does not search for or recommend restaurants yet.

## Getting started

Use Python 3.9 or newer. From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead.

Copy `.env.example` to `.env` if you do not already have one. For local use
without AI requests or verification emails, set:

```dotenv
AI_BYPASS=true
SMTP_BYPASS=true
```

Start the chatbot:

```bash
python main.py
```

Choose **Sign up** to create an account with an email and username, or
**Resume by email** to continue an existing profile. Usernames accept 1–50
characters. The chatbot asks one preference question at a time.

## Commands

| Command | What it does |
| --- | --- |
| `/help` | Show the available commands |
| `/help [command]` | Explain a command, its accepted values, and examples |
| `/profile` | Show your saved profile |
| `/edit` | Show how to change an answer |
| `/add-location` | Add areas to your saved locations |
| `/remove-location` | Remove saved areas; at least one must remain |
| `/reset` | Clear preferences immediately, keeping your account and username |
| `/logout` | Save and return to the account menu |
| `/quit` | Save and close the chatbot (`/exit` also works) |

For example, type `/edit budget`, then enter `10` when asked for your new
budget in SGD. Use `/help edit` for all editable fields and accepted answers.
Editing replaces that answer; `/add-location` keeps existing areas.

Dietary requirements are halal, vegan, both, or none. Cuisine answers use the
agreed list in `sources/profile_schema.py`; spelling suggestions require
confirmation. Travel accepts distance or time, using **1 km ≈ 20 minutes**.
Both travel values are saved. This is an estimate, not a calculated route.

## AI and email settings

Signup uses fixed prompts and Python validation. AI can interpret preference
answers; saved updates must still pass validation.

To enable AI, set these values in `.env`:

```dotenv
AI_BYPASS=false
OPENROUTER_MODEL=your-model-slug
OPENROUTER_API_KEYS='["first-key", "second-key"]'
```

Keys rotate in order, including failed requests. Alternatively, use
`OPENROUTER_API_KEYS_FILE=secrets/openrouter_keys.json` with a JSON list or a
comma/newline-separated key file. The key list takes priority over the file,
then the legacy `OPENROUTER_API_KEY` setting. Rotation resets on launch.

To send email verification codes, set `SMTP_BYPASS=false` and fill in the
SMTP settings shown in `.env.example`. Codes expire after ten minutes and
allow five attempts. SMTP bypass does not mark an email as verified.
Email format checks cannot detect every typo or prove an inbox exists.
Resuming an already verified account uses email selection, not a password.

Restart after changing settings. Keep `.env` and API keys private; they are
excluded from Git.

## Code and saved files

| File or folder | Purpose |
| --- | --- |
| `main.py` | Coordinate account selection and the chatbot session |
| `io_manager.py` | Ask questions, display messages, and handle commands |
| `ai_manager.py` | Interpret preferences with AI and rotate API keys |
| `data_manager.py` | Read and save user accounts |
| `logic_manager.py` | Apply validation, profile updates, and travel conversions |
| `sources/` | Shared schema, accepted values, questions, and help text |
| `support/` | Environment settings, email delivery, and logging helpers |
| `docs/` | Project references and the [code TLDR](docs/code_tldr.txt) |
| `data/users.json` | Saved accounts keyed by userID; username is outside preferences |
| `data/profile_state.json` | Verification and migration review state |
| `logs/bitefinder.log` | Operational logs, created on the first logged event |

Set `DEBUG=true` in `.env` to also display logs in the terminal. Logs include
travel distance and time; do not log API keys or verification codes.
Data and logs stay local. Use one chatbot process per saved database.

## Older saved profiles

If the chatbot reports an old profile schema, close it and run:

```bash
python -c "from main import run_migration; run_migration()"
```

Migration creates timestamped backups before updating the database. Accounts
may be asked to review old answers. New users never import another user's
profile. Corrupt data blocks writes so existing accounts are not overwritten.

## Optional formatting check

`requirements.txt` contains packages needed to run the chatbot.
`requirements-dev.txt` adds the optional PEP 8 formatting checker:

```bash
pip install -r requirements-dev.txt
python -m pycodestyle *.py sources support
```

The automated test suite and pytest have been removed.
