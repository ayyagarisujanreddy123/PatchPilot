"""Shared protocol interfaces (ports) for PatchPilot.

Teammates implement against these protocols to ensure clean separation of concerns.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from patchpilot.shared.contracts import (
    Approval,
    Assessment,
    AssessmentApprovalItem,
    CandidateSpec,
    CheckResult,
    DeploymentSnapshot,
    Recipe,
    RepairPlan,
    RunEvent,
    RunRecord,
    SiteManifest,
)


@runtime_checkable
class RepairService(Protocol):
    """Core repair engine service protocol (implemented by Sujan)."""

    async def list_sites(self) -> list[SiteManifest]: ...

    async def assess(self, site_id: str) -> Assessment: ...

    async def approve(
        self, items: list[AssessmentApprovalItem], policy_revision: str, operator_session: str
    ) -> Approval: ...

    async def get_approval(self, approval_id: str, operator_session: str) -> Approval: ...

    async def health(self) -> dict[str, Any]: ...

    async def prepare(self) -> dict[str, Any]: ...

    async def reset(self, clear_recipes: bool = False) -> dict[str, Any]: ...

    def close(self) -> Any: ...

    async def run(
        self, approval: Approval, memory_enabled: bool = True, *, run_id: str,
        target_outcome: Optional[str] = None,
    ) -> RunRecord:
        """Execute bounded state transitions for approved sites."""
        ...

    async def recover_interrupted(self, record: RunRecord) -> RunRecord:
        """Reconcile an incomplete or interrupted run."""
        ...


@runtime_checkable
class RunStore(Protocol):
    """Snapshot persistence for run records (implemented by Backend)."""

    async def get_run(self, run_id: str) -> Optional[RunRecord]:
        """Fetch a run snapshot by its ID."""
        ...

    async def save_run(self, record: RunRecord) -> None:
        """Durably and atomically save a run snapshot."""
        ...

    async def list_runs(
        self, limit: int = 50, cursor: Optional[str] = None
    ) -> tuple[list[RunRecord], Optional[str]]:
        """List paginated runs with an optional continuation cursor."""
        ...


@runtime_checkable
class RecipeStore(Protocol):
    """Store for validated repair recipes (implemented by Backend)."""

    async def get_recipe(self, recipe_id: str) -> Optional[Recipe]:
        """Fetch a recipe by ID."""
        ...

    async def find_matching(self, compatibility_key: str) -> Optional[Recipe]:
        """Find an exact matching recipe for a compatibility key."""
        ...

    async def save_recipe(self, recipe: Recipe) -> None:
        """Atomically persist a verified recipe."""
        ...

    async def clear_recipes(self) -> int:
        """Clear cached recipes while retaining run history."""
        ...


@runtime_checkable
class EventSink(Protocol):
    """Append-only ordered event journal (implemented by Backend)."""

    async def append_event(self, run_id: str, event: RunEvent) -> None:
        """Append an event to the run's journal."""
        ...

    async def get_events(
        self, run_id: str, after_sequence: int = 0, limit: int = 100
    ) -> tuple[list[RunEvent], int]:
        """Query ordered events occurring after sequence with nextSequence."""
        ...


@runtime_checkable
class Runtime(Protocol):
    """Container deployment and lifecycle operations (implemented by Nicholas)."""

    async def inspect(self, site: SiteManifest) -> DeploymentSnapshot:
        """Capture original deployment identity and settings."""
        ...

    async def stage(
        self, site: SiteManifest, plan: RepairPlan, run_id: str, attempt: int
    ) -> CandidateSpec:
        """Create an isolated staging candidate on loopback."""
        ...

    async def activate(
        self, site: SiteManifest, candidate: CandidateSpec, original: DeploymentSnapshot
    ) -> DeploymentSnapshot:
        """Activate the verified candidate at the original site address."""
        ...

    async def restore(
        self, site: SiteManifest, original: DeploymentSnapshot
    ) -> DeploymentSnapshot:
        """Restore the retained original deployment."""
        ...

    async def cleanup(self, candidate: CandidateSpec) -> dict[str, Any]:
        """Remove staging resources and report status."""
        ...


@runtime_checkable
class Verifier(Protocol):
    """HTTP runtime and functional assertions (implemented by Nicholas)."""

    async def check(
        self, site: SiteManifest, deployment: dict[str, Any], phase: str
    ) -> list[CheckResult]:
        """Run assertions against the serving target."""
        ...


@runtime_checkable
class Planner(Protocol):
    """AI planner for proposing repair plans (implemented by Sujan)."""

    async def propose(
        self, context: dict[str, Any], failures: list[CheckResult]
    ) -> RepairPlan:
        """Propose a typed repair plan given context and previous failures."""
        ...
