"""BRC MUIS snapshot and JSON-checking contract tests."""

import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from BRC import ai_manager, data_manager, logic_manager, main, muis_data_scraper


def restaurant(name="Encik Tan (Waterway Point)", unit="B2-03", **extra):
    row = {
        "google_place_id": "place-1", "name": name,
        "postal_code": "828761",
        "address": f"83 Punggol Central, {unit} Waterway Point, Singapore 828761",
        "dietary": ["halal"], "halal_certification": "unofficial",
        "g_rating": "3.4", "custom_field": "preserve me",
    }
    row.update(extra)
    return row


def listing(unit="B2-03", number="EERN22010013410"):
    return {
        "listing_id": "brand-id", "certificate_number": number,
        "name": "Encik Tan",
        "address": f"83 Punggol Central #{unit} Waterway Point 828761",
        "postal_code": "828761", "scheme": "Eating Establishment",
        "sub_scheme": "Restaurant",
        "source_url": muis_data_scraper.PORTAL_URL,
    }


def snapshot(*listings):
    return {
        "source_url": muis_data_scraper.PORTAL_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "complete": True, "covered_names": ["encik tan"],
        "listing_count": len(listings), "listings": list(listings),
    }


class FakeAI:
    def __init__(self, *proposals):
        self.proposals = list(proposals)

    def propose_muis_matches(self, records, source):
        return self.proposals


class FakeResponse:
    def __init__(self, data=None, text="", status=200):
        self.data, self.text, self.status_code = data, text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError(f"HTTP {self.status_code}")

    def json(self):
        return self.data


class FakeSession:
    def __init__(self, rows, total=None):
        self.rows = rows
        self.total = len(rows) if total is None else total
        self.queries = []

    def get(self, url, timeout):
        return FakeResponse(text=(
            '<input name="__RequestVerificationToken" value="test-token">'))

    def post(self, url, json, headers, timeout):
        self.queries.append(json["text"])
        assert headers["X-CSRF-TOKEN"] == "test-token"
        return FakeResponse(data={"totalRecords": self.total,
                                  "data": self.rows})


class BRCCheckerTests(unittest.TestCase):
    def test_scraper_saves_complete_targeted_snapshot(self):
        raw = dict(id="brand-id", number="EERN22010013410",
                   name="Encik Tan", address="83 Punggol Central #B2-03 828761",
                   postal="828761", schemeText="Eating Establishment",
                   subSchemeText="Restaurant")
        session = FakeSession([raw])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "muis.json"
            result = muis_data_scraper.refresh(
                ["Encik Tan (Waterway Point)"], path,
                session=session, delay=0)
            self.assertEqual(session.queries, ["Encik Tan"])
            self.assertEqual(result["covered_names"], ["encik tan"])
            self.assertEqual(result["listing_count"], 1)
            self.assertEqual(data_manager.load_muis_snapshot(path), result)

    def test_incomplete_refresh_keeps_last_good_snapshot(self):
        session = FakeSession([dict(name="Encik Tan")], total=2)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "muis.json"
            path.write_text('{"last_good": true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "truncated"):
                muis_data_scraper.refresh(
                    ["Encik Tan"], path, session=session, delay=0)
            self.assertEqual(json.loads(path.read_text()), {"last_good": True})
            capped = FakeSession([{}] * 200)
            with self.assertRaisesRegex(ValueError, "truncated"):
                muis_data_scraper.refresh(
                    ["Encik Tan"], path, session=capped, delay=0)
            self.assertEqual(json.loads(path.read_text()), {"last_good": True})

    def test_full_array_and_single_object_preserve_fields_and_verify_outlet(self):
        source = snapshot(listing())
        first = restaurant()
        second = restaurant(name="Encik Tan (Other Unit)", unit="B1-23",
                            google_place_id="place-2")
        checked = main.check_json(
            [first, second], source,
            FakeAI("EERN22010013410", "EERN22010013410"))
        self.assertEqual(len(checked), 2)
        self.assertEqual(checked[0]["halal_certification"], "official")
        self.assertEqual(checked[0]["muis_check"]["certificate_number"],
                         "EERN22010013410")
        self.assertEqual(checked[0]["custom_field"], "preserve me")
        self.assertEqual(checked[1]["halal_certification"], "unofficial")
        self.assertEqual(checked[1]["muis_check"]["status"], "not_verified")
        self.assertEqual(first["halal_certification"], "unofficial")
        single = main.check_json(first, source, FakeAI("EERN22010013410"))
        self.assertIsInstance(single, dict)
        self.assertEqual(single["halal_certification"], "official")

    def test_missing_coverage_fails_and_previous_official_is_withheld(self):
        source = snapshot(listing())
        with self.assertRaisesRegex(ValueError, "does not cover"):
            main.check_json(restaurant(name="Other Restaurant"), source,
                            FakeAI(None))
        old = restaurant(halal_certification="official", dietary=["halal"],
                         muis_check={"prior_certification": "none",
                                     "added_halal": True})
        checked = main.check_json(old, source, FakeAI(None))
        self.assertEqual(checked["halal_certification"], "none")
        self.assertEqual(checked["dietary"], [])

    def test_expired_or_wrong_branch_listing_cannot_become_official(self):
        expired = dict(listing(), valid_until="2020-01-01")
        checked = main.check_json(
            restaurant(), snapshot(expired), FakeAI("EERN22010013410"))
        self.assertEqual(checked["halal_certification"], "unofficial")
        other_unit = listing(unit="B1-23")
        checked = main.check_json(
            restaurant(), snapshot(other_unit), FakeAI("EERN22010013410"))
        self.assertEqual(checked["halal_certification"], "unofficial")

    def test_ai_only_sees_same_postal_candidates_and_validates_ids(self):
        source = snapshot(listing(), dict(listing(number="other"),
                                          postal_code="123456"))
        ai = ai_manager.AIManager("test-key", "test-model")
        with patch.object(ai, "_call_api", return_value=json.dumps([
            {"index": 0, "certificate_number": "EERN22010013410"}])) as call:
            self.assertEqual(ai.propose_muis_matches([restaurant()], source),
                             ["EERN22010013410"])
        prompt = call.call_args.args[0]
        self.assertIn("EERN22010013410", prompt)
        self.assertNotIn('"other"', prompt)
        with patch.object(ai, "_call_api", return_value=json.dumps([
            {"index": 0, "certificate_number": "fabricated"}])):
            with self.assertRaisesRegex(ValueError, "invalid MUIS"):
                ai.propose_muis_matches([restaurant()], source)

    def test_stdout_is_one_json_object_and_missing_snapshot_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            input_path, snapshot_path = root / "input.json", root / "muis.json"
            input_path.write_text(json.dumps(restaurant()), encoding="utf-8")
            data_manager.save_muis_snapshot(snapshot(listing()), snapshot_path)
            output, errors = io.StringIO(), io.StringIO()
            with (patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
                  patch.object(main.ai_manager.AIManager,
                               "propose_muis_matches",
                               return_value=["EERN22010013410"]),
                  patch("sys.stdout", output), patch("sys.stderr", errors)):
                code = main.main(["check", "--input", str(input_path),
                                  "--snapshot", str(snapshot_path), "--stdout"])
            self.assertEqual(code, 0, errors.getvalue())
            self.assertEqual(json.loads(output.getvalue())["halal_certification"],
                             "official")
            with patch("sys.stderr", errors):
                code = main.main(["check", "--input", str(input_path),
                                  "--snapshot", str(root / "missing.json")])
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
