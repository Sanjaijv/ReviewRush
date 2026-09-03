import logging
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.analysis.workspace import workspace_for
from app.config import get_settings
from app.context.chunks import reindex_changed_file_chunks
from app.context.embeddings import build_embedding_provider
from app.context.guidance import load_guidance_docs
from app.context.profile import build_repo_profile
from app.context.rerank import (
    build_semantic_context_items,
    rerank,
    semantic_candidates_for_symbol,
)
from app.context.retrieval import (
    ContextItem,
    apply_budget,
    build_context_items_for_symbol,
    find_config_items,
    iter_source_files,
    reindex_changed_files,
)
from app.github.auth import get_installation_access_token
from app.github.client import GitHubClient
from app.models import DiffSnapshot, RepoContextSnapshot, RepoFileIndex, Repository, RepoSymbolChunk

logger = logging.getLogger(__name__)


def _existing_snapshot(db: Any, diff_snapshot_id: int) -> RepoContextSnapshot | None:
    return db.query(RepoContextSnapshot).filter_by(diff_snapshot_id=diff_snapshot_id).one_or_none()


def _persist(
    db: Any,
    repository: Repository,
    diff_snapshot: DiffSnapshot,
    profile: dict,
    guidance: list[dict],
    items: list[ContextItem],
    truncated: bool,
    total_bytes: int,
    degraded: bool,
) -> RepoContextSnapshot:
    snapshot = RepoContextSnapshot(
        repository_id=repository.id,
        diff_snapshot_id=diff_snapshot.id,
        profile=profile,
        guidance=guidance,
        context_items=[item.to_dict() for item in items],
        truncated=truncated,
        total_bytes=total_bytes,
        degraded=degraded,
    )
    db.add(snapshot)
    try:
        db.commit()
    except IntegrityError:
        # Another worker already built context for this head_sha -
        # RepoContextSnapshot rows are immutable per diff_snapshot, so defer
        # to the existing row rather than racing to overwrite it.
        db.rollback()
        existing = _existing_snapshot(db, diff_snapshot.id)
        assert existing is not None
        return existing
    return snapshot


def _semantic_items_for_symbol(
    db: Any,
    repository_id: int,
    embedding_provider: Any,
    embedding_model: str,
    definition_item: ContextItem,
    path: str,
    workspace_root: Any,
    settings: Any,
) -> list[ContextItem]:
    """Embed the changed symbol's own definition and look up nearest
    neighbors elsewhere in the repository. Any failure here (provider error,
    a bad pgvector query) is the caller's responsibility to catch - this
    function raises rather than swallowing, so the caller can mark the
    snapshot degraded instead of silently pretending semantic retrieval ran.
    """
    response = embedding_provider.embed(definition_item.snippet)
    if response.error is not None or response.vector is None:
        logger.warning(
            "query embedding failed, skipping semantic retrieval for symbol",
            extra={"repository_id": repository_id, "path": path, "error": response.error},
        )
        return []

    candidates = semantic_candidates_for_symbol(
        db,
        repository_id=repository_id,
        query_embedding=response.vector,
        exclude_path=path,
        limit=settings.context_semantic_candidates,
    )
    return build_semantic_context_items(
        workspace_root,
        candidates,
        origin_symbol=definition_item.symbol or "",
        origin_path=path,
        max_file_bytes=settings.context_max_file_bytes,
    )


