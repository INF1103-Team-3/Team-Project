"""Use Gemini to normalize cuisines and propose outlet identities."""
from __future__ import annotations
import json, re
from google import genai
from google.genai import types

CUISINES = ("chinese","malay","indian","peranakan","indonesian","thai",
 "vietnamese","filipino","japanese","korean","western","italian","french",
 "american","mexican","turkish","middle eastern","mediterranean","fusion","lebanese")

class AIManager:
    def __init__(self, api_key, model):
        if not api_key: raise ValueError("Set GEMINI_API_KEY before running BRC.")
        self.api_key, self.model, self._client = api_key, model, None

    def process(self, context):
        if context["scenario"] == "build_database":
            return {"cuisines": self._tag_cuisines(
                context["raw_snapshot"]["listings"], context.get("report"))}
        return {"matches": self._match(
            context["records"], context["candidates"], context.get("report"))}

    def _tag_cuisines(self, rows, report=None):
        result, pending = [[] for _ in rows], []
        keywords = {"malay":"malay","nasi":"malay","chicken rice":"chinese",
                    "chinese":"chinese","indian":"indian","biryani":"indian",
                    "japanese":"japanese","sushi":"japanese","korean":"korean",
                    "thai":"thai","western":"western","pizza":"italian"}
        for index, row in enumerate(rows):
            text = f"{row.get('name','')} {row.get('category','')}".casefold()
            tags = sorted({tag for word, tag in keywords.items() if word in text})
            if tags: result[index] = tags
            else: pending.append((index, row))
        for start in range(0, len(pending), 40):
            batch = pending[start:start+40]
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
        return result

    def _match(self, records, groups, report=None):
        output=[]
        for index,(record,candidates) in enumerate(zip(records,groups),1):
            if report:
                report(f"AI: checking restaurant {index} of {len(records)} "
                       f"({record.get('name', 'unknown')})")
            if not candidates: output.append(None); continue
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

    def _call(self,prompt):
        if self._client is None: self._client=genai.Client(api_key=self.api_key)
        response=self._client.models.generate_content(model=self.model,contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1,
                                                response_mime_type="application/json"))
        if not response.text: raise RuntimeError("Gemini returned an empty response.")
        return response.text

    @staticmethod
    def _parse(text,object_ok=False):
        value=json.loads(re.sub(r"```(?:json)?","",text).strip())
        if object_ok and isinstance(value,dict): return value
        if not isinstance(value,list): raise ValueError("BRC AI response has the wrong shape.")
        return value
