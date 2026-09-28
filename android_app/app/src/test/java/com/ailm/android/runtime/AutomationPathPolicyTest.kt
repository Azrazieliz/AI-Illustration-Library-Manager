package com.ailm.android.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test

class AutomationPathPolicyTest {
    @Test
    fun `single character lives in its character subfolder`() {
        val plan = AutomationPathPolicy.plan(
            listOf(
                ResolvedCharacterPathInput(
                    subjectIndex = 0,
                    prominence = 1.0,
                    canonicalName = "Rin Tohsaka",
                    seriesCode = "SE0001",
                    seriesName = "Fate",
                ),
            ),
        )

        assertNotNull(plan)
        assertEquals(listOf("Fate", "Rin Tohsaka"), plan!!.folderSegments)
        assertEquals("Rin Tohsaka - Fate", plan.filenamePrefix)
    }

    @Test
    fun `intraseries multi character image stays in series folder`() {
        val plan = AutomationPathPolicy.plan(
            listOf(
                ResolvedCharacterPathInput(0, 0.8, "Artoria", "Artoria", "SE0001", "Fate"),
                ResolvedCharacterPathInput(1, 0.7, "Rin Tohsaka", "Rin Tohsaka", "SE0001", "Fate"),
            ),
        )

        assertNotNull(plan)
        assertEquals(listOf("Fate"), plan!!.folderSegments)
        assertEquals("Artoria - Rin Tohsaka - Fate", plan.filenamePrefix)
    }

    @Test
    fun `interseries image is owned by most prominent character but keeps all names`() {
        val plan = AutomationPathPolicy.plan(
            listOf(
                ResolvedCharacterPathInput(0, 0.35, "Character A", "Character A", "SE0001", "Series A"),
                ResolvedCharacterPathInput(1, 0.92, "Character B", "Character B", "SE0002", "Series B"),
            ),
        )

        assertNotNull(plan)
        assertEquals(listOf("Series B", "Character B"), plan!!.folderSegments)
        assertEquals("Character A - Character B - Series B", plan.filenamePrefix)
        assertEquals("Character B", plan.primaryCharacter)
        assertEquals("Series B", plan.primarySeries)
    }

    @Test
    fun `transformation keeps base character folder but form-aware filename`() {
        val plan = AutomationPathPolicy.plan(
            listOf(
                ResolvedCharacterPathInput(
                    subjectIndex = 0,
                    prominence = 1.0,
                    canonicalName = "Goku",
                    displayName = "Goku (Super Saiyan 3)",
                    seriesCode = "SE0002",
                    seriesName = "Dragon Ball",
                ),
            ),
        )

        assertNotNull(plan)
        assertEquals(listOf("Dragon Ball", "Goku"), plan!!.folderSegments)
        assertEquals("Goku (Super Saiyan 3) - Dragon Ball", plan.filenamePrefix)
    }

    @Test
    fun `original character path stays outside canonical character knowledge`() {
        val plan = AutomationPathPolicy.plan(
            characters = emptyList(),
            originalCharacter = true,
            originalCharacterClusterId = "OC000123",
        )

        assertNotNull(plan)
        assertEquals(listOf("Original Characters"), plan!!.folderSegments)
        assertEquals("Original Character", plan.filenamePrefix)
        assertEquals("OC000123", plan.primaryCharacter)
    }
}
