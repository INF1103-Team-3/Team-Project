"""BRNS provider-specific payloads using an injected deadline-aware HTTP call."""

import requests


class ProviderTransport:
    """Translate HTTP responses while preserving provider retry behavior."""

    def __init__(self, config, post):
        self._config, self._post = config, post

    def call_openrouter(self, model_id, system_prompt, user_text):
        """One OpenRouter attempt. Returns (True, reply_text) or (False, error)."""
        headers = {'Authorization': f'Bearer {self._config.OPENROUTER_API_KEY}', 'Content-Type': 'application/json'}
        messages = [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_text}]
        for use_json_mode in (True, False):
            payload = {'model': model_id, 'messages': messages, 'temperature': 0, 'max_tokens': 2048}
            if use_json_mode:
                payload['response_format'] = {'type': 'json_object'}
            try:
                resp = self._post(self._config.OPENROUTER_URL, headers=headers, json=payload)
            except requests.RequestException as err:
                return (False, f'network error: {err}')
            if resp.status_code == 429:
                return (False, '429 rate limited / free quota used')
            if resp.status_code == 400 and use_json_mode:
                continue
            if resp.status_code != 200:
                return (False, f'HTTP {resp.status_code}: {resp.text[:300]}')
            try:
                return (True, resp.json()['choices'][0]['message']['content'])
            except (KeyError, ValueError) as err:
                return (False, f'unexpected response shape: {err}')
        return (False, 'request rejected')

    def call_gemini(self, model_name, system_prompt, user_text):
        """One direct Google-Gemini attempt. Returns (True, reply_text) or (False, error)."""
        url = f'{self._config.GEMINI_URL}/{model_name}:generateContent'
        headers = {'x-goog-api-key': self._config.GEMINI_API_KEY, 'Content-Type': 'application/json'}
        body = {'systemInstruction': {'parts': [{'text': system_prompt}]}, 'contents': [{'role': 'user', 'parts': [{'text': user_text}]}], 'generationConfig': {'temperature': 0, 'maxOutputTokens': 2048, 'responseMimeType': 'application/json'}}
        for use_json in (True, False):
            if not use_json:
                body.pop('generationConfig', None)
            try:
                resp = self._post(url, headers=headers, json=body)
            except requests.RequestException as err:
                return (False, f'network error: {err}')
            if resp.status_code == 429:
                return (False, '429 rate limited')
            if resp.status_code == 400 and use_json:
                continue
            if resp.status_code != 200:
                return (False, f'HTTP {resp.status_code}: {resp.text[:300]}')
            try:
                parts = resp.json()['candidates'][0]['content']['parts']
                return (True, ''.join((p.get('text', '') for p in parts)))
            except (KeyError, IndexError, ValueError) as err:
                return (False, f'unexpected response shape: {err}')
        return (False, 'request rejected')

    def call_groq(self, model_id, system_prompt, user_text):
        """One Groq attempt. Returns (True, reply_text) or (False, error)."""
        headers = {'Authorization': f'Bearer {self._config.GROQ_API_KEY}', 'Content-Type': 'application/json'}
        messages = [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_text}]
        for use_json_mode in (True, False):
            payload = {'model': model_id, 'messages': messages, 'temperature': 0, 'max_tokens': 2048}
            if use_json_mode:
                payload['response_format'] = {'type': 'json_object'}
            try:
                resp = self._post(self._config.GROQ_URL, headers=headers, json=payload)
            except requests.RequestException as err:
                return (False, f'network error: {err}')
            if resp.status_code == 429:
                return (False, '429 rate limited')
            if resp.status_code == 400 and use_json_mode:
                continue
            if resp.status_code != 200:
                return (False, f'HTTP {resp.status_code}: {resp.text[:300]}')
            try:
                return (True, resp.json()['choices'][0]['message']['content'])
            except (KeyError, ValueError) as err:
                return (False, f'unexpected response shape: {err}')
        return (False, 'request rejected')
