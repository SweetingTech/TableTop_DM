from __future__ import annotations

import hmac
import ipaddress
import json
import os
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from flask import Flask, g, jsonify, make_response, request, send_from_directory
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cognition.engine import (
    DecisionAction,
    DecisionRequest,
    LayeredDecisionEngine,
    SubjectiveStatePipeline,
)
from cognition.models import RuntimeAssignment, RuntimeKind
from cognition.perception import PerceptionProfile
from cognition.planning import GoapAction
from cognition.postgres import PostgresMindRepository
from cognition.reflexes import ReflexRule
from cognition.relationships import (
    RelationshipChangeRecord,
    RelationshipEngine,
    RelationshipModifiers,
)
from cognition.store import MindStore
from domains.tabletop.portal import (
    InMemoryPortalRepository,
    PostgresPortalRepository,
    TabletopPortalService,
)
from experiments.aggregation import compare_reports
from experiments.calibration import CalibrationEngine, CalibrationStore
from experiments.executor import ApplicationBranchExecutor
from experiments.history import ExperimentHistoryStore
from experiments.jobs import JobContext, JobManager
from experiments.models import (
    ScenarioDefinition,
    SnapshotReference,
    TrialOutput,
    scenario_version_key,
)
from experiments.onboarding import OnboardingExperiment
from experiments.reference_runner import ReferenceScenarioRunner
from experiments.repository import (
    InMemoryExperimentRepository,
    PostgresExperimentRepository,
)
from experiments.telemetry import (
    PostgresTelemetryRepository,
    TelemetryRecorder,
    TelemetrySettingsStore,
)
from identity.models import AuthenticatedUser, UserProfile
from identity.repository import InMemoryIdentityRepository, PostgresIdentityRepository
from identity.service import AuthenticationError, IdentityService
from kernel.application import SimulationApplication
from kernel.branching import ConsequencePackage
from kernel.contracts import ActorKind, BranchKind, CommandProposal, RunKind
from kernel.database import execute_one
from kernel.errors import KernelError
from kernel.postgres_control_plane import PostgresControlPlane
from kernel.postgres_repository import PostgresCommandRepository
from kernel.visibility import VisibilityPolicy
from persona.compilation import PersonaCompiler
from persona.generation import PersonaGenerator
from persona.postgres import PostgresPersonaRepository
from persona.registry import PersonaSchemaRegistry
from persona.validation import PersonaValidator
from persona.versioning import PersonaVersioning
from population import CohortDefinition, PopulationLifecycle, PopulationStore
from population.postgres import PostgresPopulationRepository


class WorldCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ActorCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=160)
    kind: ActorKind = ActorKind.HUMAN
    world_id: uuid.UUID | None = None
    roles: set[str] = Field(default_factory=set)
    capabilities: set[str] = Field(default_factory=set)


class EntityCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    entity_type: str = Field(min_length=1, max_length=120)
    public_state: dict[str, Any] = Field(default_factory=dict)
    secret_state: dict[str, Any] = Field(default_factory=dict)
    controller_actor_id: uuid.UUID | None = None


class RunCreateRequest(BaseModel):
    world_id: uuid.UUID
    branch_id: uuid.UUID | None = None
    kind: RunKind = RunKind.LIVE
    seed: int | None = None


class PersonaGenerateRequest(BaseModel):
    seed: int
    fixed: dict[str, Any] = Field(default_factory=dict)


class PersonaCreateRequest(BaseModel):
    seed: int
    dimensions: dict[str, Any] = Field(default_factory=dict)
    persona_id: uuid.UUID | None = None
    parent_version_id: uuid.UUID | None = None


class PromptRequest(BaseModel):
    situation_summary: str = Field(default="", max_length=8_000)
    relevant_traits: tuple[str, ...] = ()
    max_tokens: int = Field(default=800, ge=1, le=8_000)
    max_characters: int = Field(default=3_200, ge=1, le=32_000)


class PopulationGenerateRequest(BaseModel):
    name: str = Field(default="Generated population", min_length=1, max_length=160)
    size: int = Field(default=500, ge=1, le=100_000)
    seed: int = 17
    world_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None


class PopulationSampleRequest(BaseModel):
    strata: tuple[str, ...] = ("rules_familiarity",)
    per_cell: int = Field(default=5, ge=1, le=1_000)
    seed: int = 99
    filters: dict[str, Any] = Field(default_factory=dict)


class MaterializeRequest(BaseModel):
    persona_id: uuid.UUID
    profile: dict[str, Any]
    persistent_state: dict[str, Any] = Field(default_factory=dict)
    world_step: int = Field(default=0, ge=0)
    world_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None


class ActivateRequest(BaseModel):
    active_state: dict[str, Any]
    world_step: int = Field(ge=0)
    world_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None


class DeactivateRequest(BaseModel):
    compressed_state: dict[str, Any] = Field(default_factory=dict)
    world_step: int = Field(ge=0)
    world_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None


class PopulationBulkRequest(BaseModel):
    count: int = Field(ge=1, le=10_000)
    world_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None


class OnboardingRunRequest(BaseModel):
    cohort_size: int = Field(default=12, ge=1, le=1_000)
    seeds: tuple[int, ...] = Field(default=(101, 202, 303), min_length=1, max_length=20)
    include_trials: int = Field(default=12, ge=0, le=100)


class ScenarioRunRequest(BaseModel):
    version: str | None = Field(default=None, min_length=1, max_length=80)
    cohort_size: int | None = Field(default=None, ge=1, le=1_000)
    seeds: tuple[int, ...] | None = Field(default=None, min_length=1, max_length=20)
    include_trials: int = Field(default=12, ge=0, le=100)


class CalibrationRequest(BaseModel):
    synthetic_metrics: dict[str, float]
    human_metrics: dict[str, float]
    policy_version: str = Field(min_length=1)
    evidence_version: str = Field(min_length=1)
    evidence_metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    reviewer: str = Field(default="Local operator", min_length=1, max_length=160)


class CalibrationReviewRequest(BaseModel):
    reviewer: str = Field(default="Local operator", min_length=1, max_length=160)
    decision: Literal["APPROVED", "REJECTED"]
    rationale: str = Field(default="", max_length=2_000)


class CalibrationPromotionRequest(BaseModel):
    promoted_by: str = Field(default="Local operator", min_length=1, max_length=160)


class TelemetryUpdateRequest(BaseModel):
    enabled: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3_650)


class TelemetryImportRequest(BaseModel):
    events: tuple[dict[str, Any], ...] = Field(max_length=10_000)


class CognitionDecisionApiRequest(BaseModel):
    persona_id: uuid.UUID
    seed: int
    actions: tuple[DecisionAction, ...] = Field(min_length=1)
    situation: dict[str, Any] = Field(default_factory=dict)
    actor_id: uuid.UUID | None = None
    embodied_entity_id: uuid.UUID
    world_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    idempotency_key: str | None = Field(default=None, max_length=200)
    utility_margin: float = Field(default=0.15, ge=0)
    novel_or_ambiguous: bool = False
    allow_llm: bool = False
    reflex_rules: tuple[ReflexRule, ...] = ()
    planning_goal: dict[str, Any] = Field(default_factory=dict)
    planning_actions: tuple[GoapAction, ...] = ()
    planner_max_depth: int = Field(default=6, ge=0, le=32)
    planner_max_nodes: int = Field(default=256, ge=1, le=10_000)


class RuntimeScopeRequest(BaseModel):
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID


class RuntimeAssignmentRequest(RuntimeScopeRequest):
    runtime_kind: RuntimeKind
    runtime_config: dict[str, Any] = Field(default_factory=dict)


class ObservationRequest(BaseModel):
    observer_actor_id: uuid.UUID
    observer_entity_id: uuid.UUID
    acuity: float = Field(default=1, ge=0, le=1)
    confidence_bias: float = Field(default=0, ge=-1, le=1)
    allowed_payload_fields: tuple[str, ...] | None = None
    hidden_payload_fields: frozenset[str] = frozenset()
    memory_summary: str | None = None
    emotional_weight: float = Field(default=0, ge=-1, le=1)
    importance: float = Field(default=0.5, ge=0, le=1)


class RelationshipRequest(BaseModel):
    target_entity_id: uuid.UUID
    source_event_id: uuid.UUID
    event_type: str = Field(min_length=1, max_length=120)
    deltas: dict[str, float] | None = None
    modifiers: RelationshipModifiers = Field(default_factory=RelationshipModifiers)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class ProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    legal_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    date_of_birth: date | None = None
    pronouns: str | None = Field(default=None, max_length=80)
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    locale: str = Field(default="en-US", min_length=2, max_length=40)
    bio: str | None = Field(default=None, max_length=4000)
    avatar_uri: str | None = Field(default=None, max_length=2000)

    def profile(self) -> UserProfile:
        def optional(value: str | None) -> str | None:
            return value.strip() or None if value is not None else None

        return UserProfile(
            display_name=self.display_name.strip(),
            legal_name=optional(self.legal_name),
            email=optional(self.email),
            date_of_birth=self.date_of_birth,
            pronouns=optional(self.pronouns),
            timezone=self.timezone,
            locale=self.locale,
            bio=optional(self.bio),
            avatar_uri=optional(self.avatar_uri),
        )


class AdminUserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    temporary_password: str = Field(min_length=12, max_length=256)
    profile: ProfileRequest


class AdminUserUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=64)
    is_active: bool | None = None
    profile: ProfileRequest | None = None


class PasswordResetRequest(BaseModel):
    temporary_password: str = Field(min_length=12, max_length=256)


class GlobalRolesRequest(BaseModel):
    roles: set[Literal["ADMIN"]] = Field(default_factory=set)


class WorldRolesRequest(BaseModel):
    roles: set[Literal["DM", "PLAYER"]] = Field(default_factory=set)


class CharacterCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    creation_method: Literal["BUILT", "GENERATED", "IMPORTED"] = "BUILT"
    name: str | None = Field(default=None, max_length=160)
    source_filename: str | None = Field(default=None, max_length=255)
    seed: int | None = None


class CharacterUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class GameCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    world_id: uuid.UUID
    name: str = Field(min_length=1, max_length=160)


class GameUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class GameMemberRequest(BaseModel):
    user_id: uuid.UUID
    character_id: uuid.UUID | None = None
    membership_role: Literal["PLAYER", "CO_DM"] = "PLAYER"
    status: Literal["INVITED", "JOINED", "READY", "LEFT", "REMOVED"] = "INVITED"


class GameSessionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str | None = Field(default=None, max_length=160)


def _json(model: Any, status: int = 200):
    if hasattr(model, "model_dump"):
        payload = model.model_dump(mode="json")
    else:
        payload = model
    return jsonify(payload), status


