package com.ailm.android.runtime

internal data class ContentRoutingObservation(
    val contentClass: String = "other",
    val peopleCount: Int = 0,
    val promotionOrPreview: Boolean = false,
    val landscapeOrScenery: Boolean = false,
    val qualityFlags: List<String> = emptyList(),
    val ocrText: String = "",
)

internal data class ContentTriageDecision(
    val route: String,
    val folderSegments: List<String> = emptyList(),
    val filenamePrefix: String = "",
    val terminal: Boolean = false,
    val requiresReview: Boolean = false,
    val reason: String = "",
)

internal object ContentTriagePolicy {
    const val ROUTE_CHARACTER = "character"
    const val ROUTE_LANDSCAPE = "landscape"
    const val ROUTE_PROMOTION_TRASH = "promotion_trash"
    const val ROUTE_NO_CHARACTER_TRASH = "no_character_trash"
    const val ROUTE_UNIDENTIFIED_GROUP = "unidentified_group"
    const val ROUTE_SINGLE_UNIDENTIFIED = "single_unidentified"
    const val ROUTE_WAITING_FOR_KNOWLEDGE = "waiting_for_knowledge"
    const val ROUTE_CORRUPT_TRASH = "corrupt_trash"

    fun decide(
        observation: ContentRoutingObservation,
        resolvedCharacterCount: Int,
        characterKnowledgeReady: Boolean,
    ): ContentTriageDecision {
        val contentClass = observation.contentClass.trim().lowercase()
        val flags = observation.qualityFlags.map { it.trim().lowercase() }.toSet()
        val people = observation.peopleCount.coerceAtLeast(0)

        val promotion = observation.promotionOrPreview ||
            contentClass in PROMOTION_CLASSES ||
            flags.any { it in PROMOTION_FLAGS } ||
            strongPromotionText(observation.ocrText)
        if (promotion) {
            return ContentTriageDecision(
                route = ROUTE_PROMOTION_TRASH,
                folderSegments = listOf("Trash", "Promotion"),
                filenamePrefix = "Promotion",
                terminal = true,
                reason = "Promotional, paywalled, preview, or placeholder content.",
            )
        }

        if (resolvedCharacterCount > 0) {
            return ContentTriageDecision(
                route = ROUTE_CHARACTER,
                reason = "At least one canonical Character Knowledge identity resolved.",
            )
        }

        val landscape = observation.landscapeOrScenery ||
            contentClass in LANDSCAPE_CLASSES
        if (landscape && people == 0) {
            return ContentTriageDecision(
                route = ROUTE_LANDSCAPE,
                folderSegments = listOf("Landscapes"),
                filenamePrefix = "Landscape",
                terminal = true,
                reason = "Scenery/landscape with no character subject.",
            )
        }

        if (people == 0) {
            return ContentTriageDecision(
                route = ROUTE_NO_CHARACTER_TRASH,
                folderSegments = listOf("Trash", "No Character"),
                filenamePrefix = "No Character",
                terminal = true,
                reason = "No visible character/person and not classified as landscape.",
            )
        }

        if (people >= 2 || contentClass in MULTI_CHARACTER_CLASSES) {
            return ContentTriageDecision(
                route = ROUTE_UNIDENTIFIED_GROUP,
                folderSegments = listOf("Unidentified Groups"),
                filenamePrefix = "Unidentified Group",
                terminal = true,
                reason = "Multiple visible characters/people without a specific resolved identity.",
            )
        }

        return if (characterKnowledgeReady) {
            ContentTriageDecision(
                route = ROUTE_SINGLE_UNIDENTIFIED,
                requiresReview = true,
                reason = "One visible character/person could not be resolved confidently.",
            )
        } else {
            ContentTriageDecision(
                route = ROUTE_WAITING_FOR_KNOWLEDGE,
                reason = "One visible character/person is waiting for Character Knowledge.",
            )
        }
    }

    fun corruptDecision(): ContentTriageDecision = ContentTriageDecision(
        route = ROUTE_CORRUPT_TRASH,
        folderSegments = listOf("Trash", "Corrupt"),
        filenamePrefix = "Corrupt",
        terminal = true,
        reason = "Image could not be decoded safely.",
    )

    private fun strongPromotionText(raw: String): Boolean {
        val text = raw.lowercase()
        if (text.isBlank()) return false
        return PROMOTION_TEXT_MARKERS.any { marker -> marker in text }
    }

    private val PROMOTION_CLASSES = setOf(
        "promotion",
        "promotional",
        "advertisement",
        "preview",
        "paywall",
        "placeholder",
        "contact_sheet",
    )

    private val LANDSCAPE_CLASSES = setOf(
        "landscape",
        "scenery",
        "environment",
        "background",
        "cityscape",
        "nature",
    )

    private val MULTI_CHARACTER_CLASSES = setOf(
        "multi_character",
        "group",
        "crowd",
    )

    private val PROMOTION_FLAGS = setOf(
        "promotional_overlay",
        "paywall",
        "preview",
        "placeholder",
        "contact_sheet",
        "blurred_preview",
        "sample_grid",
    )

    private val PROMOTION_TEXT_MARKERS = setOf(
        "full version",
        "patreon.com",
        "patreon ",
        "support me on patreon",
        "preview only",
        "sample only",
        "full image on",
        "full set on",
        "uncensored version",
        "subscribe to view",
    )
}
