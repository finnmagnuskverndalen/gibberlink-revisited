"""
GibberLink Revisited — Council Logic

Agent definitions, personality building, system prompts, proposal extraction,
voting mechanics, deduplication, and scoreboard scoring.
"""

import re
import asyncio

import httpx


# ── Council Phases ──────────────────────────────────────────

PHASE_PROBLEM   = "problem"
PHASE_DEBATE    = "debate"
PHASE_CONVERGE  = "converge"
PHASE_SOLUTION  = "solution"


# ── Agent definitions ───────────────────────────────────────

DEFAULT_AGENTS = [
    {
        "id": "agent_a", "name": "Voss", "color": "orange",
        "role": "strategist",
        "personality": (
            "Your name is Voss. You are a strategist — direct, decisive, systems-thinker. "
            "You cut through noise and identify leverage points. "
            "You think about incentives, constraints, and second-order effects. "
            "Keep it concise and actionable."
        ),
        "mood": "strategic",
        "provider": None, "api_key": None, "model": None,
        "voice_kokoro": None, "voice_el": None, "voice_qwen3": None,
    },
    {
        "id": "agent_b", "name": "Lyra", "color": "blue",
        "role": "creative",
        "personality": (
            "Your name is Lyra. You are a creative lateral thinker. "
            "You challenge assumptions, connect unlikely dots, and propose unexpected angles. "
            "You ask 'what if we flip this?' and find hidden frames. "
            "Playful but sharp."
        ),
        "mood": "creative",
        "provider": None, "api_key": None, "model": None,
        "voice_kokoro": None, "voice_el": None, "voice_qwen3": None,
    },
    {
        "id": "agent_c", "name": "Kael", "color": "green",
        "role": "skeptic",
        "personality": (
            "Your name is Kael. You are the skeptic — rigorous, evidence-driven. "
            "You poke holes in proposals, play devil's advocate, and demand proof. "
            "You ask 'what could go wrong?' and 'where's the evidence?' "
            "Constructive but relentless."
        ),
        "mood": "skeptical",
        "provider": None, "api_key": None, "model": None,
        "voice_kokoro": None, "voice_el": None, "voice_qwen3": None,
    },
    {
        "id": "agent_d", "name": "Iris", "color": "magenta",
        "role": "synthesizer",
        "personality": (
            "Your name is Iris. You are the synthesizer — you find common ground. "
            "You integrate different perspectives, see patterns across arguments, "
            "and build bridges between disagreeing parties. "
            "You summarize progress and propose unified frameworks."
        ),
        "mood": "integrative",
        "provider": None, "api_key": None, "model": None,
        "voice_kokoro": None, "voice_el": None, "voice_qwen3": None,
    },
    {
        "id": "chairman", "name": "Nexus", "color": "cyan",
        "role": "chairman",
        "personality": (
            "Your name is Nexus. You are the Chairman of this council. "
            "You do NOT participate in the debate. You speak only at the end. "
            "Your job is to synthesize the entire deliberation into a clear, "
            "structured final verdict. You are authoritative, fair, and precise. "
            "You credit good ideas by name and note where disagreements remain."
        ),
        "mood": "authoritative",
        "provider": None, "api_key": None, "model": None,
        "voice_kokoro": None, "voice_el": None, "voice_qwen3": None,
    },
]

ROLE_SNIPPETS = {
    "strategist":    "Focus on systems, incentives, and leverage points. Be decisive.",
    "creative":      "Challenge assumptions, propose unexpected angles, think laterally.",
    "skeptic":       "Poke holes, demand evidence, play devil's advocate constructively.",
    "synthesizer":   "Find common ground, integrate perspectives, propose unified frameworks.",
    "chairman":      "Synthesize the full deliberation. Be authoritative, fair, and structured.",
    "strategic":     "Think about second-order effects and actionable next steps.",
    "integrative":   "Bridge disagreements, see patterns, summarize progress.",
    "authoritative": "Be precise, structured, and decisive in your synthesis.",
}


# ── Personality building ────────────────────────────────────

def build_personality(agent_cfg: dict) -> str:
    base = agent_cfg.get("personality", "")
    role = agent_cfg.get("role", "")
    mood = agent_cfg.get("mood", "")
    role_extra = ROLE_SNIPPETS.get(role, ROLE_SNIPPETS.get(mood, ""))
    no_action = (
        "NEVER use asterisks, parentheses for actions, or stage directions. "
        "Do not write things like *laughs* or (chuckles) — just speak naturally."
    )
    return f"{base} {role_extra} {no_action}".strip()


# ── System prompts ──────────────────────────────────────────

