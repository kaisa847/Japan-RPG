"""CLI script to create users.

Usage (from project root):
    python -m backend.create_user <username> [--admin]
"""

import argparse
import getpass
import sys
from pathlib import Path

from backend.auth import UserManager
from backend.validation import validate_password

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(
        description="Create a user for Japan RPG"
    )
    parser.add_argument(
        "username",
        help="Username (3-20 chars, alphanumeric + underscore)",
    )
    parser.add_argument(
        "--admin", action="store_true", help="Grant admin privileges"
    )
    parser.add_argument(
        "--player-name",
        help="In-game player name (required, or will be prompted)",
    )
    args = parser.parse_args()

    player_name = args.player_name
    if not player_name:
        player_name = input("Spielername (Pflicht): ").strip()
    if not player_name:
        print("Error: Spielername darf nicht leer sein")
        sys.exit(1)
    if len(player_name) > 30:
        print("Error: Spielername darf maximal 30 Zeichen lang sein")
        sys.exit(1)

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("Error: Passwords do not match")
        sys.exit(1)

    try:
        validate_password(password)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    data_dir = str(PROJECT_ROOT / "data")
    um = UserManager(data_dir=data_dir)

    try:
        user = um.create_user(
            args.username, password, is_admin=args.admin,
            player_name=player_name,
        )
        role = " (admin)" if user.is_admin else ""
        print(f"User '{user.username}' created successfully{role}")
        print(f"Spielername: {user.player_name}")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
