from __future__ import annotations

import difflib
import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger("orchestrix.devpilot.workspace")

# Base scratch directory for isolated task workspaces
DEFAULT_WORKSPACE_BASE_DIR = os.path.join(
    os.environ.get("TEMP", "/tmp"), "orchestrix_devpilot_workspaces"
)

# Safe pattern for identifier strings (UUIDs, alphanumeric with hyphens/underscores)
SAFE_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")


@dataclass
class FileChangeRecord:
    file_path: str
    change_type: str  # CREATE, MODIFY, DELETE, RENAME
    old_content: str | None
    new_content: str | None
    diff_hunk: str | None


@dataclass
class IsolatedWorkspaceState:
    task_id: uuid.UUID
    workspace_dir: str
    created_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    file_records: list[FileChangeRecord] = field(default_factory=list)
    unified_diff: str = ""


class TaskWorkspaceManager:
    """
    Manages isolated task workspaces for DevPilot and TestPilot executions.
    Enforces the isolation model: workspace_root / repository_id / task_id.
    Guarantees strict path containment, conflict detection, diff generation, and cleanup.
    """

    def __init__(self, base_workspaces_dir: str = DEFAULT_WORKSPACE_BASE_DIR) -> None:
        self.base_dir = os.path.abspath(base_workspaces_dir)
        os.makedirs(self.base_dir, exist_ok=True)

    def validate_identifier(
        self, identifier: uuid.UUID | str, param_name: str = "identifier"
    ) -> str:
        """
        Validate and sanitize a repository or task identifier.
        Rejects path traversal, null bytes, separators, and invalid characters.
        """
        if isinstance(identifier, uuid.UUID):
            return str(identifier)

        if not isinstance(identifier, str):
            raise ValueError(f"{param_name} must be a UUID or string, got {type(identifier)}")

        cleaned = identifier.strip()
        if not cleaned:
            raise ValueError(f"{param_name} must not be empty")

        if "\x00" in cleaned or "/" in cleaned or "\\" in cleaned or ".." in cleaned:
            raise PermissionError(
                f"Path traversal or illegal separator in {param_name}: {identifier}"
            )

        if not SAFE_IDENTIFIER_PATTERN.match(cleaned):
            raise ValueError(f"Invalid characters in {param_name}: '{identifier}'")

        return cleaned

    def get_task_workspace_dir(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str | None = None,
    ) -> str:
        """
        Return the absolute path of the isolated workspace directory for a task.
        Enforces workspace_root / repository_id / task_id directory layout.
        """
        safe_task_id = self.validate_identifier(task_id, "task_id")

        if repository_id is not None:
            safe_repo_id = self.validate_identifier(repository_id, "repository_id")
            task_dir = os.path.abspath(os.path.join(self.base_dir, safe_repo_id, safe_task_id))
        else:
            # Check if task_id exists within any existing repository subdirectory
            found_dir: str | None = None
            if os.path.exists(self.base_dir):
                for entry in os.scandir(self.base_dir):
                    if entry.is_dir():
                        candidate = os.path.join(entry.path, safe_task_id)
                        if os.path.isdir(candidate):
                            found_dir = os.path.abspath(candidate)
                            break
            task_dir = found_dir or os.path.abspath(os.path.join(self.base_dir, safe_task_id))

        # Enforce strict path containment within base_dir
        if not (task_dir == self.base_dir or task_dir.startswith(self.base_dir + os.sep)):
            raise PermissionError(f"Workspace path escapes root: {task_dir}")

        return task_dir

    def create_task_workspace(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str | None = None,
        seed_files: dict[str, str] | None = None,
    ) -> str:
        """
        Initialize an isolated task directory (workspace_root / repo_id / task_id)
        and optionally seed with existing files.
        """
        task_dir = self.get_task_workspace_dir(task_id, repository_id=repository_id)
        os.makedirs(task_dir, exist_ok=True)

        if seed_files:
            for rel_path, content in seed_files.items():
                self.write_isolated_file(
                    task_id=task_id,
                    relative_path=rel_path,
                    content=content,
                    repository_id=repository_id,
                )

        return task_dir

    def resolve_safe_path(
        self,
        task_id: uuid.UUID | str,
        relative_path: str,
        repository_id: uuid.UUID | str | None = None,
    ) -> str:
        """
        Resolve and validate that a file path remains strictly within the isolated workspace.
        Raises PermissionError on path traversal attacks (.. or escape or null bytes).
        """
        if "\x00" in relative_path:
            raise PermissionError(f"Null byte detected in file path: {relative_path}")

        clean_rel = relative_path.replace("\\", "/").strip()
        if not clean_rel or clean_rel.startswith("/"):
            clean_rel = clean_rel.lstrip("/")

        # Check for path traversal attempts
        parts = clean_rel.split("/")
        if ".." in parts:
            raise PermissionError(f"Path traversal detected in file path: {relative_path}")

        task_dir = os.path.abspath(
            self.get_task_workspace_dir(task_id, repository_id=repository_id)
        )
        full_path = os.path.abspath(os.path.join(task_dir, *parts))

        # Guarantee full_path starts with task_dir
        if not (full_path == task_dir or full_path.startswith(task_dir + os.sep)):
            raise PermissionError(f"Path escape attempt blocked: {relative_path}")

        return full_path

    def write_isolated_file(
        self,
        task_id: uuid.UUID | str,
        relative_path: str,
        content: str,
        repository_id: uuid.UUID | str | None = None,
    ) -> str:
        """
        Write or update a file inside the task's isolated workspace.
        """
        full_path = self.resolve_safe_path(task_id, relative_path, repository_id=repository_id)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return full_path

    def read_isolated_file(
        self,
        task_id: uuid.UUID | str,
        relative_path: str,
        repository_id: uuid.UUID | str | None = None,
    ) -> str | None:
        """Read a file from the task's isolated workspace."""
        full_path = self.resolve_safe_path(task_id, relative_path, repository_id=repository_id)
        if not os.path.exists(full_path):
            return None
        with open(full_path, encoding="utf-8", errors="replace") as f:
            return f.read()

    def generate_unified_diff(
        self,
        task_id: uuid.UUID,
        original_files: dict[str, str],
        modified_files: dict[str, str],
    ) -> tuple[str, list[FileChangeRecord]]:
        """
        Compare original file contents with modified file contents and produce unified diff.
        """
        all_paths = sorted(set(original_files.keys()) | set(modified_files.keys()))
        diff_chunks: list[str] = []
        records: list[FileChangeRecord] = []

        for p in all_paths:
            old_str = original_files.get(p)
            new_str = modified_files.get(p)

            if old_str is None and new_str is not None:
                # CREATED
                change_type = "CREATE"
                old_lines = []
                new_lines = new_str.splitlines(keepends=True)
            elif old_str is not None and new_str is None:
                # DELETED
                change_type = "DELETE"
                old_lines = old_str.splitlines(keepends=True)
                new_lines = []
            elif old_str != new_str and new_str is not None:
                # MODIFIED
                change_type = "MODIFY"
                old_lines = old_str.splitlines(keepends=True) if old_str else []
                new_lines = new_str.splitlines(keepends=True)
            else:
                # No change
                continue

            # Compute hunk
            hunk_lines = list(
                difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=f"a/{p}",
                    tofile=f"b/{p}",
                )
            )
            hunk_str = "".join(hunk_lines)
            if hunk_str:
                diff_chunks.append(hunk_str)

            records.append(
                FileChangeRecord(
                    file_path=p,
                    change_type=change_type,
                    old_content=old_str,
                    new_content=new_str,
                    diff_hunk=hunk_str,
                )
            )

        full_unified_diff = "\n".join(diff_chunks)
        return full_unified_diff, records

    def detect_conflicts(
        self,
        task_id: uuid.UUID,
        base_files: dict[str, str],
        current_repo_files: dict[str, str],
        proposed_files: dict[str, str],
    ) -> list[str]:
        """
        Detect concurrent modifications or merge conflicts before applying changes.
        """
        conflicts: list[str] = []
        for path in proposed_files:
            base_content = base_files.get(path)
            current_content = current_repo_files.get(path)
            proposed_content = proposed_files.get(path)

            if base_content is not None and current_content is not None:
                # If current repo changed since task began, and proposed modifies it differently
                if current_content != base_content and proposed_content != current_content:
                    conflicts.append(
                        f"Conflict in {path}: file was concurrently modified on repo branch."
                    )
        return conflicts

    def cleanup_workspace(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str | None = None,
    ) -> bool:
        """Safely discard and remove an isolated task workspace directory."""
        task_dir = self.get_task_workspace_dir(task_id, repository_id=repository_id)
        if task_dir != self.base_dir and os.path.exists(task_dir):
            try:
                shutil.rmtree(task_dir)
                # If repository directory is now empty, remove it to keep scratch clean
                parent_dir = os.path.dirname(task_dir)
                if parent_dir != self.base_dir and os.path.exists(parent_dir):
                    try:
                        if not os.listdir(parent_dir):
                            os.rmdir(parent_dir)
                    except Exception:
                        pass
                return True
            except Exception as e:
                logger.warning(f"Failed to cleanup task workspace {task_dir}: {e}")
                return False
        return False
