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
    fun `two visible hair colours are fully matched by a two-colour character`() {
        val observed = mapOf("HC015" to 0.95, "HC030" to 0.90)
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
    fun `one visible colour stays compatible with a multi-colour character`() {
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
    fun `single-colour candidate is penalized when two colours are visibly observed`() {
        val observed = mapOf("EC010" to 0.95, "EC014" to 0.95)
        val candidate = setOf("EC010")

        val score = CanonicalAttributeSemantics.coherenceScore(observed, candidate, weight)
        val contradiction = CanonicalAttributeSemantics.contradictionFraction(
            observed,
            candidate,
            setOf("EC"),
            weight,
        )

        assertTrue(score in 0.45..0.55)
        assertTrue(contradiction in 0.45..0.55)
    }

    @Test
    fun `multicolored fallback is compatible with two exact component colours`() {
        val observed = mapOf("HC015" to 0.90, "HC030" to 0.85)
        val aggregateCandidate = setOf("HC043")

        assertEquals(
            1.0,
            CanonicalAttributeSemantics.coherenceScore(observed, aggregateCandidate, weight),
            0.0001,
        )
    }

    @Test
    fun `aggregate observation is compatible with a two-colour candidate`() {
        val observed = mapOf("EC027" to 0.80)
        val candidate = setOf("EC010", "EC014", "ET001")

        assertEquals(
            1.0,
            CanonicalAttributeSemantics.coherenceScore(observed, candidate, weight),
            0.0001,
        )
    }
}
