"""Contracts for the rebuilt BRC workflows."""
import io, json, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from BRC import ai_manager, data_manager, io_manager, logic_manager, main, scraper

def raw_row(name="Encik Tan", unit="B2-03"):
    return {"listing_id":"id-1","certificate_number":"cert-1","name":name,
            "address":f"83 Punggol Central #{unit}, Singapore 828761",
            "postal_code":"828761","scheme":"Eating Establishment",
            "category":"Restaurant","status":"listed","valid_until":None,
            "source_url":data_manager.SOURCE_URL,"latitude":1.4,"longitude":103.9}
def snapshot(rows=None):
    rows=rows or [raw_row()]
    return {"source_url":data_manager.SOURCE_URL,
      "fetched_at":datetime.now(timezone.utc).isoformat(),"complete":True,
      "coverage":"all_eating_establishments","postal_prefixes":list("0123456789"),
      "listing_count":len(rows),"listings":rows}
def restaurant(unit="B2-03"):
    return {"name":"Encik Tan (Waterway Point)","postal_code":"828761",
            "address":f"83 Punggol Central #{unit}, Singapore 828761",
            "dietary":[],"halal_certification":"unofficial","custom":"kept"}

class FakeAI:
    def process(self,context):
        if context["scenario"]=="build_database":
            return {"cuisines":[["malay"] for _ in context["raw_snapshot"]["listings"]]}
        return {"matches":["cert-1" for _ in context["records"]]}

