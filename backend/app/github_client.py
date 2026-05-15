from __future__ import annotations

import base64
import os
from typing import Any
from urllib.parse import quote

import httpx

from .models import RepoSummary, SelectedFile


TEXT_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".dart", ".java", ".kt", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".php", ".rb", ".swift", ".scala",
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
    ".html", ".css", ".scss", ".xml", ".sql", ".sh", ".bat", ".ps1",
    ".dockerfile",
}

TEXT_FILENAMES = {
    "README", "README.md", "readme.md", "requirements.txt", "pyproject.toml", "setup.py",
    "package.json", "tsconfig.json", "vite.config.js", "next.config.js", "pubspec.yaml",
    "Dockerfile", "docker-compose.yml", ".env.example", "Makefile", "Pipfile", "Gemfile",
}

EXCLUDED_PREFIXES = (
    ".git/", "node_modules/", "build/", "dist/", ".dart_tool/", "__pycache__/", ".venv/", "venv/",
    "coverage/", ".next/", ".nuxt/", "target/", "out/", ".gradle/", ".idea/", ".vscode/",
)

EXCLUDED_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".pdf", ".pptx", ".xlsx",
    ".docx", ".zip", ".tar", ".gz", ".7z", ".ttf", ".otf", ".woff", ".woff2", ".mp4",
    ".mov", ".mp3", ".wav", ".pkl", ".pt", ".pth", ".onnx", ".bin", ".lock",
)


class GitHubClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN") or None
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        async with httpx.AsyncClient(timeout=20.0, headers=self.headers) as client:
            response = await client.get(f"{self.base_url}{path}", params=params)
            if response.status_code == 404:
                raise ValueError("GitHub user or repository not found.")
            response.raise_for_status()
            return response.json()

    async def list_public_repos(self, username: str, limit: int = 10) -> list[dict[str, Any]]:
        # GitMesh GitHub graph cap: recently updated top 10 public repositories.
        limit = min(max(limit, 1), 10)
        repos: list[dict[str, Any]] = []
        page = 1

        while len(repos) < limit:
            data = await self._get(
                f"/users/{username}/repos",
                params={
                    "per_page": min(100, limit),
                    "page": page,
                    "sort": "updated",
                    "direction": "desc",
                    "type": "owner",
                },
            )
            if not data:
                break
            repos.extend(data)
            if len(data) < min(100, limit):
                break
            page += 1

        return repos[:limit]

    async def get_repo(self, full_name: str) -> dict[str, Any]:
        return await self._get(f"/repos/{full_name}")

    async def get_languages(self, full_name: str) -> list[str]:
        try:
            data = await self._get(f"/repos/{full_name}/languages")
            return list(data.keys())
        except Exception:
            return []

    async def get_readme(self, full_name: str) -> str:
        try:
            data = await self._get(f"/repos/{full_name}/readme")
            content = data.get("content", "")
            encoding = data.get("encoding")
            if encoding == "base64" and content:
                return base64.b64decode(content).decode("utf-8", errors="ignore")
        except Exception:
            return ""
        return ""

    async def get_file_tree(self, full_name: str, default_branch: str, max_files: int = 120) -> list[str]:
        try:
            data = await self._get(
                f"/repos/{full_name}/git/trees/{default_branch}",
                params={"recursive": "1"},
            )
            tree = data.get("tree", [])
            paths = [item.get("path", "") for item in tree if item.get("path")]
            filtered = [path for path in paths if self.is_selectable_path(path, allow_readme=True)]
            return filtered[:max_files]
        except Exception:
            return []

    @staticmethod
    def is_selectable_path(path: str, *, allow_readme: bool = True) -> bool:
        normalized = path.replace("\\", "/").strip()
        if not normalized or normalized.endswith("/"):
            return False
        if normalized.startswith(EXCLUDED_PREFIXES):
            return False
        if any(
            part in {
                "node_modules", "dist", "build", ".git", ".venv", "venv", "__pycache__",
            }
            for part in normalized.split("/")
        ):
            return False

        lower = normalized.lower()
        if lower.endswith(EXCLUDED_SUFFIXES):
            return False

        filename = normalized.split("/")[-1]
        if filename in TEXT_FILENAMES:
            return True
        if allow_readme and filename.lower().startswith("readme"):
            return True
        if "." not in filename:
            return filename in {"Dockerfile", "Makefile"}

        ext = "." + filename.rsplit(".", 1)[-1].lower()
        return ext in TEXT_EXTENSIONS

    @classmethod
    def selectable_file_paths(cls, file_tree: list[str], *, max_paths: int = 240) -> list[str]:
        return [path for path in file_tree if cls.is_selectable_path(path)][:max_paths]

    async def get_file_content(self, full_name: str, path: str, max_chars: int = 2500) -> str:
        if not self.is_selectable_path(path):
            return ""

        try:
            encoded_path = quote(path, safe="/")
            data = await self._get(f"/repos/{full_name}/contents/{encoded_path}")
            if data.get("type") != "file":
                return ""
            if int(data.get("size") or 0) > 250_000:
                return ""

            content = data.get("content", "")
            encoding = data.get("encoding")
            if encoding != "base64" or not content:
                return ""

            text = base64.b64decode(content).decode("utf-8", errors="ignore")
            return text[:max_chars]
        except Exception:
            return ""

    async def read_selected_files(
        self,
        full_name: str,
        selected_files: list[dict[str, str]],
        *,
        max_files: int = 4,
        max_chars_per_file: int = 2500,
        max_total_chars: int = 10000,
    ) -> list[SelectedFile]:
        results: list[SelectedFile] = []
        total_chars = 0
        seen: set[str] = set()

        for item in selected_files[:max_files]:
            path = str(item.get("path") or "").strip()
            reason = str(item.get("reason") or "").strip()

            if not path or path in seen or not self.is_selectable_path(path):
                continue

            seen.add(path)
            remaining = max_total_chars - total_chars
            if remaining <= 0:
                break

            content = await self.get_file_content(
                full_name,
                path,
                max_chars=min(max_chars_per_file, remaining),
            )
            if not content.strip():
                continue

            total_chars += len(content)
            results.append(SelectedFile(path=path, reason=reason, content_excerpt=content))

        return results

    async def hydrate_repo(
        self,
        raw: dict[str, Any],
        *,
        include_readme: bool = True,
        include_tree: bool = True,
        max_files: int = 120,
    ) -> RepoSummary:
        full_name = raw["full_name"]
        default_branch = raw.get("default_branch") or "main"

        languages = await self.get_languages(full_name)
        readme = await self.get_readme(full_name) if include_readme else ""
        tree = await self.get_file_tree(full_name, default_branch, max_files=max_files) if include_tree else []
        topics = raw.get("topics") or []

        return RepoSummary(
            id=str(raw["id"]),
            name=raw["name"],
            full_name=full_name,
            html_url=raw["html_url"],
            description=raw.get("description"),
            primary_language=raw.get("language"),
            languages=languages,
            topics=topics,
            stars=raw.get("stargazers_count", 0),
            forks=raw.get("forks_count", 0),
            default_branch=default_branch,
            updated_at=raw.get("updated_at"),
            readme_text=readme[:12000],
            file_tree=tree,
        )
