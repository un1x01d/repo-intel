from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from repo_intel.worker.context import ScanContext


class CloneError(RuntimeError):
    """Raised when git clone or checkout fails."""


class RepoAuthProvider:
    """Future extension point for private repository credentials."""

    def prepare_url(self, repo_url: str) -> str:
        return repo_url


_GIT_TIMEOUT_SECONDS = 300
_GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
}


@dataclass(slots=True)
class RepoCloner:
    auth_provider: RepoAuthProvider = field(default_factory=RepoAuthProvider)

    def clone(self, *, repo_url: str, requested_ref: str, destination: Path) -> str:
        clone_url = self.auth_provider.prepare_url(repo_url)
        self._git("clone", "--quiet", "--config", "credential.helper=", clone_url, str(destination))
        if requested_ref:
            self._git("checkout", "--quiet", requested_ref, cwd=destination)
        return self._git_output("rev-parse", "HEAD", cwd=destination)

    def _git(self, *args: str, cwd: Path | None = None) -> None:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=_GIT_ENV,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise CloneError(_format_git_error(result))

    def _git_output(self, *args: str, cwd: Path) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=_GIT_ENV,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise CloneError(_format_git_error(result))
        return result.stdout.strip()


@dataclass(slots=True)
class ClonePhase:
    """Clone the repository into an existing workspace path."""

    cloner: RepoCloner = field(default_factory=RepoCloner)

    def run(self, context: ScanContext) -> None:
        if context.checkout_path is None:
            raise ValueError("checkout path is required before cloning")
        context.resolved_commit_sha = self.cloner.clone(
            repo_url=context.repository_url,
            requested_ref=context.requested_ref,
            destination=context.checkout_path,
        )


def _format_git_error(result: subprocess.CompletedProcess[str]) -> str:
    detail = (result.stderr or result.stdout or "git command failed").strip()
    if not detail:
        return "git command failed"
    return _redact_credentials(detail.splitlines()[-1])


def _redact_credentials(message: str) -> str:
    """Avoid leaking future auth tokens embedded in transport URLs."""
    words = []
    for word in message.split():
        try:
            parsed = urlsplit(word)
        except ValueError:
            words.append(word)
            continue
        if parsed.username is None and parsed.password is None:
            words.append(word)
            continue
        hostname = parsed.hostname or ""
        netloc = f"{hostname}:{parsed.port}" if parsed.port else hostname
        words.append(urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)))
    return " ".join(words)
