"""
Tests for GibberLink Revisited — server.py pure functions.

Run with: python3 -m pytest tests/ -v

We extract pure functions from server.py by running specific source blocks
in an isolated namespace. This avoids triggering the venv bootstrap, dotenv
loading, and FastAPI initialization that server.py does at import time.
"""

import re
import os
import textwrap

# ── Load pure functions from server.py ────────────────────────

_SERVER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "server.py",
)


def _extract_block(lines, start_pattern):
    """Find a top-level block starting with the given pattern."""
    result = []
    capturing = False
    indent = None
    for line in lines:
        if not capturing:
            if line.strip().startswith(start_pattern):
                capturing = True
                result.append(line)
                indent = len(line) - len(line.lstrip())
        else:
            stripped = line.strip()
            current_indent = len(line) - len(line.lstrip()) if stripped else 999
            if stripped and current_indent <= indent:
                if any(stripped.startswith(kw) for kw in ("def ", "class ", "async def ")):
                    break
                if current_indent == indent and "=" in stripped and not stripped.startswith("#"):
                    if not stripped.startswith(("if ", "for ", "elif ", "else:", "while ")):
                        break
            result.append(line)
    while result and not result[-1].strip():
        result.pop()
    return "\n".join(result)


def _load_functions():
    with open(_SERVER_PATH) as f:
        lines = [l.rstrip("\n") for l in f.readlines()]

    ns = {"re": re, "_re": re, "__name__": "_test_ns"}

    exec(textwrap.dedent("""
        class LLMError(RuntimeError):
            pass
        class LLMRetryableError(LLMError):
            pass
        class LLMFatalError(LLMError):
            pass
        PHASE_PROBLEM  = "problem"
        PHASE_DEBATE   = "debate"
        PHASE_CONVERGE = "converge"
        PHASE_SOLUTION = "solution"
    """), ns)

    targets = [
        ("def", "_classify_llm_error"),
        ("var", "_GARBAGE_PATTERNS"),
        ("def", "sanitize_response"),
        ("def", "is_response_broken"),
        ("def", "extract_proposals"),
        ("def", "_proposals_are_similar"),
        ("var", "_ROLE_WEIGHTS"),
        ("def", "build_scoreboard"),
    ]

    for kind, name in targets:
        if kind == "def":
            block = _extract_block(lines, f"def {name}(")
        else:
            block = _extract_block(lines, f"{name} =")
            if not block:
                block = _extract_block(lines, f"{name}=")

        if block:
            exec(block, ns)
        else:
            raise RuntimeError(f"Could not extract '{name}' from server.py")

    return ns


_ns = _load_functions()

_classify_llm_error = _ns["_classify_llm_error"]
LLMFatalError = _ns["LLMFatalError"]
LLMRetryableError = _ns["LLMRetryableError"]
sanitize_response = _ns["sanitize_response"]
is_response_broken = _ns["is_response_broken"]
extract_proposals = _ns["extract_proposals"]
_proposals_are_similar = _ns["_proposals_are_similar"]
build_scoreboard = _ns["build_scoreboard"]


# ═══════════════════════════════════════════════════════════════
# _classify_llm_error
# ═══════════════════════════════════════════════════════════════

class TestClassifyLLMError:

    def test_401_is_fatal(self):
        assert isinstance(_classify_llm_error(401, "Unauthorized"), LLMFatalError)

    def test_403_is_fatal(self):
        assert isinstance(_classify_llm_error(403, "Forbidden"), LLMFatalError)

    def test_404_is_fatal(self):
        assert isinstance(_classify_llm_error(404, "Model not found"), LLMFatalError)

    def test_model_not_found_in_body(self):
        assert isinstance(_classify_llm_error(200, "model_not_found: does not exist"), LLMFatalError)

    def test_quota_exhausted(self):
        assert isinstance(_classify_llm_error(402, "Quota exceeded, billing"), LLMFatalError)

    def test_payment_required(self):
        assert isinstance(_classify_llm_error(402, "insufficient credits, payment"), LLMFatalError)

    def test_content_filter(self):
        assert isinstance(_classify_llm_error(400, "content_filter triggered"), LLMFatalError)

    def test_safety_blocked(self):
        assert isinstance(_classify_llm_error(400, "blocked by safety filter"), LLMFatalError)

    def test_moderation(self):
        assert isinstance(_classify_llm_error(400, "Moderation: not allowed"), LLMFatalError)

    def test_authentication_in_body(self):
        assert isinstance(_classify_llm_error(None, "Authentication failed"), LLMFatalError)

    def test_429_is_retryable(self):
        assert isinstance(_classify_llm_error(429, "Too many requests"), LLMRetryableError)

    def test_500_is_retryable(self):
        assert isinstance(_classify_llm_error(500, "Internal server error"), LLMRetryableError)

    def test_502_is_retryable(self):
        assert isinstance(_classify_llm_error(502, "Bad gateway"), LLMRetryableError)

    def test_503_is_retryable(self):
        assert isinstance(_classify_llm_error(503, "Service unavailable"), LLMRetryableError)

    def test_rate_limit_in_body(self):
        assert isinstance(_classify_llm_error(200, "rate_limit exceeded"), LLMRetryableError)

    def test_timeout(self):
        assert isinstance(_classify_llm_error(None, "Request timed out"), LLMRetryableError)

    def test_unknown_defaults_retryable(self):
        assert isinstance(_classify_llm_error(418, "I'm a teapot"), LLMRetryableError)

    def test_none_status_unknown_body(self):
        assert isinstance(_classify_llm_error(None, "Something weird"), LLMRetryableError)

    def test_empty_body_500(self):
        assert isinstance(_classify_llm_error(500, ""), LLMRetryableError)


