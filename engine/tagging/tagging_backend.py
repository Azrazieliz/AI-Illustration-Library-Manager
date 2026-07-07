from __future__ import annotations

from abc import ABC, abstractmethod

from engine.tagging.tagging_models import GeneratedTag, TaggingContext
from engine.tagging.tagging_rules import generate_rule_based_tags


class TaggingBackend(ABC):
    """Abstract backend for pluggable tagging strategies."""

    @abstractmethod
    def generate_tags(
        self,
        context: TaggingContext,
        *,
        suggested_threshold: float,
        inferred_threshold: float,
        confirmed_threshold: float,
    ) -> list[GeneratedTag]:
        """Generate automatic tags for one context."""


class RuleBasedTaggingBackend(TaggingBackend):
    """Default deterministic rule-based tagging backend."""

    def generate_tags(
        self,
        context: TaggingContext,
        *,
        suggested_threshold: float,
        inferred_threshold: float,
        confirmed_threshold: float,
    ) -> list[GeneratedTag]:
        return generate_rule_based_tags(
            context,
            suggested_threshold=suggested_threshold,
            inferred_threshold=inferred_threshold,
            confirmed_threshold=confirmed_threshold,
        )