class BRCTests(unittest.TestCase):
    def test_interactive_menu_accepts_pasted_single_restaurant(self):
        pasted = json.dumps(restaurant())
        with patch("builtins.input", side_effect=["4", pasted]):
            value = io_manager.collect_interactive_input()
        self.assertIsInstance(value, dict)
        self.assertEqual(value["name"], "Encik Tan (Waterway Point)")

    def test_interactive_single_file_rejects_an_array(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "one.json"
            path.write_text(json.dumps([restaurant()]), encoding="utf-8")
            with (patch("builtins.input", side_effect=["5", str(path)]),
                  self.assertRaisesRegex(ValueError, "one restaurant object")):
                io_manager.collect_interactive_input()

    def test_main_without_arguments_is_verbose_and_uses_menu(self):
        errors = io.StringIO()
        with (patch.object(io_manager, "collect_interactive_input",
                           return_value=io_manager.NO_INPUT),
              patch.object(main, "run", return_value=[restaurant()]) as execute,
              patch("sys.stderr", errors), patch("sys.stdout", io.StringIO())):
            self.assertEqual(main.main([]), 0)
        self.assertTrue(execute.call_args.kwargs["verbose"])
        self.assertIsNotNone(execute.call_args.kwargs["scrape_progress"])

    def test_standalone_progress_names_stage_and_current_restaurant(self):
        output = io.StringIO()
        display = scraper._ConsoleProgress(output, width=10)
        display("retrieve", 3, 10, "Encik Tan (Waterway Point)")
        display("geocode", 1, 2, "Example Restaurant (828761)")
        text = output.getvalue()
        self.assertIn("30.0% MUIS: 3/10", text)
        self.assertIn("Encik Tan", text)
        self.assertIn("50.0% OneMap: 1/2", text)
        self.assertIn("Example Restaurant", text)

    def test_no_input_builds_clean_database_through_managers(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); raw=root/"raw.json"; clean=root/"clean.json"
            data_manager.save_raw_snapshot(snapshot(),raw)
            result=main.run(ai=FakeAI(),raw_path=raw,clean_path=clean)
            self.assertEqual(result[0]["cuisine"],["malay"])
            self.assertEqual(result[0]["halal_certification"],"official")
            self.assertEqual(data_manager.load_clean_database(clean),result)

    def test_missing_clean_database_is_built_before_single_check(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); raw=root/"raw.json"; clean=root/"clean.json"
            data_manager.save_raw_snapshot(snapshot(),raw)
            with patch.object(data_manager,"save_checked_result",
                              side_effect=lambda value,**_:value):
                result=main.run(restaurant(),ai=FakeAI(),raw_path=raw,clean_path=clean)
            self.assertEqual(result["halal_certification"],"official")
            self.assertEqual(result["cuisine"],"malay")
            self.assertEqual(result["custom"],"kept")

    def test_wrong_branch_unit_cannot_be_certified(self):
        database=logic_manager.build_database(snapshot(),[["malay"]])
        checked=logic_manager.check_restaurants(
            [restaurant("B1-23")],database,["cert-1"])[0]
        self.assertEqual(checked["halal_certification"],"unofficial")
        self.assertEqual(checked["muis_check"]["status"],"not_verified")

    def test_array_shape_and_no_candidate_are_preserved(self):
        database=logic_manager.build_database(snapshot(),[["malay"]])
        records=[restaurant(),dict(restaurant(),name="Elsewhere",postal_code="123456")]
        context={"scenario":"check_restaurants","records":records,"single":False,
                 "database":database,
                 "candidates":io_manager.candidate_sets(records,database)}
        class MatchAI:
            def _call(self,prompt): return '{"certificate_number":"cert-1"}'
        manager=ai_manager.AIManager("key","model"); manager._call=MatchAI()._call
        output=logic_manager.process(context,manager.process(context))
        self.assertEqual(len(output),2)
        self.assertEqual(output[0]["halal_certification"],"official")
        self.assertEqual(output[1]["muis_check"]["status"],"not_verified")

    def test_generic_restaurant_label_does_not_invent_cuisine(self):
        manager=ai_manager.AIManager("key","model")
        manager._call=lambda _: '[{"index":0,"cuisines":[]}]'
        tags=manager._tag_cuisines([raw_row(name="Example Restaurant")])
        self.assertEqual(tags,[[]])

    def test_unsupported_ai_cuisine_labels_are_filtered(self):
        manager=ai_manager.AIManager("key","model")
        manager._call=lambda _: (
            '[{"index":0,"cuisines":["Singaporean"," CHINESE ","Cafe"]}]')
        tags=manager._tag_cuisines([raw_row(name="Example Restaurant")])
        self.assertEqual(tags,[["chinese"]])

    def test_exact_outlet_match_does_not_spend_an_ai_request(self):
        database=logic_manager.build_database(snapshot(),[["malay"]])
        manager=ai_manager.AIManager("key","model")
        manager._call=lambda _: (_ for _ in ()).throw(
            AssertionError("AI should not be called for one exact outlet"))
        matches=manager._match(
            [restaurant()],
            [io_manager.candidate_sets([restaurant()],database)[0]])
        self.assertEqual(matches,["cert-1"])

    def test_gemini_rate_limit_waits_and_retries(self):
        class RateLimited(Exception):
            code=429
        class Models:
            def __init__(self): self.calls=0
            def generate_content(self,**_):
                self.calls+=1
                if self.calls==1:
                    raise RateLimited("retry in 5.5s")
                return type("Response",(),{"text":"[]"})()
        models=Models()
        manager=ai_manager.AIManager("key","model")
        manager._client=type("Client",(),{"models":models})()
        manager._request_interval=0
        messages=[]
        manager._report=messages.append
        with patch.object(ai_manager.time,"sleep") as sleep:
            self.assertEqual(manager._call("prompt"),"[]")
        self.assertEqual(models.calls,2)
        sleep.assert_called_once_with(5.5)
        self.assertIn("rate limit reached",messages[0])

    def test_compact_opening_hours_and_cache_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); cache=root/"cache.json"
            first=dict(restaurant(),google_place_id="x",opening_hours={"monday":["0000","2359"]})
            second=dict(first,g_rating="4.5")
            data_manager.update_checked_cache([first],cache)
            data_manager.update_checked_cache([second],cache)
            text=cache.read_text()
            self.assertIn('"monday": ["0000", "2359"]',text)
            self.assertEqual(json.loads(text)["restaurant_count"],1)

    def test_atomic_json_write_retries_windows_access_denied(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "progress.json"
            real_replace = data_manager.os.replace
            attempts = []

            def temporarily_locked(source, destination):
                attempts.append(destination)
                if len(attempts) < 3:
                    raise PermissionError(5, "Access is denied")
                return real_replace(source, destination)

            with (patch.object(data_manager.os, "replace",
                               side_effect=temporarily_locked),
                  patch.object(data_manager.time, "sleep")):
                data_manager.write_json_atomic({"pending": ["519"]}, path)
            self.assertEqual(len(attempts), 3)
            self.assertEqual(json.loads(path.read_text()), {"pending": ["519"]})

    def test_scraper_splits_capped_prefix_and_preserves_target_on_failure(self):
        class Session:
            def get(self,*_,**__):
                return type("R",(),{"text":'<input name="__RequestVerificationToken" value="t">',
                                    "raise_for_status":lambda self:None})()
            def post(self,url,json,headers,timeout):
                query=json["text"]
                rows=[{}]*200 if query=="0" else []
                return type("R",(),{"raise_for_status":lambda self:None,
                    "json":lambda self:{"totalRecords":len(rows),"data":rows}})()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); target=root/"raw.json"; progress=root/"progress.json"
            target.write_text('{"last_good":true}')
            with self.assertRaisesRegex(ValueError,"no eating"):
                scraper.scrape_all(target,session=Session(),delay=0,geocode=False,
                                   progress_path=progress)
            self.assertEqual(json.loads(target.read_text()),{"last_good":True})
            state=json.loads(progress.read_text())
            self.assertIn("00",state["completed_prefixes"])

    def test_expired_listing_is_removed(self):
        row=raw_row(); row["valid_until"]=(datetime.now()-timedelta(days=1)).strftime("%Y-%m-%d")
        with self.assertRaisesRegex(ValueError,"No current"):
            logic_manager.build_database(snapshot([row]),[["malay"]])

if __name__=="__main__": unittest.main(verbosity=2)
