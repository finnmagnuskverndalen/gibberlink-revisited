"""
GibberLink Revisited — Response Sanitization

Clean up raw LLM responses: strip garbage patterns (leaked tokens,
classifier labels, HTML), remove hallucinated dialogue from other
agents, and detect broken/garbage responses.
"""

import re


# ── Garbage detection patterns ──────────────────────────────

_GARBAGE_PATTERNS = [
    re.compile(r'S\d+assistant', re.IGNORECASE),        # leaked classifier labels
    re.compile(r'^(safe|unsafe)\s*$', re.MULTILINE),     # safety labels
    re.compile(r'(safe\n){3,}', re.IGNORECASE),          # repeated safe/unsafe
    re.compile(r'(unsafe\n){2,}', re.IGNORECASE),
    re.compile(r'</?[a-z]+>'),                            # HTML tags
    re.compile(r'\[INST\]|\[/INST\]|<<SYS>>|<\|im_'),   # leaked prompt tokens
    re.compile(r'(Phase|Stimulus|Cycle).*will now', re.IGNORECASE),  # meta-narration
]


def sanitize_response(text: str, agent_name: str, other_names: list[str]) -> str:
    """Clean up a raw LLM response, stripping common garbage patterns."""
    if not text:
        return ""

    lines = text.split("\n")
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        # Skip empty lines, pure classifier labels, leaked tokens
        if not stripped:
            continue
        if stripped.lower() in ("safe", "unsafe"):
            continue
        if re.match(r'^S\d+\w*$', stripped, re.IGNORECASE):
            continue
        # Skip lines that look like internal labels
        if re.match(r'^(SCAN|PHASE|STIMULUS|CYCLE|FOCUS)\b', stripped, re.IGNORECASE):
            continue
        # Skip lines where the agent writes dialogue for OTHER agents
        is_other_dialogue = False
        for other in other_names:
            if re.match(rf'^{re.escape(other)}\s*:', stripped):
                is_other_dialogue = True
                break
        # Catch any "Name:" pattern that isn't the current agent
        if not is_other_dialogue:
            speaker_match = re.match(r'^([A-Z][a-z]+)\s*:', stripped)
            if speaker_match:
                speaker = speaker_match.group(1)
                if speaker != agent_name and speaker.lower() not in ('proposal', 'note', 'example'):
                    is_other_dialogue = True
        if is_other_dialogue:
            continue
        # Skip HTML tags
        if re.match(r'^<[^>]+>$', stripped):
            continue
        clean_lines.append(line)

    result = "\n".join(clean_lines).strip()

    # If sanitization removed everything, return a minimal fallback
    if not result or len(result) < 5:
        return ""

    # Truncate excessively long responses (should be 1-3 sentences)
    if len(result) > 800:
        for i in range(min(800, len(result)), 200, -1):
            if result[i] in '.!?':
                result = result[:i+1]
                break
        else:
            result = result[:800]

    return result


def is_response_broken(text: str, agent_name: str) -> bool:
    """Check if a response looks like garbage from a misbehaving model."""
    if not text or len(text.strip()) < 5:
        return True

    # Check for known garbage patterns
    for pattern in _GARBAGE_PATTERNS:
        if pattern.search(text):
            return True

    # Too many newlines relative to content (repetitive single-word lines)
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) > 8:
        avg_len = sum(len(l) for l in lines) / len(lines)
        if avg_len < 10:
            return True

    # Response contains the agent speaking as multiple characters
    colon_speakers = re.findall(r'^([A-Z][a-z]+):', text, re.MULTILINE)
    unique_speakers = set(colon_speakers)
    if len(unique_speakers) >= 3:
        return True

    return False
