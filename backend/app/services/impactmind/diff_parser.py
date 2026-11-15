from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("orchestrix.impactmind.diff_parser")

# Regex to detect unified diff header lines
DIFF_FILE_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+?)$")
DIFF_OLD_FILE = re.compile(r"^---\s+(?:a/)?(.+?)$")
DIFF_NEW_FILE = re.compile(r"^\+\+\+\s+(?:b/)?(.+?)$")
DIFF_HUNK_HEADER = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(?: (.*))?$")


@dataclass
class DiffHunk:
    """Represents a single unified diff hunk (contiguous block of changed lines)."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header_hint: str = ""
    added_lines: list[str] = field(default_factory=list)
    deleted_lines: list[str] = field(default_factory=list)
    context_lines: list[str] = field(default_factory=list)

    @property
    def new_end(self) -> int:
        return self.new_start + max(0, self.new_count - 1)

    @property
    def old_end(self) -> int:
        return self.old_start + max(0, self.old_count - 1)


@dataclass
class FileDiff:
    """Represents changes in a single file parsed from a diff."""

    old_path: str
    new_path: str
    change_type: str  # "added" | "modified" | "deleted" | "renamed"
    hunks: list[DiffHunk] = field(default_factory=list)
    total_additions: int = 0
    total_deletions: int = 0

    @property
    def path(self) -> str:
        """Return the current/new path (or old path if deleted)."""
        return self.new_path if self.change_type != "deleted" else self.old_path

    @property
    def file_path(self) -> str:
        """Alias for path for consistent API access."""
        return self.path

    @property
    def changed_new_line_ranges(self) -> list[tuple[int, int]]:
        """Return list of (start_line, end_line) ranges in the new file."""
        return [(h.new_start, h.new_end) for h in self.hunks if h.new_count > 0]

    @property
    def changed_old_line_ranges(self) -> list[tuple[int, int]]:
        """Return list of (start_line, end_line) ranges in the old file."""
        return [(h.old_start, h.old_end) for h in self.hunks if h.old_count > 0]


@dataclass
class ParsedDiffResult:
    """Aggregate result of parsing a complete git diff."""

    files: list[FileDiff] = field(default_factory=list)
    total_files_changed: int = 0
    total_additions: int = 0
    total_deletions: int = 0
    base_commit_sha: str | None = None
    target_commit_sha: str | None = None

    def get_file(self, path: str) -> FileDiff | None:
        for f in self.files:
            if f.new_path == path or f.old_path == path:
                return f
        return None


class GitDiffParser:
    """
    Robust Git diff parser supporting unified diffs, git patch formats,
    and GitHub compare API payloads.
    """

    @classmethod
    def parse_unified_diff(
        cls,
        diff_text: str,
        base_commit_sha: str | None = None,
        target_commit_sha: str | None = None,
    ) -> ParsedDiffResult:
        """
        Parse raw unified diff text into structured FileDiff and DiffHunk objects.
        Handles added, modified, deleted, and renamed files gracefully.
        """
        if not diff_text or not diff_text.strip():
            return ParsedDiffResult(
                base_commit_sha=base_commit_sha, target_commit_sha=target_commit_sha
            )

        files: list[FileDiff] = []
        lines = diff_text.splitlines()
        i = 0

        current_file: FileDiff | None = None
        current_hunk: DiffHunk | None = None

        while i < len(lines):
            line = lines[i]

            # Check diff --git a/file b/file
            git_match = DIFF_FILE_HEADER.match(line)
            if git_match:
                if current_hunk and current_file:
                    current_file.hunks.append(current_hunk)
                    current_hunk = None
                if current_file:
                    files.append(current_file)

                old_p = git_match.group(1).strip()
                new_p = git_match.group(2).strip()
                current_file = FileDiff(
                    old_path=old_p,
                    new_path=new_p,
                    change_type="modified",
                )
                i += 1
                continue

            # Check new file mode or deleted file mode
            if line.startswith("new file mode") and current_file:
                current_file.change_type = "added"
                i += 1
                continue
            if line.startswith("deleted file mode") and current_file:
                current_file.change_type = "deleted"
                i += 1
                continue
            if line.startswith("similarity index") and current_file:
                current_file.change_type = "renamed"
                i += 1
                continue
            if line.startswith("rename from ") and current_file:
                current_file.old_path = line.removeprefix("rename from ").strip()
                current_file.change_type = "renamed"
                i += 1
                continue
            if line.startswith("rename to ") and current_file:
                current_file.new_path = line.removeprefix("rename to ").strip()
                current_file.change_type = "renamed"
                i += 1
                continue

            # Check --- a/file or --- /dev/null
            old_match = DIFF_OLD_FILE.match(line)
            if old_match:
                raw_old = old_match.group(1).strip()
                if raw_old == "/dev/null" and current_file:
                    current_file.change_type = "added"
                elif current_file and not current_file.old_path:
                    current_file.old_path = raw_old
                i += 1
                continue

            # Check +++ b/file or +++ /dev/null
            new_match = DIFF_NEW_FILE.match(line)
            if new_match:
                raw_new = new_match.group(1).strip()
                if raw_new == "/dev/null" and current_file:
                    current_file.change_type = "deleted"
                elif current_file and not current_file.new_path:
                    current_file.new_path = raw_new
                i += 1
                continue

            # Check @@ -old_start,old_count +new_start,new_count @@
            hunk_match = DIFF_HUNK_HEADER.match(line)
            if hunk_match:
                if current_hunk and current_file:
                    current_file.hunks.append(current_hunk)

                old_s = int(hunk_match.group(1))
                old_c = int(hunk_match.group(2)) if hunk_match.group(2) else 1
                new_s = int(hunk_match.group(3))
                new_c = int(hunk_match.group(4)) if hunk_match.group(4) else 1
                hint = hunk_match.group(5) or ""

                current_hunk = DiffHunk(
                    old_start=old_s,
                    old_count=old_c,
                    new_start=new_s,
                    new_count=new_c,
                    header_hint=hint,
                )
                i += 1
                continue

            # Lines inside a hunk
            if current_hunk and current_file:
                if line.startswith("+") and not line.startswith("+++"):
                    current_hunk.added_lines.append(line[1:])
                    current_file.total_additions += 1
                elif line.startswith("-") and not line.startswith("---"):
                    current_hunk.deleted_lines.append(line[1:])
                    current_file.total_deletions += 1
                elif line.startswith(" ") or not line:
                    current_hunk.context_lines.append(line[1:] if line.startswith(" ") else line)

            i += 1

        # Flush final hunk and file
        if current_hunk and current_file:
            current_file.hunks.append(current_hunk)
        if current_file:
            files.append(current_file)

        total_add = sum(f.total_additions for f in files)
        total_del = sum(f.total_deletions for f in files)

        return ParsedDiffResult(
            files=files,
            total_files_changed=len(files),
            total_additions=total_add,
            total_deletions=total_del,
            base_commit_sha=base_commit_sha,
            target_commit_sha=target_commit_sha,
        )

    @classmethod
    def parse_github_compare_payload(cls, payload: dict[str, Any]) -> ParsedDiffResult:
        """
        Parse GitHub comparison API payload (from /repos/{owner}/{repo}/compare/{base}...{head}).
        """
        files: list[FileDiff] = []
        base_sha = payload.get("base_commit", {}).get("sha")
        target_sha = payload.get("commits", [{}])[-1].get("sha") if payload.get("commits") else None

        for item in payload.get("files", []):
            filename = item.get("filename", "")
            prev_filename = item.get("previous_filename", filename)
            gh_status = item.get("status", "modified")
            patch = item.get("patch", "")

            # Map GitHub status to internal change_type
            status_map = {
                "added": "added",
                "removed": "deleted",
                "modified": "modified",
                "renamed": "renamed",
                "copied": "added",
                "changed": "modified",
            }
            change_type = status_map.get(gh_status, "modified")

            if patch:
                # Wrap patch with pseudo diff header to parse hunks
                pseudo_diff = f"diff --git a/{prev_filename} b/{filename}\n--- a/{prev_filename}\n+++ b/{filename}\n{patch}"
                parsed = cls.parse_unified_diff(pseudo_diff)
                if parsed.files:
                    f_diff = parsed.files[0]
                    f_diff.change_type = change_type
                    if item.get("additions") is not None:
                        f_diff.total_additions = int(item["additions"])
                    if item.get("deletions") is not None:
                        f_diff.total_deletions = int(item["deletions"])
                    files.append(f_diff)
                    continue

            # Fallback if no patch provided (e.g. binary file or large file)
            files.append(
                FileDiff(
                    old_path=prev_filename,
                    new_path=filename,
                    change_type=change_type,
                    total_additions=item.get("additions", 0),
                    total_deletions=item.get("deletions", 0),
                )
            )

        total_add = sum(f.total_additions for f in files)
        total_del = sum(f.total_deletions for f in files)

        return ParsedDiffResult(
            files=files,
            total_files_changed=len(files),
            total_additions=total_add,
            total_deletions=total_del,
            base_commit_sha=base_sha,
            target_commit_sha=target_sha,
        )
