package com.ailm.android.runtime

import java.util.Locale
import java.security.MessageDigest

class KnowledgeCanonicalBuilder {
    fun build(packs: List<ParsedKnowledgePack>): CanonicalKnowledgeModel {
        val sortedPacks = packs.sortedWith(compareBy<ParsedKnowledgePack> { it.knowledgeType.lowercase(Locale.US) }.thenBy { it.packId.lowercase(Locale.US) }.thenBy { it.version })
        val characters = linkedMapOf<String, CanonicalCharacterEntity>()
        val taxonomies = linkedMapOf<String, CanonicalTaxonomyEntity>()
        val relationships = linkedMapOf<String, CanonicalRelationship>()
        val provenance = linkedMapOf<String, CanonicalProvenanceEntry>()

        sortedPacks.forEachIndexed { packIndex, pack ->
            val isTaxonomyPack = isTaxonomyPack(pack.knowledgeType)
            pack.entries.sortedWith(compareBy<ParsedKnowledgeEntry> { it.id.ifBlank { it.name } }.thenBy { it.index }).forEachIndexed { entryIndex, entry ->
                if (isTaxonomyPack) {
                    mergeTaxonomyEntry(pack, packIndex, entryIndex, entry, taxonomies, provenance)
                } else {
                    mergeCharacterEntry(pack, packIndex, entryIndex, entry, characters, taxonomies, relationships, provenance)
                }
            }
        }

        val canonicalEntries = (characters.values.map(::toEntry) + taxonomies.values.map(::toEntry)).sortedBy { it.id.lowercase(Locale.US) }
        val canonicalRelationships = relationships.values.sortedWith(compareBy<CanonicalRelationship> { it.sourceId.lowercase(Locale.US) }.thenBy { it.targetId.lowercase(Locale.US) })
        val signature = MessageDigest.getInstance("SHA-256").digest(canonicalEntries.joinToString("|") { it.id }.toByteArray()).joinToString("") { "%02x".format(it) }

        return CanonicalKnowledgeModel(
            packId = "canonical-knowledge",
            packName = "Canonical Knowledge",
            version = "1.0.0",
            knowledgeType = "canonical",
            author = "AsterionCore",
            creationDate = "",
            description = "Merged knowledge from installed packs",
            dependencies = sortedPacks.flatMap { it.dependencies }.distinct().sorted(),
            supportedCategories = sortedPacks.flatMap { it.supportedCategories }.distinct().sorted(),
            entries = canonicalEntries,
            characters = characters.values.sortedBy { it.id.lowercase(Locale.US) },
            taxonomies = taxonomies.values.sortedBy { it.id.lowercase(Locale.US) },
            relationships = canonicalRelationships,
            provenance = provenance.values.sortedBy { it.packId.lowercase(Locale.US) },
            builtAtMs = System.currentTimeMillis(),
            canonicalSignature = signature,
        )
    }

