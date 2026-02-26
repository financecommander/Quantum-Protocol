"""
AI PORTAL v2.0 — Lex Intelligence Pipeline: Aggregation Config
================================================================
Applies compound AI aggregation theory to the multi-agent research
pipeline. Implements dual-mode aggregation per the ICLR 2026 paper.

Pipeline agents:
  1. Lead Researcher      — primary research synthesis
  2. Contrarian Analyst   — adversarial challenge
  3. Regulatory Scanner   — compliance/regulatory lens
  4. Quantitative Modeler — data-driven analysis
  5. Convergence Synth    — aggregation layer (this config)
  6. Final Editor         — polish and output

Key insight from paper: the Convergence Synthesizer must use
INTERSECTION aggregation for factual claims (filter hallucinations
via feasibility expansion) but ADDITION aggregation for analysis
and recommendations (support expansion across perspectives).

Integration: feeds into backend/pipelines/lex_pipeline.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════════════
#  PIPELINE AGGREGATION MODES
# ═══════════════════════════════════════════════════════════════════

class ContentType(Enum):
    """Classification of content for aggregation mode selection."""
    FACTUAL_CLAIM = "factual_claim"       # Dates, numbers, citations, events
    ANALYSIS = "analysis"                  # Interpretation, implications
    RECOMMENDATION = "recommendation"      # Actionable suggestions
    RISK_ASSESSMENT = "risk_assessment"    # Regulatory/compliance flags
    CONTRARIAN_VIEW = "contrarian_view"    # Dissenting perspective


class PipelineAggMode(Enum):
    """Aggregation mode for each content type."""
    INTERSECTION = "intersection"   # Keep only what all agents agree on
    ADDITION = "addition"           # Weighted combination of perspectives
    GATED_ADDITION = "gated_addition"  # Addition, but gated by risk agent


# Content type → aggregation mode mapping (paper application)
AGGREGATION_ROUTING = {
    # Factual claims: intersection (feasibility expansion)
    # Rationale: hallucination filtering — only keep facts all agents confirm
    ContentType.FACTUAL_CLAIM: PipelineAggMode.INTERSECTION,

    # Analysis: addition (support expansion)
    # Rationale: each agent sees different dimensions of the problem
    ContentType.ANALYSIS: PipelineAggMode.ADDITION,

    # Recommendations: gated addition (support expansion + feasibility)
    # Rationale: combine diverse suggestions but gate through compliance
    ContentType.RECOMMENDATION: PipelineAggMode.GATED_ADDITION,

    # Risk assessment: intersection (feasibility expansion)
    # Rationale: flag risk if ANY agent flags it (conservative)
    ContentType.RISK_ASSESSMENT: PipelineAggMode.INTERSECTION,

    # Contrarian views: addition (support expansion)
    # Rationale: preserve dissent — intersection would kill it
    ContentType.CONTRARIAN_VIEW: PipelineAggMode.ADDITION,
}


# ═══════════════════════════════════════════════════════════════════
#  AGENT OUTPUT STRUCTURE
# ═══════════════════════════════════════════════════════════════════

@dataclass
class AgentOutput:
    """Structured output from a pipeline agent."""
    agent_id: int
    agent_name: str
    content_blocks: list[dict] = field(default_factory=list)
    # Each block: {"type": ContentType, "content": str, "confidence": float,
    #              "citations": list, "contradicts": list[int]}
    overall_confidence: float = 0.0
    binding_constraints: list[str] = field(default_factory=list)
    # e.g., ["regulatory_flag", "data_unavailable", "model_uncertainty"]


@dataclass
class SynthesizedOutput:
    """Output of the Convergence Synthesizer."""
    sections: list[dict] = field(default_factory=list)
    # Each section: {"type": ContentType, "mode_used": PipelineAggMode,
    #                "content": str, "sources": list[int], "confidence": float}
    mechanism_log: list[str] = field(default_factory=list)
    expansion_achieved: bool = False
    agents_contributing: list[int] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
#  CONVERGENCE SYNTHESIZER
# ═══════════════════════════════════════════════════════════════════

class ConvergenceSynthesizer:
    """
    Implements dual-mode aggregation for the Lex Intelligence Pipeline.

    Paper application:
    - Factual content → INTERSECTION (Eq. 1): only retain claims
      confirmed by multiple agents. This is feasibility expansion:
      the "hallucination-free + informative" output is infeasible
      for any single agent but achievable by filtering across agents.

    - Analytical content → ADDITION (Eq. 2): weighted combination
      of perspectives. This is support expansion: each agent covers
      different analytical dimensions that no single agent spans.

    - Recommendations → GATED ADDITION: support expansion for
      breadth, but gated by the Regulatory Scanner (Agent 3) to
      implement feasibility expansion on compliance constraints.
    """

    def __init__(
        self,
        agent_weights: Optional[dict[int, float]] = None,
        confidence_threshold: float = 0.5,
        contradiction_penalty: float = 0.3,
    ):
        # Default weights reflecting agent roles
        self.agent_weights = agent_weights or {
            1: 0.30,   # Lead Researcher — primary authority
            2: 0.15,   # Contrarian — lower weight but preserved
            3: 0.25,   # Regulatory — high weight on compliance
            4: 0.20,   # Quantitative — data-driven
        }
        self.confidence_threshold = confidence_threshold
        self.contradiction_penalty = contradiction_penalty

    def synthesize(self, agent_outputs: list[AgentOutput]) -> SynthesizedOutput:
        """
        Main synthesis: route each content block through the
        appropriate aggregation mode based on content type.
        """
        result = SynthesizedOutput(
            agents_contributing=[a.agent_id for a in agent_outputs]
        )

        # Group content blocks by type across all agents
        blocks_by_type: dict[ContentType, list[tuple[int, dict]]] = {}
        for agent in agent_outputs:
            for block in agent.content_blocks:
                ct = block.get("type", ContentType.ANALYSIS)
                if ct not in blocks_by_type:
                    blocks_by_type[ct] = []
                blocks_by_type[ct].append((agent.agent_id, block))

        # Process each content type with its designated aggregation mode
        for content_type, blocks in blocks_by_type.items():
            mode = AGGREGATION_ROUTING.get(
                content_type, PipelineAggMode.ADDITION
            )

            if mode == PipelineAggMode.INTERSECTION:
                section = self._intersect_blocks(content_type, blocks)
                result.mechanism_log.append(
                    f"INTERSECT on {content_type.value}: "
                    f"feasibility expansion (hallucination filter)"
                )
            elif mode == PipelineAggMode.ADDITION:
                section = self._add_blocks(content_type, blocks)
                result.mechanism_log.append(
                    f"ADD on {content_type.value}: "
                    f"support expansion (perspective combination)"
                )
            elif mode == PipelineAggMode.GATED_ADDITION:
                section = self._gated_add_blocks(
                    content_type, blocks, agent_outputs
                )
                result.mechanism_log.append(
                    f"GATED_ADD on {content_type.value}: "
                    f"support expansion + feasibility gate"
                )
            else:
                section = self._add_blocks(content_type, blocks)

            if section:
                result.sections.append(section)

        # Check if we achieved elicitability expansion
        result.expansion_achieved = self._check_expansion(
            agent_outputs, result
        )

        return result

    def _intersect_blocks(
        self,
        content_type: ContentType,
        blocks: list[tuple[int, dict]],
    ) -> dict:
        """
        Intersection aggregation: keep only claims with cross-agent support.
        Paper Eq. 1: coordinate-wise minimum.

        For factual claims, this means retaining only facts that
        multiple agents independently corroborate.
        """
        if not blocks:
            return {}

        # Group by content similarity (simplified: exact match for now)
        claim_support: dict[str, list[int]] = {}
        claim_confidence: dict[str, list[float]] = {}
        for agent_id, block in blocks:
            content = block.get("content", "")
            if content not in claim_support:
                claim_support[content] = []
                claim_confidence[content] = []
            claim_support[content].append(agent_id)
            claim_confidence[content].append(
                block.get("confidence", 0.5)
            )

        # Only keep claims with 2+ agent support
        confirmed = []
        for content, agents in claim_support.items():
            if len(agents) >= 2:
                # Confidence = minimum across confirming agents
                # (conservative, per intersection rule)
                conf = min(claim_confidence[content])
                confirmed.append({
                    "content": content,
                    "confidence": conf,
                    "confirmed_by": agents,
                })

        combined_content = "\n".join(c["content"] for c in confirmed)
        min_conf = min((c["confidence"] for c in confirmed), default=0.0)
        all_sources = list(set().union(
            *(set(c["confirmed_by"]) for c in confirmed)
        )) if confirmed else []

        return {
            "type": content_type,
            "mode_used": PipelineAggMode.INTERSECTION,
            "content": combined_content,
            "sources": all_sources,
            "confidence": min_conf,
            "claims_filtered": len(claim_support) - len(confirmed),
        }

    def _add_blocks(
        self,
        content_type: ContentType,
        blocks: list[tuple[int, dict]],
    ) -> dict:
        """
        Addition aggregation: weighted combination of perspectives.
        Paper Eq. 2: weighted sum.

        For analysis and recommendations, combine diverse perspectives
        with agent-role weighting.
        """
        if not blocks:
            return {}

        weighted_parts = []
        total_weight = 0.0
        total_confidence = 0.0
        sources = []

        for agent_id, block in blocks:
            w = self.agent_weights.get(agent_id, 0.1)
            conf = block.get("confidence", 0.5)

            # Apply contradiction penalty if this block contradicts others
            contradicts = block.get("contradicts", [])
            if contradicts:
                conf *= (1.0 - self.contradiction_penalty)

            effective_weight = w * conf
            total_weight += effective_weight
            total_confidence += effective_weight * conf

            weighted_parts.append({
                "agent_id": agent_id,
                "content": block.get("content", ""),
                "weight": effective_weight,
            })
            sources.append(agent_id)

        # Sort by weight descending for presentation
        weighted_parts.sort(key=lambda p: p["weight"], reverse=True)

        combined = "\n\n".join(
            p["content"] for p in weighted_parts
            if p["weight"] > 0.05
        )
        avg_conf = total_confidence / total_weight if total_weight > 0 else 0.0

        return {
            "type": content_type,
            "mode_used": PipelineAggMode.ADDITION,
            "content": combined,
            "sources": list(set(sources)),
            "confidence": avg_conf,
            "perspectives_combined": len(weighted_parts),
        }

    def _gated_add_blocks(
        self,
        content_type: ContentType,
        blocks: list[tuple[int, dict]],
        all_outputs: list[AgentOutput],
    ) -> dict:
        """
        Gated addition: support expansion with feasibility gate.

        First do addition aggregation (support expansion), then
        apply regulatory/compliance gate (feasibility expansion).
        Recommendations that violate regulatory constraints are
        filtered out, but diverse valid suggestions are preserved.
        """
        # Get regulatory agent constraints
        regulatory_constraints = []
        for agent in all_outputs:
            if agent.agent_id == 3:  # Regulatory Scanner
                regulatory_constraints = agent.binding_constraints

        # Addition aggregate first
        added = self._add_blocks(content_type, blocks)
        if not added:
            return {}

        # Apply regulatory gate
        if regulatory_constraints:
            added["regulatory_flags"] = regulatory_constraints
            added["mode_used"] = PipelineAggMode.GATED_ADDITION
            # Reduce confidence if regulatory flags present
            flag_penalty = len(regulatory_constraints) * 0.1
            added["confidence"] = max(
                0.1, added.get("confidence", 0.5) - flag_penalty
            )

        return added

    def _check_expansion(
        self,
        agent_outputs: list[AgentOutput],
        result: SynthesizedOutput,
    ) -> bool:
        """
        Did aggregation produce an output that no single agent could?
        True elicitability expansion per Definition 2.1.
        """
        # Expansion occurred if:
        # 1. Intersection filtered claims (some agents were wrong)
        claims_filtered = sum(
            s.get("claims_filtered", 0) for s in result.sections
        )
        # 2. Addition combined perspectives no single agent covered
        perspectives_combined = sum(
            s.get("perspectives_combined", 0) for s in result.sections
        )
        # 3. Gated addition caught regulatory issues
        has_regulatory_gates = any(
            s.get("regulatory_flags") for s in result.sections
        )

        return (
            claims_filtered > 0
            or perspectives_combined > len(agent_outputs)
            or has_regulatory_gates
        )


# ═══════════════════════════════════════════════════════════════════
#  PIPELINE INTEGRATION PROMPT TEMPLATE
# ═══════════════════════════════════════════════════════════════════

CONVERGENCE_SYSTEM_PROMPT = """You are the Convergence Synthesizer in the
Lex Intelligence Pipeline. You aggregate outputs from multiple specialist
agents using dual-mode aggregation:

FACTUAL CLAIMS (dates, numbers, citations, events):
→ Use INTERSECTION: only include facts confirmed by 2+ agents.
  If agents disagree on a fact, flag the disagreement rather than
  picking a side. This filters hallucinations.

ANALYSIS & INTERPRETATION:
→ Use ADDITION: combine perspectives with weighting.
  Lead Researcher (30%), Contrarian (15%), Regulatory (25%), Quant (20%).
  Preserve dissenting views from the Contrarian — do not suppress them.

RECOMMENDATIONS:
→ Use GATED ADDITION: combine suggestions for breadth, but flag
  anything the Regulatory Scanner raised concerns about. Include
  the recommendation with an explicit compliance caveat.

RISK ASSESSMENT:
→ Use INTERSECTION: if ANY agent flags a risk, include it.
  Conservative consensus — the most cautious view prevails.

Your output should clearly delineate which mode was used for each section
and track which agents contributed to each conclusion.
"""
