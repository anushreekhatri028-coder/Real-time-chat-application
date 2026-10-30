"""
Content Moderation and Profanity Filtering Module for NexusChat.
Maintains a blocklist of inappropriate terms, performs robust censoring,
and preserves original message structure and punctuation.
"""

import re

# Comprehensive list of inappropriate, abusive, and spam terms
BAD_WORDS = {
    "badword1", "badword2", "spam", "abuse", "hate",
    "idiot", "stupid", "moron", "scam", "phishing",
    "offensive1", "harass", "threat", "violence",
    "asshole", "bitch", "bastard", "damn", "crap",
    "shit", "fuck", "dick", "pussy", "slut", "whore"
}

# Compile a regex pattern that matches bad words with word boundaries, case-insensitive
_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(word) for word in sorted(BAD_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE
)


def sanitize_message(text: str) -> tuple[str, bool]:
    """
    Checks if a message contains prohibited words.
    Replaces prohibited words with asterisks (*) matching the length of the matched word,
    preserving case of surrounding text and punctuation.

    Returns:
        tuple[str, bool]: (censored_text, contains_profanity)
    """
    if not isinstance(text, str) or not text:
        return "", False

    censored = False

    def replace_match(match):
        nonlocal censored
        censored = True
        word = match.group(0)
        return "*" * len(word)

    censored_text = _PATTERN.sub(replace_match, text)
    return censored_text, censored