def build_repository_context_for_snapshot(
    db: Any, repository: Repository, diff_snapshot: DiffSnapshot
) -> RepoContextSnapshot | None:
    """Build (or reuse) repository-aware context for one immutable diff
    snapshot: a repo profile, repository guidance docs, and retrieved
    code/tests/config/semantic matches related to the diff's changed
    symbols, ranked by relevance and capped by a byte budget.

    Idempotent per diff_snapshot, mirroring `run_ai_review_for_snapshot` and
    `run_analysis_pipeline`: an existing row is returned unchanged. Returns
    None when the feature is disabled, so callers can skip context entirely
    without treating that as an error.

    Symbol-chunk re-indexing and semantic (embedding) retrieval are wrapped
    so that any unexpected failure there degrades to the lexical/structural
    result already gathered rather than aborting the whole review - the
    documented Phase 11 "degraded mode". `RepoContextSnapshot.degraded`
    records when that happened.
    """
    settings = get_settings()
    if not settings.context_enabled:
        logger.info(
            "repository context disabled, skipping",
            extra={"repository": repository.full_name, "head_sha": diff_snapshot.head_sha},
        )
        return None

    existing = _existing_snapshot(db, diff_snapshot.id)
    if existing is not None:
        return existing

    installation = repository.installation
    token = get_installation_access_token(installation.github_installation_id)
    changed_files = list(diff_snapshot.changed_files)
    embedding_provider = build_embedding_provider(settings)
    degraded = False

    with GitHubClient(token) as client:
        with workspace_for(client, repository, diff_snapshot.head_sha) as workspace:
            root = workspace.host_path

            profile = build_repo_profile(root, settings.context_max_files_scanned)
            guidance_docs = load_guidance_docs(
                root, settings.context_guidance_filenames, settings.context_guidance_max_bytes_each
            )

            changed_symbols_by_path = reindex_changed_files(
                db=db,
                repository_id=repository.id,
                workspace_root=root,
                changed_files=changed_files,
                head_sha=diff_snapshot.head_sha,
                max_file_bytes=settings.context_max_file_bytes,
                max_symbols_per_file=settings.context_max_symbols_per_file,
            )
            db.commit()

            try:
                reindex_changed_file_chunks(
                    db=db,
                    repository_id=repository.id,
                    workspace_root=root,
                    changed_files=changed_files,
                    head_sha=diff_snapshot.head_sha,
                    max_file_bytes=settings.context_max_file_bytes,
                    max_symbols_per_file=settings.context_max_symbols_per_file,
                    embedding_provider=embedding_provider,
                    embedding_model=settings.context_embeddings_model,
                )
                db.commit()
            except Exception:
                logger.exception(
                    "symbol-chunk indexing failed, continuing with lexical-only context",
                    extra={"repository": repository.full_name, "head_sha": diff_snapshot.head_sha},
                )
                db.rollback()
                degraded = True

            all_items: list[ContextItem] = []
            changed_symbol_names: set[str] = set()
            fresh_paths = {f.new_path or f.old_path or "" for f in changed_files}

            if changed_symbols_by_path:
                source_files = iter_source_files(root, settings.context_max_files_scanned)
                for path, symbols in changed_symbols_by_path.items():
                    all_items.extend(
                        find_config_items(
                            root,
                            path,
                            settings.context_max_items_per_symbol,
                            settings.context_max_file_bytes,
                        )
                    )
                    for symbol in symbols:
                        changed_symbol_names.add(symbol.name)
                        symbol_items = build_context_items_for_symbol(
                            root,
                            path,
                            symbol,
                            source_files,
                            settings.context_max_items_per_symbol,
                            settings.context_max_file_bytes,
                        )
                        all_items.extend(symbol_items)

                        if embedding_provider is not None:
                            definition_item = next(
                                (item for item in symbol_items if item.kind == "definition"), None
                            )
                            if definition_item is not None:
                                try:
                                    all_items.extend(
                                        _semantic_items_for_symbol(
                                            db,
                                            repository.id,
                                            embedding_provider,
                                            settings.context_embeddings_model,
                                            definition_item,
                                            path,
                                            root,
                                            settings,
                                        )
                                    )
                                except Exception:
                                    logger.exception(
                                        "semantic retrieval failed, continuing without it",
                                        extra={
                                            "repository": repository.full_name,
                                            "head_sha": diff_snapshot.head_sha,
                                            "path": path,
                                        },
                                    )
                                    degraded = True

            ranked_items = rerank(
                all_items,
                changed_paths=set(changed_symbols_by_path),
                changed_symbol_names=changed_symbol_names,
                fresh_paths=fresh_paths,
            )
            kept_items, retrieval_truncated, used_bytes = apply_budget(
                ranked_items, settings.context_max_bytes
            )

    guidance_dicts = [
        {"path": doc.path, "content": doc.content, "truncated": doc.truncated}
        for doc in guidance_docs
    ]
    guidance_bytes = sum(len(doc.content.encode("utf-8")) for doc in guidance_docs)

    return _persist(
        db,
        repository,
        diff_snapshot,
        profile=profile.to_dict(),
        guidance=guidance_dicts,
        items=kept_items,
        truncated=retrieval_truncated or profile.scan_truncated,
        total_bytes=used_bytes + guidance_bytes,
        degraded=degraded,
    )


def purge_repository_index(db: Any, repository_ids: list[int]) -> None:
    """Delete the searchable RAG index - `RepoFileIndex` and
    `RepoSymbolChunk` - for repositories that have been removed from an
    installation, per the roadmap's "delete or invalidate index entries when
    installations are removed" requirement.

    `RepoContextSnapshot` rows are deliberately left alone - like
    `AIReview`/`MergeAttempt`, they are an immutable per-review audit
    record, not a live index, and are not what this requirement targets.
    """
    if not repository_ids:
        return
    db.query(RepoFileIndex).filter(RepoFileIndex.repository_id.in_(repository_ids)).delete(
        synchronize_session=False
    )
    db.query(RepoSymbolChunk).filter(RepoSymbolChunk.repository_id.in_(repository_ids)).delete(
        synchronize_session=False
    )
