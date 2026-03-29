from dataclasses import dataclass, field


@dataclass
class SignalScore:
    """Score from a single signal group."""
    score: int
    flags: list[str] = field(default_factory=list)
    available: bool = True
    details: dict = field(default_factory=dict)


@dataclass
class ScoreResponse:
    """Composite counterparty risk assessment."""
    score: int
    tier: str
    confidence: float
    signals_checked: int
    flags: list[str] = field(default_factory=list)
    signal_scores: dict[str, SignalScore] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ScoreResponse":
        signal_scores = {}
        _valid_fields = {f.name for f in SignalScore.__dataclass_fields__.values()}
        for key, val in data.get("signal_scores", {}).items():
            filtered = {k: v for k, v in val.items() if k in _valid_fields}
            signal_scores[key] = SignalScore(**filtered)
        return cls(
            score=data["score"],
            tier=data["tier"],
            confidence=data["confidence"],
            signals_checked=data["signals_checked"],
            flags=data.get("flags", []),
            signal_scores=signal_scores,
            metadata=data.get("metadata", {}),
        )
