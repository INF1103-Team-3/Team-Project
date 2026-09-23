from copy import deepcopy
from datetime import datetime, timezone

from logic_manager import (
    eligible_items, opening_status, prepare_request, recommend, record_selection,
)
from schemas import validate_request, validate_restaurant
from support import function_suite, request, restaurant


def test_bad_request_types_and_numbers():
    for field in ("budget_max", "walking_time_max"):
        for bad in (True, "10", -1, float("nan"), float("inf")):
            assert validate_request(request(**{field: bad}))
    for bad in ([91, 100], [1, 181], [True, 100], "Singapore"):
        assert validate_request(request(location=bad))
    assert validate_request(request(open_now="false"))
    assert validate_request(request(requested_time="2026-09-23T12:00:00"))
    assert validate_request({})
    assert validate_request(request(extra="ignored?"))


def test_safety_preferences_cannot_be_removed():
    result, error = prepare_request(request(allergies=["Soy"]), {"allergies": ["peanuts"]})
    assert error is None and result["allergies"] == ["peanuts", "soy"]
    assert prepare_request(request(unsupported_requirements=["kosher certificate"]))[1]
    assert prepare_request(request(walking_time_max=5))[1]


def test_all_constraints_must_match_the_same_meal():
    record = restaurant()
    second = deepcopy(record["menu"][0])
    second["price"] = 30
    record["menu"][0]["dietary"] = {}
    record["menu"].append(second)
    assert eligible_items(record, request(budget_max=15, dietary_requirements=["halal"])) == []


def test_unknown_price_diet_or_allergy_excludes():
    for field, changes in (("price", {"budget_max": 20}),
                           ("dietary", {"dietary_requirements": ["halal"]}),
                           ("allergen_free", {"allergies": ["peanuts"]})):
        record = restaurant()
        record["menu"][0][field] = None if field == "price" else {}
        assert eligible_items(record, request(**changes)) == []


def test_allergy_requires_cross_contact_evidence():
    record = restaurant()
    record["menu"][0]["allergen_free"]["peanuts"].pop("cross_contact_excluded")
    assert not eligible_items(record, request(allergies=["peanuts"]))


def test_budget_and_walk_boundary_and_unknown_routes():
    record = restaurant()
    req = request(budget_max=10, walking_time_max=5, location=[1.3, 103.8])
    assert len(recommend([record], req, routes={"fixture-a": 5})[0]) == 1
    assert not recommend([record], req, routes={"fixture-a": 5.01})[0]
    assert not recommend([record], req)[0]
    assert not recommend([record], request(budget_max=9.99))[0]


def test_ranking_explanations_and_stable_ties():
    a, b = restaurant("a"), restaurant("b")
    req = request(cuisines=["japanese"])
    results, excluded, error = recommend([b, a], req)
    assert error is None and not any(excluded.values())
    assert [r["restaurant"]["restaurant_id"] for r in results] == ["a", "b"]
    assert results[0]["scores"]["food"] == 35
    assert results[0]["score"] == sum(results[0]["scores"].values())
    a["cuisines"] = ["italian"]
    assert recommend([a, b], req)[0][0]["restaurant"]["restaurant_id"] == "b"


def test_opening_hours_overnight_boundary():
    record = restaurant()
    record["opening_hours"] = {
        "timezone": "Asia/Singapore", "source_ids": ["test-source"],
        "weekly": {"0": [["22:00", "02:00"]], "1": []},
    }
    # Tuesday 01:00 local falls inside Monday's overnight service.
    assert opening_status(record, datetime(2026, 9, 21, 17, tzinfo=timezone.utc)) is True
    assert opening_status(record, datetime(2026, 9, 21, 18, tzinfo=timezone.utc)) is False
    record["opening_hours"]["weekly"]["0"] = [["bad", "hours"]]
    assert opening_status(record, datetime(2026, 9, 21, 17, tzinfo=timezone.utc)) is None


def test_unknown_opening_excludes_only_when_required():
    assert not recommend([restaurant()], request(open_now=True))[0]
    assert recommend([restaurant()], request())[0][0]["open"] is None


def test_restaurant_record_validation():
    record = restaurant()
    assert validate_restaurant(record, {"test-source"})
    assert not validate_restaurant(record, set())
    record["menu"][0]["price"] = True
    assert not validate_restaurant(record, {"test-source"})
    assert not validate_restaurant(None, {"test-source"})


def test_selection_only_updates_soft_preferences():
    profile = {"allergies": ["peanuts"], "dietary_requirements": ["halal"]}
    saved = deepcopy(profile)
    for _ in range(20):
        profile = record_selection(profile, restaurant())
    assert profile["allergies"] == saved["allergies"]
    assert profile["dietary_requirements"] == saved["dietary_requirements"]
    assert profile["cuisine_counts"]["japanese"] == 10


def load_tests(loader, tests, pattern):
    return function_suite(globals())


def test_extreme_numbers_and_control_characters_rejected():
    assert validate_request(request(budget_max=10 ** 1000))
    assert validate_request(request(cuisines=["rice\x1b[2J"]))


def test_opening_evidence_and_holiday_closure():
    record = restaurant()
    record["opening_hours"] = {
        "timezone": "Asia/Singapore", "source_ids": ["missing"],
        "weekly": {"0": [["22:00", "02:00"]], "1": []},
        "exceptions": {"2026-09-22": []},
    }
    assert not validate_restaurant(record, {"test-source"})
    record["opening_hours"]["source_ids"] = ["test-source"]
    assert validate_restaurant(record, {"test-source"})
    assert opening_status(record, datetime(2026, 9, 21, 17, tzinfo=timezone.utc)) is False
    record["opening_hours"]["weekly"] = []
    assert not validate_restaurant(record, {"test-source"})
