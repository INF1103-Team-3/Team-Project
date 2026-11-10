"""Optional real Mongo integration: only a fresh isolated test database is used."""
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "BIS")]


@unittest.skipUnless(os.getenv("MONGO_TEST_URI"), "Set MONGO_TEST_URI for isolated real-Mongo verification")
class LiveMongoTests(unittest.TestCase):
    def test_separate_clients_share_cli_and_web_domain_records(self):
        from BIS.classes.mongo_connection import MongoConnection
        from BIS.classes.mongo_user_store import MongoUserStore
        name = "bitefinder_test_" + uuid4().hex
        first = MongoConnection(uri=os.environ["MONGO_TEST_URI"], database=name)
        second = MongoConnection(uri=os.environ["MONGO_TEST_URI"], database=name)
        try:
            first.ready()
            cli, web = MongoUserStore(first), MongoUserStore(second)
            cli.ensure_indexes()
            user = cli.register_user("fixture@example.com", "CLI user")
            self.assertEqual(web.get_user(user["userID"]), user)
            web.save(dict(user, username="Web user"))
            self.assertEqual(cli.get_user(user["userID"])["username"], "Web user")
        finally:
            if name.startswith("bitefinder_test_"):
                first.execute(lambda db: db.client.drop_database(name))
            first.close()
            second.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
