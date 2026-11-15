"""BIS provider HTTP payloads and response/error translation."""

import requests


class ProviderTransport:
    """Own network transport while keeping prompt and domain logic separate."""

    def __init__(
        self,
        http,
        logger,
        key_selector,
        error_formatter,
        gemini_url,
        groq_url,
        nvidia_url=None,
        siliconflow_url=None,
    ):
        self._http, self._log = http, logger
        self._key_selector, self._error_formatter = (
            key_selector,
            error_formatter,
        )
        self._gemini_url, self._groq_url = gemini_url, groq_url
        self._nvidia_url = nvidia_url
        self._siliconflow_url = siliconflow_url

    def call_openrouter(self, payload, config):
        "Call OpenRouter's chat-completions endpoint and return model text."
        url = f"{config['openrouter_base_url']}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._key_selector(config)}",
            "Content-Type": "application/json",
            "X-Title": config["app_name"],
        }
        try:
            response = self._http.post(
                url,
                headers=headers,
                json=payload,
                timeout=config["openrouter_timeout_seconds"],
            )
            response.raise_for_status()
        except requests.Timeout as error:
            self._log("Request timed out.", "ERROR", "BIS.ai.request")
            raise RuntimeError(
                "The AI request timed out. Please try again."
            ) from error
        except requests.RequestException as error:
            status_text = self._error_formatter(error)
            self._log(status_text, "ERROR", "BIS.ai.request")
            raise RuntimeError(
                f"OpenRouter request failed: {status_text}"
            ) from error
        try:
            response_json = response.json()
            content = response_json["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            self._log(
                "OpenRouter returned an unexpected response structure.",
                "ERROR",
                "BIS.ai.request",
            )
            raise RuntimeError(
                "OpenRouter returned an unexpected response."
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenRouter returned an empty response.")
        self._log(
            "OpenRouter request completed successfully.",
            "INFO",
            "BIS.ai.request",
        )
        return content.strip()

    def call_gemini(self, payload, model, config):
        "Call Gemini directly for a BIS JSON response, using BIS credentials."
        api_key = config.get("gemini_api_key")
        if not api_key:
            raise RuntimeError("No Gemini API key is configured for BIS.")
        url = f"{self._gemini_url()}/{model}:generateContent"
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        messages = payload["messages"]
        body = {
            "systemInstruction": {"parts": [{"text": messages[0]["content"]}]},
            "contents": [
                {"role": "user", "parts": [{"text": messages[1]["content"]}]}
            ],
            "generationConfig": {
                "temperature": payload.get("temperature", 0),
                "responseMimeType": "application/json",
            },
        }
        for use_json_mode in (True, False):
            if not use_json_mode:
                body.pop("generationConfig", None)
            try:
                response = self._http.post(
                    url, headers=headers, json=body, timeout=(3, 12)
                )
            except requests.RequestException as error:
                raise RuntimeError(
                    "Gemini request failed. Please retry."
                ) from error
            if response.status_code == 400 and use_json_mode:
                continue
            if response.status_code != 200:
                raise RuntimeError(
                    f"Gemini request failed: HTTP {response.status_code}."
                )
            try:
                parts = response.json()["candidates"][0]["content"]["parts"]
                content = "".join((part["text"] for part in parts))
            except (ValueError, KeyError, IndexError, TypeError) as error:
                raise RuntimeError(
                    "Gemini returned an unexpected response."
                ) from error
            if not content.strip():
                raise RuntimeError("Gemini returned an empty response.")
            return content.strip()
        raise RuntimeError("Gemini rejected the request.")

    def _call_openai_compatible(
        self, label, url_getter, key_field, payload, model
    ):
        """Call an OpenAI-compatible chat-completions endpoint for JSON."""
        api_key = key_field
        if not api_key:
            raise RuntimeError(f"No {label} API key is configured for BIS.")
        if url_getter is None:
            raise RuntimeError(f"No {label} URL is configured for BIS.")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        request_payload = dict(payload, model=model)
        for use_json_mode in (True, False):
            if use_json_mode:
                request_payload["response_format"] = {"type": "json_object"}
            else:
                request_payload.pop("response_format", None)
            try:
                response = self._http.post(
                    url_getter(),
                    headers=headers,
                    json=request_payload,
                    timeout=(3, 12),
                )
            except requests.RequestException as error:
                raise RuntimeError(
                    f"{label} request failed. Please retry."
                ) from error
            if response.status_code == 400 and use_json_mode:
                continue
            if response.status_code != 200:
                raise RuntimeError(
                    f"{label} request failed: HTTP {response.status_code}."
                )
            try:
                content = response.json()["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as error:
                raise RuntimeError(
                    f"{label} returned an unexpected response."
                ) from error
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError(f"{label} returned an empty response.")
            return content.strip()
        raise RuntimeError(f"{label} rejected the request.")

    def call_groq(self, payload, model, config):
        """Call Groq's chat-completions endpoint for a BIS JSON response."""
        return self._call_openai_compatible(
            "Groq",
            self._groq_url,
            config.get("groq_api_key"),
            payload,
            model,
        )

    def call_nvidia(self, payload, model, config):
        """Call NVIDIA NIM's chat-completions endpoint for BIS JSON."""
        return self._call_openai_compatible(
            "NVIDIA NIM",
            self._nvidia_url,
            config.get("nvidia_api_key"),
            payload,
            model,
        )

    def call_siliconflow(self, payload, model, config):
        """Call SiliconFlow's chat-completions endpoint for BIS JSON."""
        return self._call_openai_compatible(
            "SiliconFlow",
            self._siliconflow_url,
            config.get("siliconflow_api_key"),
            payload,
            model,
        )
