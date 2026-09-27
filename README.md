# BiteFinder CLI Profile Chatbot

A procedural Python chatbot that uses OpenRouter to turn natural-language
answers into food preferences. All application logic lives in `iomanager.py`.
`main.py` remains a compatibility launcher for the previous run command.

## Setup and run

Use Python 3.9 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell.
Copy `.env.example` to `.env` if you do not already have a `.env` file, then
set `OPENROUTER_MODEL`, your selected API keys, and SMTP settings as described
below. `OPENROUTER_MODEL` is required; there is no model hardcoded in Python.
Existing process environment variables take precedence over `.env` values.

```bash
python iomanager.py
```

For local testing without AI, set `AI_BYPASS=true` in `.env` and restart.
The CLI asks the fixed profile questions and validates one answer at a time.
No OpenRouter key or model is required in this mode, and key files are not
read. Set `SMTP_BYPASS=true` as well to test without email delivery.
Both switches default to `false` when absent and in `.env.example`.

Local answer formats:

- Name and location: non-empty text, at most 200 characters.
- Travel limit: a number and unit, e.g. `1 km` or `20 mins`, up to two decimal
  places. Limits are 0.01–100 km or 0.1–2,000 minutes. Both values are saved
  using the 20-minute-per-kilometre conversion.
- Budget: `0.01`–`1000`, up to two decimal places, without currency symbols.
- Dietary requirements, allergies, cuisines, and dining preferences:
  comma-separated text, or `none`. Each entry must be 1–100 characters.
  Allergy answers cannot contain numbers, including mixed text like `peanuts2`.
- Spice preference: `none`, `mild`, `medium`, `hot`, or `extra hot`.

Invalid answers leave preferences unchanged and keep the current question
active. `/profile`, `/help`, `/reset`, `/logout`, and `/quit` work locally. Use `/reset`
to redo completed answers; natural-language corrections require AI mode.
Set `AI_BYPASS=false` and restart to restore AI extraction.

## Signup and saved profiles

Choose **Sign up** before answering preference questions. Enter an email; the
application generates a unique UUID `userID` internally for storage.
Emails are trimmed, converted to lowercase, validated, and unique across users.
A compiled regex checks email syntax, with additional length and local-part
checks. Signup sends a six-digit verification code to the address. Enter that
code before starting the chatbot. A signup is saved immediately as unverified,
so you can resume by email if you quit during verification.

Codes expire after 10 minutes and allow five attempts. Use `/resend` to request
a replacement, with at least 60 seconds between emails, or `/quit` to continue
later. Only a salted hash of the code is saved. Successful verification removes
the challenge and saves `email_verified` and `email_verified_at` on that user.

On later runs, choose **Resume a saved profile** and enter your email address.
Existing profiles without a verification flag must verify once; their
preferences are retained. Verified profiles resume without another code.
Returning-user selection uses email, without password
authentication. Use one running CLI process at a time with the shared JSON file.

All users and their preferences are stored in `data/users.json`, keyed by ID:

```json
{
    "example-generated-user-id": {
        "userID": "example-generated-user-id",
        "email": "alex@example.com",
        "email_verified": true,
        "email_verified_at": "2026-09-23T12:00:00+00:00",
        "preferences": {
            "name": "Alex",
            "location": "Punggol",
            "max_distance_km": 8,
            "max_travel_time_minutes": 160,
            "budget_per_person": 20,
            "dietary_requirements": ["vegetarian"],
            "allergies": [],
            "liked_cuisines": ["Japanese"],
            "disliked_cuisines": [],
            "spice_preference": "mild",
            "dining_preferences": ["hawker centres"]
        }
    }
}
```

An unanswered preference is `null`; an empty list means the user answered
“none.” Validated updates save automatically for the selected user. Resets
retain that user's ID and email and leave other users unchanged. Writes replace
the JSON file atomically. Unreadable or malformed saved data stops the operation
instead of silently replacing it with an empty registry.

New accounts always start with empty preferences. Signup does not offer to
import the original single-user profile, because it cannot verify ownership.
The old file is left untouched. Both profile files and `.env` are excluded
from Git.

## Email delivery configuration

Set these values in `.env` using your SMTP provider's credentials:

```dotenv
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your-smtp-username
SMTP_PASSWORD=your-smtp-password
SMTP_FROM_EMAIL=sender@example.com
```

