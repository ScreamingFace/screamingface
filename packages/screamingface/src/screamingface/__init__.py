"""ScreamingFace — evaluate composable Candidate Recipes on research Benchmarks."""

from screamingface import (
    analytics,
    benchmarks,
    cache,
    connections,
    events,
    leaderboards,
    models,
    reports,
)
from screamingface._default_client import (
    close,
    configure,
    connect,
    disconnect,
    evaluate,
    fetch_media,
)
from screamingface._reproduction import Reproduction, ReproductionOutcome
from screamingface._samples import samples
from screamingface._signals import signal
from screamingface._ui.connections import ConnectionPanel
from screamingface._version import resolve_version
from screamingface.answer import Answer
from screamingface.blocks import Extract, Reduce, matches
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
    MediaUnavailableError,
    PlanningError,
    ProviderConnectionError,
    ReproductionError,
    ScreamingFaceError,
)
from screamingface.events import Event
from screamingface.fields import FieldRule, Merge, Pick
from screamingface.fusion import Fusion
from screamingface.judge import Judge
from screamingface.leaderboard import (
    Leaderboard,
    LeaderboardBaseline,
    LeaderboardEntry,
    LeaderboardInfo,
    LeaderboardRankingNotice,
    LeaderboardScore,
    ScoreMetadataEvent,
)
from screamingface.media import CaseMedia, FetchedMedia
from screamingface.model import Model
from screamingface.operation import OperationInfo
from screamingface.pipeline import Pipeline
from screamingface.recipe import Recipe
from screamingface.reducer import Median, Vote
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
from screamingface.selection import Concat, Filter, Rank
from screamingface.url4 import Url4
from screamingface.warnings import (
    DuplicateMembersWarning,
    EvaluationWarning,
    FixedSeedSittingWarning,
)

# The installed distribution's version, resolved once at import — see `_version.py`.
__version__ = resolve_version()

__all__ = [
    "analytics",
    "__version__",
    "reports",
    "Answer",
    "AsyncClient",
    "AuthenticationError",
    "Benchmark",
    "BenchmarkInfo",
    "CaseGrade",
    "CaseMedia",
    "CaseResult",
    "CandidateResult",
    "Check",
    "Client",
    "Concat",
    "Connection",
    "ConnectionPanel",
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
    "ExecutionError",
    "Extract",
    "EvaluationWarning",
    "evaluate",
    "fetch_media",
    "samples",
    "Failure",
    "FetchedMedia",
    "FieldRule",
    "Filter",
    "FixedSeedSittingWarning",
    "Fusion",
    "Judge",
    "Leaderboard",
    "LeaderboardBaseline",
    "LeaderboardEntry",
    "LeaderboardError",
    "LeaderboardInfo",
    "LeaderboardRankingNotice",
    "LeaderboardScore",
    "matches",
    "MediaUnavailableError",
    "MemberResult",
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
    "Pick",
    "PlanningError",
    "Pipeline",
    "ProviderConnectionError",
    "ReproductionError",
    "Rank",
    "Recipe",
    "Reduce",
    "Report",
    "Reproduction",
    "ReproductionOutcome",
    "ScoreMetadataEvent",
    "ScreamingFaceError",
    "SelfCorrective",
    "signal",
    "OperationAccounting",
    "OperationCache",
    "Usage",
    "Url4",
    "Vote",
    "benchmarks",
    "cache",
    "events",
    "leaderboards",
    "models",
]
