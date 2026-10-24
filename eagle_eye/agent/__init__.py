"""Phase 5 - Claude vision verifier (spec section 7).

    from agent import status, verify, SimpleContext, extract_drawing_tags

    status()                                   -> {"enabled", "backend", "model", "fast_model", "reason", ...}
    verify(findings, ctx, run_dir=None, on_event=None)
                                               -> {"decisions": {finding_id: decision}, "calls", "usage", "cost_usd",
                                                   "summary", "overview", "errors", ...}
    extract_drawing_tags(page_image, page_no, vocabulary_hint=None) -> [{"tag", "bbox_norm", "view", "confidence",
                                                                         "source": "vlm", ...}]

The agent only verifies what the deterministic stages found (CANDIDATE_FAULT / UNCERTAIN findings); it never adds items.
Without credentials it is off and the engine stays deterministic-only. The anthropic SDK is imported lazily.
"""
from agent.drawing_extract import extract_drawing_tags
from agent.schema import Decision
from agent.tools import TOOLS, AgentContext, SimpleContext
from agent.verifier import resolve_models, status, verify

__all__ = ["status", "verify", "resolve_models", "extract_drawing_tags", "Decision", "SimpleContext", "AgentContext",
           "TOOLS"]
