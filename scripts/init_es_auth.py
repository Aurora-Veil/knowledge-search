"""One-off setup: create the project's least-privilege Elasticsearch role and user."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# repo root on sys.path, so this runs from any working directory
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from elasticsearch import Elasticsearch

from app.config import ES_PASSWORD, ES_URL, ES_USER

SUPERUSER = "elastic"
ROLE = "knowledge_app_role"
INDEX_PATTERN = "knowledge_*"

# read                 search queries (all that app/ needs)
# view_index_metadata  indices.exists
# create_index         scripts/full_sync.py creates the indices on first run
# write                scripts/full_sync.py bulk indexing
# manage               creating an index with settings/mappings
PRIVILEGES = ["read", "view_index_metadata", "create_index", "write", "manage"]

CHECK_INDEX = "knowledge_authcheck"


def admin_client() -> Elasticsearch:
    password = os.getenv("ES_ELASTIC_PASSWORD", "")
    if not password:
        sys.exit(
            "ES_ELASTIC_PASSWORD is not set: "
            "run `cp .env.example .env` and fill in the superuser password."
        )
    return Elasticsearch(ES_URL, basic_auth=(SUPERUSER, password))


def require_app_credentials() -> None:
    if not ES_USER or not ES_PASSWORD:
        sys.exit(
            "ES_USER / ES_PASSWORD are not set: "
            "run `cp .env.example .env` and fill in the project user's credentials."
        )


def create_role(admin: Elasticsearch) -> None:
    admin.security.put_role(
        name=ROLE,
        description="OIRF knowledge-search: read/write on knowledge_* only",
        indices=[
            {
                "names": [INDEX_PATTERN],
                "privileges": PRIVILEGES,
                "allow_restricted_indices": False,
            }
        ],
    )
    print(f"role   {ROLE}: {PRIVILEGES} on {INDEX_PATTERN}")


def create_user(admin: Elasticsearch) -> None:
    admin.security.put_user(
        username=ES_USER,
        password=ES_PASSWORD,
        roles=[ROLE],
        full_name="OIRF knowledge-search service",
    )
    print(f"user   {ES_USER}: roles={[ROLE]}")


def verify(app: Elasticsearch) -> None:
    """Prove reads, then writes, then clean up the write."""
    for index in ("knowledge_source", "knowledge_evidence", "knowledge_viewpoint"):
        print(f"read   {index}: {app.count(index=index)['count']} docs")

    try:
        app.indices.create(index=CHECK_INDEX)
        app.index(index=CHECK_INDEX, id="probe", document={"probe": True})
        app.indices.refresh(index=CHECK_INDEX)
        hits = app.search(index=CHECK_INDEX, query={"match_all": {}})["hits"]["total"]["value"]
        print(f"write  {CHECK_INDEX}: indexed and read back {hits} doc(s)")
    finally:
        if app.indices.exists(index=CHECK_INDEX):
            app.indices.delete(index=CHECK_INDEX)
            print(f"clean  {CHECK_INDEX}: deleted")


def main() -> None:
    require_app_credentials()
    admin = admin_client()
    try:
        create_role(admin)
        create_user(admin)
    finally:
        admin.close()

    app = Elasticsearch(ES_URL, basic_auth=(ES_USER, ES_PASSWORD))
    try:
        verify(app)
    finally:
        app.close()
    print(f"\nOK: {ES_USER} is ready on {ES_URL} (password in .env)")


if __name__ == "__main__":
    main()
