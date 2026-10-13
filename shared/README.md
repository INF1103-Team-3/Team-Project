# Shared Infrastructure

`shared` contains small, reusable services used across BiteFinder programs.
These modules provide terminal presentation, operational logging, geocode
caching, and Groq model discovery. They do not decide what restaurants qualify
or how user preferences should be interpreted.

## Modules

| File | Purpose | Main users |
| --- | --- | --- |
| `terminal_ui.py` | Consistent prompts, headings, fields, numbered items, status roles, and optional ANSI color. | BIS and BRNS |
| `debug_log.py` | One global log file and one trace identifier across a search. | BIS, BRNS, BRC |
| `geocode_cache.py` | One durable location query to coordinate cache with cross platform locking. | BIS, BRNS, BRC |
| `groq_models.py` | Discovers currently active Groq text chat models suitable for structured prompts. | BIS and BRNS AI managers |

## Terminal UI

`terminal_ui.py` keeps the CLI readable while preserving plain output for
redirects and tests. Its public functions are:

| Function | Behavior |
| --- | --- |
| `set_color_enabled(enabled)` | Applies the signed in account's color preference for the current process. |
| `colors_enabled()` | Reports the current preference. |
| `line(value, role)` | Prints a styled or plain line. |
| `message(value, role)` | Prints a consistently labeled `BiteFinder:` message. |
| `section(title, role)` | Starts a visible conversation or result section. |
| `field(label, value)` | Displays one labeled value. |
| `item(number, value)` | Displays a numbered option or result. |
| `read_input(prompt)` | Reads input while styling `You:` and question prompts when supported. |

Colors appear only when enabled and standard output is an interactive terminal.
Captured test output and redirected output retain the same words and numbering
without ANSI escape codes. `/color off` is stored in the BIS account profile;
BIS reapplies that setting through this module at sign in.

When adding a CLI message, use a semantic role such as `success`, `warning`,
`error`, `match`, or `alternative`. Keep decisions and validation in the owning
manager rather than adding domain conditions to the renderer.

## Global debug log

`debug_log.py` writes all subsystem events to:

```text
logs/bitefinder.log
```

Each line contains a UTC timestamp, severity, trace identifier, event name, and
single line message. `start_trace()` creates an identifier for one operation;
nested BRNS or BRC calls reuse the identifier started by BIS. `end_trace()`
clears only a trace created by that caller, which keeps one search connected in
the log without mixing later commands.

Docker Compose mounts the named `bitefinder-logs` volume at `/data/logs` in
both containers. Their `/app/logs` links therefore resolve to the same physical
log file.

`configure_python_logging()` attaches existing Python loggers, including BRC
logging, to the shared file. `configure(display=...)` may mirror records through
an IO owned callback while debugging.

Log stage names, counts, provider status, decisions, and errors. Do not log API
keys, verification codes, account identifiers, email addresses, full provider
responses, request URLs containing credentials, or complete private user
input. User facing failures can include the trace ID so a developer can locate
the relevant sequence without exposing the record contents.

## Global geocode cache

`geocode_cache.py` stores successful query aliases in:

```text
data/geocode_cache.json
```

The JSON maps a normalized lowercase query to `[latitude, longitude]`.
`lookup(query)` validates cached coordinates before returning them.
`remember(queries, latitude, longitude)` can save several equivalent aliases,
such as the user's query, formatted address, and postal code, for one point.

Writes hold a small lock file across the read, update, and atomic replacement.
Unix uses `fcntl`; Windows uses `msvcrt`. Brief Windows `PermissionError`
failures are retried. Because caching is an optimization, a final write failure
is logged and returns `False`; it does not discard the freshly resolved
location or fail the user's search.

Callers should cache only a successful, validated geocode. They remain
responsible for Singapore specific interpretation and for deciding when a
provider request is needed.

## Groq model discovery

`fetch_chat_models(api_key, timeout=(3, 10))` requests Groq's model catalog and
returns active models that:

- accept text input;
- produce text output; and
- expose a context window of at least 4,096 tokens.

Models are ordered by largest context window first for use in a fallback chain.
Missing credentials, network errors, non-success HTTP responses, or no eligible
models return an empty list and write a concise log event. The BIS or BRNS AI
manager owns the final configured fallback list and provider request policy.

## Design rules

Keep shared modules generic and procedural:

- accept ordinary values and return ordinary values;
- avoid importing BIS, BRNS, or BRC modules;
- leave restaurant, account, and halal rules in their owning subsystem;
- avoid hidden network calls except in a helper whose name and contract make
  the request explicit;
- use shared paths rooted at the repository, not the caller's current working
  directory; and
- preserve useful plain text behavior for automated tests.

These rules prevent circular imports and let each subsystem run independently.

## Testing

Shared behavior is exercised by subsystem tests, especially data manager,
black box, BRC, and AI fallback cases. Run the complete suite with:

```bash
docker compose exec bis-brns env -u BRC_SERVICE_URL \
  python -m unittest discover -s tests -v
```

See [ProjectFlow.md](../ProjectFlow.md) for where each shared service appears in
the complete application workflow.
