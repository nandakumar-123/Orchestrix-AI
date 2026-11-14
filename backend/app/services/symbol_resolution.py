from __future__ import annotations

import logging
import posixpath
from dataclasses import dataclass, field
from typing import Any

from app.db.models.repository_intelligence import CodeSymbol, FileDependency, RepositoryFile

logger = logging.getLogger("orchestrix.symbol_resolution")


@dataclass
class ResolvedSymbolResult:
    target_symbol: CodeSymbol | None
    target_id: str | None
    status: str  # "resolved" | "partially_resolved" | "unresolved"
    resolution_type: str  # "same_file" | "import_match" | "unique_global_match" | "ambiguous_match" | "unresolved"
    confidence: float  # 0.0 to 1.0
    candidates: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class SymbolResolutionEngine:
    """
    Symbol Resolution Engine for multi-language codebases.
    Resolves symbol references across files, imports, inheritance, and call sites.
    """

    def __init__(
        self,
        snapshot_id: str,
        files: list[RepositoryFile],
        symbols: list[CodeSymbol],
        dependencies: list[FileDependency],
    ) -> None:
        self.snapshot_id = snapshot_id
        self.files_by_path: dict[str, RepositoryFile] = {f.path: f for f in files}
        self.file_paths: set[str] = set(self.files_by_path.keys())

        # Symbols indexed by file path and by name
        self.symbols_by_file: dict[str, list[CodeSymbol]] = {}
        self.symbols_by_name: dict[str, list[CodeSymbol]] = {}
        self.symbols_by_qualified: dict[str, CodeSymbol] = {}

        for sym in symbols:
            self.symbols_by_file.setdefault(sym.file_path, []).append(sym)
            self.symbols_by_name.setdefault(sym.name, []).append(sym)
            qualified_key = f"{sym.file_path}:{sym.name}"
            self.symbols_by_qualified[qualified_key] = sym

        # File imports indexed by source file path
        self.imports_by_file: dict[str, list[FileDependency]] = {}
        for dep in dependencies:
            if dep.dependency_type == "import":
                self.imports_by_file.setdefault(dep.source_file_path, []).append(dep)

    def _normalize_import_path(self, current_file: str, raw_import: str) -> str | None:
        """
        Normalize relative or module import paths to repository file paths.
        Examples:
        - './utils' in 'src/index.ts' -> 'src/utils.ts'
        - 'app.services.auth' in 'app/api/v1/auth.py' -> 'app/services/auth.py'
        """
        raw = raw_import.strip().strip("'\"")

        # TypeScript / JavaScript relative import
        if raw.startswith("./") or raw.startswith("../"):
            current_dir = posixpath.dirname(current_file)
            target_base = posixpath.normpath(posixpath.join(current_dir, raw))
            # Try matching extensions
            extensions = [
                "",
                ".ts",
                ".tsx",
                ".js",
                ".jsx",
                "/index.ts",
                "/index.tsx",
                "/index.js",
            ]
            for ext in extensions:
                candidate = target_base + ext
                if candidate in self.file_paths:
                    return candidate
            return None

        # Python dot module notation: app.services.auth
        if "." in raw and not raw.endswith((".py", ".ts", ".js", ".java")):
            as_path = raw.replace(".", "/")
            py_candidate = as_path + ".py"
            if py_candidate in self.file_paths:
                return py_candidate
            init_candidate = as_path + "/__init__.py"
            if init_candidate in self.file_paths:
                return init_candidate

        # Direct path check
        if raw in self.file_paths:
            return raw

        return None

    def resolve_symbol(
        self,
        source_file: str,
        symbol_name: str,
        target_type: str | None = None,
    ) -> ResolvedSymbolResult:
        """
        Resolve a symbol name referenced in source_file to its target symbol.
        """
        clean_name = symbol_name.strip()
        if not clean_name:
            return ResolvedSymbolResult(
                target_symbol=None,
                target_id=None,
                status="unresolved",
                resolution_type="unresolved",
                confidence=0.0,
            )

        # 1. Same-file resolution
        same_file_syms = self.symbols_by_file.get(source_file, [])
        for sym in same_file_syms:
            if sym.name == clean_name:
                if target_type is None or sym.symbol_type == target_type:
                    target_id = (
                        f"sym:{self.snapshot_id}:{sym.file_path}:{sym.symbol_type}:{sym.name}"
                    )
                    return ResolvedSymbolResult(
                        target_symbol=sym,
                        target_id=target_id,
                        status="resolved",
                        resolution_type="same_file",
                        confidence=1.0,
                    )

        # 2. Import match resolution
        imports = self.imports_by_file.get(source_file, [])
        for imp in imports:
            # Check if import explicitly mentions symbol name (e.g. from x import SymbolName)
            if clean_name in imp.name:
                normalized_target = self._normalize_import_path(source_file, imp.name)
                if normalized_target and normalized_target in self.symbols_by_file:
                    for sym in self.symbols_by_file[normalized_target]:
                        if sym.name == clean_name:
                            target_id = f"sym:{self.snapshot_id}:{sym.file_path}:{sym.symbol_type}:{sym.name}"
                            return ResolvedSymbolResult(
                                target_symbol=sym,
                                target_id=target_id,
                                status="resolved",
                                resolution_type="import_match",
                                confidence=0.95,
                                metadata={"imported_from": normalized_target},
                            )

            # Check normalized target module path
            target_path = self._normalize_import_path(source_file, imp.name)
            if target_path and target_path in self.symbols_by_file:
                for sym in self.symbols_by_file[target_path]:
                    if sym.name == clean_name:
                        target_id = (
                            f"sym:{self.snapshot_id}:{sym.file_path}:{sym.symbol_type}:{sym.name}"
                        )
                        return ResolvedSymbolResult(
                            target_symbol=sym,
                            target_id=target_id,
                            status="resolved",
                            resolution_type="import_match",
                            confidence=0.9,
                            metadata={"imported_from": target_path},
                        )

        # 3. Global unique match
        global_matches = self.symbols_by_name.get(clean_name, [])
        if target_type:
            global_matches = [s for s in global_matches if s.symbol_type == target_type]

        if len(global_matches) == 1:
            sym = global_matches[0]
            target_id = f"sym:{self.snapshot_id}:{sym.file_path}:{sym.symbol_type}:{sym.name}"
            return ResolvedSymbolResult(
                target_symbol=sym,
                target_id=target_id,
                status="resolved",
                resolution_type="unique_global_match",
                confidence=0.85,
            )

        # 4. Ambiguous match
        if len(global_matches) > 1:
            cand_ids = [
                f"sym:{self.snapshot_id}:{s.file_path}:{s.symbol_type}:{s.name}"
                for s in global_matches
            ]
            # Pick first candidate as primary representation but flag as partially_resolved
            first_cand = global_matches[0]
            first_id = f"sym:{self.snapshot_id}:{first_cand.file_path}:{first_cand.symbol_type}:{first_cand.name}"
            return ResolvedSymbolResult(
                target_symbol=first_cand,
                target_id=first_id,
                status="partially_resolved",
                resolution_type="ambiguous_match",
                confidence=0.5,
                candidates=cand_ids,
            )

        # 5. Unresolved
        return ResolvedSymbolResult(
            target_symbol=None,
            target_id=None,
            status="unresolved",
            resolution_type="unresolved",
            confidence=0.0,
        )
