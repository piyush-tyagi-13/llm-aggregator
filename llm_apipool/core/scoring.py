"""Bandit routing score with Thompson sampling for FreeLLMAPI-style routing.

Translated from server/src/services/scoring.ts
"""

from __future__ import annotations


import random
import math
from typing import NamedTuple

# ── Bandit routing score ────────────────────────────────────────────────────
#
# A redesign of the analytics-driven router. Instead of summing a pile of
# hand-tuned, dimensionally-incompatible bonuses (a probability + a raw latency
# term + an intelligence term, each hand-capped to keep orderings sane), every
# signal here is normalized to [0, 1] and combined as a CONVEX COMBINATION:
#
#   base = w_rel·reliability + w_speed·speed + w_intel·intelligence
#          (weights are a preset that sums to 1, so base ∈ [0, 1])
#
# Two always-on GUARDRAILS then multiply the base — they never reorder good
# models against each other, they only pull a model down as it gets dangerous:
#
#   effective = base × headroomFactor × rateLimitFactor
#
#   headroomFactor  → protects a model that is nearly out of its free quota
#   rateLimitFactor → demotes a model that is currently throwing 429s
#
# Reliability is drawn from a Beta posterior (Thompson sampling) so exploration
# is automatic and proportional to uncertainty — a model is never permanently
# frozen out after a couple of failures. Speed and intelligence are
# deterministic. The result stays in a bounded, interpretable range and no term
# needs a manual cap to "still beat a 0%-success model".

DEFAULT_STRATEGY = "balanced"


class RoutingWeights(NamedTuple):
    """Weight vector for combining routing axes. Sums to 1."""

    reliability: float
    speed: float
    intelligence: float


# Strategy presets are loaded from default_strategies.json via ConfigLoader.
# This dict is populated at module load time and kept in sync with config.
_BANDIT_PRESETS: dict[str, RoutingWeights] | None = None


def _get_bandit_presets() -> dict[str, RoutingWeights]:
    """Lazy-load strategy weights from ConfigLoader (not hardcoded)."""
    global _BANDIT_PRESETS
    if _BANDIT_PRESETS is not None:
        return _BANDIT_PRESETS
    try:
        from ..config.loader import load_settings

        settings = load_settings()
        _BANDIT_PRESETS = {
            name: RoutingWeights(
                reliability=w.reliability,
                speed=w.speed,
                intelligence=w.intelligence,
            )
            for name, s in settings.strategies.items()
            if (w := s.weights) is not None
        }
    except Exception:
        _BANDIT_PRESETS = {}
    return _BANDIT_PRESETS


# Public alias for backward compatibility
def get_bandit_presets() -> dict[str, RoutingWeights]:
    return _get_bandit_presets()


BANDIT_PRESETS: dict[str, RoutingWeights] = _get_bandit_presets()

# ── Reliability ───────────────────────────────────────────────────────────
# Beta(1,1) prior = uniform: an unseen model is genuinely uncertain, not assumed
# good or bad. With decay-weighted pseudo-counts the alpha/beta are continuous.
PRIOR_SUCCESS = 1
PRIOR_FAILURE = 1


def reliability_posterior(successes: float, failures: float) -> tuple[float, float]:
    """Compute Beta posterior parameters from successes and failures."""
    alpha = max(0, successes) + PRIOR_SUCCESS
    beta = max(0, failures) + PRIOR_FAILURE
    return alpha, beta


def expected_reliability(successes: float, failures: float) -> float:
    """Deterministic expected reliability — used for the dashboard display score."""
    alpha, beta = reliability_posterior(successes, failures)
    return alpha / (alpha + beta)


# ── Speed (throughput + TTFB blended into one [0,1] axis) ───────────────────
# Throughput uses a saturating curve so one very fast tiny model can't make a
# perfectly-fine larger model look "slow" (the global-max-normalization bug in
# the fork). TTFB is a simple linear ramp from "instant" to "painfully slow".
SPEED_SCALE_TOK_S = 60  # tok/s at which throughput ≈ 0.63
TTFB_BEST_MS = 300  # ≤ this → full latency credit
TTFB_WORST_MS = 5000  # ≥ this → zero latency credit
THROUGHPUT_WEIGHT = 0.6  # within the speed axis
TTFB_WEIGHT = 0.4
# Optimistic prior so unmeasured models still get explored on the speed axis.
SPEED_PRIOR = 0.6


def _throughput_score(tok_per_sec: float) -> float:
    """Saturating curve for throughput."""
    if tok_per_sec <= 0:
        return 0
    return 1 - math.exp(-tok_per_sec / SPEED_SCALE_TOK_S)


def _ttfb_score(ttfb_ms: float) -> float:
    """Linear ramp for time-to-first-byte."""
    if ttfb_ms <= TTFB_BEST_MS:
        return 1
    if ttfb_ms >= TTFB_WORST_MS:
        return 0
    return 1 - (ttfb_ms - TTFB_BEST_MS) / (TTFB_WORST_MS - TTFB_BEST_MS)


