package com.ailm.android.runtime

/**
 * Scoring semantics for taxonomy-bound visual attributes.
 *
 * A taxonomy family is not assumed to be single-valued. Hair colour and eye
 * colour explicitly allow several canonical IDs at once (for example red+blue
 * hair, or red+blue eyes with a heterochromia trait). Other families can also
 * carry multiple observations when the taxonomy makes that meaningful.
 */
internal object CanonicalAttributeSemantics {
    private val aggregateColorIds = setOf("HC043", "EC027")

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
                if (isCovered(id, entries.map { it.key }.toSet(), candidateFamily)) bounded else 0.0
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
                if (isCovered(id, entries.map { it.key }.toSet(), candidateFamily)) bounded else 0.0
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
        observedFamilyIds: Set<String>,
        candidateFamilyIds: Set<String>,
    ): Boolean {
        if (observedId in candidateFamilyIds) return true
        val family = family(observedId)
        if (!isExplicitMultiValueFamily(family)) return false

        val observedAggregate = observedId in aggregateColorIds
        val candidateHasAggregate = candidateFamilyIds.any { it in aggregateColorIds }
        val observedSpecificCount = observedFamilyIds.count { it !in aggregateColorIds }
        val candidateSpecificCount = candidateFamilyIds.count { it !in aggregateColorIds }

        // "Multicolored" is a safe fallback when the model can see multiple
        // colours but cannot resolve each exact component. If exact component
        // colours are available, the vision prompt emits them instead.
        return (observedAggregate && candidateSpecificCount >= 2) ||
            (candidateHasAggregate && observedSpecificCount >= 2)
    }
}
