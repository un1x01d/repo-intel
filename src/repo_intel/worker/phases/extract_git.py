from __future__ import annotations

import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from repo_intel.storage.models import Commit, CommitFileChange, RepoFile
from repo_intel.storage.repositories import RepoFileStore
from repo_intel.worker.context import ScanContext

_DEFAULT_LIMIT = 100
_CRITICAL_TOKENS = ("auth", "config", "db", "database", "routes", "middleware", "payment", "session")
_GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
}


@dataclass(frozen=True, slots=True)
class ParsedCommit:
    sha: str
    author_name: str | None
    author_email: str | None
    authored_at: datetime | None
    message: str | None


@dataclass(frozen=True, slots=True)
class ParsedChange:
    commit_sha: str
    path: str
    additions: int
    deletions: int


class ExtractGitPhase:
    """Extract bounded commit history and per-file churn from the checked out git repository."""

    def __init__(self, session: Session, limit: int = _DEFAULT_LIMIT) -> None:
        self.session = session
        self.limit = limit

    def run(self, context: ScanContext) -> dict[str, Any]:
        if context.checkout_path is None:
            raise ValueError("checkout path is required before git extraction")
        commits, changes = read_git_history(context.checkout_path, self.limit)
        files_by_path = RepoFileStore(self.session).map_by_path(context.scan_id)
        commit_models = [
            Commit(
                scan_job_id=context.scan_id,
                commit_sha=commit.sha,
                author_name=commit.author_name,
                author_email=commit.author_email,
                authored_at=commit.authored_at,
                message=commit.message,
                files_changed=sum(1 for change in changes if change.commit_sha == commit.sha),
                insertions=sum(change.additions for change in changes if change.commit_sha == commit.sha),
                deletions=sum(change.deletions for change in changes if change.commit_sha == commit.sha),
            )
            for commit in commits
        ]
        self.session.execute(delete(CommitFileChange).where(CommitFileChange.scan_job_id == context.scan_id))
        self.session.execute(delete(Commit).where(Commit.scan_job_id == context.scan_id))
        self.session.add_all(commit_models)
        self.session.flush()
        commits_by_sha = {commit.commit_sha: commit for commit in commit_models}
        change_models = [
            CommitFileChange(
                scan_job_id=context.scan_id,
                commit_id=commits_by_sha[change.commit_sha].id,
                file_id=files_by_path[change.path].id,
                additions=change.additions,
                deletions=change.deletions,
            )
            for change in changes
            if change.commit_sha in commits_by_sha and change.path in files_by_path
        ]
        self.session.add_all(change_models)
        self.session.commit()
        return build_git_summary(commits, changes)


def read_git_history(repo_path: Path, limit: int = _DEFAULT_LIMIT) -> tuple[list[ParsedCommit], list[ParsedChange]]:
    try:
        log_output = _git(repo_path, "log", f"--max-count={limit}", "--date=iso-strict", "--pretty=format:%H%x1f%an%x1f%ae%x1f%aI%x1f%s")
    except subprocess.SubprocessError:
        return [], []
    commits: list[ParsedCommit] = []
    changes: list[ParsedChange] = []
    for line in log_output.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 5:
            continue
        sha, author_name, author_email, authored_at, message = parts
        commits.append(
            ParsedCommit(
                sha=sha,
                author_name=author_name or None,
                author_email=author_email or None,
                authored_at=_parse_datetime(authored_at),
                message=message or None,
            )
        )
        changes.extend(_read_commit_changes(repo_path, sha))
    return commits, changes


def build_git_summary(commits: list[ParsedCommit], changes: list[ParsedChange]) -> dict[str, Any]:
    churn = Counter(change.path for change in changes)
    authors_by_file: dict[str, set[str]] = defaultdict(set)
    authors_by_sha = {commit.sha: commit.author_email or commit.author_name or "unknown" for commit in commits}
    for change in changes:
        authors_by_file[change.path].add(authors_by_sha.get(change.commit_sha, "unknown"))
    hot_files = [{"path": path, "changes": count} for path, count in churn.most_common(10)]
    critical_changes = [
        {"path": path, "changes": count}
        for path, count in churn.most_common()
        if any(token in path.lower() for token in _CRITICAL_TOKENS)
    ][:10]
    return {
        "commit_count": len(commits),
        "hot_files": hot_files,
        "critical_file_changes": critical_changes,
        "author_concentration": {
            path: {"authors": len(authors), "primary_author_share": _primary_author_share(path, changes, authors_by_sha)}
            for path, authors in sorted(authors_by_file.items())
        },
    }


def build_hotspot_summary(git_summary: dict[str, Any]) -> dict[str, Any]:
    hot_files = git_summary.get("hot_files", [])
    max_changes = max((item["changes"] for item in hot_files), default=1)
    hotspots = []
    for item in hot_files[:10]:
        path = item["path"]
        changes = item["changes"]
        kind = "high_churn_critical_file" if any(token in path.lower() for token in _CRITICAL_TOKENS) else "high_churn_file"
        hotspots.append({"kind": kind, "path": path, "score": round(changes / max_changes, 2)})
    return {"hotspots": hotspots}


def _read_commit_changes(repo_path: Path, sha: str) -> list[ParsedChange]:
    try:
        output = _git(repo_path, "show", "--numstat", "--format=", "--find-renames", sha)
    except subprocess.SubprocessError:
        return []
    changes: list[ParsedChange] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        additions, deletions, path = parts[0], parts[1], parts[-1]
        changes.append(ParsedChange(sha, path, _to_int(additions), _to_int(deletions)))
    return changes


def _git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        env=_GIT_ENV,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )
    return result.stdout


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _to_int(value: str) -> int:
    return int(value) if value.isdigit() else 0


def _primary_author_share(path: str, changes: list[ParsedChange], authors_by_sha: dict[str, str]) -> float:
    authors = Counter(authors_by_sha.get(change.commit_sha, "unknown") for change in changes if change.path == path)
    total = sum(authors.values())
    return round(authors.most_common(1)[0][1] / total, 2) if total else 0.0
