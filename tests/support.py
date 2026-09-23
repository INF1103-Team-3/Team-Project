"""Synthetic data only; never used as real restaurant recommendations."""

import unittest

from schemas import empty_request


def request(**changes):
    value = empty_request()
    value.update(changes)
    return value


def restaurant(identifier="fixture-a"):
    claim = {"confirmed": True, "evidence_type": "official",
             "source_ids": ["test-source"], "cross_contact_excluded": True}
    return {
        "restaurant_id": identifier, "name": "Synthetic test restaurant",
        "address": "Synthetic address", "location": [1.3, 103.8],
        "cuisines": ["japanese"], "source_ids": ["test-source"],
        "menu": [{"name": "Synthetic test meal", "price": 10, "currency": "SGD",
                  "food_tags": ["rice"], "source_ids": ["test-source"],
                  "dietary": {"halal": dict(claim)},
                  "allergen_free": {"peanuts": dict(claim)}}],
    }


def function_suite(namespace):
    return unittest.TestSuite(unittest.FunctionTestCase(function)
                              for name, function in namespace.items()
                              if name.startswith("test_"))