# ═══════════════════════════════════════════════════════════════
# sanitize_response
# ═══════════════════════════════════════════════════════════════

class TestSanitizeResponse:

    def test_normal_unchanged(self):
        text = "I think we should consider the infrastructure costs carefully."
        assert sanitize_response(text, "Voss", ["Lyra", "Kael"]) == text

    def test_empty_returns_empty(self):
        assert sanitize_response("", "Voss", []) == ""

    def test_none_returns_empty(self):
        assert sanitize_response(None, "Voss", []) == ""

    def test_strips_safe_unsafe(self):
        result = sanitize_response("safe\nWe should proceed.\nunsafe", "Voss", [])
        assert "We should proceed" in result
        for line in result.split("\n"):
            assert line.strip().lower() not in ("safe", "unsafe")

    def test_strips_classifier_labels(self):
        result = sanitize_response("S1assistant\nThis is a good idea.", "Voss", [])
        assert "S1" not in result
        assert "good idea" in result

    def test_strips_other_agent_dialogue(self):
        result = sanitize_response(
            "I agree.\nLyra: I think we should pivot.\nKael: No way.",
            "Voss", ["Lyra", "Kael"]
        )
        assert "Lyra:" not in result
        assert "Kael:" not in result
        assert "I agree" in result

    def test_strips_html_only_lines(self):
        result = sanitize_response("<div>\nGood point.\n</div>", "Voss", [])
        assert "<div>" not in result
        assert "Good point" in result

    def test_strips_scan_phase_labels(self):
        result = sanitize_response("SCAN: processing\nLet me think.", "Voss", [])
        assert "SCAN" not in result
        assert "think" in result

    def test_truncates_long_responses(self):
        text = "This is a sentence. " * 100
        result = sanitize_response(text, "Voss", [])
        assert len(result) <= 801

    def test_all_garbage_returns_empty(self):
        assert sanitize_response("safe\nunsafe\nS1\n", "Voss", []) == ""

    def test_allows_proposal_prefix(self):
        text = "Proposal: we should implement this for better outcomes in the long run."
        assert "Proposal" in sanitize_response(text, "Voss", [])


# ═══════════════════════════════════════════════════════════════
# is_response_broken
# ═══════════════════════════════════════════════════════════════

class TestIsResponseBroken:

    def test_normal_not_broken(self):
        assert is_response_broken("I think we should proceed with caution.", "Voss") is False

    def test_empty_is_broken(self):
        assert is_response_broken("", "Voss") is True

    def test_none_is_broken(self):
        assert is_response_broken(None, "Voss") is True

    def test_whitespace_only(self):
        assert is_response_broken("   ", "Voss") is True

    def test_too_short(self):
        assert is_response_broken("Hi", "Voss") is True

    def test_html_tags(self):
        assert is_response_broken("<div>Hello</div>", "Voss") is True

    def test_leaked_inst_tokens(self):
        assert is_response_broken("[INST] You are helpful [/INST]", "Voss") is True

    def test_leaked_sys_tokens(self):
        assert is_response_broken("<<SYS>> system prompt", "Voss") is True

    def test_repeated_safe(self):
        assert is_response_broken("safe\nsafe\nsafe\n", "Voss") is True

    def test_many_short_lines(self):
        assert is_response_broken("\n".join(["word"] * 15), "Voss") is True

    def test_multi_speaker_hallucination(self):
        assert is_response_broken("Alice: hi\nBob: hello\nCarol: hey\nDave: sup", "Voss") is True

    def test_two_speakers_ok(self):
        assert is_response_broken("Alice: hi\nBob: hello\nI think so too.", "Voss") is False

    def test_meta_narration(self):
        assert is_response_broken("Phase 3 will now begin with stimulus.", "Voss") is True


# ═══════════════════════════════════════════════════════════════
# extract_proposals
# ═══════════════════════════════════════════════════════════════

