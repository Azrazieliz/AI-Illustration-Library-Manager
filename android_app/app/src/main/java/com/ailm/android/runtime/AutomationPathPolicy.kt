package com.ailm.android.runtime

internal data class ResolvedCharacterPathInput(
    val subjectIndex: Int,
    val prominence: Double,
    val canonicalName: String,
    val seriesCode: String,
    val seriesName: String,
)

internal data class AutomationPathPlan(
    val folderSegments: List<String>,
    val filenamePrefix: String,
    val primarySeries: String,
    val primaryCharacter: String,
)

/**
 * Pure path policy for autonomous organization. Storage creation and SAF I/O
 * remain in StandaloneRuntime; this object fixes the canonical ownership rules.
 */
internal object AutomationPathPolicy {
    fun plan(
        characters: List<ResolvedCharacterPathInput>,
        originalCharacter: Boolean = false,
        originalCharacterClusterId: String = "",
    ): AutomationPathPlan? {
        if (originalCharacter) {
            return AutomationPathPlan(
                folderSegments = listOf("Original Characters"),
                filenamePrefix = "Original Character",
                primarySeries = "",
                primaryCharacter = originalCharacterClusterId,
            )
        }
        if (characters.isEmpty()) return null

        val primary = characters.maxWithOrNull(
            compareBy<ResolvedCharacterPathInput> { it.prominence }
                .thenBy { -it.subjectIndex },
        ) ?: characters.first()
        if (primary.seriesName.isBlank() || primary.canonicalName.isBlank()) return null

        val sameSeries = characters.map { it.seriesCode }.filter(String::isNotBlank).distinct().size == 1
        val folderSegments = when {
            characters.size == 1 -> listOf(primary.seriesName, primary.canonicalName)
            sameSeries -> listOf(primary.seriesName)
            else -> listOf(primary.seriesName, primary.canonicalName)
        }
        val orderedNames = characters
            .sortedBy(ResolvedCharacterPathInput::subjectIndex)
            .map(ResolvedCharacterPathInput::canonicalName)
            .filter(String::isNotBlank)
        if (orderedNames.isEmpty()) return null

        return AutomationPathPlan(
            folderSegments = folderSegments,
            filenamePrefix = orderedNames.joinToString(" - ") + " - " + primary.seriesName,
            primarySeries = primary.seriesName,
            primaryCharacter = primary.canonicalName,
        )
    }
}
