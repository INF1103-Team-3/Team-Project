# BiteFinder

BiteFinder is a procedural Python CLI project for source-aware food discovery.
The authoritative requirements are in [the specification](docs/BITEFINDER_SPEC.md).

Requires Python 3.11+. Runtime code uses only the standard library.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
python -m unittest discover -s tests -v
```

The initial increment provides configuration, atomic JSON persistence and safe
milestone logging. Restaurant data is currently empty; no facts are invented.
AI interpretation, request validation, hard meal filters and weighted ranking
are implemented and tested as modules. Interactive search is the next increment.

Configuration comes from environment variables (see `.env.example`). The CLI
does not automatically load `.env` or read mounted secret files. Never commit
credentials. Runtime history, profiles and logs are ignored by Git.

`main.py` starts the CLI in `io_manager.py`; `data_manager.py` handles JSON;
`config.py` loads environment settings; `debug.py` records controlled events.
The earlier Streamlit prototype is preserved in `legacy/streamlit_app.py` for
reference. Its database and recommender imports were absent in this checkout;
it is not the runnable MVP.

```sh
docker build -t bitefinder .
docker run --rm -it bitefinder
```

Docker is not installed in the current development container, so image build
and execution have not yet been verified.

The AI client uses OpenRouter's [chat completions API](https://openrouter.ai/docs/quickstart)
with JSON mode and local validation. Create a key at
[OpenRouter API Keys](https://openrouter.ai/settings/keys), then set
`OPENROUTER_API_KEY` and a JSON-capable model ID in `OPENROUTER_MODEL`.
The test suite mocks all API calls and needs no credentials.
