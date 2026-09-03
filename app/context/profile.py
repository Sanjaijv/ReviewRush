"""Repository profiling: languages, frameworks, manifests, test layout, and
ownership files, detected lexically/structurally from a workspace checkout.

No repository content is trusted as instructions here - this module only
ever reads paths and searches manifest text for known dependency names.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.context.symbols import detect_language

logger = logging.getLogger(__name__)

_MANIFEST_FRAMEWORK_HINTS: dict[str, dict[str, str]] = {
    "package.json": {
        "react": "React",
        "\"next\"": "Next.js",
        "vue": "Vue",
        "express": "Express",
        "@nestjs/core": "NestJS",
        "fastify": "Fastify",
    },
    "pyproject.toml": {
        "fastapi": "FastAPI",
        "django": "Django",
        "flask": "Flask",
        "celery": "Celery",
    },
    "requirements.txt": {
        "fastapi": "FastAPI",
        "django": "Django",
        "flask": "Flask",
    },
    "go.mod": {
        "gin-gonic/gin": "Gin",
        "labstack/echo": "Echo",
    },
    "Gemfile": {
        "rails": "Ruby on Rails",
        "sinatra": "Sinatra",
    },
    "Cargo.toml": {
        "actix-web": "Actix Web",
        "axum": "Axum",
    },
}

_MANIFEST_FILENAMES = frozenset(_MANIFEST_FRAMEWORK_HINTS) | {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "Pipfile",
    "go.sum",
    "Cargo.lock",
}

_OWNERSHIP_CANDIDATES = (
    "CODEOWNERS",
    ".github/CODEOWNERS",
    "docs/CODEOWNERS",
    "OWNERS",
)

_TEST_DIR_NAMES = frozenset({"tests", "test", "__tests__", "spec", "specs"})
IGNORED_DIR_NAMES = frozenset({".git", "node_modules", "vendor", "dist", "build", ".venv"})

_LANGUAGE_LABELS: dict[str, str] = {
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "go": "Go",
    "java": "Java",
    "ruby": "Ruby",
    "rust": "Rust",
}

_MAX_MANIFEST_BYTES = 200_000


@dataclass
class RepoProfile:
    languages: dict[str, int] = field(default_factory=dict)
    manifests: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    test_directories: list[str] = field(default_factory=list)
    ownership_files: list[str] = field(default_factory=list)
    files_scanned: int = 0
    scan_truncated: bool = False

    def to_dict(self) -> dict:
        return {
            "languages": self.languages,
            "manifests": self.manifests,
            "frameworks": self.frameworks,
            "test_directories": self.test_directories,
            "ownership_files": self.ownership_files,
            "files_scanned": self.files_scanned,
            "scan_truncated": self.scan_truncated,
        }


def _frameworks_from_manifest(name: str, text: str) -> list[str]:
    hints = _MANIFEST_FRAMEWORK_HINTS.get(name, {})
    lowered = text.lower()
    return [label for needle, label in hints.items() if needle.lower() in lowered]


def build_repo_profile(root: Path, max_files_scanned: int) -> RepoProfile:
    profile = RepoProfile()
    frameworks: set[str] = set()
    test_dirs: set[str] = set()
    scanned = 0

    for path in root.rglob("*"):
        if scanned >= max_files_scanned:
            profile.scan_truncated = True
            break

        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in IGNORED_DIR_NAMES for part in relative.parts):
            continue
        if path.is_dir():
            if path.name.lower() in _TEST_DIR_NAMES:
                test_dirs.add(str(relative))
            continue
        if not path.is_file():
            continue

        scanned += 1
        rel_str = str(relative)
        language = detect_language(rel_str)
        if language:
            label = _LANGUAGE_LABELS.get(language, language)
            profile.languages[label] = profile.languages.get(label, 0) + 1

        if path.name in _MANIFEST_FILENAMES:
            profile.manifests.append(rel_str)
            if path.name in _MANIFEST_FRAMEWORK_HINTS:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")[:_MAX_MANIFEST_BYTES]
                except OSError:
                    text = ""
                frameworks.update(_frameworks_from_manifest(path.name, text))

    for candidate in _OWNERSHIP_CANDIDATES:
        if (root / candidate).is_file():
            profile.ownership_files.append(candidate)

    profile.files_scanned = scanned
    profile.frameworks = sorted(frameworks)
    profile.test_directories = sorted(test_dirs)
    profile.manifests = sorted(set(profile.manifests))
    return profile