    private fun mergeCharacterEntry(
        pack: ParsedKnowledgePack,
        packIndex: Int,
        entryIndex: Int,
        entry: ParsedKnowledgeEntry,
        characters: LinkedHashMap<String, CanonicalCharacterEntity>,
        taxonomies: LinkedHashMap<String, CanonicalTaxonomyEntity>,
        relationships: LinkedHashMap<String, CanonicalRelationship>,
        provenance: LinkedHashMap<String, CanonicalProvenanceEntry>,
    ) {
        val entryId = entry.id.ifBlank { buildDeterministicId(pack.packId, entry.name, entryIndex) }
        val mergeKey = normalizeMergeKey(entry.id, entry.name)
        val existing = characters.values.firstOrNull { normalizeMergeKey(it.id, it.name) == mergeKey }
        val entityId = existing?.id ?: entryId
        val taxonomyIds = collectTaxonomyIds(entry)
        val entity = (existing ?: CanonicalCharacterEntity(
            id = entityId,
            name = entry.name.ifBlank { entryId },
            aliases = entry.aliases.toMutableList(),
            categories = entry.categories.toMutableList(),
            taxonomyIds = taxonomyIds.toMutableList(),
            metadata = entry.metadata.toMap().mapValues { (_, value) -> value.toString() }.toMutableMap(),
            provenance = mutableListOf(),
            sourcePackId = pack.packId,
            sourcePackName = pack.packName,
            sourceVersion = pack.version,
            sourceKnowledgeType = pack.knowledgeType,
            sourcePrecedence = sourcePrecedence(pack, packIndex),
        )).copy(
            name = (existing?.name ?: entry.name).ifBlank { entryId },
            aliases = (existing?.aliases ?: emptyList()) + entry.aliases,
            categories = (existing?.categories ?: emptyList()) + entry.categories,
            taxonomyIds = (existing?.taxonomyIds ?: emptyList()) + taxonomyIds,
            metadata = mergeStringMaps(existing?.metadata ?: emptyMap(), entry.metadata.toMap().mapValues { (_, value) -> value.toString() }),
            provenance = (existing?.provenance ?: emptyList()) + createProvenance(pack, entry),
            sourcePackId = existing?.sourcePackId ?: pack.packId,
            sourcePackName = existing?.sourcePackName ?: pack.packName,
            sourceVersion = existing?.sourceVersion ?: pack.version,
            sourceKnowledgeType = existing?.sourceKnowledgeType ?: pack.knowledgeType,
            sourcePrecedence = maxOf(existing?.sourcePrecedence ?: Long.MIN_VALUE, sourcePrecedence(pack, packIndex)),
        )
        characters[entityId] = entity
        taxonomyIds.forEach { taxonomyId ->
            val taxonomy = taxonomies[taxonomyId]
            if (taxonomy == null) {
                taxonomies[taxonomyId] = CanonicalTaxonomyEntity(
                    id = taxonomyId,
                    name = taxonomyId,
                    parentId = null,
                    aliases = emptyList(),
                    metadata = emptyMap(),
                    provenance = mutableListOf(),
                    sourcePackId = pack.packId,
                    sourcePackName = pack.packName,
                    sourceVersion = pack.version,
                    sourceKnowledgeType = pack.knowledgeType,
                    sourcePrecedence = sourcePrecedence(pack, packIndex),
                )
            }
        }
        entry.relationships.forEach { relationship ->
            val targetId = relationship.targetId.ifBlank { entryId }
            val relId = "${entityId}::${targetId}::${relationship.relation}"
            relationships[relId] = CanonicalRelationship(
                id = relId,
                sourceId = entityId,
                targetId = targetId,
                relation = relationship.relation.ifBlank { "related" },
                provenance = createProvenance(pack, entry),
            )
        }
        createProvenance(pack, entry).forEach { prov -> provenance[prov.packId + ":" + prov.entryId] = prov }
    }

