"""GitHub-compatible heading slugifier for MkDocs.

Python port of github-slugger (the library GitHub's own markdown pipeline
behaves like). The PyPI `github-slugger` package is unusable on Python 3.13
(its generated source contains a lone surrogate and fails to import), so the
algorithm is reimplemented here.

The algorithm is deliberately simple:

    1. lowercase
    2. delete every character that is not a letter, mark, digit, space,
       hyphen or underscore
    3. replace each remaining space with a hyphen -- WITHOUT collapsing runs

Step 3 is the part every other slugifier gets differently, and it is why
these docs' anchors look the way they do:

    "Dusk and away rules -- per window"  ->  dusk-and-away-rules--per-window
    "[warning emoji] Nightlight script ID desync" ->  -nightlight-script-id-desync

Collapsing the runs (what pymdownx/docsify/mkdocs-default all do) silently
breaks every one of those links.
"""

import unicodedata

# Categories GitHub keeps: letters, combining marks, decimal/letter numbers.
# Note "No" (superscripts, fractions) is NOT kept -- GitHub strips those.
_KEEP_CATEGORIES = frozenset(
    ("Ll", "Lu", "Lt", "Lm", "Lo", "Mn", "Mc", "Me", "Nd", "Nl")
)

# Kept verbatim despite being punctuation/separator.
_KEEP_CHARS = frozenset(" -_")


def _keep(ch: str) -> bool:
    # Variation selectors (VS1-VS16) are category Mn, but they are invisible
    # modifiers on emoji and GitHub drops them. Same for format characters
    # such as ZWJ, used to join emoji sequences.
    if 0xFE00 <= ord(ch) <= 0xFE0F:
        return False
    if ch in _KEEP_CHARS:
        return True
    category = unicodedata.category(ch)
    if category == "Cf":
        return False
    return category in _KEEP_CATEGORIES


def slugify(text: str, separator: str = "-") -> str:
    """Slugify heading text the way GitHub does.

    `separator` is accepted because MkDocs' toc extension passes it
    positionally; GitHub always uses "-", but honour it anyway.
    """
    lowered = text.lower()
    stripped = "".join(ch for ch in lowered if _keep(ch))
    return stripped.replace(" ", separator)
