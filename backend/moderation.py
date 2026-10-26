"""
Content Moderation and Profanity Filtering Module.
Maintains a blocklist of inappropriate terms and provides censoring functionality.
"""

# Common prohibited words list (aap isme aur words add kar sakti hain)
BAD_WORDS = ["badword1", "badword2", "spam", "abuse", "hate"]

def sanitize_message(text: str) -> tuple[str, bool]:
    """
    Checks if a message contains bad words.
    Returns a tuple: (censored_text, contains_profanity)
    """
    words = text.split()
    censored = False
    cleaned_words = []

    for word in words:
        clean_word = word.strip(".,!?\"'").lower()
        if clean_word in BAD_WORDS:
            # Replace bad word with asterisks (*) keeping the length same
            cleaned_words.append("*" * len(word))
            censored = True
        else:
            cleaned_words.append(word)

    return " ".join(cleaned_words), censored