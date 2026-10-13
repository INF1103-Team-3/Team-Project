"""Validate AI proposals against exact MUIS evidence."""
from __future__ import annotations
import re
from datetime import date, datetime, timezone
from difflib import SequenceMatcher

def _key(text): return " ".join(re.findall(r"[a-z0-9]+", str(text).casefold()))
def _brand(text): return _key(re.split(r"\s*(?:\(|@|\|)\s*",str(text),maxsplit=1)[0])
def _postal(row):
    value=str(row.get("postal_code") or "")
    if re.fullmatch(r"\d{6}",value): return value
    found=re.findall(r"\b\d{6}\b",str(row.get("address") or ""))
    return found[-1] if found else None
_UNIT=re.compile(r"(?:#\s*|\b)((?:B\d{1,2}|\d{2})[-/]\d{2,3}(?:/\d{2,3})?[A-Z]?)\b",re.I)
def _unit(text):
    match=_UNIT.search(str(text))
    return re.sub(r"[^A-Z0-9]","",match.group(1).upper()) if match else None
def _address(text):
    text=_UNIT.sub(" ",str(text))
    text=re.sub(r"\b(?:singapore|\d{6})\b"," ",text,flags=re.I)
    return _key(text)

def _active(row):
    expiry=row.get("valid_until")
    if not expiry: return True
    for fmt in ("%Y-%m-%d","%d/%m/%Y","%d-%m-%Y"):
        try: return datetime.strptime(str(expiry)[:10],fmt).date() >= date.today()
        except ValueError: pass
    return False

def build_database(snapshot,cuisines):
    if len(snapshot["listings"]) != len(cuisines):
        raise ValueError("BRC AI did not return cuisine data for every listing.")
    output=[]; seen=set()
    for row,tags in zip(snapshot["listings"],cuisines):
        if row.get("scheme")!="Eating Establishment" or not _active(row): continue
        certificate=row["certificate_number"]
        identity=(str(row.get("listing_id") or certificate),
                  row["postal_code"],_address(row["address"]),
                  _unit(row["address"]))
        if identity in seen: continue
        seen.add(identity)
        output.append({
            "name":row["name"],"postal_code":row["postal_code"],"address":row["address"],
            "latitude":row.get("latitude"),"longitude":row.get("longitude"),
            "cuisine":tags,"dietary":["halal"],"halal_certification":"official",
            "muis":{"certificate_number":certificate,"listing_id":row.get("listing_id"),
                    "scheme":row["scheme"],"category":row.get("category"),
                    "valid_until":row.get("valid_until"),"source_url":snapshot["source_url"],
                    "raw_fetched_at":snapshot["fetched_at"]}})
    if not output: raise ValueError("No current MUIS restaurants remain after validation.")
    return output

def _same(record,listing):
    if _postal(record)!=listing["postal_code"] or not _active(listing["muis"]): return False
    if SequenceMatcher(None,_brand(record["name"]),_brand(listing["name"])).ratio()<.72:
        return False
    left,right=_unit(record.get("address")),_unit(listing["address"])
    if bool(left)!=bool(right) or (left and left!=right): return False
    return SequenceMatcher(None,_address(record.get("address")),_address(listing["address"])).ratio()>=.55

def check_restaurants(records,database,matches):
    if len(records)!=len(matches): raise ValueError("BRC AI omitted restaurant matches.")
    by_cert={row["muis"]["certificate_number"]:row for row in database}
    checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds")
    output=[]
    for record,certificate in zip(records,matches):
        result=dict(record); listing=by_cert.get(certificate) if certificate else None
        if listing and _same(record,listing):
            dietary=list(dict.fromkeys([*(record.get("dietary") or []),"halal"]))
            result.update({"dietary":dietary,"halal_certification":"official",
                           "cuisines":listing["cuisine"]})
            if not result.get("cuisine") and listing["cuisine"]:
                result["cuisine"]=listing["cuisine"][0]
            result["muis_check"]={"status":"verified","checked_at":checked_at,
                "certificate_number":certificate,"listing_id":listing["muis"].get("listing_id"),
                "source_url":listing["muis"]["source_url"],
                "valid_until":listing["muis"].get("valid_until")}
        else:
            if result.get("halal_certification")=="official":
                result["halal_certification"]="none"
                result["dietary"]=[x for x in result.get("dietary",[]) if x!="halal"]
            result["muis_check"]={"status":"not_verified","checked_at":checked_at}
        output.append(result)
    return output

def process(context,ai_output):
    if context["scenario"]=="build_database":
        return build_database(context["raw_snapshot"],ai_output["cuisines"])
    return check_restaurants(context["records"],context["database"],ai_output["matches"])


def evaluate(record):
    """Apply BRC business rules to one AI-enriched workflow record."""
    if not isinstance(record, dict) or set(record) != {"context", "ai_output"}:
        raise ValueError("BRC evaluation needs context and AI output.")
    return process(record["context"], record["ai_output"])


def score(record):
    """Return 1 for official MUIS verification and 0 otherwise."""
    return int(isinstance(record, dict)
               and record.get("halal_certification") == "official")


def route(record):
    """Route a checked restaurant to its verification outcome."""
    return "verified" if score(record) else "not_verified"
