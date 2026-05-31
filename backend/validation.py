"""Shared input-validation helpers used by the API and the CLI."""

MIN_PASSWORD_LENGTH = 8


def validate_password(password: str) -> None:
    """Raise ``ValueError`` with a German message if the password is too weak.

    Policy is deliberately pragmatic: at least ``MIN_PASSWORD_LENGTH``
    characters, with at least one letter and one digit.  This rejects trivial
    passwords like ``"aaaaaaaa"`` or ``"12345678"`` without forcing awkward
    special-character rules.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein.")
    if not any(c.isalpha() for c in password):
        raise ValueError("Passwort muss mindestens einen Buchstaben enthalten.")
    if not any(c.isdigit() for c in password):
        raise ValueError("Passwort muss mindestens eine Ziffer enthalten.")
