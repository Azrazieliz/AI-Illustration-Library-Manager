package com.ailm.android.runtime

class KnowledgeValidator {
    fun validate(pack: ParsedKnowledgePack): KnowledgeValidationReport {
        val issues = mutableListOf<KnowledgeValidationIssue>()

        if (pack.packId.isBlank()) {
            issues += issue("missing_pack_id", "Knowledge Pack ID is required.")
        }
        if (pack.version.isBlank()) {
            issues += issue("missing_version", "Knowledge Pack version is required.")
        }
        if (pack.knowledgeType.isBlank()) {
            issues += issue("missing_knowledge_type", "Knowledge Pack knowledge type is required.")
        }
        if (pack.entries.isEmpty()) {
            issues += issue("empty_entries", "Knowledge Pack contains no entries.")
        }

        val knownIds = linkedSetOf<String>()
        val seenIds = linkedMapOf<String, String>()
        pack.entries.forEachIndexed { index, entry ->
            val path = "entries[$index]"
            if (entry.name.isBlank() && entry.id.isBlank()) {
                issues += issue("missing_identity", "Entry ${index + 1} is missing both name and id.", path)
            }
            if (entry.id.isNotBlank()) {
                val normalizedId = entry.id.trim().lowercase()
                if (seenIds.containsKey(normalizedId)) {
                    issues += issue("duplicate_id", "Duplicate entry id '${entry.id}' found in ${pack.packId}.", path)
                } else {
                    seenIds[normalizedId] = entry.id
                    knownIds += entry.id
                }
            }
            if (entry.relationships.isNotEmpty()) {
                entry.relationships.forEachIndexed { relationIndex, relation ->
                    if (relation.targetId.isBlank()) {
                        issues += issue("invalid_relationship", "Relationship ${relationIndex + 1} is missing a target id.", "$path.relationships[$relationIndex]")
                    } else if (!knownIds.contains(relation.targetId) && !seenIds.containsKey(relation.targetId.trim().lowercase())) {
                        issues += issue("missing_relationship_target", "Relationship references missing target '${relation.targetId}'.", "$path.relationships[$relationIndex]")
                    }
                }
            }
            validateTaxonomyReferences(entry, knownIds, issues, path)
            if (taxonomicKnowledgeType(pack.knowledgeType) && entry.taxonomy.length() == 0) {
                issues += issue("missing_taxonomy", "Entry ${index + 1} does not declare taxonomy data.", path)
            }
        }

        return KnowledgeValidationReport(
            ok = issues.isEmpty(),
            packId = pack.packId,
            packName = pack.packName,
            issues = issues,
            entryCount = pack.entries.size,
            warnings = emptyList(),
        )
    }

    private fun validateTaxonomyReferences(
        entry: ParsedKnowledgeEntry,
        knownIds: Set<String>,
        issues: MutableList<KnowledgeValidationIssue>,
        path: String,
    ) {
        val refs = mutableListOf<String>()
        if (entry.metadata.has("taxonomy_id")) {
            refs += entry.metadata.optString("taxonomy_id")
        }
        if (entry.metadata.has("parent_taxonomy_id")) {
            refs += entry.metadata.optString("parent_taxonomy_id")
        }
        if (entry.taxonomy.has("parent_id")) {
            refs += entry.taxonomy.optString("parent_id")
        }
        if (entry.taxonomy.has("taxonomy_id")) {
            refs += entry.taxonomy.optString("taxonomy_id")
        }
        refs.filter { it.isNotBlank() }.forEach { reference ->
            if (!knownIds.contains(reference) && !entry.rawProperties.containsKey(reference)) {
                issues += issue("missing_taxonomy_reference", "Taxonomy reference '$reference' could not be resolved.", path)
            }
        }
    }

    private fun issue(code: String, message: String, path: String? = null): KnowledgeValidationIssue {
        return KnowledgeValidationIssue(code = code, message = message, path = path)
    }

    private fun taxonomicKnowledgeType(knowledgeType: String): Boolean {
        return knowledgeType in setOf("taxonomy", "taxonomies", "tag", "tags", "taxonomy_database")
    }
}

data class KnowledgeValidationIssue(
    val code: String,
    val message: String,
    val path: String? = null,
)

data class KnowledgeValidationReport(
    val ok: Boolean,
    val packId: String,
    val packName: String,
    val issues: List<KnowledgeValidationIssue>,
    val entryCount: Int,
    val warnings: List<KnowledgeValidationIssue>,
)
