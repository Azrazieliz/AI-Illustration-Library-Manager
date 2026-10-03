package com.ailm.android.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ContentTriagePolicyTest {
    @Test
    fun `promotion takes priority and routes to trash`() {
        val decision = ContentTriagePolicy.decide(
            observation = ContentRoutingObservation(
                contentClass = "other",
                peopleCount = 0,
                ocrText = "FULL VERSION PATREON.COM/example",
            ),
            resolvedCharacterCount = 0,
            characterKnowledgeReady = true,
        )

        assertEquals(ContentTriagePolicy.ROUTE_PROMOTION_TRASH, decision.route)
        assertEquals(listOf("Trash", "Promotion"), decision.folderSegments)
        assertTrue(decision.terminal)
        assertFalse(decision.requiresReview)
    }

    @Test
    fun `landscape without people is preserved in landscapes`() {
        val decision = ContentTriagePolicy.decide(
            observation = ContentRoutingObservation(
                contentClass = "landscape",
                peopleCount = 0,
                landscapeOrScenery = true,
            ),
            resolvedCharacterCount = 0,
            characterKnowledgeReady = true,
        )

        assertEquals(ContentTriagePolicy.ROUTE_LANDSCAPE, decision.route)
        assertEquals(listOf("Landscapes"), decision.folderSegments)
        assertTrue(decision.terminal)
    }

    @Test
    fun `generic no character content routes to trash`() {
        val decision = ContentTriagePolicy.decide(
            observation = ContentRoutingObservation(
                contentClass = "non_character",
                peopleCount = 0,
            ),
            resolvedCharacterCount = 0,
            characterKnowledgeReady = true,
        )

        assertEquals(ContentTriagePolicy.ROUTE_NO_CHARACTER_TRASH, decision.route)
        assertEquals(listOf("Trash", "No Character"), decision.folderSegments)
    }

    @Test
    fun `unidentified multi character image is separated from review`() {
        val decision = ContentTriagePolicy.decide(
            observation = ContentRoutingObservation(
                contentClass = "multi_character",
                peopleCount = 4,
            ),
            resolvedCharacterCount = 0,
            characterKnowledgeReady = true,
        )

        assertEquals(ContentTriagePolicy.ROUTE_UNIDENTIFIED_GROUP, decision.route)
        assertEquals(listOf("Unidentified Groups"), decision.folderSegments)
        assertTrue(decision.terminal)
        assertFalse(decision.requiresReview)
    }

    @Test
    fun `single unresolved character remains reviewable when knowledge exists`() {
        val decision = ContentTriagePolicy.decide(
            observation = ContentRoutingObservation(
                contentClass = "character",
                peopleCount = 1,
            ),
            resolvedCharacterCount = 0,
            characterKnowledgeReady = true,
        )

        assertEquals(ContentTriagePolicy.ROUTE_SINGLE_UNIDENTIFIED, decision.route)
        assertTrue(decision.requiresReview)
        assertFalse(decision.terminal)
    }

    @Test
    fun `single unresolved character waits when knowledge is absent`() {
        val decision = ContentTriagePolicy.decide(
            observation = ContentRoutingObservation(
                contentClass = "character",
                peopleCount = 1,
            ),
            resolvedCharacterCount = 0,
            characterKnowledgeReady = false,
        )

        assertEquals(ContentTriagePolicy.ROUTE_WAITING_FOR_KNOWLEDGE, decision.route)
        assertFalse(decision.requiresReview)
        assertFalse(decision.terminal)
    }

    @Test
    fun `resolved character stays in canonical character flow`() {
        val decision = ContentTriagePolicy.decide(
            observation = ContentRoutingObservation(
                contentClass = "character",
                peopleCount = 1,
            ),
            resolvedCharacterCount = 1,
            characterKnowledgeReady = true,
        )

        assertEquals(ContentTriagePolicy.ROUTE_CHARACTER, decision.route)
        assertFalse(decision.terminal)
        assertFalse(decision.requiresReview)
    }
}
