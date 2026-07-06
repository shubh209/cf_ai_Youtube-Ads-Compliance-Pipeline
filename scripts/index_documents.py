from src.db.session import SessionLocal
from src.services.policy_indexing import run_policy_index


def index_docs():
    db = SessionLocal()
    try:
        result = run_policy_index(db)
        print(f"Indexing complete: {result}")
    finally:
        db.close()


if __name__ == "__main__":
    index_docs()