def speed_score(tok_per_sec: float, ttfb_ms: float | None) -> float:
    """Blend throughput and TTFB into a single [0,1] speed score.

    tok_per_sec <= 0 means no successful samples → return the exploration prior.
    ttfb_ms is None means we have throughput but no first-byte timing → fall
    back to throughput alone rather than guessing latency.
    """
    if tok_per_sec <= 0 and ttfb_ms is None:
        return SPEED_PRIOR
    tp = _throughput_score(tok_per_sec)
    if ttfb_ms is None:
        return tp
    if tok_per_sec <= 0:
        return _ttfb_score(ttfb_ms)
    return THROUGHPUT_WEIGHT * tp + TTFB_WEIGHT * _ttfb_score(ttfb_ms)


# ── Intelligence ────────────────────────────────────────────────────────────
# Caller supplies a composite (tier-first, rank-as-tiebreaker) and the min/max
# across the enabled chain. We min-max normalize to [0,1], 1 = best.


def intelligence_score(composite: float, min_val: float, max_val: float) -> float:
    """Normalize intelligence composite to [0,1] range."""
    if max_val <= min_val:
        return 1  # single model or all equal → neutral-high
    return (composite - min_val) / (max_val - min_val)


# ── Guardrail: free-quota headroom ───────────────────────────────────────────
# Multiplier that stays at 1 while a model has comfortable monthly headroom and
# ramps down to a floor as it approaches its free-tier cap, so we stop steering
# traffic at a model we're about to burn out. Unknown budget (0) → no opinion.
HEADROOM_FLOOR = 0.1
HEADROOM_RAMP_START = 0.2  # start protecting at 20% remaining


def headroom_factor(used_tokens: float, budget_tokens: float) -> float:
    """Compute headroom multiplier based on token usage vs budget."""
    if not budget_tokens or budget_tokens <= 0:
        return 1  # unknown budget → no opinion
    remaining = max(0, 1 - used_tokens / budget_tokens)
    if remaining >= HEADROOM_RAMP_START:
        return 1
    # Linear from (0 remaining → floor) to (RAMP_START remaining → 1).
    return HEADROOM_FLOOR + (1 - HEADROOM_FLOOR) * (remaining / HEADROOM_RAMP_START)


# ── Guardrail: live rate-limit penalty ───────────────────────────────────────
# Maps the existing 0..MAX_PENALTY 429 penalty to a multiplier. At max penalty a
# model keeps 40% of its score — demoted hard but never fully excluded, so it
# can recover once the penalty decays.
MAX_PENALTY = 10
RATE_LIMIT_MAX_DAMP = 0.6


def rate_limit_factor(penalty: float) -> float:
    """Convert penalty to demotion multiplier."""
    p = min(max(0, penalty), MAX_PENALTY)
    return 1 - (p / MAX_PENALTY) * RATE_LIMIT_MAX_DAMP


# ── Beta sampler (Marsaglia & Tsang via two Gamma draws) ─────────────────────
def _random_normal() -> float:
    """Generate a random normal value using Box-Muller."""
    u1 = random.random() or float(2.220446049250313e-16)  # Avoid log(0)
    u2 = random.random()
    return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)


def _sample_gamma(shape: float) -> float:
    """Sample from Gamma distribution using Marsaglia & Tsang method."""
    if shape < 1:
        return _sample_gamma(shape + 1) * math.pow(
            random.random() or float(2.220446049250313e-16), 1 / shape
        )
    d = shape - 1 / 3
    c = 1 / math.sqrt(9 * d)
    while True:
        while True:
            x = _random_normal()
            v = 1 + c * x
            if v > 0:
                break
        v = v**3
        u = random.random()
        if u < 1 - 0.0331 * x**4:
            return d * v
        if math.log(u) < 0.5 * x * x + d * (1 - v + math.log(v)):
            return d * v


def sample_beta(alpha: float, beta: float) -> float:
    """Sample from Beta(alpha, beta) distribution."""
    x = _sample_gamma(alpha)
    y = _sample_gamma(beta)
    total = x + y
    return x / total if total > 0 else 0.5


# ── The combined score ───────────────────────────────────────────────────────
class ScoreInputs(NamedTuple):
    """Normalized inputs for score combination."""

    reliability: float  # [0,1] — sampled (routing) or expected (display)
    speed: float  # [0,1]
    intelligence: float  # [0,1]
    headroom: float  # [floor,1] multiplier
    rate_limit: float  # [floor,1] multiplier


def combine_score(inputs: ScoreInputs, weights: RoutingWeights) -> float:
    """Convex base × guardrail multipliers.

    The weights are assumed to sum to 1; if a caller passes a non-normalized
    vector we renormalize so the base never escapes [0,1].
    """
    w_sum = weights.reliability + weights.speed + weights.intelligence or 1
    base = (
        weights.reliability * inputs.reliability
        + weights.speed * inputs.speed
        + weights.intelligence * inputs.intelligence
    ) / w_sum
    return base * inputs.headroom * inputs.rate_limit
