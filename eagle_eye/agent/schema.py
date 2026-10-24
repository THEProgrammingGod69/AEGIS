"""Pydantic models for everything the agent outputs: the record_decision verdict and VLM drawing extraction."""
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

VERDICTS = ("CONFIRMED_OK", "CONFIRMED_FAULT", "UNCLEAR")
Verdict = Literal["CONFIRMED_OK", "CONFIRMED_FAULT", "UNCLEAR"]


def _check_box(b, ndigits=1):
    if len(b) != 4:
        raise ValueError("a box is [x0, y0, x1, y1]: exactly 4 numbers")
    if not (b[2] > b[0] and b[3] > b[1]):
        raise ValueError(f"box {list(b)}: need x1 > x0 and y1 > y0")
    return [round(float(x), ndigits) for x in b]


class Decision(BaseModel):
    """The agent's verdict on ONE finding (the only thing the agent may output)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    finding_id: str = Field(min_length=1, max_length=200)
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=2000)
    evidence_boxes: List[List[float]] = Field(default_factory=list, max_length=16)
    rephoto_hint: Optional[str] = Field(default=None, max_length=600)

    @field_validator("evidence_boxes")
    @classmethod
    def _boxes(cls, v):
        return [_check_box(b) for b in v]

    @field_validator("rephoto_hint")
    @classmethod
    def _hint(cls, v):
        return v or None


def unclear(finding_id, reason, hint=None, confidence=0.0):
    """An UNCLEAR decision made by the harness itself (budget, refusal, no answer ...)."""
    return Decision(finding_id=finding_id, verdict="UNCLEAR", confidence=confidence, reason=reason[:2000],
                    evidence_boxes=[], rephoto_hint=hint)


def errors_text(exc: ValidationError, limit=4):
    """Short, model-readable list of validation errors."""
    out = []
    for e in exc.errors()[:limit]:
        loc = ".".join(str(p) for p in e.get("loc", ())) or "input"
        out.append(f"{loc}: {e.get('msg')}")
    return "; ".join(out)


class DrawingTag(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    tag: str = Field(min_length=1, max_length=40)
    bbox_norm: List[float]
    view: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("bbox_norm")
    @classmethod
    def _bbox(cls, v):
        return [min(1.0, max(0.0, x)) for x in _check_box(v, 5)]


class DrawingTags(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tags: List[DrawingTag] = Field(default_factory=list)
    page_notes: str = ""


# JSON schema for output_config.format (structured outputs: no numeric/length constraints, additionalProperties false).
DRAWING_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tag": {"type": "string", "description": "device tag exactly as printed, e.g. PS11, CB14"},
                    "bbox_norm": {"type": "array", "items": {"type": "number"},
                                  "description": "[x0, y0, x1, y1] of the tag text, 0..1 of this image's width/height"},
                    "view": {"anyOf": [{"type": "string"}, {"type": "null"}],
                             "description": "view the tag belongs to (front, rear, left, right) or null"},
                    "confidence": {"type": "number", "description": "0..1"},
                },
                "required": ["tag", "bbox_norm", "view", "confidence"],
                "additionalProperties": False,
            },
        },
        "page_notes": {"type": "string", "description": "one short sentence about the page"},
    },
    "required": ["tags", "page_notes"],
    "additionalProperties": False,
}
