"""ScreamingFace — evaluate composable Candidate Recipes on research Benchmarks."""

from screamingface import benchmarks, connections, events, leaderboards, models
from screamingface._default_client import close, configure, connect, disconnect, evaluate
from screamingface._ui.connections import ConnectionPanel
from screamingface._version import resolve_version
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
    EngineUnavailableError,
    ExecutionError,
    LeaderboardError,
    PlanningError,
    ProviderConnectionError,
    ScreamingFaceError,
)
from screamingface.events import Event
from screamingface.fusion import Fusion
from screamingface.leaderboard import (
    Leaderboard,
    LeaderboardBaseline,
    LeaderboardEntry,
    LeaderboardInfo,
    LeaderboardScore,
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
from screamingface.url4 import Url4
from screamingface.warnings import EvaluationWarning

# The installed distribution's version, resolved once at import — see `_version.py`.
__version__ = resolve_version()

__all__ = [
    "__version__",
    "AsyncClient",
    "AuthenticationError",
    "Benchmark",
    "BenchmarkInfo",
    "CaseGrade",
    "CaseResult",
    "CandidateResult",
    "Check",
    "Client",
    "Connection",
    "ConnectionPanel",
    "CorrectiveLoop",
    "AsyncOAuthFlow",
    "close",
    "configure",
    "connect",
    "connections",
    "disconnect",
    "Evidence",
    "EvidenceProducer",
    "Event",
    "EngineUnavailableError",
    "ExecutionError",
    "EvaluationWarning",
    "evaluate",
    "Failure",
    "Fusion",
    "Leaderboard",
    "LeaderboardBaseline",
    "LeaderboardEntry",
    "LeaderboardError",
    "LeaderboardInfo",
    "LeaderboardScore",
    "MemberResult",
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
    "Recipe",
    "Report",
    "ScreamingFaceError",
    "SelfCorrective",
    "OperationAccounting",
    "OperationCache",
    "Usage",
    "Url4",
    "benchmarks",
    "events",
    "leaderboards",
    "models",
]
