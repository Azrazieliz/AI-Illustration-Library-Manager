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

    @Test
    fun `character parser preserves multiple ids in one attribute family`() {
        val bundle = ReferenceKnowledgeParser.parseDocuments(
            mapOf(
                "characters.json" to """[
                    {
                      "character_id":"CH000001",
                      "canonical_name":"Example",
                      "primary_series_code":"SE0001",
                      "attributes":{
                        "hair_color":["HC015","HC030"],
                        "eye_color":["EC010","EC014"],
                        "eye_traits":["ET001"]
                      }
                    }
                ]"""
            ),
        )

        val character = bundle.characters.single()
        assertEquals(
            setOf("HC015", "HC030", "EC010", "EC014", "ET001"),
            character.attributeIds.toSet(),
        )
        assertEquals(5, character.attributeIds.size)
    }

    @Test
    fun `transformation parser keeps base name and explicit form name`() {
        val bundle = ReferenceKnowledgeParser.parseDocuments(
            mapOf(
                "characters.json" to """[
                    {
                      "character_id":"CH000002-1",
                      "parent_character_id":"CH000002",
                      "entry_type":"transformation",
                      "canonical_name":"Goku",
                      "form_name":"Super Saiyan 3",
                      "primary_series_code":"SE0002",
                      "attribute_ids":["HC011"]
                    }
                ]"""
            ),
        )

        val character = bundle.characters.single()
        assertEquals("Goku", character.canonicalName)
        assertEquals("Super Saiyan 3", character.formName)
        assertEquals("Goku (Super Saiyan 3)", character.displayName)
        assertEquals("transformation", character.entryType)
    }
}
