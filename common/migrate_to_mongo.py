"""Explicit JSON import. Default is validation/counts only; no database connection."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from BIS.classes.data.sync.json_mongo_migration import JsonMongoMigration
from BIS.classes.io.cli.helpers.migration_io_manager import MigrationIOManager


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('users', 'states', 'restaurants', 'history'):
        parser.add_argument('--' + name)
    parser.add_argument('--database', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirm-database')
    args = parser.parse_args(argv)
    if not any((args.users, args.states, args.restaurants, args.history)):
        parser.error('Select at least one approved input path.')
    if args.apply and args.confirm_database != args.database:
        parser.error('--apply requires --confirm-database matching --database exactly.')
    io = MigrationIOManager()
    try:
        migration = JsonMongoMigration()
        records = migration.prepare(args.users, args.states, args.restaurants, args.history)
        if args.apply:
            from BIS.classes.data.stores.mongo.mongo_connection import MongoConnection
            from BIS.classes.data.stores.mongo.mongo_user_store import MongoUserStore
            connection = MongoConnection(database=args.database)
            try:
                MongoUserStore(connection).ensure_indexes()
                counts = migration.apply(connection, records)
            finally:
                connection.close()
        else:
            counts = migration.counts(records)
        io.display(counts, args.apply)
        return 0
    except (ValueError, RuntimeError) as error:
        io.error(str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
