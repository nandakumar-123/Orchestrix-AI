import logging
import uuid

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.repository_intelligence import (
    CodeSymbol,
    FileDependency,
    RepositoryFile,
    RepositorySnapshot,
)
from app.db.models.semantic_intelligence import (
    EmbeddingModelMetadata,
    SemanticCodeChunk,
)
from app.services.code_intelligence import ExtractedImport, ExtractedSymbol
from app.services.embedding_service import BaseEmbeddingProvider, get_embedding_provider
from app.services.semantic_chunking import ASTSemanticChunker, GeneratedChunk

logger = logging.getLogger("orchestrix.semantic_indexing")


class SemanticIndexingService:
    """
    Manages semantic chunk generation, incremental embedding reuse,
    and vector persistence for repository snapshots.
    """

    def __init__(
        self,
        provider: BaseEmbeddingProvider | None = None,
        chunker: ASTSemanticChunker | None = None,
    ) -> None:
        self.provider = provider or get_embedding_provider()
        self.chunker = chunker or ASTSemanticChunker()

    async def index_snapshot(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        snapshot_id: uuid.UUID,
        force_reembed: bool = False,
    ) -> EmbeddingModelMetadata:
        """
        Generate semantic chunks and embeddings for a snapshot incrementally.
        Reuses embeddings from previous snapshots for unchanged files.
        """
        # 1. Verify snapshot and repository
        snap_stmt = select(RepositorySnapshot).where(
            RepositorySnapshot.id == snapshot_id,
            RepositorySnapshot.repository_id == repository_id,
            RepositorySnapshot.workspace_id == workspace_id,
        )
        snap_res = await db.execute(snap_stmt)
        snapshot = snap_res.scalars().first()
        if not snapshot:
            raise LookupError(f"Snapshot {snapshot_id} not found for repository {repository_id}")

        # 2. Get or create EmbeddingModelMetadata
        meta_stmt = select(EmbeddingModelMetadata).where(
            EmbeddingModelMetadata.snapshot_id == snapshot_id,
            EmbeddingModelMetadata.model_name == self.provider.model_name,
        )
        meta_res = await db.execute(meta_stmt)
        metadata = meta_res.scalars().first()

        if not metadata:
            metadata = EmbeddingModelMetadata(
                workspace_id=workspace_id,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                provider_name=self.provider.provider_name,
                model_name=self.provider.model_name,
                dimension=self.provider.dimension,
                total_chunks=0,
                status="indexing",
            )
            db.add(metadata)
            await db.commit()
            await db.refresh(metadata)
        else:
            if metadata.status == "completed" and not force_reembed:
                logger.info("Snapshot %s already has completed embeddings.", snapshot_id)
                return metadata
            metadata.status = "indexing"
            await db.commit()

        try:
            # 3. Find previous snapshot to support incremental embedding reuse
            prev_snap_stmt = (
                select(RepositorySnapshot.id)
                .where(
                    RepositorySnapshot.repository_id == repository_id,
                    RepositorySnapshot.workspace_id == workspace_id,
                    RepositorySnapshot.id != snapshot_id,
                )
                .order_by(desc(RepositorySnapshot.created_at))
                .limit(1)
            )
            prev_res = await db.execute(prev_snap_stmt)
            prev_snapshot_id = prev_res.scalar_one_or_none()

            # Map of content_hash -> embedding list from previous snapshot
            cached_embeddings: dict[str, list[float]] = {}
            if prev_snapshot_id and not force_reembed:
                prev_chunks_stmt = select(
                    SemanticCodeChunk.content_hash, SemanticCodeChunk.embedding
                ).where(
                    SemanticCodeChunk.snapshot_id == prev_snapshot_id,
                    SemanticCodeChunk.embedding.isnot(None),
                )
                prev_chunks_res = await db.execute(prev_chunks_stmt)
                for c_hash, c_emb in prev_chunks_res.all():
                    if c_emb is not None:
                        cached_embeddings[c_hash] = (
                            list(c_emb) if not isinstance(c_emb, list) else c_emb
                        )

            # If force_reembed, remove previous chunks for this snapshot
            if force_reembed:
                del_stmt = delete(SemanticCodeChunk).where(
                    SemanticCodeChunk.snapshot_id == snapshot_id
                )
                await db.execute(del_stmt)
                await db.commit()

            # 4. Fetch all non-binary files for this snapshot
            files_stmt = select(RepositoryFile).where(
                RepositoryFile.snapshot_id == snapshot_id,
                RepositoryFile.is_binary == False,  # noqa: E712
            )
            files_res = await db.execute(files_stmt)
            files = files_res.scalars().all()

            # Fetch symbols and imports for these files
            syms_stmt = select(CodeSymbol).where(CodeSymbol.snapshot_id == snapshot_id)
            syms_res = await db.execute(syms_stmt)
            all_symbols = syms_res.scalars().all()
            symbols_by_file: dict[uuid.UUID, list[ExtractedSymbol]] = {}
            for s in all_symbols:
                symbols_by_file.setdefault(s.file_id, []).append(
                    ExtractedSymbol(
                        name=s.name,
                        symbol_type=s.symbol_type,
                        start_line=s.start_line,
                        end_line=s.end_line,
                        start_column=s.start_column,
                        end_column=s.end_column,
                        signature=s.signature,
                        parent_symbol_name=s.parent_symbol_name,
                    )
                )

            deps_stmt = select(FileDependency).where(
                FileDependency.snapshot_id == snapshot_id,
                FileDependency.dependency_type == "import",
            )
            deps_res = await db.execute(deps_stmt)
            all_deps = deps_res.scalars().all()
            imports_by_file: dict[uuid.UUID, list[ExtractedImport]] = {}
            for d in all_deps:
                if d.file_id:
                    imports_by_file.setdefault(d.file_id, []).append(
                        ExtractedImport(module_name=d.name, is_external=d.is_external)
                    )

            # 5. Generate chunks across all files
            all_generated_chunks: list[tuple[RepositoryFile, GeneratedChunk]] = []
            for file_obj in files:
                f_syms = symbols_by_file.get(file_obj.id, [])
                f_imps = imports_by_file.get(file_obj.id, [])

                # Placeholder code representation for chunker
                # In full ingestion, content_bytes is cached or fetched; if not stored in file_obj,
                # we generate symbol chunks from the symbol signatures or file summary
                placeholder_code = (
                    f"// File: {file_obj.path}\n// Language: {file_obj.language or 'unknown'}\n"
                )
                for sym_item in f_syms:
                    placeholder_code += f"\n{sym_item.signature or sym_item.name}\n"

                file_chunks = self.chunker.chunk_file(
                    file_path=file_obj.path,
                    content_bytes=placeholder_code.encode("utf-8"),
                    language=file_obj.language or "Unknown",
                    symbols=f_syms,
                    imports=f_imps,
                )
                for chk in file_chunks:
                    all_generated_chunks.append((file_obj, chk))

            # 6. Embed chunks in bounded batches
            texts_to_embed: list[str] = []
            chunks_to_embed_indices: list[int] = []

            for idx, (_, g_chunk) in enumerate(all_generated_chunks):
                if g_chunk.content_hash in cached_embeddings:
                    # Reuse cached vector
                    continue
                texts_to_embed.append(g_chunk.embeddable_text)
                chunks_to_embed_indices.append(idx)

            # Generate embeddings for new/modified content
            new_embeddings: list[list[float]] = []
            if texts_to_embed:
                batch_size = 32
                for b_start in range(0, len(texts_to_embed), batch_size):
                    batch_texts = texts_to_embed[b_start : b_start + batch_size]
                    batch_vecs = await self.provider.embed_texts(batch_texts)
                    new_embeddings.extend(batch_vecs)

            # Map generated embeddings back
            chunk_vectors: dict[int, list[float]] = {}
            for map_i, chunk_idx in enumerate(chunks_to_embed_indices):
                chunk_vectors[chunk_idx] = new_embeddings[map_i]

            # 7. Persist SemanticCodeChunk records
            created_count = 0
            for idx, (f_obj, g_chunk) in enumerate(all_generated_chunks):
                vec = cached_embeddings.get(g_chunk.content_hash) or chunk_vectors.get(idx)
                if vec is None:
                    vec = [0.0] * self.provider.dimension

                chunk_record = SemanticCodeChunk(
                    workspace_id=workspace_id,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                    file_id=f_obj.id,
                    file_path=g_chunk.file_path,
                    language=g_chunk.language,
                    symbol_name=g_chunk.symbol_name,
                    symbol_type=g_chunk.symbol_type,
                    parent_symbol_name=g_chunk.parent_symbol_name,
                    start_line=g_chunk.start_line,
                    end_line=g_chunk.end_line,
                    chunk_index=g_chunk.chunk_index,
                    content=g_chunk.content,
                    content_hash=g_chunk.content_hash,
                    metadata_=g_chunk.metadata,
                    embedding=vec,
                )
                db.add(chunk_record)
                created_count += 1

            # 8. Complete metadata
            metadata.status = "completed"
            metadata.total_chunks = created_count
            metadata.completed_at = utc_now()
            await db.commit()
            await db.refresh(metadata)
            return metadata

        except Exception as exc:
            logger.exception("Failed semantic indexing for snapshot %s: %s", snapshot_id, exc)
            metadata.status = "failed"
            metadata.error_message = str(exc)
            await db.commit()
            raise
