"""Operator-only recovery; run while the panel container is stopped."""

import argparse
import os
from pathlib import Path
import secrets

from .state import Store


def reset_admin(directory):
    store = Store(directory)
    with store.lock:
        store.data.update(
            username=None,
            password_hash=None,
            auth_version=store.data["auth_version"] + 1,
            secret=secrets.token_hex(32),
        )
        store.save()
    print("Administrator login reset. Connections and library locations were kept.")
    print("Open the panel to choose a new administrator username and password.")


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