    private fun mergeTaxonomyEntry(
        pack: ParsedKnowledgePack,
        packIndex: Int,
        entryIndex: Int,
        entry: ParsedKnowledgeEntry,
        taxonomies: LinkedHashMap<String, CanonicalTaxonomyEntity>,
        provenance: LinkedHashMap<String, CanonicalProvenanceEntry>,
    ) {
        val taxonomyId = entry.id.ifBlank { buildDeterministicId(pack.packId, entry.name, entryIndex) }
        val existing = taxonomies[taxonomyId]
        val entity = (existing ?: CanonicalTaxonomyEntity(
            id = taxonomyId,
            name = entry.name.ifBlank { taxonomyId },
            parentId = entry.taxonomy.optString("parent_id").ifBlank { entry.taxonomy.optString("parent_taxonomy_id") },
            aliases = entry.aliases.toMutableList(),
            metadata = entry.metadata.toMap().mapValues { (_, value) -> value.toString() }.toMutableMap(),
            provenance = mutableListOf(),
            sourcePackId = pack.packId,
            sourcePackName = pack.packName,
            sourceVersion = pack.version,
            sourceKnowledgeType = pack.knowledgeType,
            sourcePrecedence = sourcePrecedence(pack, packIndex),
        )).copy(
            name = (existing?.name ?: entry.name).ifBlank { taxonomyId },
            aliases = (existing?.aliases ?: emptyList()) + entry.aliases,
            metadata = mergeStringMaps(existing?.metadata ?: emptyMap(), entry.metadata.toMap().mapValues { (_, value) -> value.toString() }),
            provenance = (existing?.provenance ?: emptyList()) + createProvenance(pack, entry),
            parentId = existing?.parentId ?: entry.taxonomy.optString("parent_id").ifBlank { entry.taxonomy.optString("parent_taxonomy_id") },
            sourcePackId = existing?.sourcePackId ?: pack.packId,
            sourcePackName = existing?.sourcePackName ?: pack.packName,
            sourceVersion = existing?.sourceVersion ?: pack.version,
            sourceKnowledgeType = existing?.sourceKnowledgeType ?: pack.knowledgeType,
            sourcePrecedence = maxOf(existing?.sourcePrecedence ?: Long.MIN_VALUE, sourcePrecedence(pack, packIndex)),
        )
        taxonomies[taxonomyId] = entity
        createProvenance(pack, entry).forEach { prov -> provenance[prov.packId + ":" + prov.entryId] = prov }
    }

    private fun collectTaxonomyIds(entry: ParsedKnowledgeEntry): List<String> {
        val refs = mutableListOf<String>()
        refs += entry.taxonomy.keys().asSequence().filter { it.endsWith("_id") || it == "taxonomy_id" }.mapNotNull { key -> entry.taxonomy.optString(key).takeIf { it.isNotBlank() } }
        refs += entry.metadata.optString("taxonomy_id").takeIf { it.isNotBlank() }.orEmpty().let { if (it.isNotBlank()) listOf(it) else emptyList() }
        refs += entry.metadata.optString("parent_taxonomy_id").takeIf { it.isNotBlank() }.orEmpty().let { if (it.isNotBlank()) listOf(it) else emptyList() }
        return refs.distinct()
    }

    private fun createProvenance(pack: ParsedKnowledgePack, entry: ParsedKnowledgeEntry): List<CanonicalProvenanceEntry> {
        val packRef = CanonicalProvenanceEntry(
            packId = pack.packId,
            packName = pack.packName,
            version = pack.version,
            knowledgeType = pack.knowledgeType,
            entryId = entry.id.ifBlank { "${pack.packId}:entry:${entry.index + 1}" },
            entryName = entry.name.ifBlank { entry.id },
        )
        return listOf(packRef)
    }

    private fun isTaxonomyPack(knowledgeType: String): Boolean {
        return knowledgeType.lowercase(Locale.US) in setOf("taxonomy", "taxonomies", "tag", "tags", "taxonomy_database")
    }

    private fun sourcePrecedence(pack: ParsedKnowledgePack, packIndex: Int): Long {
        val metadataPriority = (pack.rawMetadata["priority"] as? Number)?.toLong() ?: 0L
        val versionScore = pack.version.split(".").mapNotNull { it.toLongOrNull() }.fold(0L) { acc, value -> acc * 1000 + value }
        return metadataPriority * 1_000_000_000L + versionScore * 1_000L + packIndex.toLong()
    }

    private fun buildDeterministicId(packId: String, name: String, index: Int): String {
        val normalized = name.ifBlank { "entry" }.trim().lowercase(Locale.US).replace(Regex("[^a-z0-9]+"), "-")
        return "${packId.lowercase(Locale.US)}:$normalized:${index + 1}"
    }

    private fun normalizeMergeKey(id: String, name: String): String {
        val primary = id.ifBlank { name }.trim().lowercase(Locale.US)
        return primary.ifBlank { "unknown" }
    }

    private fun mergeStringMaps(first: Map<String, String>, second: Map<String, String>): Map<String, String> {
        val merged = linkedMapOf<String, String>()
        (first.keys + second.keys).distinct().sorted().forEach { key ->
            val firstValue = first[key]
            val secondValue = second[key]
            merged[key] = when {
                !firstValue.isNullOrBlank() -> firstValue
                !secondValue.isNullOrBlank() -> secondValue
                else -> ""
            }
        }
        return merged
    }

