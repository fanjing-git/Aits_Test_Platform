"""Provider-neutral embedding and project-safe similarity retrieval."""
from dataclasses import dataclass
from hashlib import sha256
from math import sqrt
from typing import Iterable, Protocol, Sequence
from django.db import transaction
from django.db.models import Q
from apps.knowledge.models import Document, Embedding, KnowledgeBase, ReviewStatus


class Vectorizer(Protocol):
    """Generate a fixed-length numeric vector without owning persistence."""
    model_name: str
    def embed(self, text: str) -> Sequence[float]: ...


class HashVectorizer:
    """Deterministic local fallback for development and offline tests."""
    model_name = "local-hash-v1"

    def __init__(self, dimensions: int = 64) -> None:
        """Set a bounded positive vector dimension."""
        if dimensions < 2:
            raise ValueError("向量维度必须至少为2。")
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        """Map normalized tokens into a deterministic unit vector."""
        values = [0.0] * self.dimensions
        tokens = text.lower().split()
        if not tokens:
            return values
        for token in tokens:
            digest = sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            values[index] += 1.0 if digest[4] % 2 else -1.0
        norm = sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]


@dataclass(frozen=True)
class RetrievalHit:
    """Safe retrieval result with provenance and similarity score."""
    embedding_id: str
    knowledge_base_id: str
    document_id: str | None
    content: str
    score: float


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Calculate cosine similarity while rejecting malformed vectors."""
    if len(left) != len(right) or not left:
        return 0.0
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


@transaction.atomic
def vectorize_document(document: Document, vectorizer: Vectorizer | None = None) -> list[Embedding]:
    """Generate vectors for ready document chunks and replace prior vectors."""
    if document.status != Document.Status.READY:
        raise ValueError("文档必须先完成解析才能向量化。")
    vectorizer = vectorizer or HashVectorizer()
    chunks = list(document.embeddings.order_by("chunk_index"))
    if not chunks:
        raise ValueError("文档没有可向量化的分块。")
    for embedding in chunks:
        vector = list(vectorizer.embed(embedding.content))
        if not vector or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
            raise ValueError("向量化适配器返回了无效向量。")
        embedding.vector = vector
        embedding.model_name = vectorizer.model_name
        embedding.save(update_fields=("vector", "model_name"))
    document.metadata = {**document.metadata, "embedding_model": vectorizer.model_name, "embedding_dimensions": len(chunks[0].vector)}
    document.save(update_fields=("metadata", "updated_at"))
    return chunks


def retrieve(query: str, knowledge_base_ids: Iterable[str] | None = None, *, vectorizer: Vectorizer | None = None, top_k: int = 5, threshold: float = 0.0) -> list[RetrievalHit]:
    """Retrieve only indexed chunks from active bases and approved sources."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("检索内容不能为空。")
    if top_k < 1 or top_k > 50:
        raise ValueError("Top-K 必须在1到50之间。")
    if not -1 <= threshold <= 1:
        raise ValueError("相似度阈值必须在-1到1之间。")
    vectorizer = vectorizer or HashVectorizer()
    query_vector = vectorizer.embed(query)
    queryset = Embedding.objects.filter(vector__isnull=False, knowledge_base__status=KnowledgeBase.Status.ACTIVE).filter(Q(document__status=Document.Status.READY, document__review_status=ReviewStatus.APPROVED) | Q(qa_pair__review_status=ReviewStatus.APPROVED)).select_related("knowledge_base", "document", "qa_pair")
    if knowledge_base_ids is not None:
        queryset = queryset.filter(knowledge_base_id__in=list(knowledge_base_ids))
    hits: list[RetrievalHit] = []
    for embedding in queryset.iterator():
        if embedding.document_id and embedding.document.status != Document.Status.READY:
            continue
        if embedding.qa_pair_id and embedding.qa_pair.review_status != ReviewStatus.APPROVED:
            continue
        score = _cosine(query_vector, embedding.vector or [])
        if score >= threshold:
            hits.append(RetrievalHit(str(embedding.pk), str(embedding.knowledge_base_id), str(embedding.document_id) if embedding.document_id else None, embedding.content, round(score, 6)))
    return sorted(hits, key=lambda hit: (-hit.score, hit.embedding_id))[:top_k]
