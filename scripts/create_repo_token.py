from __future__ import annotations

import argparse

from app.config import get_settings
from app.db import SessionLocal
from app.models import Repository
from app.security import generate_upload_token, hash_upload_token


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or rotate a repository upload token.")
    parser.add_argument("repository", help="Repository full name, for example owner/repo")
    parser.add_argument("--default-branch", default="main")
    args = parser.parse_args()

    owner, name = args.repository.split("/", 1)
    settings = get_settings()
    token = generate_upload_token()
    with SessionLocal() as session:
        repository = (
            session.query(Repository)
            .filter(Repository.owner == owner, Repository.name == name)
            .one_or_none()
        )
        if repository is None:
            repository = Repository(
                owner=owner,
                name=name,
                full_name=args.repository,
                default_branch=args.default_branch,
                private=False,
            )
            session.add(repository)
        repository.upload_token_hash = hash_upload_token(token, settings.upload_token_pepper)
        session.commit()
    print(token)


if __name__ == "__main__":
    main()
