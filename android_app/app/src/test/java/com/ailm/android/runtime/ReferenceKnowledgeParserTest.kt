package com.ailm.android.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ReferenceKnowledgeParserTest {
    @Test
    fun `parses series and heterogeneous tag schemas without characters`() {
        val bundle = ReferenceKnowledgeParser.parseDocuments(
            mapOf(
                "series_1623_entries.json" to """[
                    {"series_code":"SE0001","canonical_name":"Example Series","franchise":"SE0001","aliases":["Example"]}
                ]""",
                "Outfits.json" to """[
                    {"id":"OF001","parent_outfit":"","canonical_name":"Casual","aliases":["Casual Wear"]}
                ]""",
                "Expressions.json" to """{
                    "expressions":[
                        {"tag_id":"EX001","canonical_name":"Neutral","aliases":[]}
                    ]
                }""",
            ),
        )

        assertEquals(1, bundle.series.size)
        assertEquals("SE0001", bundle.series.single().code)
        assertEquals(2, bundle.tags.size)
        assertTrue(bundle.tags.any { it.id == "OF001" && it.category == "outfit" })
        assertTrue(bundle.tags.any { it.id == "EX001" && it.category == "expression" })
    }
}