class TestExtractProposals:

    def test_explicit_proposal(self):
        text = "Thinking.\nPROPOSAL: Use a staged rollout with weekly checkpoints and feedback loops."
        props = extract_proposals(text)
        assert len(props) == 1
        assert "staged rollout" in props[0]

    def test_multiple_proposals(self):
        text = "PROPOSAL: First approach with gradual step by step migration.\nTalk.\nPROPOSAL: Second approach with parallel running systems simultaneously."
        assert len(extract_proposals(text)) == 2

    def test_case_insensitive(self):
        assert len(extract_proposals("proposal: Implement continuous feedback mechanisms for all stakeholders involved.")) == 1

    def test_short_ignored(self):
        assert len(extract_proposals("PROPOSAL: Do it.")) == 0

    def test_no_proposal(self):
        assert len(extract_proposals("I think we need more data before deciding.")) == 0

    def test_fallback_i_propose(self):
        assert len(extract_proposals("I propose that we implement a tiered system with gradual onboarding and mentorship.")) == 1

    def test_fallback_i_suggest(self):
        assert len(extract_proposals("I suggest we adopt a hybrid approach combining remote and in-person collaboration.")) == 1

    def test_fallback_we_should_adopt(self):
        assert len(extract_proposals("We should adopt a framework that balances innovation with risk management at every level.")) == 1

    def test_explicit_takes_priority(self):
        text = "I propose something.\nPROPOSAL: Use a concrete mechanism with specific implementation details and timelines."
        props = extract_proposals(text)
        assert len(props) == 1
        assert "concrete mechanism" in props[0]


# ═══════════════════════════════════════════════════════════════
# _proposals_are_similar
# ═══════════════════════════════════════════════════════════════

class TestProposalsAreSimilar:

    def test_identical(self):
        assert _proposals_are_similar("use staged rollout", "use staged rollout") is True

    def test_high_overlap(self):
        assert _proposals_are_similar(
            "implement staged rollout with weekly checkpoints",
            "implement staged rollout with daily checkpoints"
        ) is True

    def test_different(self):
        assert _proposals_are_similar(
            "use AI to automate the process end to end",
            "hire more people to handle the workload increase"
        ) is False

    def test_empty(self):
        assert _proposals_are_similar("", "something") is False
        assert _proposals_are_similar("something", "") is False


# ═══════════════════════════════════════════════════════════════
# build_scoreboard
# ═══════════════════════════════════════════════════════════════

class TestBuildScoreboard:

    def _agents(self):
        return [
            {"id": "agent_a", "role": "strategist"},
            {"id": "agent_b", "role": "creative"},
            {"id": "agent_c", "role": "skeptic"},
            {"id": "agent_d", "role": "synthesizer"},
            {"id": "chairman", "role": "chairman"},
        ]

    def _rec(self, text="Test", votes=None, **kw):
        d = {"text": text, "author": kw.get("author", "Voss"),
             "author_id": kw.get("author_id", "agent_a"),
             "turn": kw.get("turn", 1), "votes": votes or {}, "reasons": kw.get("reasons", {})}
        return d

    def test_empty(self):
        assert build_scoreboard([], self._agents()) == []

    def test_all_agree(self):
        r = self._rec(votes={"agent_b": "agree", "agent_c": "agree", "agent_d": "agree", "chairman": "agree"})
        result = build_scoreboard([r], self._agents())
        assert result[0]["vote_counts"]["agree"] == 4
        assert result[0]["score"] > 0
        assert result[0]["chairman_vetoed"] is False

    def test_chairman_veto(self):
        r_veto = self._rec(votes={"agent_b": "agree", "agent_c": "agree", "chairman": "disagree"})
        r_ok = self._rec(votes={"agent_b": "agree", "agent_c": "agree", "chairman": "agree"})
        s_veto = build_scoreboard([r_veto], self._agents())[0]
        s_ok = build_scoreboard([r_ok], self._agents())[0]
        assert s_veto["chairman_vetoed"] is True
        assert s_veto["score"] < s_ok["score"]

    def test_sorted_descending(self):
        weak = self._rec(text="Weak", votes={"agent_a": "disagree", "chairman": "disagree"})
        strong = self._rec(text="Strong", votes={"agent_b": "agree", "agent_c": "agree", "chairman": "agree"})
        result = build_scoreboard([weak, strong], self._agents())
        assert result[0]["text"] == "Strong"

    def test_skeptic_weighs_more(self):
        r_sk = self._rec(votes={"agent_c": "agree"})
        r_cr = self._rec(votes={"agent_b": "agree"})
        assert build_scoreboard([r_sk], self._agents())[0]["score"] > build_scoreboard([r_cr], self._agents())[0]["score"]

    def test_amend_less_than_agree(self):
        r_ag = self._rec(votes={"agent_b": "agree"})
        r_am = self._rec(votes={"agent_b": "amend"})
        assert build_scoreboard([r_ag], self._agents())[0]["score"] > build_scoreboard([r_am], self._agents())[0]["score"]

    def test_preserves_fields(self):
        r = self._rec(text="My proposal", author="Kael", author_id="agent_c", turn=7,
                      votes={"agent_a": "agree"}, reasons={"agent_a": "Sounds good"})
        result = build_scoreboard([r], self._agents())[0]
        assert result["text"] == "My proposal"
        assert result["author"] == "Kael"
        assert result["turn"] == 7
        assert result["reasons"] == {"agent_a": "Sounds good"}
