"""Use Gemini to normalize cuisines and propose outlet identities."""
from __future__ import annotations
import json, os, re, time
from google import genai
from google.genai import types

CUISINES = ("chinese","malay","indian","peranakan","indonesian","thai",
 "vietnamese","filipino","japanese","korean","western","italian","french",
 "american","mexican","turkish","middle eastern","mediterranean","fusion","lebanese")

class AIManager:
    def __init__(self, api_key, model):
        if not api_key: raise ValueError("Set GEMINI_API_KEY before running BRC.")
        self.api_key, self.model, self._client = api_key, model, None
        try:
            interval = float(os.getenv(
                "BRC_AI_REQUEST_INTERVAL_SECONDS", "4.2"))
        except ValueError:
            interval = 4.2
        self._request_interval = min(max(interval, 0.0), 60.0)
        try:
            timeout = float(os.getenv("BRC_AI_TIMEOUT_SECONDS", "20"))
        except ValueError:
            timeout = 20.0
        self._timeout_seconds = min(max(timeout, 1.0), 120.0)
        self._last_request_at = None
        self._report = None

    def process(self, context):
        self._report = context.get("report")
        if context["scenario"] == "build_database":
            return {"cuisines": self._tag_cuisines(
                context["raw_snapshot"]["listings"], context.get("report"),
                context.get("cuisine_cache"),
                context.get("save_cuisine_cache"))}
        return {"matches": self._match(
            context["records"], context["candidates"], context.get("report"))}

    def _tag_cuisines(self, rows, report=None, cache=None, save_cache=None):
        from BRC import data_manager

        cache = cache if cache is not None else {}
        result, pending = [[] for _ in rows], []
        keywords = {"malay":"malay","nasi":"malay","chicken rice":"chinese",
                    "chinese":"chinese","indian":"indian","biryani":"indian",
                    "japanese":"japanese","sushi":"japanese","korean":"korean",
                    "thai":"thai","western":"western","pizza":"italian"}
        for index, row in enumerate(rows):
            cache_key = data_manager.cuisine_cache_key(row)
            if cache_key in cache:
                result[index] = list(cache[cache_key])
                continue
            text = f"{row.get('name','')} {row.get('category','')}".casefold()
            tags = sorted({tag for word, tag in keywords.items() if word in text})
            if tags:
                result[index] = tags
                cache[cache_key] = list(tags)
            else: pending.append((index, row))
        cached_count = len(rows) - len(pending)
        if report and cached_count:
            report(f"AI: reused or derived {cached_count} cached cuisine tags; "
                   f"{len(pending)} still need AI.")
        if save_cache:
            save_cache(cache)
        try:
            batch_size = int(os.getenv("BRC_AI_BATCH_SIZE", "100"))
        except ValueError:
            batch_size = 100
        batch_size = min(max(batch_size, 1), 200)
        for start in range(0, len(pending), batch_size):
            batch = pending[start:start + batch_size]
            if report:
                report(f"AI: tagging cuisines for restaurants "
                       f"{start + 1}–{start + len(batch)} of {len(pending)} "
                       f"(currently {batch[0][1].get('name', 'unknown')})")
            prompt = ("Tag every restaurant with zero or more allowed cuisines. Generic words "
                      "such as restaurant are not cuisines. Return only a JSON array of "
                      "{index,cuisines}. Allowed: "+", ".join(CUISINES)+"\n"+
                      json.dumps([{"index":i,"name":r.get("name"),
                                   "category":r.get("category")} for i,r in batch]))
            parsed = self._parse(self._call(prompt))
            allowed = {i for i,_ in batch}
            if (len(parsed) != len(batch)
                    or {item.get("index") for item in parsed
                        if isinstance(item, dict)} != allowed):
                raise ValueError("BRC AI omitted or duplicated cuisine rows.")
            for item in parsed:
                if (not isinstance(item,dict) or set(item)!={"index","cuisines"}
                    or item["index"] not in allowed
                    or not isinstance(item["cuisines"],list)):
                    raise ValueError("BRC AI returned invalid cuisine tags.")
                normalized = []
                for tag in item["cuisines"]:
                    if not isinstance(tag, str):
                        continue
                    tag = re.sub(r"\s+", " ", tag.strip().casefold())
                    if tag in CUISINES and tag not in normalized:
                        normalized.append(tag)
                result[item["index"]] = normalized
                cache[data_manager.cuisine_cache_key(
                    rows[item["index"]])] = list(normalized)
            if save_cache:
                save_cache(cache)
        return result

    def _match(self, records, groups, report=None):
        output=[]
        for index,(record,candidates) in enumerate(zip(records,groups),1):
            if report:
                report(f"AI: checking restaurant {index} of {len(records)} "
                       f"({record.get('name', 'unknown')})")
            if not candidates: output.append(None); continue
            from BRC import logic_manager
            exact = [row for row in candidates
                     if logic_manager._same(record, row)]
            if len(exact) == 1:
                output.append(exact[0]["muis"]["certificate_number"])
                continue
            prompt=("Select the exact same outlet or null. Branch and unit must agree. Return "
                    "only {\"certificate_number\": string|null}.\n"+
                    json.dumps({"restaurant":record,"candidates":candidates}))
            item=self._parse(self._call(prompt), object_ok=True)
            if not isinstance(item,dict) or set(item)!={"certificate_number"}:
                raise ValueError(f"BRC AI returned an invalid match for restaurant {index}.")
            certificate=item["certificate_number"]
            allowed={row["muis"]["certificate_number"] for row in candidates}
            if certificate not in allowed|{None}:
                raise ValueError(f"BRC AI invented a match for restaurant {index}.")
            output.append(certificate)
        return output

    def _pace_request(self):
        if self._last_request_at is None:
            return
        remaining = self._request_interval - (
            time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    @staticmethod
    def _retry_delay(error, attempt):
        match = re.search(
            r"(?:retry in|retryDelay[^0-9]*)\s*(\d+(?:\.\d+)?)\s*s",
            str(error), re.IGNORECASE)
        supplied = float(match.group(1)) if match else 0.0
        return max(supplied, 4.2 * (attempt + 1))

    def _call(self,prompt):
        if self._client is None:
            self._client=genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(
                    timeout=int(self._timeout_seconds * 1000)))
        for attempt in range(5):
            self._pace_request()
            self._last_request_at = time.monotonic()
            try:
                response=self._client.models.generate_content(
                    model=self.model,contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,response_mime_type="application/json"))
            except Exception as error:
                if getattr(error, "code", None) != 429 or attempt == 4:
                    raise
                delay = self._retry_delay(error, attempt)
                if self._report:
                    self._report(
                        f"AI: Gemini rate limit reached; retrying in "
                        f"{delay:g} seconds...")
                time.sleep(delay)
                continue
            if not response.text:
                raise RuntimeError("Gemini returned an empty response.")
            return response.text
        raise RuntimeError("Gemini rate-limit retries were exhausted.")

    @staticmethod
    def _parse(text,object_ok=False):
        value=json.loads(re.sub(r"```(?:json)?","",text).strip())
        if object_ok and isinstance(value,dict): return value
        if not isinstance(value,list): raise ValueError("BRC AI response has the wrong shape.")
        return value
