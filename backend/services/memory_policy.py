from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MemoryKind = Literal["fact", "state", "event"]
Cardinality = Literal["one", "many"]
Mutability = Literal["correctable", "mutable", "append_only"]


@dataclass(frozen=True)
class RelationPolicy:
    kind: MemoryKind = "fact"
    cardinality: Cardinality = "many"
    mutability: Mutability = "mutable"
    ttl_days: int | None = None
    source_labels: tuple[str, ...] | None = None
    target_labels: tuple[str, ...] | None = None

    @property
    def ttl_milliseconds(self) -> int | None:
        if self.ttl_days is None:
            return None
        return self.ttl_days * 24 * 60 * 60 * 1000


DEFAULT_RELATION_POLICY = RelationPolicy()

# Relation semantics are enforced in code rather than delegated to a
# probabilistic extractor. Keep this registry deliberately conservative: only
# relations that are inherently single-valued are marked ``one``.
RELATION_POLICIES: dict[str, RelationPolicy] = {
    "LIVES_IN": RelationPolicy(source_labels=("Person",), target_labels=("Location",)),
    "LOCATED_IN": RelationPolicy(
        source_labels=("Organization", "Location", "University", "School", "Company", "Office", "Institution", "Campus"),
        target_labels=("Location",),
    ),
    "INTERNS_AT": RelationPolicy(source_labels=("Person",), target_labels=("Organization", "Company", "Institution")),
    "BORN_IN": RelationPolicy(
        cardinality="one",
        mutability="correctable",
        source_labels=("Person",),
        target_labels=("Location",),
    ),
    "BORN_ON": RelationPolicy(
        cardinality="one",
        mutability="correctable",
        source_labels=("Person",),
    ),
    "ORIGINATES_FROM": RelationPolicy(
        cardinality="one",
        mutability="correctable",
        source_labels=("Person",),
        target_labels=("Location",),
    ),
    "FEELS": RelationPolicy(kind="state", ttl_days=2),
    "ANGRY_AT": RelationPolicy(kind="state", ttl_days=7),
    "DISCUSSING": RelationPolicy(kind="state", ttl_days=14),
    "STRUGGLING_WITH": RelationPolicy(kind="state", ttl_days=30),
    "DOING": RelationPolicy(kind="state", ttl_days=30),
    "WANTS": RelationPolicy(kind="state", ttl_days=90),
    "WANTS_TO_BUY": RelationPolicy(kind="state", ttl_days=90),
    "PLANNING": RelationPolicy(kind="state", ttl_days=90),
    "ATTENDING": RelationPolicy(kind="state", ttl_days=90),
    "WATCHED": RelationPolicy(kind="event"),
    "VISITED": RelationPolicy(kind="event"),
    "BOUGHT": RelationPolicy(kind="event"),
    "CONSUMES": RelationPolicy(kind="event"),
    "READS": RelationPolicy(kind="event"),
    "LISTENS_TO": RelationPolicy(kind="event"),
    "PLAYED": RelationPolicy(kind="event"),
}


def normalize_relation(value: object) -> str:
    relation = "_".join(str(value or "").strip().upper().split())
    if not relation:
        raise ValueError("relation cannot be empty")
    if not relation[0].isalpha() or not all(character.isalnum() or character == "_" for character in relation):
        raise ValueError(f"invalid relation identifier: {relation!r}")
    if len(relation) > 80:
        raise ValueError("relation must contain at most 80 characters")
    return relation


def get_relation_policy(relation: str) -> RelationPolicy:
    return RELATION_POLICIES.get(normalize_relation(relation), DEFAULT_RELATION_POLICY)


