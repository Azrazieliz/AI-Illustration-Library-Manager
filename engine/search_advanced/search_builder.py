from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from engine.search_advanced.search_exceptions import AdvancedSearchParseError, AdvancedSearchQueryError
from engine.search_advanced.search_models import (
    AdvancedSearchDocument,
    AdvancedSearchFilters,
    AdvancedSearchQuery,
    AdvancedSearchWeights,
    AdvancedSortBy,
    AdvancedSortDirection,
)


@dataclass(slots=True)
class QueryTerm:
    raw: str
    field: str | None = None
    value: str = ""
    is_phrase: bool = False
    is_exact: bool = False
    is_fuzzy: bool = False


@dataclass(slots=True)
class QueryNode:
    op: str
    left: QueryNode | None = None
    right: QueryNode | None = None
    term: QueryTerm | None = None


class AdvancedSearchBuilder:
    _token_pattern = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"|\(|\)|\bAND\b|\bOR\b|\bNOT\b|[^\s()]+', re.IGNORECASE)

    def normalize_text(self, value: Any) -> str:
        text = "" if value is None else str(value)
        text = text.strip().casefold()
        text = re.sub(r"\s+", " ", text)
        return text

    def tokenize_text(self, value: Any) -> list[str]:
        normalized = self.normalize_text(value)
        if not normalized:
            return []
        return [item for item in re.split(r"[^a-z0-9]+", normalized) if item]

    def parse_query(self, query_text: str) -> QueryNode | None:
        tokens = self._tokenize_query(query_text)
        if not tokens:
            return None
        tokens = self._inject_implicit_and(tokens)
        return self._build_ast(tokens)

    def evaluate(self, node: QueryNode | None, document: AdvancedSearchDocument) -> tuple[bool, int, int, set[str], set[str]]:
        if node is None:
            return True, 0, 0, set(), set()

        if node.op == "TERM" and node.term is not None:
            matched, field_name = self._match_term(node.term, document)
            return matched, int(matched), 1, ({field_name} if matched and field_name else set()), ({node.term.value} if matched else set())

        if node.op == "NOT" and node.left is not None:
            matched, found, total, fields, terms = self.evaluate(node.left, document)
            return (not matched), found, total, fields, terms

        if node.left is None or node.right is None:
            raise AdvancedSearchParseError("Malformed boolean expression.")

        left_match, left_found, left_total, left_fields, left_terms = self.evaluate(node.left, document)
        right_match, right_found, right_total, right_fields, right_terms = self.evaluate(node.right, document)

        if node.op == "AND":
            return (
                left_match and right_match,
                left_found + right_found,
                left_total + right_total,
                left_fields.union(right_fields),
                left_terms.union(right_terms),
            )
        if node.op == "OR":
            if left_match and right_match:
                found = left_found + right_found
            elif left_match:
                found = left_found
            elif right_match:
                found = right_found
            else:
                found = 0
            return (
                left_match or right_match,
                found,
                left_total + right_total,
                left_fields.union(right_fields),
                left_terms.union(right_terms),
            )

        raise AdvancedSearchParseError(f"Unknown operation: {node.op}")

    def query_from_payload(self, payload: dict[str, Any]) -> AdvancedSearchQuery:
        filters_payload = dict(payload.get("filters", {}))
        weights_payload = dict(payload.get("weights", {}))

        filters = AdvancedSearchFilters(
            review_statuses=self._to_norm_set(filters_payload.get("review_statuses")),
            include_duplicates=filters_payload.get("include_duplicates"),
            min_rating=filters_payload.get("min_rating"),
            max_rating=filters_payload.get("max_rating"),
            min_width=filters_payload.get("min_width"),
            max_width=filters_payload.get("max_width"),
            min_height=filters_payload.get("min_height"),
            max_height=filters_payload.get("max_height"),
            file_types=self._to_norm_set(filters_payload.get("file_types")),
            mime_types=self._to_norm_set(filters_payload.get("mime_types")),
            date_from=self._parse_datetime(filters_payload.get("date_from")),
            date_to=self._parse_datetime(filters_payload.get("date_to")),
            folder_contains=filters_payload.get("folder_contains"),
            path_contains=filters_payload.get("path_contains"),
            series=self._to_norm_set(filters_payload.get("series")),
            characters=self._to_norm_set(filters_payload.get("characters")),
            tags=self._to_norm_set(filters_payload.get("tags")),
            collections=self._to_norm_set(filters_payload.get("collections")),
        )

        weights = AdvancedSearchWeights(
            metadata_score=float(weights_payload.get("metadata_score", 0.35)),
            semantic_score=float(weights_payload.get("semantic_score", 0.35)),
            tag_score=float(weights_payload.get("tag_score", 0.15)),
            recognition_score=float(weights_payload.get("recognition_score", 0.15)),
        )

        query = AdvancedSearchQuery(
            query_text=str(payload.get("query_text", "")),
            page=max(1, int(payload.get("page", 1))),
            page_size=max(1, int(payload.get("page_size", 25))),
            sort_by=AdvancedSortBy(str(payload.get("sort_by", AdvancedSortBy.SCORE.value))),
            sort_direction=AdvancedSortDirection(str(payload.get("sort_direction", AdvancedSortDirection.DESC.value))),
            filters=filters,
            weights=weights,
            semantic_query=payload.get("semantic_query"),
            preview_mode=bool(payload.get("preview_mode", False)),
            include_facets=bool(payload.get("include_facets", True)),
            include_explanations=bool(payload.get("include_explanations", True)),
            use_cache=bool(payload.get("use_cache", True)),
            saved_search_id=payload.get("saved_search_id"),
            query_id=payload.get("query_id"),
        )
        self.validate_query(query)
        return query

    def validate_query(self, query: AdvancedSearchQuery) -> None:
        if query.page <= 0:
            raise AdvancedSearchQueryError("page must be greater than zero")
        if query.page_size <= 0:
            raise AdvancedSearchQueryError("page_size must be greater than zero")

        total_weight = (
            query.weights.metadata_score
            + query.weights.semantic_score
            + query.weights.tag_score
            + query.weights.recognition_score
        )
        if total_weight <= 0:
            raise AdvancedSearchQueryError("At least one ranking weight must be > 0")

    def build_query_cache_key(self, query: AdvancedSearchQuery, corpus_signature: str) -> str:
        serializable = {
            "query_text": query.query_text,
            "page": query.page,
            "page_size": query.page_size,
            "sort_by": str(query.sort_by),
            "sort_direction": str(query.sort_direction),
            "filters": self._serialize_filters(query.filters),
            "weights": asdict(query.weights),
            "semantic_query": query.semantic_query,
            "preview_mode": query.preview_mode,
            "include_facets": query.include_facets,
            "include_explanations": query.include_explanations,
            "saved_search_id": query.saved_search_id,
            "corpus_signature": corpus_signature,
        }
        payload = json.dumps(serializable, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def vector_from_seed(self, seed_text: str, dimensions: int = 128) -> list[float]:
        seed = seed_text.encode("utf-8")
        values: list[float] = []
        while len(values) < dimensions:
            for byte in seed:
                values.append(float(byte) / 255.0)
                if len(values) >= dimensions:
                    break
        return values

    def cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        left_norm = sum(item * item for item in left) ** 0.5
        right_norm = sum(item * item for item in right) ** 0.5
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        return max(0.0, min(1.0, dot / (left_norm * right_norm)))

    def fuzzy_score(self, needle: str, haystack: str) -> float:
        return SequenceMatcher(None, self.normalize_text(needle), self.normalize_text(haystack)).ratio()

    def _tokenize_query(self, query_text: str) -> list[str]:
        tokens: list[str] = []
        for match in self._token_pattern.finditer(query_text):
            phrase = match.group(1)
            if phrase is not None:
                tokens.append('"' + phrase + '"')
            else:
                token = match.group(0)
                if token:
                    tokens.append(token)
        return tokens

    def _inject_implicit_and(self, tokens: list[str]) -> list[str]:
        if not tokens:
            return tokens
        out: list[str] = []
        previous: str | None = None
        for token in tokens:
            if previous is not None and self._needs_implicit_and(previous, token):
                out.append("AND")
            out.append(token)
            previous = token
        return out

    def _needs_implicit_and(self, left: str, right: str) -> bool:
        left_is_operand = self._is_operand(left) or left == ")"
        right_is_operand = self._is_operand(right) or right in {"(", "NOT"}
        return left_is_operand and right_is_operand

    def _is_operand(self, token: str) -> bool:
        upper = token.upper()
        return upper not in {"AND", "OR", "NOT", "(", ")"}

    def _build_ast(self, tokens: list[str]) -> QueryNode:
        precedence = {"OR": 1, "AND": 2, "NOT": 3}
        output: list[QueryNode] = []
        operators: list[str] = []

        def apply_operator() -> None:
            if not operators:
                raise AdvancedSearchParseError("Invalid query expression")
            op = operators.pop()
            if op == "NOT":
                if not output:
                    raise AdvancedSearchParseError("NOT requires one operand")
                operand = output.pop()
                output.append(QueryNode(op="NOT", left=operand))
                return
            if len(output) < 2:
                raise AdvancedSearchParseError(f"{op} requires two operands")
            right = output.pop()
            left = output.pop()
            output.append(QueryNode(op=op, left=left, right=right))

        for token in tokens:
            upper = token.upper()
            if token == "(":
                operators.append(token)
            elif token == ")":
                while operators and operators[-1] != "(":
                    apply_operator()
                if not operators:
                    raise AdvancedSearchParseError("Mismatched parentheses")
                operators.pop()
            elif upper in precedence:
                while operators and operators[-1] != "(" and precedence.get(operators[-1], 0) >= precedence[upper]:
                    apply_operator()
                operators.append(upper)
            else:
                output.append(QueryNode(op="TERM", term=self._parse_term(token)))

        while operators:
            if operators[-1] == "(":
                raise AdvancedSearchParseError("Mismatched parentheses")
            apply_operator()

        if len(output) != 1:
            raise AdvancedSearchParseError("Invalid query expression")
        return output[0]

    def _parse_term(self, token: str) -> QueryTerm:
        raw = token
        is_phrase = token.startswith('"') and token.endswith('"') and len(token) >= 2
        if is_phrase:
            value = token[1:-1]
            return QueryTerm(raw=raw, value=value, is_phrase=True)

        field: str | None = None
        value = token
        if ":" in token:
            left, right = token.split(":", maxsplit=1)
            if left and right:
                field = self.normalize_text(left)
                value = right

        is_exact = value.startswith("=")
        if is_exact:
            value = value[1:]

        is_fuzzy = value.endswith("~")
        if is_fuzzy:
            value = value[:-1]

        return QueryTerm(
            raw=raw,
            field=field,
            value=self.normalize_text(value),
            is_phrase=False,
            is_exact=is_exact,
            is_fuzzy=is_fuzzy,
        )

    def _match_term(self, term: QueryTerm, document: AdvancedSearchDocument) -> tuple[bool, str | None]:
        searchable = self._build_searchable_fields(document)

        fields = [term.field] if term.field else list(searchable.keys())
        fields = [item for item in fields if item in searchable]
        if not fields:
            return False, None

        for field in fields:
            values = searchable[field]
            for value in values:
                normalized = self.normalize_text(value)
                if not normalized:
                    continue
                if term.is_phrase:
                    if self.normalize_text(term.value) in normalized:
                        return True, field
                    continue
                if term.is_exact:
                    if self.normalize_text(term.value) == normalized:
                        return True, field
                    continue
                if term.is_fuzzy:
                    if self.fuzzy_score(term.value, normalized) >= 0.78:
                        return True, field
                    continue
                if term.value in normalized:
                    return True, field
        return False, None

    def _build_searchable_fields(self, document: AdvancedSearchDocument) -> dict[str, list[str]]:
        metadata_values = [f"{key}:{value}" for key, value in sorted(document.metadata.items())]
        values = {
            "path": [document.path],
            "folder": [document.folder],
            "filename": [document.filename],
            "filetype": [document.extension],
            "series": [document.series or ""],
            "character": list(document.characters),
            "characters": list(document.characters),
            "tag": list(document.tags),
            "tags": list(document.tags),
            "collection": list(document.collections),
            "collections": list(document.collections),
            "review": [document.review_status],
            "metadata": metadata_values,
            "mime": [str(document.metadata.get("mime_type", ""))],
            "all": [
                document.path,
                document.filename,
                document.folder,
                document.series or "",
                " ".join(document.characters),
                " ".join(document.tags),
                " ".join(document.collections),
                " ".join(metadata_values),
            ],
        }
        return values

    def _to_norm_set(self, value: Any) -> set[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = self.normalize_text(value)
            return {normalized} if normalized else None
        out = {self.normalize_text(item) for item in value if self.normalize_text(item)}
        return out or None

    def _parse_datetime(self, value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _serialize_filters(self, filters: AdvancedSearchFilters) -> dict[str, Any]:
        return {
            "review_statuses": sorted(filters.review_statuses or []),
            "include_duplicates": filters.include_duplicates,
            "min_rating": filters.min_rating,
            "max_rating": filters.max_rating,
            "min_width": filters.min_width,
            "max_width": filters.max_width,
            "min_height": filters.min_height,
            "max_height": filters.max_height,
            "file_types": sorted(filters.file_types or []),
            "mime_types": sorted(filters.mime_types or []),
            "date_from": filters.date_from.isoformat() if filters.date_from else None,
            "date_to": filters.date_to.isoformat() if filters.date_to else None,
            "folder_contains": self.normalize_text(filters.folder_contains),
            "path_contains": self.normalize_text(filters.path_contains),
            "series": sorted(filters.series or []),
            "characters": sorted(filters.characters or []),
            "tags": sorted(filters.tags or []),
            "collections": sorted(filters.collections or []),
        }
