"""CLI script to create users.

Usage (from project root):
    python -m backend.create_user <username> [--admin]
"""

import argparse
import getpass
import sys
from pathlib import Path

from backend.auth import UserManager

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
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("Error: Passwords do not match")
        sys.exit(1)

    if len(password) < 4:
        print("Error: Password must be at least 4 characters")
        sys.exit(1)

    data_dir = str(PROJECT_ROOT / "data")
    um = UserManager(data_dir=data_dir)

    try:
        user = um.create_user(args.username, password, is_admin=args.admin)
        role = " (admin)" if user.is_admin else ""
        print(f"User '{user.username}' created successfully{role}")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