    private fun toEntry(entity: CanonicalCharacterEntity): CanonicalKnowledgeEntry {
        return CanonicalKnowledgeEntry(
            id = entity.id,
            name = entity.name,
            categories = entity.categories.distinct().sorted(),
            taxonomy = entity.metadata.filterKeys { it.contains("taxonomy", ignoreCase = true) || it.endsWith("_id") },
            metadata = entity.metadata,
            sourcePackId = entity.sourcePackId,
            sourcePackName = entity.sourcePackName,
            sourceVersion = entity.sourceVersion,
            sourceKnowledgeType = entity.sourceKnowledgeType,
            provenance = entity.provenance.map { it.packId },
            aliases = entity.aliases,
            tags = entity.categories,
        )
    }

    private fun toEntry(entity: CanonicalTaxonomyEntity): CanonicalKnowledgeEntry {
        return CanonicalKnowledgeEntry(
            id = entity.id,
            name = entity.name,
            categories = entity.metadata.keys.filter { it.contains("category", ignoreCase = true) }.toList(),
            taxonomy = mapOf("parent_id" to entity.parentId.orEmpty()),
            metadata = entity.metadata,
            sourcePackId = entity.sourcePackId,
            sourcePackName = entity.sourcePackName,
            sourceVersion = entity.sourceVersion,
            sourceKnowledgeType = entity.sourceKnowledgeType,
            provenance = entity.provenance.map { it.packId },
            aliases = entity.aliases,
            tags = emptyList(),
        )
    }
}

data class CanonicalKnowledgeModel(
    val packId: String,
    val packName: String,
    val version: String,
    val knowledgeType: String,
    val author: String,
    val creationDate: String,
    val description: String,
    val dependencies: List<String>,
    val supportedCategories: List<String>,
    val entries: List<CanonicalKnowledgeEntry>,
    val characters: List<CanonicalCharacterEntity>,
    val taxonomies: List<CanonicalTaxonomyEntity>,
    val relationships: List<CanonicalRelationship>,
    val provenance: List<CanonicalProvenanceEntry>,
    val builtAtMs: Long,
    val canonicalSignature: String,
)

data class CanonicalKnowledgeEntry(
    val id: String,
    val name: String,
    val categories: List<String>,
    val taxonomy: Map<String, String>,
    val metadata: Map<String, String>,
    val sourcePackId: String,
    val sourcePackName: String,
    val sourceVersion: String,
    val sourceKnowledgeType: String,
    val provenance: List<String>,
    val aliases: List<String>,
    val tags: List<String>,
)

data class CanonicalCharacterEntity(
    val id: String,
    val name: String,
    val aliases: List<String>,
    val categories: List<String>,
    val taxonomyIds: List<String>,
    val metadata: Map<String, String>,
    val provenance: List<CanonicalProvenanceEntry>,
    val sourcePackId: String,
    val sourcePackName: String,
    val sourceVersion: String,
    val sourceKnowledgeType: String,
    val sourcePrecedence: Long,
)

data class CanonicalTaxonomyEntity(
    val id: String,
    val name: String,
    val parentId: String?,
    val aliases: List<String>,
    val metadata: Map<String, String>,
    val provenance: List<CanonicalProvenanceEntry>,
    val sourcePackId: String,
    val sourcePackName: String,
    val sourceVersion: String,
    val sourceKnowledgeType: String,
    val sourcePrecedence: Long,
)

data class CanonicalRelationship(
    val id: String,
    val sourceId: String,
    val targetId: String,
    val relation: String,
    val provenance: List<CanonicalProvenanceEntry>,
)

data class CanonicalProvenanceEntry(
    val packId: String,
    val packName: String,
    val version: String,
    val knowledgeType: String,
    val entryId: String,
    val entryName: String,
)
