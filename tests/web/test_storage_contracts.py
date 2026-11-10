"""Storage substitution and migration characterization, using temporary data."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "BIS")]
import mongomock
from BIS.classes.json_user_store import JsonUserStore
from BIS.classes.mongo_user_store import MongoUserStore
from BIS.classes.mongo_connection import MongoConnection
from BIS.classes.json_mongo_migration import JsonMongoMigration
from BRNS.classes.json_recommendation_store import JsonRecommendationStore
from BRNS.classes.mongo_recommendation_store import MongoRecommendationStore
from BRNS.classes.search_history_scope import SearchHistoryScope


class StorageContractTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.conn = MongoConnection(client=mongomock.MongoClient(), database="storage_test")
        self.addCleanup(self.conn.close)

    def test_user_stores_preserve_records_states_and_reload(self):
        json_store = JsonUserStore(self.root / "users.json", self.root / "state.json")
        mongo_store = MongoUserStore(self.conn)
        mongo_store.ensure_indexes()
        for store in (json_store, mongo_store):
            with self.subTest(store=type(store).__name__):
                user = store.register_user("person@example.com", "Tester")
                user = store.save(dict(user, email_verified=True))
                store.set_state("search", user["userID"], {"completed": True})
                self.assertEqual(store.get_state("search", user["userID"]), {"completed": True})
                self.assertEqual(store.query(lambda row: row["email"] == user["email"]), [user])
                store.set_state("search", user["userID"], None)
                self.assertIsNone(store.get_state("search", user["userID"]))
                with self.assertRaises(ValueError):
                    store.register_user("person@example.com", "Duplicate")
                new_store = JsonUserStore(self.root / "users.json", self.root / "state.json") if store is json_store else MongoUserStore(self.conn)
                self.assertEqual(new_store.find_user("person@example.com"), user)
                self.assertEqual(set(user), {"userID", "email", "email_verified", "username", "preferences"})

    def test_restaurant_json_and_mongo_formatters_remain_equivalent(self):
        scope = SearchHistoryScope()
        json_store = JsonRecommendationStore(self.root / "restaurants.json", self.root / "history.json")
        mongo_store = MongoRecommendationStore(self.conn, scope)
        candidate = dict(name="Cafe", google_place_id="fixture", address="1 Road Singapore 123456",
                         rating=4.6, rating_count=80, cuisines=["japanese"],
                         dietary_requirements=["vegetarian"], price_start=10)
        for store in (json_store, mongo_store):
            self.assertEqual(store.save_restaurants([deepcopy(candidate)]), 1)
        self.assertEqual(json_store.load_restaurants(), mongo_store.load_restaurants())
        candidate["rating"] = None
        for store in (json_store, mongo_store):
            store.save_restaurants([deepcopy(candidate)])
        self.assertEqual(json_store.load_restaurants(), mongo_store.load_restaurants())
        self.assertEqual(mongo_store.load_restaurants()[0]["g_rating"], "4.6")

    def test_explicit_migration_dry_run_idempotence_and_conflict(self):
        source = JsonUserStore(self.root / "users.json", self.root / "state.json")
        user = source.register_user("migrate@example.com", "Migrated")
        source.set_state("search", user["userID"], {"completed": True})
        migration = JsonMongoMigration()
        records = migration.prepare(self.root / "users.json", self.root / "state.json")
        self.assertEqual(self.conn.db.users.count_documents({}), 0)
        MongoUserStore(self.conn).ensure_indexes()
        self.assertEqual(migration.apply(self.conn, records)["users"], 1)
        migration.apply(self.conn, records)
        self.assertEqual(self.conn.db.users.count_documents({}), 1)
        self.assertEqual(MongoUserStore(self.conn).get_user(user["userID"]), user)
        self.assertTrue(MongoUserStore(self.conn).get_state("search", user["userID"])["completed"])
        self.conn.db.users.update_one({"_id": user["userID"]}, {"$set": {"username": "Edited"}})
        with self.assertRaisesRegex(ValueError, "conflicts"):
            migration.apply(self.conn, records)
        self.assertEqual(MongoUserStore(self.conn).get_user(user["userID"])["username"], "Edited")

    def test_invalid_json_and_duplicate_data_are_not_imported(self):
        migration = JsonMongoMigration()
        path = self.root / "bad.json"
        path.write_text("invalid")
        with self.assertRaises(ValueError):
            migration.prepare(users=path)
        path.write_text(json.dumps([{"name": "No place id"}]))
        with self.assertRaises(ValueError):
            migration.prepare(restaurants=path)
        self.assertEqual(self.conn.db.restaurants.count_documents({}), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
