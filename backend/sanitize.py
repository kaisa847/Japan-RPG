"""Sanitization helpers for user-controlled text that flows into the LLM prompt.

The system prompt embeds player-controlled fields (player name, custom scenario)
via ``str.format``.  ``str.format`` itself is safe — the values are not
re-evaluated — but a user could still try to inject *instructions* or fake the
XML schema the model is told to produce (``<scene>``, ``<analysis>`` …) to
manipulate scene generation.  ``neutralize_prompt_text`` strips control
characters and defuses tag-/marker-like structures so injected text can no
longer masquerade as part of the prompt template or the response schema.
"""

import re

# C0/C1 control characters except the whitespace we want to keep (\t \n).
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Tag-like tokens that mimic the prompt's own XML schema, e.g. "<scene>",
# "</analysis>", "<dialog_jp>".  We neutralize the angle brackets so the text
# can no longer be read as markup, while keeping the inner words readable.
_PSEUDO_TAG = re.compile(r"<\s*/?\s*([a-zA-Z_][\w-]*)\s*>")

# Structural markers used by the scenario parser / prompt headings that a user
# could abuse to inject their own premise or stage directions.
_INJECTED_MARKERS = re.compile(
    r"(?im)^\s*(SPIELSTART|PR[ÄA]MISSE|SYSTEM|ASSISTANT|USER)\s*:",
)


def neutralize_prompt_text(
    text: str,
    max_length: int = 5000,
    neutralize_markers: bool = True,
) -> str:
    """Defuse prompt-injection vectors in user-supplied text.

    - Drops control characters (keeps ``\\t`` and ``\\n``).
    - Rewrites schema-like ``<tag>`` tokens to a harmless ``(tag)`` form.
    - Caps the length as a final guard.

    When ``neutralize_markers`` is true, line-leading structural markers
    (SPIELSTART:, SYSTEM:, …) are also defused.  This must stay ``False`` for
    the custom scenario, where ``SPIELSTART:`` is a legitimate, intentional
    separator parsed by ``_parse_scenario``; it should be ``True`` for short
    free-text fields such as the player name.

    The result stays human-readable so a legitimate name or scenario survives,
    but it can no longer impersonate the prompt template or response schema.
    """
    if not text:
        return ""

    text = _CONTROL_CHARS.sub("", text)
    text = _PSEUDO_TAG.sub(r"(\1)", text)
    if neutralize_markers:
        text = _INJECTED_MARKERS.sub(lambda m: m.group(0).replace(":", " -"), text)

    if len(text) > max_length:
        text = text[:max_length]

    return text.strip()