Use `SMTP_SECURITY=ssl` and your provider's SSL port (usually 465) for TLS from
the start of the connection. Both modes verify TLS certificates using
[Python's SMTP client](https://docs.python.org/3/library/smtplib.html).
Use a sender address authorized by the provider. An unauthenticated TLS relay
may leave both username and password empty; otherwise set both. Verification
requires working email delivery unless the testing bypass below is enabled.
Missing SMTP settings do not
prevent already verified profiles from resuming.

For local testing without SMTP, set this in `.env` and restart the application:

```dotenv
SMTP_BYPASS=true
```

This skips email delivery and code entry for signup and resume, allowing chat,
profile saves and resets. Email format validation still runs.
The bypass does not mark users as verified. Set `SMTP_BYPASS=false` and restart
to require verification again for unverified users. The default and
`.env.example` value are `false`.

## AI router configuration

Select the keys to rotate by listing them in the desired order in `.env`:

```dotenv
OPENROUTER_MODEL=your-chosen-model-slug
OPENROUTER_API_KEYS='["your-first-api-key", "your-second-api-key"]'
```

Comma-separated values also work: `OPENROUTER_API_KEYS=key-one,key-two`.
Alternatively, leave that setting empty and specify a file:

```dotenv
OPENROUTER_API_KEYS_FILE=secrets/openrouter_keys.json
```

The file contains a JSON array:

```json
["your-first-api-key", "your-second-api-key"]
```

A plain text file with one key per line or comma-separated keys also works.
Relative paths resolve from the directory containing `iomanager.py`.
`secrets/`, `openrouter_keys.json`, and `openrouter_keys.txt` are ignored by Git.
Keep other custom key-file paths outside Git or add them to `.gitignore`.

Source precedence is `OPENROUTER_API_KEYS`, then `OPENROUTER_API_KEYS_FILE`,
then the original `OPENROUTER_API_KEY` single-key setting. A malformed or
unreadable selected source stops startup rather than using a different source.
Duplicate keys are removed while preserving order.

`next_api_key(config)` selects the next key for `_call_openrouter()` using
[OpenRouter bearer authentication](https://openrouter.ai/docs/api/reference/authentication).
For keys A and B, request attempts use A, B, A, B. The cursor advances even if a
request fails; there are no automatic retries. It restarts at the first key on
each application launch. Debug logs identify only the key slot, never the key.

## Chat commands

- `/profile`: show the selected user's preferences.
- `/reset`: clear only the selected user's preferences.
- `/help`: show help.
- `/logout`: save and return to the signup/resume menu to use another email.
- `/quit` or `/exit`: save and exit.

Natural-language answers can provide several preferences at once or correct
previous answers, such as “actually make my budget $30.” The original question
sequence, validation, AI extraction, and natural-language commands are retained.

Travel limits accept distance or time. For example, “10 mins away” saves
`max_travel_time_minutes: 10` and `max_distance_km: 0.5`. “2 km away” saves
2 km and an estimated 40 minutes. AI extraction uses an approximate walking
conversion of **20 minutes per kilometre**, and Python fills any missing
counterpart using the same rule. This is an estimate, not a route calculation.
Hours and metres are converted by the AI to minutes and kilometres.

Both values appear in `/profile`, are saved per user, and are written to the
debug log under `profile.travel`. Corrections to one limit also update the
estimated counterpart; explicitly supplied limits are both retained. Existing
distance-only profiles gain an estimated time when loaded and saved. Accepted
limits are greater than zero, up to 100 km or 2,000 minutes.

## Debugging

```bash
python iomanager.py --debug
```

Events always go to `logs/bitefinder.log`; `--debug` also prints them to stderr.
Each line has a timestamp, severity (`DEBUG`, `INFO`, `WARNING`, or `ERROR`),
event name, and message:

```text
2026-09-23T12:00:00+00:00 | INFO    | storage.save | Saved preferences.
```

Call `debug_log(message, level="DEBUG", event="application")` for new events.
Messages describe operations, field names, and saved travel time/distance;
they do not include API keys,
email addresses, verification codes, SMTP passwords, raw chat text, or provider
error bodies. Log write failures
do not stop the chatbot.

## Development checks

Tests use temporary files, mocked SMTP delivery, and mocked API responses,
without sending real emails, calling OpenRouter, or changing real user data.
The test code also uses procedural functions.

```bash
pip install pytest pycodestyle
python -m pytest -q
python -m pycodestyle iomanager.py main.py tests
```

## Shared preference validation

AI extraction and local CLI answers use the same Python validation before
saving. Spice values are exactly `none`, `mild`, `medium`, `hot`, or `extra hot`.
The AI can interpret natural phrasing, but unsupported output values are
rejected and the user is asked to clarify.

Dietary requirements use a controlled list: `halal`, `kosher`, `vegetarian`,
`vegan`, `pescatarian`, `gluten-free`, `dairy-free`, `lactose-free`, `egg-free`,
`nut-free`, `peanut-free`, `shellfish-free`, `soy-free`, `low-sodium`,
`low-sugar`, `low-carb`, and `keto`. `none` means an empty list. Clear aliases
such as “gluten free” normalize to one canonical term and duplicates are
removed. Distinct requirements remain separate. Unknown entries such as
`dkdk`, including entries mixed with valid restrictions, are rejected as a
whole rather than guessed or silently removed. Unsupported requirements need
clarification; they are never treated as “none.”

Invalid AI values trigger clarification before any of that response is
applied. Shared checks also enforce numeric bounds, lengths, list item types,
and the prohibition on numbers in allergies. Names, locations, cuisines,
allergy names, and dining descriptions remain free text; their structural
validation cannot prove that every phrase is meaningful. The AI is instructed
to extract only supported facts and leave uncertain fields unanswered.
