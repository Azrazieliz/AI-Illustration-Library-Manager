package com.ailm.android.runtime

import org.junit.Test
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue

class KnowledgePackRoutingTest {
    @Test
    fun arrayRootKnowledgeJsonParsesAsKnowledgePack() {
        val raw = """
            [
              {
                "id": "char:hero",
                "name": "Hero",
                "categories": ["character"],
                "tags": ["hero"]
              }
            ]
        """.trimIndent()

        val parsed = KnowledgePackParser().parse(raw)
        val report = KnowledgeValidator().validate(parsed)

        assertTrue(parsed.packId.startsWith("inline-array-"))
        assertEquals("Inline Array Pack", parsed.packName)
        assertEquals(1, parsed.entries.size)
        assertTrue(report.ok)
    }
}
