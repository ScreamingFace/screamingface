"""ScreamingFace — evaluate composable Candidate Recipes on research Benchmarks."""

from screamingface import benchmarks, connections, events, leaderboards, models, reports
from screamingface._default_client import (
    close,
    configure,
    connect,
    disconnect,
    evaluate,
    reproduce,
)
from screamingface._reproduction import Reproduction, ReproductionOutcome
from screamingface._samples import samples
from screamingface._signals import signal
from screamingface._surface.fanout import Fanout
from screamingface._surface.gate import Gate
from screamingface._surface.judge import Judge, JudgePick
from screamingface._surface.refs import agreement, field
from screamingface._surface.steps import (
    ArgMax,
    ArgMin,
    Concat,
    Filter,
    First,
    Mean,
    Median,
    Merge,
    Rank,
    Vote,
)
from screamingface._surface.synthesize import Synthesize
from screamingface._ui.connections import ConnectionPanel
from screamingface._version import resolve_version
from screamingface.answer import Answer
from screamingface.blocks import Extract, matches
from screamingface.client import AsyncClient, Client
from screamingface.connections import AsyncOAuthFlow, Connection, OAuthFlow
from screamingface.corrective import CorrectiveLoop, SelfCorrective
from screamingface.discovery import (
    Benchmark,
    BenchmarkInfo,
    ModelCapability,
    ModelDetails,
    ModelInfo,
    ModelParameter,
    ModelParameterSchema,
)
from screamingface.errors import (
    AuthenticationError,
    EngineCapabilityError,
    EngineUnavailableError,
    ExecutionError,
    LeaderboardError,
    PlanningError,
    ProviderConnectionError,
    ScreamingFaceError,
)
from screamingface.events import Event
from screamingface.fields import FieldRule
from screamingface.leaderboard import (
    Leaderboard,
    LeaderboardBaseline,
    LeaderboardEntry,
    LeaderboardInfo,
    LeaderboardRankingNotice,
    LeaderboardScore,
    ScoreMetadataEvent,
)
from screamingface.model import Model
from screamingface.operation import OperationInfo
from screamingface.pipeline import Pipeline
from screamingface.recipe import Recipe
from screamingface.report import (
    CandidateResult,
    CaseGrade,
    CaseResult,
    Check,
    Evidence,
    EvidenceProducer,
    Failure,
    MemberResult,
    OperationAccounting,
    OperationCache,
    Report,
    Usage,
)
from screamingface.signal_sources import Consistency, Entropy, Logprob, Sum, Verbalized
from screamingface.url4 import Url4
from screamingface.warnings import (
    DuplicateMembersWarning,
    EvaluationWarning,
    FixedSeedSittingWarning,
    JudgeWriterWarning,
)

# The installed distribution's version, resolved once at import — see `_version.py`.
__version__ = resolve_version()

__all__ = [
    "__version__",
    "reports",
    "Answer",
    "ArgMax",
    "ArgMin",
    "AsyncClient",
    "AuthenticationError",
    "Benchmark",
    "BenchmarkInfo",
    "CaseGrade",
    "CaseResult",
    "CandidateResult",
    "Check",
    "Client",
    "Concat",
    "Connection",
    "ConnectionPanel",
    "Consistency",
    "CorrectiveLoop",
    "AsyncOAuthFlow",
    "close",
    "configure",
    "connect",
    "connections",
    "disconnect",
    "DuplicateMembersWarning",
    "Evidence",
    "EvidenceProducer",
    "Event",
    "EngineCapabilityError",
    "EngineUnavailableError",
    "Entropy",
    "ExecutionError",
    "Extract",
    "Fanout",
    "EvaluationWarning",
    "evaluate",
    "reproduce",
    "samples",
    "Failure",
    "FieldRule",
    "Filter",
    "First",
    "FixedSeedSittingWarning",
    "Gate",
    "Judge",
    "JudgePick",
    "JudgeWriterWarning",
    "Leaderboard",
    "LeaderboardBaseline",
    "LeaderboardEntry",
    "LeaderboardError",
    "LeaderboardInfo",
    "LeaderboardRankingNotice",
    "LeaderboardScore",
    "Logprob",
    "matches",
    "MemberResult",
    "Mean",
    "Median",
    "Merge",
    "Model",
    "ModelCapability",
    "ModelDetails",
    "ModelInfo",
    "ModelParameter",
    "ModelParameterSchema",
    "OperationInfo",
    "OAuthFlow",
    "PlanningError",
    "Pipeline",
    "ProviderConnectionError",
    "Rank",
    "Recipe",
    "Report",
    "Reproduction",
    "ReproductionOutcome",
    "ScoreMetadataEvent",
    "ScreamingFaceError",
    "SelfCorrective",
    "Sum",
    "Synthesize",
    "signal",
    "OperationAccounting",
    "OperationCache",
    "Usage",
    "Url4",
    "Vote",
    "Verbalized",
    "agreement",
    "benchmarks",
    "events",
    "field",
    "leaderboards",
    "models",
]
