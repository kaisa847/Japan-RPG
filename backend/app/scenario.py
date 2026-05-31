"""Helpers for resolving the player's narrative scenario."""


def parse_scenario(scenario_text: str, player_name: str) -> tuple[str, str]:
    """Split scenario into (premise, start_prompt) and substitute player_name.

    If the text contains a 'SPIELSTART:' marker, everything before it becomes
    the premise (PRÄMISSE) and everything after becomes the start prompt.
    Otherwise the full text is used for both.
    """
    text = scenario_text.replace("{player_name}", player_name)
    marker = "SPIELSTART:"
    idx = text.find(marker)
    if idx >= 0:
        premise = text[:idx].strip()
        start = text[idx + len(marker) :].strip()
        start_prompt = f"(SPIELSTART – Regieanweisung, NICHT als Dialog anzeigen:\n{start})"
    else:
        premise = text.strip()
        start_prompt = f"(SPIELSTART – Regieanweisung, NICHT als Dialog anzeigen:\n{premise})"
    return premise, start_prompt
