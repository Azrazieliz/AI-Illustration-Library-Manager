package com.ailm.android.runtime

/**
 * Scoring semantics for taxonomy-bound visual attributes.
 *
 * A taxonomy family is not assumed to be single-valued.
 *
 * IMPORTANT COLOR SEMANTICS:
 * - several specific HC/EC IDs WITHOUT a semantic marker are canonical alternatives
 *   across appearances; they do not mean that the colours coexist simultaneously;
 * - simultaneous multicoloured hair requires HC043 in addition to any known
 *   component HC IDs;
 * - a multicoloured iris/eye treatment requires EC027 in addition to any known
 *   component EC IDs;
 * - heterochromia requires ET001 in addition to the visible EC component IDs.
 *
 * The resolver therefore never infers Multicolored or Heterochromia merely from
 * the number of specific colour IDs present in Character Knowledge.
 */
internal object CanonicalAttributeSemantics {
    private val simultaneousColorMarkers = mapOf(
        "HC" to "HC043",
        "EC" to "EC027",
    )

    fun family(id: String): String = id
        .trim()
        .takeWhile(Char::isLetter)
        .uppercase()

    fun isExplicitMultiValueFamily(family: String): Boolean =
        family.uppercase() in setOf("HC", "EC")

    /**
     * Scores observed evidence by family rather than blindly counting IDs.
     * This keeps two legitimate colours in one attribute from being treated as
     * two unrelated attributes while still rewarding candidates that explain
     * both visible colours.
     *
     * Extra candidate values are not penalized here because an image can hide
     * one eye/colour region. Missing visible observed values reduce coverage.
     */
    fun coherenceScore(
        observed: Map<String, Double>,
        candidateFeatures: Set<String>,
        weight: (String) -> Double,
    ): Double {
        if (observed.isEmpty()) return 0.0
        val grouped = observed.entries.groupBy { family(it.key) }
        var matchedWeight = 0.0
        var availableWeight = 0.0

        grouped.forEach { (family, entries) ->
            val candidateFamily = candidateFeatures.filter { family(it) == family }.toSet()
            val evidence = entries.sumOf { it.value.coerceIn(0.0, 1.0) }.coerceAtLeast(0.0001)
            val covered = entries.sumOf { (id, confidence) ->
                val bounded = confidence.coerceIn(0.0, 1.0)
                if (isCovered(id, candidateFamily)) bounded else 0.0
            }
            val coverage = (covered / evidence).coerceIn(0.0, 1.0)
            val familyWeight = familyEvidenceWeight(family, entries, weight)
            availableWeight += familyWeight
            matchedWeight += familyWeight * coverage
        }

        return if (availableWeight <= 0.0) 0.0
        else (matchedWeight / availableWeight).coerceIn(0.0, 1.0)
    }

    /**
     * Fraction of strong observed evidence contradicted by a candidate.
     * A candidate with no declared value for a family is treated as unknown,
     * not contradictory. A multi-valued candidate remains compatible when only
     * one of its values is visible.
     */
    fun contradictionFraction(
        observed: Map<String, Double>,
        candidateFeatures: Set<String>,
        strictFamilies: Set<String>,
        weight: (String) -> Double,
    ): Double {
        if (observed.isEmpty()) return 0.0
        val grouped = observed.entries.groupBy { family(it.key) }
        var contradictionWeight = 0.0
        var evidenceWeight = 0.0

        grouped.forEach { (family, entries) ->
            if (family !in strictFamilies) return@forEach
            val candidateFamily = candidateFeatures.filter { family(it) == family }.toSet()
            if (candidateFamily.isEmpty()) return@forEach

            val familyWeight = familyEvidenceWeight(family, entries, weight)
            evidenceWeight += familyWeight

            val totalConfidence = entries.sumOf { it.value.coerceIn(0.0, 1.0) }.coerceAtLeast(0.0001)
            val matchedConfidence = entries.sumOf { (id, confidence) ->
                val bounded = confidence.coerceIn(0.0, 1.0)
                if (isCovered(id, candidateFamily)) bounded else 0.0
            }
            val mismatch = (1.0 - matchedConfidence / totalConfidence).coerceIn(0.0, 1.0)
            contradictionWeight += familyWeight * mismatch
        }

        return if (evidenceWeight <= 0.0) 0.0
        else (contradictionWeight / evidenceWeight).coerceIn(0.0, 1.0)
    }

    private fun familyEvidenceWeight(
        family: String,
        entries: List<Map.Entry<String, Double>>,
        weight: (String) -> Double,
    ): Double {
        val strongest = entries.maxOfOrNull { weight(it.key) * it.value.coerceIn(0.0, 1.0) } ?: 0.0
        if (!isExplicitMultiValueFamily(family)) return strongest
        val distinct = entries.map { it.key }.distinct().size
        val multiValueBonus = (1.0 + 0.15 * (distinct - 1).coerceAtLeast(0)).coerceAtMost(1.30)
        return strongest * multiValueBonus
    }

    private fun isCovered(
        observedId: String,
        candidateFamilyIds: Set<String>,
    ): Boolean {
        // Exact IDs are authoritative. Semantic markers are not inferred from
        // the mere presence of two or more specific colour IDs.
        if (observedId in candidateFamilyIds) return true

        val family = family(observedId)
        if (!isExplicitMultiValueFamily(family)) return false

        // A Multicolored marker only matches the same explicit marker.
        // Conversely, an aggregate marker alone does not stand in for a known
        // specific component colour.
        val marker = simultaneousColorMarkers[family]
        if (observedId == marker || marker in candidateFamilyIds) return false

        return false
    }
}