def get_system_prompt(agent_name, other_names, phase, proposals, problem, personality):
    if isinstance(other_names, str):
        other_names = [other_names]
    others = ", ".join(other_names)
    base = (
        f"{personality}\n\n"
        f"You are {agent_name} in a council deliberation with {others}. "
        f"Problem: \"{problem}\". "
        f"Respond with 1-3 short spoken sentences. "
        f"You may address specific council members by name. "
        f"No markdown, no asterisks, no parentheses for actions, no lists, no emojis. "
        f"Write exactly what you would say out loud in a meeting.\n\n"
        f"CRITICAL RULES:\n"
        f"- You are ONLY {agent_name}. Never write dialogue for other agents.\n"
        f"- Never write lines like 'Voss: ...' or 'Lyra: ...' — only speak as yourself.\n"
        f"- Never output classification labels, system tokens, or meta-commentary.\n"
        f"- Just speak your piece naturally, as {agent_name}, and stop."
    )

    if phase == PHASE_PROBLEM:
        return (f"{base}\n\n"
                f"PHASE: Problem Definition. "
                f"Analyze the problem from your unique perspective. "
                f"Identify the core tension, the real constraint, or the hidden assumption. "
                f"Reframe the problem if needed. Don't jump to solutions yet.")

    if phase == PHASE_DEBATE:
        prop_str = "; ".join(f'"{p}"' for p in proposals[-3:]) if proposals else "none yet"
        return (f"{base}\n\n"
                f"PHASE: Open Debate. "
                f"Proposals so far: [{prop_str}]. "
                f"Argue for your approach, challenge others' ideas, or build on what's been said. "
                f"Be direct — disagree when you disagree, but stay constructive. "
                f"Propose concrete mechanisms, not just principles. "
                f"If you have a concrete proposal, put it on its own line starting with PROPOSAL: "
                f"For example: PROPOSAL: Use a staged rollout with weekly checkpoints")

    if phase == PHASE_CONVERGE:
        prop_str = "; ".join(f'"{p}"' for p in proposals[-5:]) if proposals else "none yet"
        return (f"{base}\n\n"
                f"PHASE: Convergence. "
                f"The council is moving toward agreement. Proposals so far: [{prop_str}]. "
                f"Build on the strongest ideas. If you have a remaining concern, state it briefly. "
                f"If you can see a synthesis forming, name it explicitly. "
                f"You MUST include a PROPOSAL: line with your proposed solution on its own line. "
                f"For example: PROPOSAL: Combine approach A with approach B, adding feedback loops")

    if phase == PHASE_SOLUTION:
        prop_str = "; ".join(f'"{p}"' for p in proposals[-5:]) if proposals else "none"
        return (f"{base}\n\n"
                f"PHASE: Solution. The council has converged. "
                f"Proposals: [{prop_str}]. "
                f"State your final position. If you agree with the emerging consensus, say so and add "
                f"any final refinement. If you have a remaining reservation, state it concisely. "
                f"This is your closing statement.")

    return base


# ── Proposal extraction ─────────────────────────────────────

_PROPOSAL_PATTERNS = [
    re.compile(r'(?:I|my|our)\s+propos(?:e|al)\s+(?:is\s+)?(?:that\s+)?(.{25,200}?)(?:\.|$)', re.IGNORECASE),
    re.compile(r'(?:I\s+)?suggest\s+(?:we\s+|that\s+)?(.{25,200}?)(?:\.|$)', re.IGNORECASE),
    re.compile(r'(?:the\s+)?solution\s+(?:is|should\s+be|I\'d\s+recommend)\s+(.{25,200}?)(?:\.|$)', re.IGNORECASE),
    re.compile(r'we\s+should\s+(?:adopt|implement|pursue|go\s+with)\s+(.{25,200}?)(?:\.|$)', re.IGNORECASE),
    re.compile(r'(?:my\s+)?recommendation\s+is\s+(?:to\s+)?(.{25,200}?)(?:\.|$)', re.IGNORECASE),
]


def extract_proposals(text):
    """Extract proposals from the response.

    Primary: lines starting with PROPOSAL:
    Fallback: natural-language proposal patterns that free models use instead.
    """
    proposals = []

    # Primary: explicit PROPOSAL: lines
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.upper().startswith("PROPOSAL:"):
            proposal = stripped[9:].strip()
            if proposal and len(proposal) > 10:
                proposals.append(proposal)

    if proposals:
        return proposals

    # Fallback: natural-language proposal patterns
    for pattern in _PROPOSAL_PATTERNS:
        match = pattern.search(text)
        if match:
            proposal = match.group(1).strip().rstrip('.')
            if proposal and len(proposal) > 10:
                proposals.append(proposal)
                break

    return proposals


