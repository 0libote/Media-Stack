"""Operator-only recovery; run while the panel container is stopped."""

import argparse
import hashlib
import os
from pathlib import Path
import secrets

from .state import Store


def reset_admin(directory):
    store = Store(directory)
    token = secrets.token_urlsafe(24)
    with store.lock:
        store.data.update(
            password_hash=None,
            claim_hash=hashlib.sha256(token.encode()).hexdigest(),
            auth_version=store.data["auth_version"] + 1,
            secret=secrets.token_hex(32),
        )
        store.save()
        path = store.directory / "setup-code"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(token + "\n")
    print("Administrator login reset. Connections and library locations were kept.")
    print(
        "Read the new one-time code from config/portal/setup-code on the host after starting the panel."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["reset-admin"])
    args = parser.parse_args()
    if args.command == "reset-admin":
        reset_admin(
            os.environ.get(
                "PANEL_STATE_DIR",
                str(Path(__file__).resolve().parents[1] / "config/portal"),
            )
        )


if __name__ == "__main__":
    main()