def create_app(
    simulation: SimulationApplication | None = None,
    *,
    artifact_root: Path | None = None,
) -> Flask:
    root = (artifact_root or Path(os.environ.get("TTDM_ARTIFACT_ROOT", "artifacts"))).resolve()
    static_root = Path(__file__).resolve().parents[2] / "static" / "v2"
    app = Flask(__name__, static_folder=None)
    simulation = simulation or SimulationApplication(root / "snapshots")
    demo = simulation.bootstrap_demo()
    database_dsn = os.environ.get("DATABASE_URL")
    identity_repository = (
        PostgresIdentityRepository(database_dsn, bootstrap_actor_id=demo["actor_id"])
        if database_dsn
        else InMemoryIdentityRepository(bootstrap_actor_id=demo["actor_id"])
    )
    identity = IdentityService(identity_repository)
    portal = TabletopPortalService(
        PostgresPortalRepository(database_dsn) if database_dsn else InMemoryPortalRepository(),
        identity_repository,
    )
    durable_control: PostgresControlPlane | None = None
    if database_dsn:
        durable_control = PostgresControlPlane(database_dsn)
        durable_control.sync(simulation)
        for world_id in simulation.worlds:
            identity.sync_admin_world(world_id)
        durable_control.hydrate(simulation)
        simulation.configure_durable(
            PostgresCommandRepository(database_dsn),
            durable_control.load_projection,
            durable_control.persist_snapshot,
        )
    registry = PersonaSchemaRegistry.load_default()
    generator = PersonaGenerator(registry)
    compiler = PersonaCompiler()
    persona_validator = PersonaValidator(registry)
    onboarding = OnboardingExperiment()
    jobs = JobManager()
    experiment_history = ExperimentHistoryStore(root / "experiments")
    calibrations = CalibrationStore(root / "calibration")
    telemetry_settings = TelemetrySettingsStore(database_dsn)
    telemetry = TelemetryRecorder(
        telemetry_settings,
        PostgresTelemetryRepository(database_dsn, demo["actor_id"]) if database_dsn else None,
    )
    minds = MindStore()
    mind_repository = PostgresMindRepository(database_dsn) if database_dsn else None
    if mind_repository is not None:
        for entity in simulation.entities.values():
            state, observations, relationships = mind_repository.load_projection(
                world_id=entity.world_id,
                branch_id=entity.branch_id,
                entity_id=entity.entity_id,
                actor_id=demo["actor_id"],
            )
            minds.restore(
                state,
                branch_id=entity.branch_id,
                observations=observations,
                relationships=relationships,
            )
            for assignment in mind_repository.list_runtime_assignments(
                world_id=entity.world_id,
                branch_id=entity.branch_id,
                entity_id=entity.entity_id,
                actor_id=demo["actor_id"],
            ):
                minds.set_runtime_assignment(assignment)
    subjective_pipeline = SubjectiveStatePipeline()
    decision_engine = LayeredDecisionEngine()
    relationship_engine = RelationshipEngine()
    personas: dict[uuid.UUID, Any] = {}
    persona_versions: dict[uuid.UUID, Any] = {}
    persona_repository: PostgresPersonaRepository | None = None
    if database_dsn:
        persona_repository = PostgresPersonaRepository(database_dsn, registry)
        persona_repository.sync_schema()
        for stored_version in persona_repository.list_versions():
            persona_versions[stored_version.version_id] = stored_version
            personas[stored_version.blueprint.persona_id] = stored_version.blueprint
    populations: dict[uuid.UUID, dict[str, Any]] = {}
    population_lifecycles: dict[uuid.UUID, PopulationLifecycle] = {}
    population_repository = PostgresPopulationRepository(database_dsn) if database_dsn else None
    if population_repository is not None:
        for stored_population in population_repository.list_pools():
            population_id = uuid.UUID(stored_population["population_id"])
            populations[population_id] = stored_population
            population_lifecycles[population_id] = population_repository.load_lifecycle(
                population_id
            )
    reports: dict[uuid.UUID, Any] = dict(experiment_history.reports())
    trials: dict[uuid.UUID, TrialOutput] = {
        output.trial_id: output for output in experiment_history.trials()
    }
    scenarios: dict[tuple[str, str], ScenarioDefinition] = {
        ("player-onboarding", "1.0.0"): ScenarioDefinition(
            scenario_id="player-onboarding",
            version="1.0.0",
            name="First Light onboarding",
            description="Simulated player cohorts exercise the opening rules and quest flow.",
            cohort_size=12,
            seeds=(101, 202, 303),
            run_horizon_steps=24,
            stop_conditions=("onboarding.completed",),
            verifier_versions=("onboarding-verifier-1.0.0",),
            metric_contract={
                "completion_rate": "ratio",
                "mean_invalid_actions": "actions",
                "mean_help_requests": "requests",
            },
        )
    }
    for definition in experiment_history.scenarios():
        scenarios[(definition.scenario_id, definition.version)] = definition
    for definition in scenarios.values():
        experiment_history.save_scenario(definition)
    experiment_repository = (
        PostgresExperimentRepository(database_dsn, root / "experiments") if database_dsn else None
    )
    if experiment_repository is not None:
        for definition in tuple(scenarios.values()):
            experiment_repository.save_scenario(definition)
        for definition in experiment_repository.list_scenarios():
            scenarios[(definition.scenario_id, definition.version)] = definition
            experiment_history.save_scenario(definition)
        for report_id, report in experiment_repository.load_reports():
            reports.setdefault(report_id, report)
        for output in experiment_repository.load_trial_outputs():
            trials.setdefault(output.trial_id, output)

    durable_jobs = {record.job_id: record for record in experiment_history.jobs()}
    if experiment_repository is not None:
        for record in experiment_repository.load_jobs():
            durable_jobs[record.job_id] = record
    for record in durable_jobs.values():
        restored = jobs.restore(record)
        if restored != record:
            experiment_history.save_job(restored)
            if experiment_repository is not None:
                experiment_repository.save_job(restored)
    trial_repository: Any = experiment_repository or InMemoryExperimentRepository()
    if experiment_repository is None:
        for definition in scenarios.values():
            trial_repository.save_scenario(definition)

    app.extensions["simulation"] = simulation
    app.extensions["demo_ids"] = demo
    app.extensions["jobs"] = jobs
    app.extensions["experiment_history"] = experiment_history
    app.extensions["minds"] = minds

    def compiled_persona(persona_id: uuid.UUID):
        blueprint = personas[persona_id]
        versions = [
            record
            for record in persona_versions.values()
            if record.blueprint.persona_id == persona_id
        ]
        version = max(versions, key=lambda item: item.created_at) if versions else None
        compiled = compiler.compile(
            blueprint,
            persona_version=str(version.version_id) if version is not None else None,
        )
        if persona_repository is not None:
            persona_repository.save_compiled(compiled)
        return compiled

    def world_payload(world: Any) -> dict[str, Any]:
        live_run = next(
            (item for item in simulation.runs.values() if item.world_id == world.world_id),
            None,
        )
        return {
            **world.model_dump(mode="json"),
            "current_run_id": str(live_run.run_id) if live_run is not None else None,
            "updated_at": world.created_at.isoformat(),
        }

    def run_payload(run: Any) -> dict[str, Any]:
        return {
            **run.model_dump(mode="json"),
            "name": f"{run.kind.value.title()} run {str(run.run_id)[:8]}",
        }

    def branch_payload(state: Any) -> dict[str, Any]:
        base = next(
            (
                item
                for item in simulation.snapshots.values()
                if item.state_hash == state.base_snapshot_hash
            ),
            None,
        )
        return {
            "branch_id": str(state.branch_id),
            "world_id": str(state.world_id),
            "name": (
                "Canonical"
                if state.kind.value == "CANONICAL"
                else f"Trial {str(state.branch_id)[:8]}"
            ),
            "kind": state.kind.value,
            "status": "ACTIVE",
            "base_snapshot_id": str(base.snapshot_id) if base is not None else None,
            "state_hash": state.state_hash,
            "projection_version": state.version,
        }

    def snapshot_payload(manifest: Any) -> dict[str, Any]:
        return {
            **manifest.model_dump(mode="json"),
            "name": f"Snapshot {str(manifest.snapshot_id)[:8]}",
            "event_sequence": manifest.through_event_seq,
        }

    def population_payload(record: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if not key.startswith("_")}

    def new_population_target(
        world_id: uuid.UUID | None,
        branch_id: uuid.UUID | None,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        if branch_id is not None:
            state = simulation.states.get(branch_id)
            resolved_world = world_id or state.world_id
            if state.world_id != resolved_world:
                raise ValueError("population branch does not belong to target world")
            return resolved_world, branch_id
        resolved_world = world_id or demo["world_id"]
        return resolved_world, simulation.worlds[resolved_world].canonical_branch_id

    def population_target(
        record: dict[str, Any],
        world_id: uuid.UUID | None,
        branch_id: uuid.UUID | None,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        stored_world = uuid.UUID(str(record["world_id"]))
        stored_branch = uuid.UUID(str(record["branch_id"]))
        resolved_world, resolved_branch = new_population_target(
            world_id or stored_world,
            branch_id or stored_branch,
        )
        if (resolved_world, resolved_branch) != (stored_world, stored_branch):
            raise ValueError("population target world and branch are immutable")
        return resolved_world, resolved_branch

    def ensure_population_version(
        record: dict[str, Any],
        persona_id: uuid.UUID,
        profile: dict[str, Any],
    ):
        versions = [
            item for item in persona_versions.values() if item.blueprint.persona_id == persona_id
        ]
        if versions:
            return max(versions, key=lambda item: item.created_at)
        row = PopulationStore(Path(record["artifact"])).get(persona_id)
        blueprint = generator.generate(int(row["seed"]))
        if blueprint.persona_id != persona_id:
            raise ValueError("population artifact persona identity is inconsistent")
        if profile and profile != blueprint.dimensions:
            raise ValueError("materialization profile differs from immutable population artifact")
        version = PersonaVersioning.record(blueprint)
        if persona_repository is not None:
            persona_repository.save_version(version)
        personas[persona_id] = blueprint
        persona_versions[version.version_id] = version
        return version

    def canonical_entity(entity_id: uuid.UUID):
        for (branch_id, identity), entity in simulation.entities.items():
            if identity == entity_id and simulation.states.get(branch_id).kind.value == "CANONICAL":
                return entity
        raise KeyError(entity_id)

    def job_payload(job: Any) -> dict[str, Any]:
        payload = job.model_dump(mode="json")
        result = job.result or {}
        report = result.get("report") if isinstance(result, dict) else None
        requested = int(job.request.get("cohort_size", 0)) * len(job.request.get("seeds", ()))
        payload.update(
            {
                "kind": "SCENARIO" if job.job_type.startswith("scenario.") else job.job_type,
                "total": requested,
                "completed": int(report.get("completed", 0)) if isinstance(report, dict) else 0,
                "report": report,
            }
        )
        return payload

    def user_payload(user: Any) -> dict[str, Any]:
        payload = user.model_dump(mode="json")
        payload.update(
            {
                "is_admin": user.is_admin,
                "has_dm_role": user.has_dm_role,
                "has_player_role": user.has_player_role,
            }
        )
        return payload

    def current_user() -> AuthenticatedUser:
        user = getattr(g, "current_user", None)
        if user is None:
            raise AuthenticationError("authentication required")
        return user

    def current_actor_id() -> uuid.UUID:
        if getattr(g, "operator_compatibility", False):
            requested = request.headers.get("X-TTDM-Actor-ID")
            if requested:
                return uuid.UUID(requested)
        return current_user().actor_id

    def session_cookie(response, token: str, *, expires_at: datetime):
        response.set_cookie(
            "ttdm_session",
            token,
            expires=expires_at,
            httponly=True,
            secure=request.is_secure,
            samesite="Lax",
            path="/",
        )
        return response

    def clear_session_cookie(response):
        response.delete_cookie("ttdm_session", path="/", samesite="Lax")
        return response

    @app.before_request
    def authentication_boundary():
        if not request.path.startswith("/api/v2"):
            return None
        public_paths = {
            "/api/v2/health/live",
            "/api/v2/health/ready",
            "/api/v2/auth/login",
        }
        if request.path in public_paths:
            return None
        configured = os.environ.get("TTDM_OPERATOR_TOKEN", "")
        supplied = request.headers.get("X-TTDM-Operator-Token", "")
        if configured and supplied and hmac.compare_digest(configured, supplied):
            g.current_user = identity.bootstrap_admin.model_copy(
                update={"password_change_required": False}
            )
            g.operator_compatibility = True
            return None
        if not database_dsn and not configured:
            g.current_user = identity.bootstrap_admin.model_copy(
                update={"password_change_required": False}
            )
            g.operator_compatibility = True
            try:
                peer_is_local = ipaddress.ip_address(request.remote_addr or "").is_loopback
            except ValueError:
                peer_is_local = False
            host_name = urlsplit(f"//{request.host}").hostname or ""
            if host_name.casefold() == "localhost":
                host_is_local = True
            else:
                try:
                    host_is_local = ipaddress.ip_address(host_name).is_loopback
                except ValueError:
                    host_is_local = False
            fetch_site = request.headers.get("Sec-Fetch-Site", "").casefold()
            origin = request.headers.get("Origin")
            origin_is_local = True
            if origin:
                try:
                    origin_parts = urlsplit(origin)
                    request_parts = urlsplit(request.host_url)
                    origin_is_local = (
                        origin_parts.scheme.casefold() == request_parts.scheme.casefold()
                        and origin_parts.hostname is not None
                        and request_parts.hostname is not None
                        and origin_parts.hostname.rstrip(".").casefold()
                        == request_parts.hostname.rstrip(".").casefold()
                        and (origin_parts.port or (443 if origin_parts.scheme == "https" else 80))
                        == (request_parts.port or (443 if request_parts.scheme == "https" else 80))
                    )
                except ValueError:
                    origin_is_local = False
            if not host_is_local:
                return jsonify({"error": "untrusted_loopback_host"}), 403
            if not peer_is_local or fetch_site == "cross-site" or not origin_is_local:
                return jsonify({"error": "cross_site_request_rejected"}), 403
        else:
            user = identity.authenticate(request.cookies.get("ttdm_session"))
            if user is None:
                return jsonify({"error": "authentication_required"}), 401
            g.current_user = user
            if user.password_change_required and request.path not in {
                "/api/v2/auth/session",
                "/api/v2/auth/change-password",
                "/api/v2/auth/logout",
            }:
                return jsonify({"error": "password_change_required"}), 403
        admin_workspaces = (
            "/api/v2/personas",
            "/api/v2/populations",
            "/api/v2/scenarios",
            "/api/v2/experiments",
            "/api/v2/jobs",
            "/api/v2/reports",
            "/api/v2/calibration",
            "/api/v2/telemetry",
        )
        if request.path.startswith(admin_workspaces) and not current_user().is_admin:
            return jsonify(
                {"error": "permission_denied", "details": "administrator role required"}
            ), 403
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            fetch_site = request.headers.get("Sec-Fetch-Site", "").casefold()
            if fetch_site == "cross-site":
                return jsonify({"error": "cross_site_request_rejected"}), 403
            origin = request.headers.get("Origin")
            if origin:
                try:
                    origin_parts = urlsplit(origin)
                    request_parts = urlsplit(request.host_url)
                    same_origin = (
                        origin_parts.scheme.casefold() == request_parts.scheme.casefold()
                        and origin_parts.hostname is not None
                        and request_parts.hostname is not None
                        and origin_parts.hostname.rstrip(".").casefold()
                        == request_parts.hostname.rstrip(".").casefold()
                        and (origin_parts.port or (443 if origin_parts.scheme == "https" else 80))
                        == (request_parts.port or (443 if request_parts.scheme == "https" else 80))
                    )
                except ValueError:
                    same_origin = False
                if not same_origin:
                    return jsonify({"error": "cross_site_request_rejected"}), 403
        return None

    @app.errorhandler(ValidationError)
    def validation_error(exc: ValidationError):
        return jsonify(
            {"error": "invalid_request", "details": exc.errors(include_input=False)}
        ), 400

    @app.errorhandler(ValueError)
    def value_error(exc: ValueError):
        return jsonify({"error": "invalid_operation", "details": str(exc)}), 400

    @app.errorhandler(KeyError)
    def missing_error(exc: KeyError):
        return jsonify({"error": "not_found", "details": str(exc)}), 404

    @app.errorhandler(KernelError)
    def kernel_error(exc: KernelError):
        return jsonify({"error": type(exc).__name__, "details": str(exc)}), 403

    @app.errorhandler(PermissionError)
    def permission_error(exc: PermissionError):
        return jsonify({"error": "permission_denied", "details": str(exc)}), 403

    @app.errorhandler(AuthenticationError)
    def authentication_error(exc: AuthenticationError):
        return jsonify({"error": "authentication_failed", "details": str(exc)}), 401

    @app.post("/api/v2/auth/login")
    def login():
        body = LoginRequest.model_validate(request.get_json(force=True))
        user, token = identity.login(
            body.username,
            body.password,
            user_agent=request.user_agent.string,
            remote_address=request.remote_addr,
        )
        response = make_response(jsonify({"user": user_payload(user)}))
        return session_cookie(response, token, expires_at=user.session_expires_at)

    @app.get("/api/v2/auth/session")
    def auth_session():
        return jsonify({"user": user_payload(current_user())})

    @app.post("/api/v2/auth/logout")
    def logout():
        identity.logout(request.cookies.get("ttdm_session"))
        return clear_session_cookie(make_response("", 204))

    @app.post("/api/v2/auth/change-password")
    def change_password():
        body = ChangePasswordRequest.model_validate(request.get_json(force=True))
        user, token = identity.change_password(
            current_user(),
            body.current_password,
            body.new_password,
            user_agent=request.user_agent.string,
            remote_address=request.remote_addr,
        )
        response = make_response(jsonify({"user": user_payload(user)}))
        return session_cookie(response, token, expires_at=user.session_expires_at)

    @app.get("/api/v2/profile")
    def profile_detail():
        return jsonify({"user": user_payload(current_user())})

    @app.put("/api/v2/profile")
    def profile_update():
        body = ProfileRequest.model_validate(request.get_json(force=True))
        account = identity.update_profile(current_user(), body.profile())
        return jsonify({"user": user_payload(account)})

    @app.get("/api/v2/admin/users")
    def admin_users():
        return jsonify(
            {"items": [user_payload(user) for user in identity.list_users(current_user())]}
        )

    @app.post("/api/v2/admin/users")
    def admin_user_create():
        body = AdminUserCreateRequest.model_validate(request.get_json(force=True))
        account = identity.create_user(
            current_user(),
            username=body.username,
            temporary_password=body.temporary_password,
            profile=body.profile.profile(),
        )
        return jsonify({"user": user_payload(account)}), 201

    @app.patch("/api/v2/admin/users/<uuid:user_id>")
    def admin_user_update(user_id: uuid.UUID):
        body = AdminUserUpdateRequest.model_validate(request.get_json(force=True))
        account = identity.update_user(
            current_user(),
            user_id,
            username=body.username,
            is_active=body.is_active,
            profile=body.profile.profile() if body.profile else None,
        )
        return jsonify({"user": user_payload(account)})

    @app.delete("/api/v2/admin/users/<uuid:user_id>")
    def admin_user_delete(user_id: uuid.UUID):
        identity.delete_user(current_user(), user_id)
        return "", 204

    @app.put("/api/v2/admin/users/<uuid:user_id>/password")
    def admin_user_password(user_id: uuid.UUID):
        body = PasswordResetRequest.model_validate(request.get_json(force=True))
        identity.reset_password(current_user(), user_id, body.temporary_password)
        return "", 204

    @app.put("/api/v2/admin/users/<uuid:user_id>/roles")
    def admin_user_global_roles(user_id: uuid.UUID):
        body = GlobalRolesRequest.model_validate(request.get_json(force=True))
        account = identity.set_global_roles(current_user(), user_id, frozenset(body.roles))
        return jsonify({"user": user_payload(account)})

    @app.put("/api/v2/admin/users/<uuid:user_id>/worlds/<uuid:world_id>/roles")
    def admin_user_world_roles(user_id: uuid.UUID, world_id: uuid.UUID):
        body = WorldRolesRequest.model_validate(request.get_json(force=True))
        account = identity.set_world_roles(
            current_user(),
            user_id,
            world_id,
            frozenset(body.roles),
        )
        return jsonify({"user": user_payload(account)})

    @app.get("/api/v2/admin/audit")
    def admin_audit():
        IdentityService.require_admin(current_user())
        return jsonify({"items": identity_repository.audit_entries(200)})

    @app.get("/api/v2/player/characters")
    def player_characters():
        return jsonify(
            {
                "items": [
                    row.model_dump(mode="json") for row in portal.list_characters(current_user())
                ]
            }
        )

    @app.post("/api/v2/player/characters")
    def player_character_create():
        body = CharacterCreateRequest.model_validate(request.get_json(force=True))
        row = portal.create_character(current_user(), body.model_dump(exclude_none=True))
        return _json(row, 201)

    @app.patch("/api/v2/player/characters/<uuid:character_id>")
    def player_character_update(character_id: uuid.UUID):
        body = CharacterUpdateRequest.model_validate(request.get_json(force=True))
        return _json(
            portal.update_character(
                current_user(), character_id, body.model_dump(exclude_none=True)
            )
        )

    @app.delete("/api/v2/player/characters/<uuid:character_id>")
    def player_character_delete(character_id: uuid.UUID):
        portal.delete_character(current_user(), character_id)
        return "", 204

    @app.get("/api/v2/games")
    def games_list():
        return jsonify(
            {"items": [row.model_dump(mode="json") for row in portal.list_games(current_user())]}
        )

    @app.get("/api/v2/dm/worlds/<uuid:world_id>/eligible-users")
    def dm_eligible_users(world_id: uuid.UUID):
        actor = current_user()
        IdentityService.require_world_role(actor, world_id, "DM")
        rows = [
            user_payload(account)
            for account in identity_repository.list_accounts()
            if account.is_active and account.roles_for(world_id).intersection({"DM", "PLAYER"})
        ]
        return jsonify({"items": rows})

    @app.post("/api/v2/dm/games")
    def dm_game_create():
        body = GameCreateRequest.model_validate(request.get_json(force=True))
        return _json(portal.create_game(current_user(), body.model_dump(exclude_none=True)), 201)

    @app.patch("/api/v2/dm/games/<uuid:game_id>")
    def dm_game_update(game_id: uuid.UUID):
        body = GameUpdateRequest.model_validate(request.get_json(force=True))
        return _json(
            portal.update_game(current_user(), game_id, body.model_dump(exclude_none=True))
        )

    @app.delete("/api/v2/dm/games/<uuid:game_id>")
    def dm_game_delete(game_id: uuid.UUID):
        portal.delete_game(current_user(), game_id)
        return "", 204

    @app.put("/api/v2/dm/games/<uuid:game_id>/members")
    def dm_game_member(game_id: uuid.UUID):
        body = GameMemberRequest.model_validate(request.get_json(force=True))
        return _json(portal.set_member(current_user(), game_id, body.model_dump(mode="json")))

    @app.delete("/api/v2/dm/games/<uuid:game_id>/members/<uuid:user_id>")
    def dm_game_member_delete(game_id: uuid.UUID, user_id: uuid.UUID):
        portal.remove_member(current_user(), game_id, user_id)
        return "", 204

    @app.get("/api/v2/games/<uuid:game_id>/sessions")
    def game_sessions(game_id: uuid.UUID):
        return jsonify(
            {
                "items": [
                    row.model_dump(mode="json")
                    for row in portal.list_sessions(current_user(), game_id)
                ]
            }
        )

    @app.post("/api/v2/dm/games/<uuid:game_id>/sessions")
    def dm_game_session_create(game_id: uuid.UUID):
        body = GameSessionRequest.model_validate(request.get_json(force=True))
        return _json(
            portal.save_session(current_user(), game_id, body.model_dump(exclude_none=True)), 201
        )

    @app.patch("/api/v2/dm/games/<uuid:game_id>/sessions/<uuid:session_id>")
    def dm_game_session_update(game_id: uuid.UUID, session_id: uuid.UUID):
        body = GameSessionRequest.model_validate(request.get_json(force=True))
        return _json(
            portal.save_session(
                current_user(), game_id, body.model_dump(exclude_none=True), session_id
            )
        )

    @app.get("/healthz")
    @app.get("/api/v2/health/live")
    def live():
        return jsonify({"status": "live", "live": True})

    @app.get("/readyz")
    @app.get("/api/v2/health/ready")
    def ready():
        checks: dict[str, Any] = {}
        if database_dsn:
            try:
                row = execute_one(
                    """
                    SELECT version FROM infra_meta.schema_migrations
                    ORDER BY version DESC LIMIT 1
                    """,
                    dsn=database_dsn,
                )
                version = row["version"] if row else None
                checks["postgres"] = {
                    "ok": version == "002_identity_and_tabletop_workspaces.sql",
                    "migration": version,
                }
            except Exception as exc:
                checks["postgres"] = {"ok": False, "error": type(exc).__name__}
        else:
            checks["postgres"] = {"ok": True, "mode": "local_reference"}

        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            try:
                from redis import Redis

                checks["redis"] = {"ok": bool(Redis.from_url(redis_url).ping())}
            except Exception as exc:
                checks["redis"] = {"ok": False, "error": type(exc).__name__}
        else:
            checks["redis"] = {"ok": True, "mode": "not_configured"}

        qdrant_url = os.environ.get("QDRANT_URL")
        if qdrant_url:
            try:
                with urlopen(qdrant_url.rstrip("/") + "/readyz", timeout=2) as response:
                    checks["qdrant"] = {"ok": response.status == 200}
            except URLError as exc:
                checks["qdrant"] = {"ok": False, "error": type(exc).__name__}
        else:
            checks["qdrant"] = {"ok": True, "mode": "not_configured"}
        is_ready = all(bool(value.get("ok")) for value in checks.values())
        return jsonify(
            {
                "status": "ready" if is_ready else "not_ready",
                "ready": is_ready,
                "storage_mode": "postgres" if database_dsn else "local_reference",
                "checks": checks,
                "worlds": len(simulation.worlds),
                "command_contracts": len(simulation.bus.contracts()),
            }
        ), (200 if is_ready else 503)

    @app.get("/api/v2/meta")
    def meta():
        return jsonify(
            {
                "contract_version": "2.0.0",
                "kernel": "tabletop-simulation-kernel",
                "persona_schema_version": registry.VERSION,
                "persona_dimensions": len(registry.dimensions),
                "telemetry_enabled": telemetry_settings.get().human_telemetry_enabled,
                "migrations_from_v1_supported": False,
                "modes": ["LIVE", "POPULATION", "EVALUATION"],
                "invariants": [
                    "models_never_own_world_truth",
                    "persona_is_runtime_independent",
                    "trial_branches_cannot_mutate_canonical_state",
                    "synthetic_results_are_hypotheses",
                ],
            }
        )

    @app.get("/api/v2/bootstrap")
    def bootstrap():
        world = simulation.worlds[demo["world_id"]]
        run = simulation.runs[demo["run_id"]]
        return jsonify(
            {
                "ids": {key: str(value) for key, value in demo.items()},
                "world": world.model_dump(mode="json"),
                "run": run.model_dump(mode="json"),
                "command_contracts": simulation.bus.contracts(),
            }
        )

    @app.route("/api/v2/worlds", methods=["GET", "POST"])
    def worlds():
        if request.method == "GET":
            return jsonify(
                [
                    world_payload(world)
                    for world in sorted(simulation.worlds.values(), key=lambda item: item.name)
                ]
            )
        IdentityService.require_admin(current_user())
        body = WorldCreateRequest.model_validate(request.get_json(silent=True) or {})
        creator_id = current_actor_id()
        creator = simulation.authority(demo["world_id"], creator_id)
        world = simulation.create_world(body.name, body.slug)
        simulation.grant_authority(
            world.world_id,
            creator_id,
            roles=creator.roles,
            capabilities=creator.capabilities,
            controlled_entity_ids=set(),
        )
        if durable_control:
            durable_control.sync(simulation)
            identity.sync_admin_world(world.world_id)
        return jsonify(world_payload(world)), 201

    @app.get("/api/v2/worlds/<uuid:world_id>")
    def world_detail(world_id: uuid.UUID):
        world = simulation.worlds[world_id]
        state = simulation.states.get(world.canonical_branch_id)
        return jsonify(
            {
                **world.model_dump(mode="json"),
                "state_hash": state.state_hash,
                "projection_version": state.version,
                "projections": state.projections,
            }
        )

    @app.route("/api/v2/actors", methods=["GET", "POST"])
    def actors():
        if request.method == "GET":
            return jsonify([item.model_dump(mode="json") for item in simulation.actors.values()])
        body = ActorCreateRequest.model_validate(request.get_json(silent=True) or {})
        actor = simulation.create_actor(
            body.display_name,
            body.kind,
            body.roles,
            body.capabilities,
            set(),
            world_id=body.world_id or demo["world_id"],
        )
        if durable_control:
            durable_control.sync(simulation)
        return _json(actor, 201)

    @app.get("/api/v2/worlds/<uuid:world_id>/actors")
    def world_actors(world_id: uuid.UUID):
        if world_id not in simulation.worlds:
            raise KeyError(world_id)
        return jsonify(
            [item.model_dump(mode="json") for item in simulation.authorities_for_world(world_id)]
        )

    @app.route("/api/v2/worlds/<uuid:world_id>/entities", methods=["GET", "POST"])
    def entities(world_id: uuid.UUID):
        world = simulation.worlds[world_id]
        if request.method == "GET":
            projected = simulation.states.get(world.canonical_branch_id).projections.get(
                "tabletop.entities", {}
            )
            values = []
            for (branch_id, entity_id), entity in simulation.entities.items():
                if branch_id != world.canonical_branch_id:
                    continue
                payload = entity.model_dump(mode="json", exclude={"secret_state"})
                current = dict(projected.get(str(entity_id), {}))
                current.pop("name", None)
                current.pop("entity_type", None)
                payload["public_state"] = current
                if "x" in current and "y" in current:
                    payload["location"] = f"({current['x']}, {current['y']})"
                payload["health"] = current.get("hp")
                payload["max_health"] = current.get("max_hp")
                payload["status"] = "DEFEATED" if current.get("defeated") else "ACTIVE"
                values.append(payload)
            return jsonify(values)
        body = EntityCreateRequest.model_validate(request.get_json(silent=True) or {})
        if (
            body.controller_actor_id is not None
            and (world_id, body.controller_actor_id) not in simulation.world_authorities
        ):
            raise ValueError("controller actor has no authority in this world")
        entity_id = uuid.uuid4()
        actor_id = current_actor_id()
        live_run = next(
            item
            for item in simulation.runs.values()
            if item.world_id == world_id
            and item.branch_id == world.canonical_branch_id
            and item.kind is RunKind.LIVE
        )
        receipt = simulation.submit(
            CommandProposal(
                command_type="tabletop.entity.spawn",
                world_id=world_id,
                branch_id=world.canonical_branch_id,
                run_id=live_run.run_id,
                actor_id=actor_id,
                parameters={
                    "entity_id": entity_id,
                    "name": body.name,
                    "entity_type": body.entity_type,
                    "public_state": body.public_state,
                    "secret_state": body.secret_state,
                    "controller_actor_id": body.controller_actor_id,
                },
                idempotency_key=f"entity-spawn:{entity_id}",
            )
        )
        entity = simulation.entities[(world.canonical_branch_id, entity_id)]
        payload = entity.model_dump(mode="json", exclude={"secret_state"})
        payload["creation_event_id"] = str(receipt.event.event_id)
        payload["state_hash"] = receipt.state_hash
        return jsonify(payload), 201

    @app.route("/api/v2/runs", methods=["GET", "POST"])
    def runs():
        if request.method == "POST":
            body = RunCreateRequest.model_validate(request.get_json(silent=True) or {})
            actor_id = current_actor_id()
            actor = simulation.authority(body.world_id, actor_id)
            if "run.branch" not in actor.capabilities:
                raise PermissionError("actor cannot create runs in this world")
            branch_id = body.branch_id or simulation.worlds[body.world_id].canonical_branch_id
            run = simulation.create_run(body.world_id, branch_id, body.kind, seed=body.seed)
            if durable_control:
                durable_control.sync(simulation)
            return jsonify(run_payload(run)), 201
        world_id = request.args.get("world_id")
        return jsonify(
            [
                run_payload(item)
                for item in simulation.runs.values()
                if world_id is None or str(item.world_id) == world_id
            ]
        )

    @app.get("/api/v2/worlds/<uuid:world_id>/runs")
    def world_runs(world_id: uuid.UUID):
        return jsonify(
            [run_payload(item) for item in simulation.runs.values() if item.world_id == world_id]
        )

    @app.get("/api/v2/branches")
    def branches():
        world_id = request.args.get("world_id")
        return jsonify(
            [
                branch_payload(item)
                for item in simulation.states.all()
                if world_id is None or str(item.world_id) == world_id
            ]
        )

    @app.get("/api/v2/snapshots")
    def all_snapshots():
        world_id = request.args.get("world_id")
        return jsonify(
            [
                snapshot_payload(item)
                for item in simulation.snapshots.values()
                if world_id is None or str(item.world_id) == world_id
            ]
        )

    @app.get("/api/v2/commands/contracts")
    def command_contracts():
        return jsonify(simulation.bus.contracts())

    @app.post("/api/v2/commands")
    def submit_command():
        payload = request.get_json(silent=True) or {}
        payload.setdefault("world_id", str(demo["world_id"]))
        payload.setdefault("branch_id", str(demo["branch_id"]))
        payload.setdefault("run_id", str(demo["run_id"]))
        payload.setdefault("actor_id", str(demo["actor_id"]))
        payload.setdefault("idempotency_key", str(uuid.uuid4()))
        proposal = CommandProposal.model_validate(payload)
        receipt = simulation.submit(proposal)
        return jsonify(
            {
                "result": receipt.result.model_dump(mode="json"),
                "event": receipt.event.model_dump(mode="json"),
                "state_hash": receipt.state_hash,
            }
        )

    @app.get("/api/v2/events")
    def events():
        actor_id = uuid.UUID(request.args.get("actor_id", str(demo["actor_id"])))
        world_id = request.args.get("world_id")
        branch_id = request.args.get("branch_id")
        return jsonify(
            [
                event.model_dump(mode="json")
                for event in simulation.visible_events(actor_id)
                if (world_id is None or str(event.world_id) == world_id)
                and (branch_id is None or str(event.branch_id) == branch_id)
            ]
        )

    @app.post("/api/v2/cognition/decide")
    def cognition_decide():
        body = CognitionDecisionApiRequest.model_validate(request.get_json(silent=True) or {})
        world_id = body.world_id or demo["world_id"]
        branch_id = body.branch_id or simulation.worlds[world_id].canonical_branch_id
        run_id = body.run_id or next(
            item.run_id for item in simulation.runs.values() if item.branch_id == branch_id
        )
        actor_id = body.actor_id or demo["actor_id"]
        actor = simulation.authority(world_id, actor_id)
        run = simulation.runs.get(run_id)
        if run is None or (run.world_id, run.branch_id) != (world_id, branch_id):
            raise ValueError("cognition run does not belong to the world branch")
        embodied = simulation.entities.get((branch_id, body.embodied_entity_id))
        if embodied is None or embodied.world_id != world_id:
            raise ValueError("cognition entity is not embodied in the world branch")
        if (
            body.embodied_entity_id not in actor.controlled_entity_ids
            and "mind.write.all" not in actor.capabilities
        ):
            raise PermissionError("actor cannot make decisions for this embodied mind")
        runtime_assignment = minds.runtime_assignment(
            world_id=world_id,
            branch_id=branch_id,
            run_id=run_id,
            entity_id=body.embodied_entity_id,
        )
        allow_llm = body.allow_llm
        llm_runtime_kind: Literal["LOCAL_LLM", "HOSTED_LLM"] = "HOSTED_LLM"
        planning_goal = body.planning_goal
        planning_actions = body.planning_actions
        if runtime_assignment is not None:
            runtime_kind = runtime_assignment.runtime_kind
            if runtime_kind in {"HUMAN", "REPLAY"}:
                raise PermissionError(
                    f"{runtime_kind} runtime assignments cannot make automatic decisions"
                )
            if runtime_kind in {"DETERMINISTIC", "UTILITY"}:
                planning_goal = {}
                planning_actions = ()
                allow_llm = False
            elif runtime_kind == "PLANNER":
                allow_llm = False
            elif runtime_kind == "LOCAL_LLM":
                allow_llm = True
                llm_runtime_kind = "LOCAL_LLM"
            elif runtime_kind == "HOSTED_LLM":
                allow_llm = True
                llm_runtime_kind = "HOSTED_LLM"
        key = body.idempotency_key or (
            "cognition:"
            + str(uuid.uuid5(uuid.NAMESPACE_URL, body.model_dump_json(exclude_none=True)))
        )
        outcome = decision_engine.decide(
            DecisionRequest(
                persona=compiled_persona(body.persona_id),
                world_id=world_id,
                branch_id=branch_id,
                run_id=run_id,
                actor_id=actor_id,
                embodied_entity_id=body.embodied_entity_id,
                seed=body.seed,
                idempotency_key=key,
                situation=body.situation,
                actions=body.actions,
                utility_margin=body.utility_margin,
                novel_or_ambiguous=body.novel_or_ambiguous,
                allow_llm=allow_llm,
                llm_runtime_kind=llm_runtime_kind,
                reflex_rules=body.reflex_rules,
                planning_goal=planning_goal,
                planning_actions=planning_actions,
                planner_max_depth=body.planner_max_depth,
                planner_max_nodes=body.planner_max_nodes,
            )
        )
        if mind_repository is not None:
            mind_repository.save_decision(outcome)
        minds.record_decision(outcome)
        return jsonify(
            {
                "tier": outcome.tier,
                "trace": outcome.trace.model_dump(mode="json"),
                "proposal": outcome.proposal.model_dump(mode="json"),
                "runtime_assignment": (
                    runtime_assignment.model_dump(mode="json")
                    if runtime_assignment is not None
                    else None
                ),
                "committed": False,
            }
        ), 201

    @app.route(
        "/api/v2/entities/<uuid:entity_id>/runtime",
        methods=["GET", "PUT"],
    )
    def cognition_runtime(entity_id: uuid.UUID):
        payload = (
            request.args.to_dict()
            if request.method == "GET"
            else request.get_json(silent=True) or {}
        )
        if request.method == "GET":
            scope = RuntimeScopeRequest.model_validate(payload)
            assignment_request = None
        else:
            assignment_request = RuntimeAssignmentRequest.model_validate(payload)
            scope = RuntimeScopeRequest.model_validate(assignment_request.model_dump())
        run = simulation.runs.get(scope.run_id)
        if run is None or (run.world_id, run.branch_id) != (
            scope.world_id,
            scope.branch_id,
        ):
            raise ValueError("runtime run does not belong to the world branch")
        entity = simulation.entities.get((scope.branch_id, entity_id))
        if entity is None or entity.world_id != scope.world_id:
            raise ValueError("runtime entity is not embodied in the world branch")
        actor_id = current_actor_id()
        actor = simulation.authority(scope.world_id, actor_id)
        if (
            entity_id not in actor.controlled_entity_ids
            and "mind.write.all" not in actor.capabilities
        ):
            raise PermissionError("actor cannot manage this entity's runtime")
        existing = minds.runtime_assignment(
            world_id=scope.world_id,
            branch_id=scope.branch_id,
            run_id=scope.run_id,
            entity_id=entity_id,
        )
        if request.method == "GET":
            if existing is None:
                raise KeyError((scope.world_id, scope.branch_id, scope.run_id, entity_id))
            return _json(existing)
        if assignment_request is None:  # pragma: no cover - narrowed by request method
            raise RuntimeError("runtime assignment request was not validated")
        assignment = RuntimeAssignment(
            world_id=scope.world_id,
            branch_id=scope.branch_id,
            run_id=scope.run_id,
            entity_id=entity_id,
            runtime_kind=assignment_request.runtime_kind,
            runtime_config=assignment_request.runtime_config,
        )
        if mind_repository is not None:
            assignment = mind_repository.save_runtime_assignment(
                assignment,
                actor_id=actor_id,
            )
        minds.set_runtime_assignment(assignment)
        return _json(assignment, 200 if existing is not None else 201)

    @app.post("/api/v2/events/<uuid:event_id>/observe")
    def cognition_observe(event_id: uuid.UUID):
        body = ObservationRequest.model_validate(request.get_json(silent=True) or {})
        event = simulation.events[event_id]
        observer_actor = simulation.authority(event.world_id, body.observer_actor_id)
        observer_entity = simulation.entities.get((event.branch_id, body.observer_entity_id))
        if observer_entity is None or observer_entity.world_id != event.world_id:
            raise ValueError("observer entity is not embodied in the event branch")
        if (
            body.observer_entity_id not in observer_actor.controlled_entity_ids
            and "mind.write.all" not in observer_actor.capabilities
        ):
            raise PermissionError("observer actor cannot update this mind")
        perception_event = event
        if (
            body.observer_actor_id not in event.visible_to
            and "world.read.all" in observer_actor.capabilities
        ):
            perception_event = event.model_copy(
                update={"visible_to": (*event.visible_to, body.observer_actor_id)}
            )
        existing = minds.get(body.observer_entity_id, branch_id=event.branch_id)
        update = subjective_pipeline.process(
            perception_event,
            PerceptionProfile(
                observer_entity_id=body.observer_entity_id,
                observer_actor_id=body.observer_actor_id,
                acuity=body.acuity,
                confidence_bias=body.confidence_bias,
                allowed_payload_fields=body.allowed_payload_fields,
                hidden_payload_fields=body.hidden_payload_fields,
            ),
            existing_beliefs=existing.beliefs,
            memory_summary=body.memory_summary,
            emotional_weight=body.emotional_weight,
            importance=body.importance,
        )
        if update.observation is None:
            return jsonify({"perceived": False, "reason": "outside_observation_scope"})
        projected = minds.preview_subjective_update(
            body.observer_entity_id, update, branch_id=event.branch_id
        )
        if mind_repository is not None:
            mind_repository.save_subjective_update(
                world_id=event.world_id,
                branch_id=event.branch_id,
                actor_id=body.observer_actor_id,
                state=projected,
                update=update,
            )
        state = minds.apply_subjective_update(
            body.observer_entity_id, update, branch_id=event.branch_id
        )
        return jsonify(
            {
                "perceived": True,
                "observation": update.observation.model_dump(mode="json"),
                "belief_revision": (
                    update.belief_revision.model_dump(mode="json")
                    if update.belief_revision is not None
                    else None
                ),
                "memory": (
                    update.memory.model_dump(mode="json") if update.memory is not None else None
                ),
                "mind_state": state.model_dump(mode="json"),
            }
        ), 201

    @app.post("/api/v2/entities/<uuid:entity_id>/relationships")
    def cognition_relationship(entity_id: uuid.UUID):
        body = RelationshipRequest.model_validate(request.get_json(silent=True) or {})
        entity = canonical_entity(entity_id)
        target = canonical_entity(body.target_entity_id)
        if (entity.world_id, entity.branch_id) != (target.world_id, target.branch_id):
            raise ValueError("relationship entities must share a world branch")
        source_event = simulation.events[body.source_event_id]
        if (source_event.world_id, source_event.branch_id) != (
            entity.world_id,
            entity.branch_id,
        ):
            raise ValueError("relationship source event must share the entity world branch")
        actor_id = current_actor_id()
        actor = simulation.authority(entity.world_id, actor_id)
        if (
            entity_id not in actor.controlled_entity_ids
            and "mind.write.all" not in actor.capabilities
        ):
            raise PermissionError("actor cannot update this entity's relationships")
        has_global_mind_write = "mind.write.all" in actor.capabilities
        if not has_global_mind_write and (
            body.deltas is not None or body.modifiers != RelationshipModifiers()
        ):
            raise PermissionError(
                "controlled actors must use deterministic relationship event mappings"
            )
        if VisibilityPolicy.event_for(source_event, actor) is None:
            raise PermissionError("relationship source event is not visible to actor")
        change_id = RelationshipChangeRecord.identity(
            world_id=entity.world_id,
            branch_id=entity.branch_id,
            source_entity_id=entity_id,
            target_entity_id=body.target_entity_id,
            source_event_id=source_event.event_id,
        )
        existing = minds.relationship_change(change_id, branch_id=entity.branch_id)
        if existing is None and mind_repository is not None:
            existing = mind_repository.get_relationship_change(change_id, actor_id=actor_id)
        before = (
            existing.before
            if existing is not None
            else minds.relationship(
                entity_id,
                body.target_entity_id,
                branch_id=entity.branch_id,
            )
        )
        change = relationship_engine.apply(
            before,
            body.event_type,
            modifiers=body.modifiers,
            deltas=body.deltas,
        )
        record = RelationshipChangeRecord.from_change(
            change,
            world_id=entity.world_id,
            branch_id=entity.branch_id,
            source_entity_id=entity_id,
            target_entity_id=body.target_entity_id,
            source_event_id=source_event.event_id,
            actor_id=actor_id,
            policy_version=relationship_engine.VERSION,
        )
        if mind_repository is not None:
            record = mind_repository.save_relationship_change(record)
        committed = minds.apply_relationship_change(record)
        return _json(committed, 201)

    @app.get("/api/v2/entities/<uuid:entity_id>/mind")
    def cognition_inspect(entity_id: uuid.UUID):
        if mind_repository is not None:
            entity = canonical_entity(entity_id)
            actor_id = uuid.UUID(request.args.get("actor_id", str(demo["actor_id"])))
            return jsonify(
                mind_repository.inspect(
                    world_id=entity.world_id,
                    branch_id=entity.branch_id,
                    entity_id=entity_id,
                    actor_id=actor_id,
                )
            )
        entity = canonical_entity(entity_id)
        return jsonify(minds.inspect(entity_id, branch_id=entity.branch_id))

    @app.route("/api/v2/worlds/<uuid:world_id>/snapshots", methods=["GET", "POST"])
    def snapshots(world_id: uuid.UUID):
        if request.method == "GET":
            return jsonify(
                [
                    snapshot_payload(item)
                    for item in simulation.snapshots.values()
                    if item.world_id == world_id
                ]
            )
        actor_id = current_actor_id()
        actor = simulation.authority(world_id, actor_id)
        if "run.branch" not in actor.capabilities:
            raise PermissionError("actor cannot snapshot this world")
        manifest = simulation.create_snapshot(world_id)
        if durable_control:
            state = simulation.states.get(manifest.branch_id)
            durable_control.persist_snapshot(manifest, state.version)
        return _json(manifest, 201)

    @app.post("/api/v2/snapshots/<uuid:snapshot_id>/branches")
    def create_branch(snapshot_id: uuid.UUID):
        body = request.get_json(silent=True) or {}
        manifest = simulation.snapshots[snapshot_id]
        world_id = uuid.UUID(str(body.get("world_id", manifest.world_id)))
        actor_id = current_actor_id()
        actor = simulation.authority(world_id, actor_id)
        if "run.branch" not in actor.capabilities:
            raise PermissionError("actor cannot create trial branches in this world")
        seed = int(body.get("seed", 101))
        branch, run = simulation.create_trial(world_id, snapshot_id, seed)
        if durable_control:
            durable_control.sync(simulation)
        return jsonify(
            {
                "branch_id": str(branch.branch_id),
                "branch_kind": branch.kind.value,
                "base_snapshot_hash": branch.base_snapshot_hash,
                "run": run.model_dump(mode="json"),
            }
        ), 201

    @app.get("/api/v2/branches/<uuid:branch_id>/replay")
    def replay(branch_id: uuid.UUID):
        state = simulation.replay(branch_id)
        return jsonify(
            {
                "branch_id": str(branch_id),
                "state_hash": state.state_hash,
                "projection_version": state.version,
                "projections": state.projections,
                "verified": state.state_hash == simulation.states.get(branch_id).state_hash,
            }
        )

    @app.post("/api/v2/branches/<uuid:branch_id>/promotions")
    def promote(branch_id: uuid.UUID):
        package = ConsequencePackage.model_validate(request.get_json(silent=True) or {})
        state = simulation.states.get(branch_id)
        if state.kind is not BranchKind.CANONICAL:
            raise ValueError("promotion target must be a canonical branch")
        source = simulation.states.get(package.source_branch_id)
        if source.kind is not BranchKind.TRIAL or source.world_id != state.world_id:
            raise ValueError("promotion source must be a trial branch in the same world")
        if source.base_snapshot_hash != package.expected_canonical_hash:
            raise ValueError("promotion package does not match the trial's immutable base")
        run = next(
            item
            for item in simulation.runs.values()
            if item.branch_id == branch_id and item.kind.value == "LIVE"
        )
        actor_id = current_actor_id()
        key = uuid.uuid5(uuid.NAMESPACE_URL, package.model_dump_json())
        receipt = simulation.submit(
            CommandProposal(
                command_type="kernel.branch.promote",
                world_id=state.world_id,
                branch_id=branch_id,
                run_id=run.run_id,
                actor_id=actor_id,
                parameters=package.model_dump(mode="json"),
                idempotency_key=f"promotion:{key}",
            )
        )
        return jsonify(
            {
                "result": receipt.result.model_dump(mode="json"),
                "event": receipt.event.model_dump(mode="json"),
                "state_hash": receipt.state_hash,
            }
        ), 201

    @app.get("/api/v2/personas/schema")
    @app.get("/api/v2/contracts/persona-schema")
    def persona_schema():
        return jsonify(
            {
                "version": registry.VERSION,
                "dimensions": [
                    item.model_dump(mode="json") for item in registry.ordered_dimensions()
                ],
            }
        )

    @app.get("/api/v2/personas")
    def persona_list():
        return jsonify([item.model_dump(mode="json") for item in personas.values()])

    @app.post("/api/v2/personas")
    def persona_create():
        body = PersonaCreateRequest.model_validate(request.get_json(silent=True) or {})
        identity = body.persona_id
        if body.parent_version_id is not None:
            parent = persona_versions[body.parent_version_id]
            if identity is not None and identity != parent.blueprint.persona_id:
                raise ValueError("parent version belongs to another persona")
            identity = parent.blueprint.persona_id
        updates: dict[str, Any] = {"source": "manual"}
        if identity is not None:
            updates["persona_id"] = identity
        blueprint = generator.generate(body.seed, body.dimensions).model_copy(update=updates)
        validation = persona_validator.validate_blueprint(blueprint)
        if validation.status != "valid":
            return jsonify(
                {"error": "invalid_persona", "validation": validation.model_dump(mode="json")}
            ), 400
        blueprint = blueprint.model_copy(update={"validation": validation})
        record = PersonaVersioning.record(blueprint, parent_version_id=body.parent_version_id)
        if persona_repository is not None:
            persona_repository.save_version(record)
        personas[blueprint.persona_id] = blueprint
        persona_versions[record.version_id] = record
        return jsonify(
            {
                "blueprint": blueprint.model_dump(mode="json"),
                "version": record.model_dump(mode="json"),
            }
        ), 201

    @app.post("/api/v2/personas/generate")
    def persona_generate():
        body = PersonaGenerateRequest.model_validate(request.get_json(silent=True) or {})
        persona = generator.generate(body.seed, body.fixed)
        if persona.validation.status != "valid":
            raise ValueError("generated persona failed validation")
        personas[persona.persona_id] = persona
        version = PersonaVersioning.record(persona)
        if persona_repository is not None:
            persona_repository.save_version(version)
        persona_versions[version.version_id] = version
        return _json(persona, 201)

    @app.get("/api/v2/personas/<uuid:persona_id>")
    def persona_detail(persona_id: uuid.UUID):
        return _json(personas[persona_id])

    @app.post("/api/v2/personas/<uuid:persona_id>/compile")
    def persona_compile(persona_id: uuid.UUID):
        return _json(compiled_persona(persona_id))

    @app.post("/api/v2/personas/<uuid:persona_id>/prompt")
    def persona_prompt(persona_id: uuid.UUID):
        body = PromptRequest.model_validate(request.get_json(silent=True) or {})
        compiled = compiled_persona(persona_id)
        return _json(
            compiler.assemble_prompt(
                compiled,
                situation_summary=body.situation_summary,
                relevant_traits=body.relevant_traits,
                max_tokens=body.max_tokens,
                max_characters=body.max_characters,
            )
        )

    @app.get("/api/v2/personas/<uuid:persona_id>/versions")
    def persona_version_list(persona_id: uuid.UUID):
        return jsonify(
            [
                item.model_dump(mode="json")
                for item in persona_versions.values()
                if item.blueprint.persona_id == persona_id
            ]
        )

    @app.route("/api/v2/populations", methods=["GET", "POST"])
    @app.get("/api/v2/populations/definitions")
    def population_definitions():
        if request.method == "GET":
            return jsonify([population_payload(item) for item in populations.values()])
        body = PopulationGenerateRequest.model_validate(request.get_json(silent=True) or {})
        world_id, branch_id = new_population_target(body.world_id, body.branch_id)
        population_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:population:{world_id}:{branch_id}:{body.name}:{body.seed}:{body.size}",
        )
        path = root / "populations" / f"{population_id}.parquet"
        store = PopulationStore(path)
        store.generate(body.size, body.seed)
        pool_size = store.count()
        record = {
            "population_id": str(population_id),
            "name": body.name,
            "size": pool_size,
            "seed": body.seed,
            "artifact": str(path),
            "status": "READY",
            "schema_version": registry.VERSION,
            "world_id": str(world_id),
            "branch_id": str(branch_id),
            "materialized": 0,
            "active": 0,
            "dimensions": {},
            "_materialized_ids": [],
            "_active_ids": [],
        }
        populations[population_id] = record
        population_lifecycles[population_id] = PopulationLifecycle(world_id, branch_id)
        if population_repository is not None:
            record = population_repository.save_pool(
                population_id=population_id,
                name=body.name,
                size=pool_size,
                seed=body.seed,
                schema_version=registry.VERSION,
                path=path,
                world_id=world_id,
                branch_id=branch_id,
            )
            populations[population_id] = record
        return jsonify(population_payload(record)), 201

    @app.post("/api/v2/populations/generate")
    def population_generate_alias():
        return population_definitions()

    @app.post("/api/v2/populations/<uuid:population_id>/sample")
    def population_sample(population_id: uuid.UUID):
        body = PopulationSampleRequest.model_validate(request.get_json(silent=True) or {})
        record = populations[population_id]
        store = PopulationStore(Path(record["artifact"]))
        rows = store.sample_stratified(body.strata, body.per_cell, body.seed, body.filters)
        items = [
            {
                "persona_id": row["persona_id"],
                "seed": row["seed"],
                "dimensions": json.loads(row["dimensions_json"]),
            }
            for row in rows
        ]
        return jsonify(
            {
                "population_id": str(population_id),
                "count": len(rows),
                "rows": rows,
                "items": items,
            }
        )

    @app.post("/api/v2/populations/<uuid:population_id>/cohorts/feasibility")
    def population_feasibility(population_id: uuid.UUID):
        definition = CohortDefinition.model_validate(request.get_json(silent=True) or {})
        record = populations[population_id]
        report = PopulationStore(Path(record["artifact"])).cohort_feasibility(definition)
        return _json(report)

    @app.post("/api/v2/populations/<uuid:population_id>/materialize")
    def population_materialize(population_id: uuid.UUID):
        payload = request.get_json(silent=True) or {}
        if "count" in payload:
            bulk = PopulationBulkRequest.model_validate(payload)
            record = populations[population_id]
            world_id, branch_id = population_target(record, bulk.world_id, bulk.branch_id)
            lifecycle = population_lifecycles[population_id]
            rows = PopulationStore(Path(record["artifact"])).sample_stratified(
                (), bulk.count, int(record["seed"])
            )
            materialized_ids: list[str] = record["_materialized_ids"]
            start_step = (
                max((transition.world_step for transition in lifecycle.history), default=-1) + 1
            )
            for index, row in enumerate(rows):
                persona_id = uuid.UUID(row["persona_id"])
                if str(persona_id) in materialized_ids:
                    continue
                blueprint = generator.generate(int(row["seed"]))
                version = PersonaVersioning.record(blueprint)
                if persona_repository is not None:
                    persona_repository.save_version(version)
                personas[persona_id] = blueprint
                persona_versions[version.version_id] = version
                member = lifecycle.materialize(
                    persona_id,
                    profile=blueprint.dimensions,
                    world_step=start_step + index,
                    world_id=world_id,
                    branch_id=branch_id,
                )
                if population_repository is not None:
                    population_repository.save_materialized(
                        population_id=population_id,
                        version=version,
                        member=member,
                        transition=lifecycle.history[-1],
                    )
                materialized_ids.append(str(persona_id))
            record["materialized"] = len(materialized_ids)
            return jsonify(
                {
                    "materialized": record["materialized"],
                    "world_id": str(world_id),
                    "branch_id": str(branch_id),
                }
            ), 201
        materialization = MaterializeRequest.model_validate(payload)
        record = populations[population_id]
        world_id, branch_id = population_target(
            record, materialization.world_id, materialization.branch_id
        )
        version = ensure_population_version(
            record, materialization.persona_id, materialization.profile
        )
        lifecycle = population_lifecycles[population_id]
        member = lifecycle.materialize(
            materialization.persona_id,
            profile=materialization.profile,
            persistent_state=materialization.persistent_state,
            world_step=materialization.world_step,
            world_id=world_id,
            branch_id=branch_id,
        )
        if str(materialization.persona_id) not in record["_materialized_ids"]:
            record["_materialized_ids"].append(str(materialization.persona_id))
        record["materialized"] = len(record["_materialized_ids"])
        if population_repository is not None:
            population_repository.save_materialized(
                population_id=population_id,
                version=version,
                member=member,
                transition=lifecycle.history[-1],
            )
        return _json(member, 201)

    @app.post("/api/v2/populations/<uuid:population_id>/activate")
    def population_activate_bulk(population_id: uuid.UUID):
        body = PopulationBulkRequest.model_validate(request.get_json(silent=True) or {})
        record = populations[population_id]
        world_id, branch_id = population_target(record, body.world_id, body.branch_id)
        lifecycle = population_lifecycles[population_id]
        active_ids: list[str] = record["_active_ids"]
        candidates = [
            identity for identity in record["_materialized_ids"] if identity not in active_ids
        ][: body.count]
        start_step = (
            max((transition.world_step for transition in lifecycle.history), default=-1) + 1
        )
        for offset, identity in enumerate(candidates):
            member = lifecycle.activate(
                uuid.UUID(identity),
                active_state={"attention_budget": 100, "activation_reason": "ui_request"},
                world_step=start_step + offset,
            )
            if population_repository is not None:
                population_repository.save_transition(
                    population_id=population_id,
                    member=member,
                    transition=lifecycle.history[-1],
                    activation_state="ACTIVE",
                )
            active_ids.append(identity)
        record["active"] = len(active_ids)
        return jsonify(
            {
                "active": record["active"],
                "world_id": str(world_id),
                "branch_id": str(branch_id),
            }
        ), 201

    @app.get("/api/v2/populations/<uuid:population_id>/members/<uuid:persona_id>")
    def population_member(population_id: uuid.UUID, persona_id: uuid.UUID):
        return _json(population_lifecycles[population_id].get(persona_id))

    @app.post("/api/v2/populations/<uuid:population_id>/members/<uuid:persona_id>/activate")
    def population_activate(population_id: uuid.UUID, persona_id: uuid.UUID):
        body = ActivateRequest.model_validate(request.get_json(silent=True) or {})
        record = populations[population_id]
        population_target(record, body.world_id, body.branch_id)
        lifecycle = population_lifecycles[population_id]
        member = lifecycle.activate(
            persona_id,
            active_state=body.active_state,
            world_step=body.world_step,
        )
        if str(persona_id) not in record["_active_ids"]:
            record["_active_ids"].append(str(persona_id))
        record["active"] = len(record["_active_ids"])
        if population_repository is not None:
            population_repository.save_transition(
                population_id=population_id,
                member=member,
                transition=lifecycle.history[-1],
                activation_state="ACTIVE",
            )
        return _json(member)

    @app.post("/api/v2/populations/<uuid:population_id>/members/<uuid:persona_id>/deactivate")
    def population_deactivate(population_id: uuid.UUID, persona_id: uuid.UUID):
        body = DeactivateRequest.model_validate(request.get_json(silent=True) or {})
        record = populations[population_id]
        population_target(record, body.world_id, body.branch_id)
        lifecycle = population_lifecycles[population_id]
        member = lifecycle.deactivate(
            persona_id,
            world_step=body.world_step,
            compressed_state=body.compressed_state,
        )
        if str(persona_id) in record["_active_ids"]:
            record["_active_ids"].remove(str(persona_id))
        record["active"] = len(record["_active_ids"])
        if population_repository is not None:
            population_repository.save_transition(
                population_id=population_id,
                member=member,
                transition=lifecycle.history[-1],
                activation_state="COMPRESSED",
            )
        return _json(member)

    @app.get("/api/v2/populations/<uuid:population_id>/transitions")
    def population_transitions(population_id: uuid.UUID):
        return jsonify(
            [item.model_dump(mode="json") for item in population_lifecycles[population_id].history]
        )

    @app.route("/api/v2/scenarios", methods=["GET", "POST"])
    def scenario_list():
        if request.method == "GET":
            return jsonify(
                [
                    {**item.model_dump(mode="json"), "status": "ACTIVE"}
                    for item in scenarios.values()
                ]
            )
        definition = ScenarioDefinition.model_validate(request.get_json(silent=True) or {})
        key = (definition.scenario_id, definition.version)
        if key in scenarios:
            raise ValueError("scenario version already exists")
        trial_repository.save_scenario(definition)
        experiment_history.save_scenario(definition)
        scenarios[key] = definition
        return _json(definition, 201)

    report_artifact_ids: dict[uuid.UUID, uuid.UUID] = {}

    def persist_job(record: Any) -> None:
        experiment_history.save_job(record)
        if experiment_repository is not None:
            result = record.result or {}
            report_id = result.get("report_id") if isinstance(result, dict) else None
            artifact_id = report_artifact_ids.get(uuid.UUID(str(report_id))) if report_id else None
            experiment_repository.save_job(record, result_artifact_id=artifact_id)

    def persist_trial(output: TrialOutput, *, catalog: bool) -> None:
        existing = trials.get(output.trial_id)
        if existing is not None and existing != output:
            raise ValueError("immutable trial output differs from durable history")
        experiment_history.save_trial(output)
        trials[output.trial_id] = output
        if catalog and experiment_repository is not None:
            experiment_repository.save_trial_artifact(output)

    def persist_report(report: Any) -> uuid.UUID:
        report_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:cohort-report:{report.model_dump_json()}",
        )
        existing = reports.get(report_id)
        if existing is not None and existing != report:
            raise ValueError("immutable cohort report differs from durable history")
        reports[report_id] = report
        experiment_history.save_report(report_id, report)
        if experiment_repository is not None:
            artifact_id = experiment_repository.save_report(report_id, report)
            if artifact_id is not None:
                report_artifact_ids[report_id] = artifact_id
        return report_id

    def checkpoint_trial(
        context: JobContext,
        completed: int,
        total: int,
        output: TrialOutput,
        *,
        catalog: bool,
    ) -> None:
        persist_trial(output, catalog=catalog)
        checkpoint = context.checkpoint(
            {"completed_trials": completed, "last_trial_id": str(output.trial_id)},
            min(0.99, completed / max(1, total)),
        )
        persist_job(checkpoint)

    def execute_onboarding(context: JobContext) -> dict[str, Any]:
        body = OnboardingRunRequest.model_validate(context.request)
        report = onboarding.run_cohort(
            body.cohort_size,
            body.seeds,
            body.include_trials,
            on_trial=lambda completed, total, output: checkpoint_trial(
                context, completed, total, output, catalog=True
            ),
        )
        report_id = persist_report(report)
        return {"report_id": str(report_id), "report": report.model_dump(mode="json")}

    def select_scenario(scenario_id: str, version: str | None) -> ScenarioDefinition:
        canonical_id = (
            "player-onboarding" if scenario_id == "tabletop.player-onboarding" else scenario_id
        )
        matches = [
            definition
            for (candidate_id, candidate_version), definition in scenarios.items()
            if candidate_id == canonical_id and (version is None or candidate_version == version)
        ]
        if not matches:
            suffix = f"@{version}" if version else ""
            raise KeyError(f"Unknown scenario {canonical_id}{suffix}")
        return max(matches, key=lambda item: scenario_version_key(item.version))

    def generic_persona(persona_seed: int, _index: int) -> tuple[uuid.UUID, str]:
        blueprint = generator.generate(persona_seed)
        version = PersonaVersioning.record(blueprint)
        personas[blueprint.persona_id] = blueprint
        persona_versions[version.version_id] = version
        if persona_repository is not None:
            persona_repository.save_version(version)
        return blueprint.persona_id, str(version.version_id)

    def snapshot_reference(definition: ScenarioDefinition) -> SnapshotReference:
        if definition.base_snapshot_id is None:
            manifest = simulation.create_snapshot(demo["world_id"])
            if durable_control is not None:
                state = simulation.states.get(manifest.branch_id)
                durable_control.persist_snapshot(manifest, state.version)
        else:
            manifest = simulation.snapshots[definition.base_snapshot_id]
        return SnapshotReference(
            snapshot_id=manifest.snapshot_id,
            world_id=manifest.world_id,
            canonical_branch_id=manifest.branch_id,
            state_hash=manifest.state_hash,
            contract_version=manifest.contract_version,
        )

    def execute_generic(context: JobContext) -> dict[str, Any]:
        body = ScenarioRunRequest.model_validate(context.request)
        scenario_id = str(context.request["scenario_id"])
        definition = select_scenario(scenario_id, body.version)
        snapshot = snapshot_reference(definition)

        def persist_simulation() -> None:
            if durable_control is not None:
                durable_control.sync(simulation)

        executor = ApplicationBranchExecutor(
            simulation,
            demo["actor_id"],
            persist=persist_simulation,
        )
        runner = ReferenceScenarioRunner(
            executor,
            repository=trial_repository,
            persona_factory=generic_persona,
        )
        report = runner.run(
            definition,
            snapshot,
            cohort_size=body.cohort_size,
            seeds=body.seeds,
            include_trials=body.include_trials,
            attempt=context.attempt,
            cancelled=context.is_cancelled,
            on_trial=lambda completed, total, output: checkpoint_trial(
                context, completed, total, output, catalog=False
            ),
        )
        if not report.canonical_world_unchanged:
            raise ValueError("scenario trial changed canonical world state")
        for output in runner.last_outputs:
            persist_trial(output, catalog=False)
        report_id = persist_report(report)
        return {"report_id": str(report_id), "report": report.model_dump(mode="json")}

    def runner_for(definition: ScenarioDefinition):
        return (
            execute_onboarding if definition.scenario_id == "player-onboarding" else execute_generic
        )

    def launch_scenario(
        definition: ScenarioDefinition,
        body: ScenarioRunRequest,
    ) -> Any:
        cohort_size = body.cohort_size or definition.cohort_size
        seeds = body.seeds or definition.seeds
        job_request = {
            "scenario_id": definition.scenario_id,
            "version": definition.version,
            "cohort_size": cohort_size,
            "seeds": list(seeds),
            "include_trials": body.include_trials,
        }
        job = jobs.create_resumable(
            f"scenario.{definition.scenario_id}",
            job_request,
            runner_for(definition),
        )
        persist_job(job)
        finished = jobs.run(job.job_id)
        persist_job(finished)
        if finished.status == "FAILED":
            raise ValueError(finished.error or "scenario failed")
        response = dict(finished.result or {})
        response["job"] = job_payload(finished)
        return response

    for restored_job in jobs.list():
        scenario_id = str(restored_job.request.get("scenario_id", "player-onboarding"))
        version = restored_job.request.get("version")
        try:
            restored_definition = select_scenario(scenario_id, str(version) if version else None)
        except KeyError:
            continue
        jobs.attach_runner(restored_job.job_id, runner_for(restored_definition))

    @app.post("/api/v2/scenarios/player-onboarding/run")
    def run_onboarding():
        body = ScenarioRunRequest.model_validate(request.get_json(silent=True) or {})
        definition = select_scenario("player-onboarding", body.version)
        return jsonify(launch_scenario(definition, body)), 201

    @app.post("/api/v2/experiments/onboarding/run")
    def run_onboarding_compatibility():
        legacy = OnboardingRunRequest.model_validate(request.get_json(silent=True) or {})
        definition = select_scenario("player-onboarding", "1.0.0")
        body = ScenarioRunRequest(
            version=definition.version,
            cohort_size=legacy.cohort_size,
            seeds=legacy.seeds,
            include_trials=legacy.include_trials,
        )
        return jsonify(launch_scenario(definition, body)["report"])

    @app.post("/api/v2/scenarios/<path:scenario_id>/run")
    def run_scenario(scenario_id: str):
        body = ScenarioRunRequest.model_validate(request.get_json(silent=True) or {})
        definition = select_scenario(scenario_id, body.version)
        return jsonify(launch_scenario(definition, body)), 201

    @app.get("/api/v2/jobs")
    def job_list():
        return jsonify([job_payload(item) for item in jobs.list()])

    @app.get("/api/v2/jobs/<uuid:job_id>")
    def job_detail(job_id: uuid.UUID):
        return jsonify(job_payload(jobs.get(job_id)))

    @app.post("/api/v2/jobs/<uuid:job_id>/cancel")
    def job_cancel(job_id: uuid.UUID):
        cancelled = jobs.cancel(job_id)
        persist_job(cancelled)
        return jsonify(job_payload(cancelled))

    @app.post("/api/v2/jobs/<uuid:job_id>/retry")
    def job_retry(job_id: uuid.UUID):
        queued = jobs.retry(job_id)
        persist_job(queued)
        finished = jobs.run(job_id)
        persist_job(finished)
        return jsonify(job_payload(finished))

    @app.get("/api/v2/trials/<uuid:trial_id>")
    def trial_detail(trial_id: uuid.UUID):
        return _json(trials[trial_id])

    @app.get("/api/v2/reports")
    def report_list():
        return jsonify(
            [
                {"report_id": str(report_id), **report.model_dump(mode="json")}
                for report_id, report in reports.items()
            ]
        )

    @app.get("/api/v2/reports/<uuid:report_id>")
    def report_detail(report_id: uuid.UUID):
        return _json(reports[report_id])

    @app.post("/api/v2/trials/compare")
    def trial_compare():
        payload = request.get_json(silent=True) or {}
        left = trials[uuid.UUID(str(payload["left_trial_id"]))]
        right = trials[uuid.UUID(str(payload["right_trial_id"]))]
        comparison = compare_reports(left.metrics, right.metrics)
        return jsonify(
            {
                **comparison,
                "left_trial_id": str(left.trial_id),
                "right_trial_id": str(right.trial_id),
                "metric_deltas": {
                    name: values["delta"] for name, values in comparison["metrics"].items()
                },
                "same_canonical_origin": (
                    left.canonical_hash_before == right.canonical_hash_before
                ),
            }
        )

    @app.post("/api/v2/calibration/compare")
    def calibration_compare():
        body = CalibrationRequest.model_validate(request.get_json(silent=True) or {})
        report = CalibrationEngine().compare(
            body.synthetic_metrics,
            body.human_metrics,
            body.policy_version,
            body.evidence_version,
            body.evidence_metadata,
        )
        return _json(calibrations.add(report), 201)

    @app.get("/api/v2/calibration/history")
    def calibration_history():
        return jsonify([item.model_dump(mode="json") for item in calibrations.list()])

    @app.get("/api/v2/calibration/<uuid:report_id>")
    def calibration_detail(report_id: uuid.UUID):
        return _json(calibrations.get(report_id))

    @app.post("/api/v2/calibration/<uuid:report_id>/review")
    def calibration_review(report_id: uuid.UUID):
        body = CalibrationReviewRequest.model_validate(request.get_json(silent=True) or {})
        review = calibrations.review(
            report_id,
            body.reviewer,
            body.decision,
            rationale=body.rationale,
        )
        return jsonify(
            {
                "review": review.model_dump(mode="json"),
                "report": calibrations.get(report_id).model_dump(mode="json"),
            }
        ), 201

    @app.post("/api/v2/calibration/<uuid:report_id>/promote")
    def calibration_promote(report_id: uuid.UUID):
        body = CalibrationPromotionRequest.model_validate(request.get_json(silent=True) or {})
        promotion = calibrations.promote(report_id, body.promoted_by)
        return jsonify(
            {
                "promotion": promotion.model_dump(mode="json"),
                "report": calibrations.get(report_id).model_dump(mode="json"),
            }
        ), 201

    @app.post("/api/v2/calibration/<uuid:report_id>/approve")
    def calibration_approve(report_id: uuid.UUID):
        body = ApprovalRequest.model_validate(request.get_json(silent=True) or {})
        # Compatibility alias: approval is a review decision, never promotion.
        return _json(calibrations.approve(report_id, body.reviewer))

    @app.route("/api/v2/telemetry", methods=["GET", "PUT"])
    def telemetry_settings_endpoint():
        if request.method == "GET":
            return _json(telemetry_settings.get())
        body = TelemetryUpdateRequest.model_validate(request.get_json(silent=True) or {})
        return _json(
            telemetry_settings.configure(enabled=body.enabled, retention_days=body.retention_days)
        )

    @app.post("/api/v2/telemetry/events")
    def telemetry_capture():
        payload = request.get_json(silent=True) or {}
        return _json(
            telemetry.capture(
                str(payload.get("event_type", "unknown")),
                dict(payload.get("payload", {})),
                str(payload.get("consent_version", "local-v1")),
                world_id=uuid.UUID(str(payload.get("world_id", demo["world_id"]))),
                actor_id=uuid.UUID(str(payload.get("actor_id", demo["actor_id"]))),
            ),
            201,
        )

    @app.get("/api/v2/telemetry/events")
    @app.get("/api/v2/telemetry/export")
    def telemetry_events():
        return jsonify([item.model_dump(mode="json") for item in telemetry.events()])

    @app.post("/api/v2/telemetry/import")
    def telemetry_import():
        body = TelemetryImportRequest.model_validate(request.get_json(silent=True) or {})
        imported = []
        for item in body.events:
            imported.append(
                telemetry.capture(
                    str(item.get("event_type", "imported")),
                    dict(item.get("payload", {})),
                    str(item.get("consent_version", "local-import-v1")),
                    world_id=uuid.UUID(str(item.get("world_id", demo["world_id"]))),
                    actor_id=uuid.UUID(str(item.get("actor_id", demo["actor_id"]))),
                )
            )
        return jsonify(
            {"imported": len(imported), "event_ids": [str(item.event_id) for item in imported]}
        ), 201

    @app.delete("/api/v2/telemetry/events")
    def telemetry_delete():
        world_id = request.args.get("world_id")
        actor_id = request.args.get("actor_id")
        before = request.args.get("before")
        return jsonify(
            {
                "deleted": telemetry.delete(
                    world_id=uuid.UUID(world_id) if world_id else None,
                    actor_id=uuid.UUID(actor_id) if actor_id else None,
                    before=datetime.fromisoformat(before) if before else None,
                )
            }
        )

    @app.post("/api/v2/telemetry/purge-expired")
    def telemetry_purge_expired():
        return jsonify({"deleted": telemetry.purge_expired()})

    @app.get("/assets/<path:asset>")
    def assets(asset: str):
        return send_from_directory(static_root / "assets", asset)

    @app.get("/static/v2/<path:asset>")
    def built_frontend_asset(asset: str):
        """Serve Vite's configured base path before the SPA history fallback."""
        return send_from_directory(static_root, asset)

    @app.get("/")
    @app.get("/<path:path>")
    def spa(path: str = ""):
        if path.startswith("api/"):
            return jsonify({"error": "not_found"}), 404
        index = static_root / "index.html"
        if index.exists():
            return send_from_directory(static_root, "index.html")
        return jsonify(
            {"status": "frontend_not_built", "hint": "run npm --prefix frontend run build"}
        ), 503

    return app


app = create_app()
