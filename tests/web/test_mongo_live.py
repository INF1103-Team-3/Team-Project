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
        from BIS.classes.mongo_credential_store import MongoCredentialStore
        from BIS.classes.password_hasher import PasswordHasher
        name = "bitefinder_test_" + uuid4().hex
        first = MongoConnection(uri=os.environ["MONGO_TEST_URI"], database=name)
        second = MongoConnection(uri=os.environ["MONGO_TEST_URI"], database=name)
        hasher = PasswordHasher()
        try:
            first.ready()
            cli, web = MongoUserStore(first), MongoUserStore(second)
            cli_creds, web_creds = MongoCredentialStore(first), MongoCredentialStore(second)
            cli.ensure_indexes()
            user = cli.register_user("fixture@example.com", "CLI user")
            cli_creds.save(user["userID"], hasher.create("cli-secret-1"))
            self.assertEqual(web.get_user(user["userID"]), user)
            self.assertTrue(hasher.verify("cli-secret-1", web_creds.get(user["userID"])))
            web.save(dict(user, username="Web user"))
            web_creds.save(user["userID"], hasher.create("web-secret-2"))
            self.assertEqual(cli.get_user(user["userID"])["username"], "Web user")
            self.assertTrue(hasher.verify("web-secret-2", cli_creds.get(user["userID"])))
        finally:
            if name.startswith("bitefinder_test_"):
                first.execute(lambda db: db.client.drop_database(name))
            first.close()
            second.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