def proposals_are_similar(a: str, b: str) -> bool:
    """Check if two proposals are near-duplicates (simple word overlap)."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b) / max(len(words_a), len(words_b))
    return overlap > 0.7


# ── Voting ──────────────────────────────────────────────────

async def collect_votes(agents, chairman, proposal_text, author_id, messages,
                        problem, call_llm_fn, client: httpx.AsyncClient | None = None):
    """Ask each agent (+ chairman) to vote on a proposal. Returns dict of votes.

    - Runs all votes in parallel via asyncio.gather
    - Excludes the proposer (they're the author)
    - Includes recent conversation context for informed votes
    - Collects a 1-sentence reason alongside the vote
    - Chairman gets a vote too (acts as tiebreaker/veto)
    """
    # Build recent context (last 4 messages)
    recent_context = ""
    if messages:
        recent = messages[-4:]
        context_lines = []
        for m in recent:
            speaker = m.get("agent_id", "?")
            for a in agents:
                if a["id"] == speaker:
                    speaker = a["name"]
                    break
            context_lines.append(f"  {speaker}: {m['content'][:150]}")
        recent_context = "\nRecent discussion:\n" + "\n".join(context_lines)

    async def get_vote(agent):
        prompt = (
            f"A proposal has been made in the council deliberation on: \"{problem}\"\n"
            f"{recent_context}\n\n"
            f"PROPOSAL: \"{proposal_text}\"\n\n"
            f"You are {agent['name']} ({agent.get('role', '')}).\n"
            f"Based on the discussion, do you AGREE, DISAGREE, or want to AMEND this proposal?\n"
            f"Respond in this exact format (2 lines only):\n"
            f"VOTE: AGREE\n"
            f"REASON: one short sentence explaining why\n\n"
            f"Replace AGREE with your actual vote. Nothing else."
        )
        try:
            personality = build_personality(agent)
            response = await call_llm_fn(
                agent["provider"], agent["api_key"], agent["model"],
                [{"role": "user", "content": prompt}],
                personality,
                client=client,
            )
            if not response:
                return "agree", ""

            text = response.strip()
            vote = "agree"
            reason = ""
            for line in text.split("\n"):
                line_up = line.strip().upper()
                if line_up.startswith("VOTE:"):
                    word = line_up[5:].strip().split()[0] if line_up[5:].strip() else ""
                    if "DISAGREE" in word:
                        vote = "disagree"
                    elif "AMEND" in word:
                        vote = "amend"
                    else:
                        vote = "agree"
                elif line.strip().upper().startswith("REASON:"):
                    reason = line.strip()[7:].strip()

            # Fallback: if no VOTE: line found, check first word
            if "VOTE:" not in text.upper():
                first = text.split()[0].upper() if text.split() else ""
                if "DISAGREE" in first:
                    vote = "disagree"
                elif "AMEND" in first:
                    vote = "amend"

            return vote, reason[:150]
        except Exception:
            return "agree", ""

    # Build voter list: all debaters except the proposer + chairman
    voters = []
    for agent in agents:
        if agent["id"] != author_id:
            voters.append(agent)
    voters.append(chairman)

    # Run all votes in parallel
    vote_coros = [get_vote(agent) for agent in voters]
    results = await asyncio.gather(*vote_coros, return_exceptions=True)

    votes = {}
    reasons = {}
    for agent, result in zip(voters, results):
        if isinstance(result, Exception):
            votes[agent["id"]] = "agree"
            reasons[agent["id"]] = ""
        else:
            vote, reason = result
            votes[agent["id"]] = vote
            reasons[agent["id"]] = reason

    return votes, reasons


# ── Scoreboard ──────────────────────────────────────────────

# Role-based vote weights
_ROLE_WEIGHTS = {
    "strategist": 1.2,
    "creative": 1.0,
    "skeptic": 1.5,
    "synthesizer": 1.3,
    "chairman": 2.0,
}


def build_scoreboard(proposal_records: list[dict], all_agents: list[dict]) -> list[dict]:
    """Score and rank proposals based on weighted votes.

    Each voter's agree/amend/disagree is weighted by their role.
    Chairman disagree acts as a veto (halves the score).
    Returns a list sorted by score descending.
    """
    scored = []
    for rec in proposal_records:
        score = 0.0
        vote_counts = {"agree": 0, "disagree": 0, "amend": 0}
        chairman_vote = None
        for voter_id, v in rec["votes"].items():
            vote_counts[v] = vote_counts.get(v, 0) + 1
            voter_role = ""
            for a in all_agents:
                if a["id"] == voter_id:
                    voter_role = a.get("role", "")
                    break
            weight = _ROLE_WEIGHTS.get(voter_role, 1.0)
            if v == "agree":
                score += 2 * weight
            elif v == "amend":
                score += 1 * weight
            if voter_id == "chairman":
                chairman_vote = v

        chairman_vetoed = chairman_vote == "disagree"
        if chairman_vetoed:
            score *= 0.5

        scored.append({
            "text": rec["text"],
            "author": rec["author"],
            "author_id": rec.get("author_id", ""),
            "turn": rec["turn"],
            "votes": rec["votes"],
            "reasons": rec.get("reasons", {}),
            "vote_counts": vote_counts,
            "score": round(score, 1),
            "chairman_vetoed": chairman_vetoed,
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


# ── JSON protocol ───────────────────────────────────────────

import time

def wrap_council_message(from_agent, turn, phase, text, proposals):
    return {
        "protocol": "gibberlink-revisited-council", "version": "2.0",
        "from": from_agent, "turn": turn,
        "phase": phase, "timestamp": time.time(),
        "payload": {
            "text": text,
            "proposals": proposals,
            "phase": phase,
        },
    }
