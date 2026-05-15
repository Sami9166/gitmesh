from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class SelectedFile(BaseModel):
    path: str
    reason: str = ""
    content_excerpt: str = ""


class RepoSummary(BaseModel):
    id: str
    name: str
    full_name: str
    html_url: str
    description: str | None = None
    primary_language: str | None = None
    languages: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    stars: int = 0
    forks: int = 0
    default_branch: str = "main"
    updated_at: str | None = None
    readme_text: str = ""
    file_tree: list[str] = Field(default_factory=list)


class ProjectDNA(BaseModel):
    domain: list[str] = Field(default_factory=list)
    target_user: str = "Unknown"
    core_problem: str = "Unknown"
    core_features: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    summary: str = ""


class AssetCard(BaseModel):
    name: str
    type: str
    reuse_score: float = 0.5
    reusable_for: list[str] = Field(default_factory=list)
    improvement_needed: list[str] = Field(default_factory=list)


class DevelopReport(BaseModel):
    limitations: list[str] = Field(default_factory=list)
    develop_points: list[str] = Field(default_factory=list)
    keep: list[str] = Field(default_factory=list)
    modify: list[str] = Field(default_factory=list)
    drop: list[str] = Field(default_factory=list)
    next_builds: list[str] = Field(default_factory=list)
    file_tree_suggestion: list[str] = Field(default_factory=list)


class ProjectReport(BaseModel):
    project_id: str
    repo: RepoSummary
    dna: ProjectDNA
    assets: list[AssetCard]
    report: DevelopReport
    related_project_ids: list[str] = Field(default_factory=list)
    selected_files: list[SelectedFile] = Field(default_factory=list)


class ProjectPreview(BaseModel):
    project_id: str
    repo: RepoSummary
    related_project_ids: list[str] = Field(default_factory=list)
    relation_reasons: list[str] = Field(default_factory=list)
    analysis_status: Literal["not_started", "running", "completed", "failed"] = "not_started"


class GraphNode(BaseModel):
    id: str
    label: str
    type: Literal["Project", "Domain", "Tech", "Asset", "Limitation", "NextBuild", "Topic"]
    meta: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    weight: float = 1.0
    meta: dict[str, Any] = Field(default_factory=dict)


class ProjectGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class ScanResponse(BaseModel):
    username: str
    projects: list[ProjectPreview]
    graph: ProjectGraph


class AnalyzeResponse(BaseModel):
    # Kept for compatibility with older frontend versions.
    username: str
    projects: list[ProjectReport]
    graph: ProjectGraph


class RepoAnalyzeResponse(BaseModel):
    project: ProjectReport