class ExtractedNode(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    label: str = Field(default="Entity", min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=500)
    identity_context: str = Field(default="", max_length=500)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        compact = "".join(character for character in value if character.isalnum() or character == "_")
        if not compact or not compact[0].isalpha():
            raise ValueError("label must start with a letter and contain only letters, numbers, or underscores")
        return compact

    @field_validator("name", "identity_context")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
            raise ValueError("text contains unsupported control characters")
        return " ".join(value.split())

    @model_validator(mode="after")
    def require_context_for_noncanonical_people(self) -> "ExtractedNode":
        if (
            self.label.lower() == "person"
            and self.name.lower() not in {"nafiz", "claire"}
            and not self.identity_context
        ):
            raise ValueError(
                "Person nodes other than nafiz/claire require an evidence-backed identity_context"
            )
        return self


class ExtractedEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    relation: str = Field(min_length=1, max_length=80)
    supersedes: list[str] = Field(default_factory=list, max_length=20)
    replaces_current_relation: bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("relation", mode="before")
    @classmethod
    def normalize_relation_name(cls, value: object) -> str:
        return normalize_relation(value)

    @field_validator("supersedes")
    @classmethod
    def normalize_fact_ids(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for fact_id in value:
            normalized = str(fact_id).strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result


class ExtractedRetraction(BaseModel):
    """Explicitly retire existing evidence without inventing a replacement edge."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source: str = Field(min_length=1, max_length=80)
    relation: str = Field(min_length=1, max_length=80)
    target: str | None = Field(default=None, max_length=80)
    fact_id: str | None = Field(default=None, max_length=100)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("relation", mode="before")
    @classmethod
    def normalize_relation_name(cls, value: object) -> str:
        return normalize_relation(value)


class ExtractedKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[ExtractedNode] = Field(default_factory=list, max_length=100)
    edges: list[ExtractedEdge] = Field(default_factory=list, max_length=150)
    retractions: list[ExtractedRetraction] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_graph_shape(self) -> "ExtractedKnowledge":
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("every extracted node id must be unique")

        known_ids = set(node_ids)
        nodes_by_id = {node.id: node for node in self.nodes}
        for edge in self.edges:
            if edge.source not in known_ids or edge.target not in known_ids:
                raise ValueError("every edge endpoint must reference a node id in the same extraction")

            policy = get_relation_policy(edge.relation)
            source_label = nodes_by_id[edge.source].label.lower()
            target_label = nodes_by_id[edge.target].label.lower()
            if policy.source_labels and source_label not in {
                label.lower() for label in policy.source_labels
            }:
                raise ValueError(
                    f"{edge.relation} requires source label in {policy.source_labels}"
                )
            if policy.target_labels and target_label not in {
                label.lower() for label in policy.target_labels
            }:
                raise ValueError(
                    f"{edge.relation} requires target label in {policy.target_labels}"
                )
            if edge.replaces_current_relation and policy.cardinality != "one":
                raise ValueError(
                    f"replaces_current_relation is forbidden for multi-valued relation {edge.relation}"
                )

        for retraction in self.retractions:
            if retraction.source not in known_ids:
                raise ValueError("every retraction source must reference a node id in the same extraction")
            if retraction.target is not None and retraction.target not in known_ids:
                raise ValueError("every retraction target must reference a node id in the same extraction")

        single_value_targets: dict[tuple[str, str], set[str]] = {}
        for edge in self.edges:
            policy = get_relation_policy(edge.relation)
            if policy.cardinality != "one":
                continue
            key = (edge.source, edge.relation)
            single_value_targets.setdefault(key, set()).add(edge.target)

        conflicts = [
            f"{source}:{relation}"
            for (source, relation), targets in single_value_targets.items()
            if len(targets) > 1
        ]
        if conflicts:
            raise ValueError(
                "single-valued relation has multiple targets in one extraction: " + ", ".join(conflicts)
            )
        return self


def validate_extracted_knowledge(data: object) -> dict:
    """Return a normalized graph batch or raise before any graph write occurs."""
    normalized = ExtractedKnowledge.model_validate(data).model_dump()
    # Preserve the old two-key envelope for callers/tests that do not use
    # retractions yet, while keeping strict validation above.
    if not normalized["retractions"]:
        normalized.pop("retractions")
    return normalized


def transient_relation_ttls() -> dict[str, int]:
    return {
        relation: policy.ttl_milliseconds
        for relation, policy in RELATION_POLICIES.items()
        if policy.ttl_milliseconds is not None
    }
