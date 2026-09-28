package com.ailm.android.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CanonicalAttributeSemanticsTest {
    private val weight: (String) -> Double = { id ->
        when {
            id.startsWith("HC") -> 1.30
            id.startsWith("EC") -> 1.25
            id.startsWith("ET") -> 0.75
            else -> 1.0
        }
    }

    @Test
    fun `unmarked multiple hair colours are alternatives not multicolored`() {
        val observed = mapOf(
            "HC043" to 0.95,
            "HC015" to 0.95,
            "HC030" to 0.90,
        )
        val alternatives = setOf("HC015", "HC030")
        val simultaneous = setOf("HC043", "HC015", "HC030")

        val alternativesScore = CanonicalAttributeSemantics.coherenceScore(
            observed,
            alternatives,
            weight,
        )
        assertTrue(alternativesScore < 1.0)
        assertEquals(
            1.0,
            CanonicalAttributeSemantics.coherenceScore(observed, simultaneous, weight),
            0.0001,
        )
        assertEquals(
            0.0,
            CanonicalAttributeSemantics.contradictionFraction(
                observed,
                simultaneous,
                setOf("HC"),
                weight,
            ),
            0.0001,
        )
    }

    @Test
    fun `one visible colour stays compatible with alternative canonical colours`() {
        val observed = mapOf("HC015" to 0.95)
        val candidate = setOf("HC015", "HC030")

        assertEquals(
            1.0,
            CanonicalAttributeSemantics.coherenceScore(observed, candidate, weight),
            0.0001,
        )
        assertEquals(
            0.0,
            CanonicalAttributeSemantics.contradictionFraction(
                observed,
                candidate,
                setOf("HC"),
                weight,
            ),
            0.0001,
        )
    }

    @Test
    fun `one visible component stays compatible with marked multicolored hair`() {
        val observed = mapOf("HC015" to 0.95)
        val candidate = setOf("HC043", "HC015", "HC030")

        assertEquals(
            1.0,
            CanonicalAttributeSemantics.coherenceScore(observed, candidate, weight),
            0.0001,
        )
    }

    @Test
    fun `multicolored marker does not substitute for known component colours`() {
        val observed = mapOf(
            "HC043" to 0.90,
            "HC015" to 0.90,
            "HC030" to 0.85,
        )
        val markerOnly = setOf("HC043")

        val score = CanonicalAttributeSemantics.coherenceScore(observed, markerOnly, weight)
        assertTrue(score > 0.0)
        assertTrue(score < 1.0)
    }

    @Test
    fun `heterochromia marker is required for a full heterochromia match`() {
        val observed = mapOf(
            "EC010" to 0.95,
            "EC014" to 0.95,
            "ET001" to 0.95,
        )
        val alternatives = setOf("EC010", "EC014")
        val heterochromia = setOf("EC010", "EC014", "ET001")

        val alternativesScore = CanonicalAttributeSemantics.coherenceScore(
            observed,
            alternatives,
            weight,
        )
        assertTrue(alternativesScore < 1.0)
        assertEquals(
            1.0,
            CanonicalAttributeSemantics.coherenceScore(observed, heterochromia, weight),
            0.0001,
        )
    }

    @Test
    fun `multicolored eye marker must match explicitly`() {
        val observed = mapOf("EC027" to 0.80)
        val unmarkedAlternatives = setOf("EC010", "EC014")
        val marked = setOf("EC027", "EC010", "EC014")

        assertEquals(
            0.0,
            CanonicalAttributeSemantics.coherenceScore(observed, unmarkedAlternatives, weight),
            0.0001,
        )
        assertEquals(
            1.0,
            CanonicalAttributeSemantics.coherenceScore(observed, marked, weight),
            0.0001,
        )
    }
}
