from app.db.lancedb_client import LanceDBClient
from app.db.postgres import init_db


if __name__ == "__main__":
    init_db()
    LanceDBClient().ensure_table()
    print("initialized PostgreSQL schema and LanceDB table")

