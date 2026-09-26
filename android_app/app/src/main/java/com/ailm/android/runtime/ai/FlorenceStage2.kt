package com.ailm.android.runtime.ai

import android.content.Context
import java.io.File

internal interface FlorenceOnnxExecutor {
    fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>>
}

internal data class FlorenceStage2RuntimeResult(
    val encoder: FlorenceEncoderResult,
    val executionOrder: List<String>,
)

internal data class FlorenceDecoderResult(
    val decoderStartTokenId: Int,
    val decoderInputIds: List<List<Int>>,
    val decoderInputsEmbeds: List<List<List<Float>>>,
    val encoderHiddenStates: List<List<List<Float>>>,
    val encoderAttentionMask: List<List<Long>>,
    val logits: List<Float>,
    val presentKeyValues: Map<String, List<Float>>,
    val outputMetadata: Map<String, Any>,
) {
    fun toMap(): Map<String, Any> = linkedMapOf(
        "decoder_start_token_id" to decoderStartTokenId,
        "decoder_input_ids" to decoderInputIds,
        "decoder_inputs_embeds" to decoderInputsEmbeds,
        "encoder_hidden_states" to encoderHiddenStates,
        "encoder_attention_mask" to encoderAttentionMask,
        "logits" to logits,
        "present_key_values" to presentKeyValues,
        "output_metadata" to outputMetadata,
    )
}

internal data class FlorenceStage3RuntimeResult(
    val decoder: FlorenceDecoderResult,
    val executionOrder: List<String>,
)

internal data class FlorenceGenerationResult(
    val decoderInputIds: List<List<Int>>,
    val generatedTokenIds: List<Int>,
    val generatedText: String,
    val parsedResult: Map<String, Any> = emptyMap(),
    val logits: List<Float>,
    val presentKeyValues: Map<String, List<Float>>,
    val outputMetadata: Map<String, Any>,
) {
    fun toMap(): Map<String, Any> = linkedMapOf(
        "decoder_input_ids" to decoderInputIds,
        "generated_token_ids" to generatedTokenIds,
        "generated_text" to generatedText,
        "parsed_result" to parsedResult,
        "logits" to logits,
        "present_key_values" to presentKeyValues,
        "output_metadata" to outputMetadata,
    )
}

internal data class FlorenceStage4RuntimeResult(
    val generation: FlorenceGenerationResult,
    val executionOrder: List<String>,
)

internal fun FlorenceEncoderResult.toMap(): Map<String, Any> = mapOf(
    "input_ids" to inputIds,
    "text_sequence_length" to textSequenceLength,
    "image_sequence_length" to imageSequenceLength,
    "encoder_sequence_length" to encoderSequenceLength,
    "encoder_attention_mask" to encoderAttentionMask,
    "last_hidden_state" to (lastHiddenState ?: emptyList<List<List<Float>>>()),
    "hidden_size" to hiddenSize,
)

internal class FlorenceStage2Coordinator(
    private val context: Context?,
    private val executor: FlorenceOnnxExecutor,
) {
    fun execute(model: AiModelDescriptor, request: AiExecutionRequest): FlorenceStage2RuntimeResult {
        val roles = model.metadata["artifact_paths_by_role"] as? Map<*, *>
            ?: throw ModelInferenceContractException("Florence package is missing artifact role paths")
        fun roleModel(role: String): AiModelDescriptor {
            val path = roles[role]?.toString()?.takeIf(String::isNotBlank)
                ?: throw ModelInferenceContractException("Florence package has no artifact for role '$role'")
            return model.copy(installPath = path)
        }

        val internalImageFeatures = request.payload["image_features"]?.let(::decodeInternalImageFeatures)
        val imageFeatures = internalImageFeatures
            ?: run {
                val visionModel = roleModel("vision_encoder")
                val visionContract = ModelInferenceContract.resolve(visionModel, "vision_encoder")
                val visionInputs = ModelInputPreprocessor(context).prepare(visionContract, request.payload)
                val visionOutput = executor.run("vision_encoder", visionModel, visionInputs)
                decodeFlorenceImageFeatures(
                    visionOutput["image_features"] ?: throw ModelInferenceContractException("Florence vision encoder returned no image_features"),
                )
            }

        val tokenizer = FlorenceTokenizer.fromModel(model)
        val tokenized = tokenizer.encode(request.payload["text"]?.toString() ?: request.payload["prompt"]?.toString() ?: request.taskType)
        val inputIds = listOf(tokenized.ids)
        val textLength = tokenized.ids.size
        val idsTensor = PreparedInferenceTensor("input_ids", "int64", longArrayOf(1, textLength.toLong()), longs = tokenized.ids.map(Int::toLong).toLongArray())
        val embedModel = roleModel("embed_tokens")
        val embedOutput = executor.run("embed_tokens", embedModel, listOf(idsTensor))
        val textEmbeddings = decodeFlorenceEmbedding(embedOutput["inputs_embeds"], textLength, "inputs_embeds")
        val composed = composeFlorencePrefixEncoderInputs(
            inputIds = inputIds,
            textEmbeddings = textEmbeddings,
            imageFeatures = listOf(imageFeatures.tokens),
            attentionMask = listOf(tokenized.mask.map(Int::toLong)),
        )
        require(composed.encoderAttentionMask.single().size == composed.inputsEmbeds.single().size) {
            "Florence encoder attention mask length does not match inputs_embeds"
        }
        val encoderModel = roleModel("encoder")
        val encoderInputs = listOf(
            PreparedInferenceTensor("attention_mask", "int64", longArrayOf(1, composed.encoderSequenceLength.toLong()), longs = composed.encoderAttentionMask.single().toLongArray()),
            PreparedInferenceTensor("inputs_embeds", "float32", longArrayOf(1, composed.encoderSequenceLength.toLong(), FLORENCE_HIDDEN_SIZE.toLong()), floats = composed.inputsEmbeds.single().flatten().toFloatArray()),
        )
        val encoderOutput = executor.run("encoder", encoderModel, encoderInputs)
        val lastHiddenState = decodeFlorenceEmbedding(encoderOutput["last_hidden_state"], composed.encoderSequenceLength, "last_hidden_state")
        val order = if (internalImageFeatures == null) {
            listOf("vision_encoder", "embed_tokens", "encoder")
        } else {
            listOf("embed_tokens", "encoder")
        }
        return FlorenceStage2RuntimeResult(composed.withFlorenceLastHiddenState(lastHiddenState), order)
    }

    private fun decodeInternalImageFeatures(raw: Any): FlorenceImageFeatures {
        val rows = when (raw) {
            is List<*> -> raw.map { row ->
                (row as? List<*>)?.map { it.toString().toFloat() }
                    ?: throw ModelInferenceContractException("Florence image_features must be rank 3")
            }
            else -> throw ModelInferenceContractException("Florence image_features must be rank 3")
        }
        require(rows.isNotEmpty() && rows.all { it.size == FLORENCE_HIDDEN_SIZE }) {
            "Florence image_features must have hidden size 768"
        }
        return FlorenceImageFeatures(rows, rows.size, FLORENCE_HIDDEN_SIZE)
    }

}

private fun decodeFlorenceEmbedding(values: List<Float>?, sequenceLength: Int, name: String): List<List<List<Float>>> {
    val raw = values ?: throw ModelInferenceContractException("Florence $name output is missing")
    require(raw.size == sequenceLength * FLORENCE_HIDDEN_SIZE) {
        "Florence $name must be [B,$sequenceLength,768], got ${raw.size} values"
    }
    return listOf(raw.toList().chunked(FLORENCE_HIDDEN_SIZE))
}

internal class FlorenceStage3Coordinator(
    private val executor: FlorenceOnnxExecutor,
) {
    fun execute(
        model: AiModelDescriptor,
        request: AiExecutionRequest,
        stage2: FlorenceStage2RuntimeResult,
    ): FlorenceStage3RuntimeResult {
        val roles = model.metadata["artifact_paths_by_role"] as? Map<*, *>
            ?: throw ModelInferenceContractException("Florence package is missing artifact role paths")
        fun roleModel(role: String): AiModelDescriptor {
            val path = roles[role]?.toString()?.takeIf(String::isNotBlank)
                ?: throw ModelInferenceContractException("Florence package has no artifact for role '$role'")
            return model.copy(installPath = path)
        }

        val decoderStartTokenId = decodeFlorenceDecoderStartTokenId(model)
        val decoderInputIds = listOf(List(1) { decoderStartTokenId })
        val embedModel = roleModel("embed_tokens")
        val embedInput = PreparedInferenceTensor(
            "input_ids",
            "int64",
            longArrayOf(1, 1),
            longs = decoderInputIds.single().map(Int::toLong).toLongArray(),
        )
        val decoderEmbeddings = executor.run("embed_tokens", embedModel, listOf(embedInput))
        val decoderInputsEmbeds = decodeFlorenceEmbedding(decoderEmbeddings["inputs_embeds"], 1, "inputs_embeds")

        val encoderHiddenStates = stage2.encoder.lastHiddenState
            ?: throw ModelInferenceContractException("Florence Stage 2 encoder output is missing last_hidden_state")
        val encoderAttentionMask = stage2.encoder.encoderAttentionMask
        val flattenedEncoderHiddenState = encoderHiddenStates.single().flatMap { row -> row }

        val decoderModel = roleModel("decoder")
        val decoderInputs = listOf(
            PreparedInferenceTensor(
                "input_ids",
                "int64",
                longArrayOf(1, 1),
                longs = decoderInputIds.single().map(Int::toLong).toLongArray(),
            ),
            PreparedInferenceTensor(
                "encoder_hidden_states",
                "float32",
                longArrayOf(1, stage2.encoder.encoderSequenceLength.toLong(), FLORENCE_HIDDEN_SIZE.toLong()),
                floats = flattenedEncoderHiddenState.toFloatArray(),
            ),
            PreparedInferenceTensor(
                "encoder_attention_mask",
                "int64",
                longArrayOf(1, stage2.encoder.encoderSequenceLength.toLong()),
                longs = encoderAttentionMask.single().toLongArray(),
            ),
        )
        val decoderOutput = executor.run("decoder", decoderModel, decoderInputs)
        val logits = decoderOutput["logits"] ?: emptyList()
        val expectedPresentKeys = buildList {
            for (layer in 0 until 6) {
                add("present.$layer.decoder.key")
                add("present.$layer.decoder.value")
                add("present.$layer.encoder.key")
                add("present.$layer.encoder.value")
            }
        }
        val presentKeyValues = decoderOutput.filterKeys { key -> expectedPresentKeys.contains(key) }
        require(presentKeyValues.size == expectedPresentKeys.size) {
            "Florence decoder output is missing required present tensors: ${expectedPresentKeys.filterNot(presentKeyValues::containsKey)}"
        }
        val outputMetadata = linkedMapOf<String, Any>(
            "decoder_input_name" to "input_ids",
            "encoder_hidden_state_name" to "encoder_hidden_states",
            "encoder_attention_mask_name" to "encoder_attention_mask",
            "present_output_count" to presentKeyValues.size,
            "has_logits" to logits.isNotEmpty(),
            "cache_enabled" to true,
            "request_task" to request.taskType,
        )

        return FlorenceStage3RuntimeResult(
            decoder = FlorenceDecoderResult(
                decoderStartTokenId = decoderStartTokenId,
                decoderInputIds = decoderInputIds,
                decoderInputsEmbeds = decoderInputsEmbeds,
                encoderHiddenStates = encoderHiddenStates,
                encoderAttentionMask = encoderAttentionMask,
                logits = logits,
                presentKeyValues = presentKeyValues,
                outputMetadata = outputMetadata,
            ),
            executionOrder = stage2.executionOrder + listOf("embed_tokens", "decoder"),
        )
    }

    private fun decodeFlorenceDecoderStartTokenId(model: AiModelDescriptor): Int {
        val generationConfig = model.metadata["generation_config"] as? Map<*, *> ?: emptyMap<String, Any>()
        val config = model.metadata["config"] as? Map<*, *> ?: emptyMap<String, Any>()
        val detected = generationConfig["decoder_start_token_id"]
            ?: config["decoder_start_token_id"]
            ?: (model.metadata["florence_package"] as? Map<*, *>)?.get("decoder_start_token_id")
            ?: 2
        return (detected as? Number)?.toInt() ?: 2
    }
}

internal class FlorenceStage4Coordinator(
    private val executor: FlorenceOnnxExecutor,
) {
    fun execute(
        model: AiModelDescriptor,
        request: AiExecutionRequest,
        stage3: FlorenceStage3RuntimeResult,
    ): FlorenceStage4RuntimeResult {
        val roles = model.metadata["artifact_paths_by_role"] as? Map<*, *>
            ?: throw ModelInferenceContractException("Florence package is missing artifact role paths")
        fun roleModel(role: String): AiModelDescriptor {
            val path = roles[role]?.toString()?.takeIf(String::isNotBlank)
                ?: throw ModelInferenceContractException("Florence package has no artifact for role '$role'")
            return model.copy(installPath = path)
        }

        val generationConfig = model.metadata["generation_config"] as? Map<*, *> ?: emptyMap<String, Any>()
        val config = model.metadata["config"] as? Map<*, *> ?: emptyMap<String, Any>()
        val textConfig = config["text_config"] as? Map<*, *> ?: emptyMap<String, Any>()
        val eosTokenId = (generationConfig["eos_token_id"] ?: generationConfig["forced_eos_token_id"] ?: textConfig["eos_token_id"] ?: 2) as? Number ?: 2
        val forcedBosTokenId = (generationConfig["forced_bos_token_id"] ?: generationConfig["bos_token_id"] ?: textConfig["forced_bos_token_id"] ?: textConfig["bos_token_id"] ?: 0) as? Number ?: 0
        val forcedEosTokenId = (generationConfig["forced_eos_token_id"] ?: generationConfig["eos_token_id"] ?: textConfig["forced_eos_token_id"] ?: textConfig["eos_token_id"] ?: 2) as? Number ?: 2
        val lengthPenalty = (generationConfig["length_penalty"] ?: textConfig["length_penalty"] ?: 1.0) as? Number ?: 1.0
        val maxLength = (request.payload["max_length"] as? Number)?.toInt()
            ?: (textConfig["max_length"] as? Number)?.toInt()
            ?: 20
        val maxNewTokens = (request.payload["max_new_tokens"] as? Number)?.toInt()
            ?: (maxLength - stage3.decoder.decoderInputIds.single().size).coerceAtLeast(0)
        val numBeams = ((generationConfig["num_beams"] ?: config["num_beams"] ?: textConfig["num_beams"] ?: 1) as? Number)?.toInt()
            ?: 1
        val effectiveNumBeams = numBeams.coerceAtLeast(1)
        val embedModel = roleModel("embed_tokens")
        val decoderModel = roleModel("decoder_with_past")
        val expectedPresentKeys = buildList {
            for (layer in 0 until 6) {
                add("present.$layer.decoder.key")
                add("present.$layer.decoder.value")
                add("present.$layer.encoder.key")
                add("present.$layer.encoder.value")
            }
        }

        val tokenizer = FlorenceTokenizer.fromModel(model)
        val beamSearchBeams = florenceInitialBeamStates(
            initialSequence = stage3.decoder.decoderInputIds.single(),
            numBeams = effectiveNumBeams,
            presentKeyValues = stage3.decoder.presentKeyValues,
            logits = stage3.decoder.logits,
        ).toMutableList()
        val completedBeams = mutableListOf<FlorenceGenerationBeam>()
        var decoderWithPastRuns = 0
        var generationStep = 0
        var currentEosEncountered = false

        while (generationStep < maxNewTokens.coerceAtLeast(1) && beamSearchBeams.isNotEmpty()) {
            val expandedBeams = mutableListOf<FlorenceGenerationBeam>()
            for (beam in beamSearchBeams) {
                if (beam.finished || beam.sequence.size >= maxLength) {
                    completedBeams += beam
                    continue
                }

                val topCandidates = florenceTopCandidates(
                    logits = beam.logits,
                    beamLimit = effectiveNumBeams,
                    parentBeamIndex = beam.beamIndex,
                    parentBeamScore = beam.score,
                )

                if (topCandidates.isEmpty()) {
                    completedBeams += beam
                    continue
                }

                for (candidate in topCandidates) {
                    val nextSequence = beam.sequence + candidate.tokenId
                    val completedBeam = FlorenceGenerationBeam(
                        sequence = nextSequence,
                        score = candidate.cumulativeScore,
                        presentKeyValues = beam.presentKeyValues,
                        logits = beam.logits,
                        finished = true,
                        beamIndex = candidate.parentBeamIndex,
                        parentBeamIndex = candidate.parentBeamIndex,
                        parentTokenId = candidate.tokenId,
                    )

                    if (candidate.tokenId == eosTokenId.toInt()) {
                        currentEosEncountered = true
                        completedBeams += completedBeam
                        continue
                    }

                    if (nextSequence.size >= maxLength) {
                        completedBeams += completedBeam
                        continue
                    }

                    val embedInput = PreparedInferenceTensor(
                        "input_ids",
                        "int64",
                        longArrayOf(1, 1),
                        longs = longArrayOf(candidate.tokenId.toLong()),
                    )
                    val embeddingOutput = executor.run("embed_tokens", embedModel, listOf(embedInput))
                    val decoderInputsEmbeds = decodeFlorenceEmbedding(embeddingOutput["inputs_embeds"], 1, "inputs_embeds")
                    val decoderInputs = buildFlorenceDecoderWithPastInputs(
                        stage3 = stage3,
                        presentKeyValues = beam.presentKeyValues,
                        decoderInputsEmbeds = decoderInputsEmbeds,
                    )
                    val decoderWithPastOutput = executor.run("decoder_with_past", decoderModel, decoderInputs)
                    val presentKeyValues = extractFlorencePresentKeyValues(decoderWithPastOutput, expectedPresentKeys)
                    val nextLogits = requireFlorenceLogits(decoderWithPastOutput["logits"])
                    decoderWithPastRuns += 1

                    expandedBeams += FlorenceGenerationBeam(
                        sequence = nextSequence,
                        score = candidate.cumulativeScore,
                        presentKeyValues = presentKeyValues,
                        logits = nextLogits,
                        finished = false,
                        beamIndex = expandedBeams.size,
                        parentBeamIndex = candidate.parentBeamIndex,
                        parentTokenId = candidate.tokenId,
                    )
                }
            }

            if (expandedBeams.isEmpty()) {
                break
            }

            val selectedBeams = florenceSelectTopBeamCandidates(expandedBeams, effectiveNumBeams, lengthPenalty.toFloat())
            val selectedParentIndices = selectedBeams.map { it.parentBeamIndex ?: -1 }
            beamSearchBeams.clear()
            beamSearchBeams += selectedBeams.mapIndexed { index, beam ->
                beam.copy(
                    beamIndex = index,
                    parentBeamIndex = beam.parentBeamIndex,
                    parentTokenId = beam.parentTokenId,
                )
            }

            val reorderedParentIndices = florenceReorderBeamStatesByParentIndices(
                beams = beamSearchBeams,
                parentBeamIndices = selectedParentIndices,
            )
            if (reorderedParentIndices.isNotEmpty()) {
                beamSearchBeams.clear()
                beamSearchBeams += reorderedParentIndices.mapIndexed { index, beam ->
                    beam.copy(beamIndex = index)
                }
            }

            if (completedBeams.size >= effectiveNumBeams) {
                break
            }

            generationStep += 1
        }

        val finalBeam = completedBeams
            .filter { it.presentKeyValues.isNotEmpty() }
            .maxByOrNull { florenceNormalizedBeamScore(it.score, it.sequence.size, lengthPenalty.toFloat()) }
            ?: beamSearchBeams
                .filter { it.presentKeyValues.isNotEmpty() }
                .maxByOrNull { florenceNormalizedBeamScore(it.score, it.sequence.size, lengthPenalty.toFloat()) }
            ?: FlorenceGenerationBeam(
                sequence = stage3.decoder.decoderInputIds.single().toMutableList(),
                score = 0f,
                presentKeyValues = stage3.decoder.presentKeyValues,
                logits = stage3.decoder.logits,
                finished = true,
            )

        val beamParentIndices = (completedBeams + beamSearchBeams)
            .map { it.parentBeamIndex ?: -1 }
            .takeIf { it.isNotEmpty() }
            ?: listOf(-1)

        val taskToken = FlorencePostProcessor.taskForPrompt(
            request.payload["prompt"]?.toString() ?: request.payload["text"]?.toString(),
        )
        val rawDecodedText = tokenizer.decodeForPostProcessing(finalBeam.sequence)
        val parsedResult = taskToken?.let { task ->
            FlorencePostProcessor.process(
                task = task,
                rawDecodedText = rawDecodedText,
                imageWidth = (request.payload["image_width"] as? Number)?.toInt(),
                imageHeight = (request.payload["image_height"] as? Number)?.toInt(),
            ).toMap()
        } ?: emptyMap()

        val outputMetadata = linkedMapOf<String, Any>(
            "decoder_with_past_model" to File(decoderModel.installPath).name,
            "generated_token_ids" to finalBeam.sequence,
            "generated_count" to finalBeam.sequence.size,
            "max_length" to maxLength,
            "max_new_tokens" to maxNewTokens,
            "eos_seen" to currentEosEncountered,
            "decoder_with_past_runs" to decoderWithPastRuns,
            "request_task" to request.taskType,
            "cache_enabled" to true,
            "num_beams" to effectiveNumBeams,
            "forced_bos_token_id" to forcedBosTokenId,
            "forced_eos_token_id" to forcedEosTokenId,
            "length_penalty" to lengthPenalty,
            "beam_parent_indices" to beamParentIndices,
            "generation_policy" to "beam_search",
        )

        return FlorenceStage4RuntimeResult(
            generation = FlorenceGenerationResult(
                decoderInputIds = stage3.decoder.decoderInputIds,
                generatedTokenIds = finalBeam.sequence,
                generatedText = tokenizer.decode(finalBeam.sequence),
                parsedResult = parsedResult,
                logits = finalBeam.logits,
                presentKeyValues = finalBeam.presentKeyValues,
                outputMetadata = outputMetadata,
            ),
            executionOrder = stage3.executionOrder + listOf("decoder_with_past"),
        )
    }

}

internal data class FlorenceGenerationBeam(
    val sequence: List<Int>,
    val score: Float,
    val presentKeyValues: Map<String, List<Float>>,
    val logits: List<Float>,
    val finished: Boolean,
    val beamIndex: Int = -1,
    val parentBeamIndex: Int? = null,
    val parentTokenId: Int? = null,
)

private fun florenceInitialBeamStates(
    initialSequence: List<Int>,
    numBeams: Int,
    presentKeyValues: Map<String, List<Float>>,
    logits: List<Float>,
): List<FlorenceGenerationBeam> {
    val beamCount = numBeams.coerceAtLeast(1)
    return List(beamCount) { index ->
        FlorenceGenerationBeam(
            sequence = initialSequence,
            score = if (index == 0) 0f else Float.NEGATIVE_INFINITY,
            presentKeyValues = if (index == 0) presentKeyValues else emptyMap(),
            logits = if (index == 0) logits else emptyList(),
            finished = false,
            beamIndex = index,
            parentBeamIndex = if (index == 0) null else null,
            parentTokenId = if (index == 0) null else null,
        )
    }
}

internal fun florenceApplyForcedTokenPolicy(
    logits: List<Float>,
    sequenceLength: Int,
    maxLength: Int,
    forcedBosTokenId: Int,
    forcedEosTokenId: Int,
): List<Float> {
    val masked = logits.toMutableList()

    if (sequenceLength == 1 && forcedBosTokenId >= 0) {
        val forcedScore = logits.getOrNull(forcedBosTokenId) ?: 0f
        for (index in masked.indices) {
            masked[index] = if (index == forcedBosTokenId) forcedScore else Float.NEGATIVE_INFINITY
        }
        return masked
    }

    if (sequenceLength == maxLength - 1 && forcedEosTokenId >= 0) {
        val forcedScore = logits.getOrNull(forcedEosTokenId) ?: 0f
        for (index in masked.indices) {
            masked[index] = if (index == forcedEosTokenId) forcedScore else Float.NEGATIVE_INFINITY
        }
        return masked
    }

    return logits
}

private data class FlorenceBeamCandidate(
    val tokenId: Int,
    val parentBeamIndex: Int,
    val cumulativeScore: Float,
    val tokenScore: Float,
)

private fun florenceTopCandidates(
    logits: List<Float>,
    beamLimit: Int,
    parentBeamIndex: Int,
    parentBeamScore: Float,
): List<FlorenceBeamCandidate> {
    if (logits.isEmpty()) return emptyList()
    val logProbabilities = florenceLogSoftmax(logits)
    val safeBeamLimit = beamLimit.coerceAtLeast(1)
    return logProbabilities
        .withIndex()
        .sortedByDescending { it.value }
        .take(safeBeamLimit)
        .map { (tokenId, tokenScore) ->
            FlorenceBeamCandidate(
                tokenId = tokenId,
                parentBeamIndex = parentBeamIndex,
                cumulativeScore = parentBeamScore + tokenScore,
                tokenScore = tokenScore,
            )
        }
}

private fun florenceSelectBeamCandidates(
    candidates: List<FlorenceBeamCandidate>,
    beamLimit: Int,
): List<FlorenceBeamCandidate> {
    require(beamLimit > 0) { "Florence beam search requires beamLimit > 0" }
    return candidates
        .sortedByDescending { it.cumulativeScore }
        .take(beamLimit)
}

internal fun florenceSelectTopBeamCandidates(
    expandedBeams: List<FlorenceGenerationBeam>,
    beamLimit: Int,
    lengthPenalty: Float,
): List<FlorenceGenerationBeam> {
    require(beamLimit > 0) { "Florence beam search requires beamLimit > 0" }
    return expandedBeams
        .sortedByDescending { florenceNormalizedBeamScore(it.score, it.sequence.size, lengthPenalty) }
        .take(beamLimit)
}

private fun florenceLogSoftmax(logits: List<Float>): List<Float> {
    if (logits.isEmpty()) return emptyList()
    val maxLogit = logits.maxOrNull() ?: 0f
    val shifted = logits.map { value -> value - maxLogit }
    val expValues = shifted.map { value -> kotlin.math.exp(value.toDouble()).toFloat() }
    val total = expValues.sum()
    return if (total <= 0f) {
        List(logits.size) { -kotlin.math.log(logits.size.toDouble(), kotlin.math.E).toFloat() }
    } else {
        expValues.map { value ->
            kotlin.math.log((value / total).toDouble(), kotlin.math.E).toFloat()
        }
    }
}

internal fun florenceNormalizedBeamScore(
    cumulativeScore: Float,
    sequenceLength: Int,
    lengthPenalty: Float,
): Float {
    val safeLengthPenalty = lengthPenalty.takeIf { it > 0f } ?: 1f
    val tokenCount = sequenceLength.coerceAtLeast(1)
    val denominator = Math.pow(tokenCount.toDouble(), safeLengthPenalty.toDouble()).toFloat()
    return cumulativeScore / denominator
}

internal fun florenceReorderBeamStatesByParentIndices(
    beams: List<FlorenceGenerationBeam>,
    parentBeamIndices: List<Int>,
): List<FlorenceGenerationBeam> {
    require(parentBeamIndices.size == beams.size) {
        "Florence beam reorder requires the same number of parent indices as beams"
    }

    val orderedBeams = beams.sortedByDescending { beam ->
        parentBeamIndices.getOrNull(beam.beamIndex) ?: Int.MIN_VALUE
    }

    return orderedBeams.mapIndexed { index, beam ->
        beam.copy(beamIndex = parentBeamIndices[index])
    }
}

private fun buildFlorenceDecoderWithPastInputs(
    stage3: FlorenceStage3RuntimeResult,
    presentKeyValues: Map<String, List<Float>>,
    decoderInputsEmbeds: List<List<List<Float>>>,
): List<PreparedInferenceTensor> {
    val decoderInputs = mutableListOf(
        PreparedInferenceTensor(
            "encoder_attention_mask",
            "int64",
            longArrayOf(1, stage3.decoder.encoderAttentionMask.single().size.toLong()),
            longs = stage3.decoder.encoderAttentionMask.single().toLongArray(),
        ),
    )

    decoderInputs += buildList {
        for (layer in 0 until 6) {
            val sourceKey = "present.$layer.decoder.key"
            val sourceValue = presentKeyValues[sourceKey]
                ?: throw ModelInferenceContractException("Florence decoder_with_past requires present cache '$sourceKey'")
            val decoderKeyShape = longArrayOf(1, 12, (sourceValue.size / (12 * 64)).coerceAtLeast(1).toLong(), 64)
            add(
                PreparedInferenceTensor(
                    "past_key_values.$layer.decoder.key",
                    "float32",
                    decoderKeyShape,
                    floats = sourceValue.toFloatArray(),
                ),
            )
            add(
                PreparedInferenceTensor(
                    "past_key_values.$layer.decoder.value",
                    "float32",
                    decoderKeyShape,
                    floats = presentKeyValues["present.$layer.decoder.value"]?.toFloatArray()
                        ?: throw ModelInferenceContractException("Florence decoder_with_past requires present cache 'present.$layer.decoder.value'"),
                ),
            )
            val encoderSourceKey = "present.$layer.encoder.key"
            val encoderSourceValue = presentKeyValues[encoderSourceKey]
                ?: throw ModelInferenceContractException("Florence decoder_with_past requires present cache '$encoderSourceKey'")
            val encoderShape = longArrayOf(1, 12, (encoderSourceValue.size / (12 * 64)).coerceAtLeast(1).toLong(), 64)
            add(
                PreparedInferenceTensor(
                    "past_key_values.$layer.encoder.key",
                    "float32",
                    encoderShape,
                    floats = encoderSourceValue.toFloatArray(),
                ),
            )
            add(
                PreparedInferenceTensor(
                    "past_key_values.$layer.encoder.value",
                    "float32",
                    encoderShape,
                    floats = presentKeyValues["present.$layer.encoder.value"]?.toFloatArray()
                        ?: throw ModelInferenceContractException("Florence decoder_with_past requires present cache 'present.$layer.encoder.value'"),
                ),
            )
        }
    }

    decoderInputs += PreparedInferenceTensor(
        "inputs_embeds",
        "float32",
        longArrayOf(1, decoderInputsEmbeds.single().size.toLong(), FLORENCE_HIDDEN_SIZE.toLong()),
        floats = decoderInputsEmbeds.single().flatten().toFloatArray(),
    )

    return decoderInputs
}

private fun extractFlorencePresentKeyValues(
    outputs: Map<String, List<Float>>,
    expectedPresentKeys: List<String>,
): Map<String, List<Float>> {
    val presentKeyValues = outputs.filterKeys { expectedPresentKeys.contains(it) }
    val missingKeys = expectedPresentKeys.filterNot(presentKeyValues::containsKey)
    require(missingKeys.isEmpty()) {
        "Florence decoder_with_past output is missing required present cache tensors: $missingKeys"
    }

    for ((key, values) in presentKeyValues) {
        require(values.size % (12 * 64) == 0) {
            "Florence decoder_with_past cache tensor '$key' must contain a valid sequence-length multiple of 768 floats"
        }
        require(values.isNotEmpty()) {
            "Florence decoder_with_past cache tensor '$key' must not be empty"
        }
    }

    return presentKeyValues
}

private fun requireFlorenceLogits(logits: List<Float>?): List<Float> {
    val resolved = logits ?: emptyList()
    require(resolved.size == 51289) {
        "Florence decoder_with_past logits must match the local Florence vocab size 51289"
    }
    return resolved
}

private fun decodeFlorenceDecoderStartTokenId(model: AiModelDescriptor): Int {
    val generationConfig = model.metadata["generation_config"] as? Map<*, *> ?: emptyMap<String, Any>()
    val config = model.metadata["config"] as? Map<*, *> ?: emptyMap<String, Any>()
    val detected = generationConfig["decoder_start_token_id"]
        ?: config["decoder_start_token_id"]
        ?: (model.metadata["florence_package"] as? Map<*, *>)?.get("decoder_start_token_id")
        ?: 2
    return (detected as? Number)?.toInt() ?: 2
}

private object FlorenceTokenizer {
    fun fromModel(model: AiModelDescriptor): FlorenceTokenizerAdapter {
        val json = model.metadata["tokenizer_json"] as? Map<*, *> ?: throw ModelInferenceContractException("Florence tokenizer.json metadata is missing")
        val modelJson = json["model"] as? Map<*, *> ?: throw ModelInferenceContractException("Florence tokenizer model metadata is missing")
        val vocab = (modelJson["vocab"] as? Map<*, *>)?.entries?.sortedBy { (it.value as Number).toInt() }?.map { it.key.toString() }.orEmpty()
        val merges = (modelJson["merges"] as? List<*>)?.mapNotNull { it?.toString() }.orEmpty()
        val added = (json["added_tokens"] as? List<*>)?.mapNotNull { it as? Map<*, *> }.orEmpty()
        val addedIds = added.associate { it["content"].toString() to (it["id"] as Number).toInt() }
        return FlorenceTokenizerAdapter(vocab, merges, addedIds)
    }
}

private class FlorenceTokenizerAdapter(
    vocabulary: List<String>,
    merges: List<String>,
    addedIds: Map<String, Int>,
) {
    private val tokenById = vocabulary.withIndex().associate { it.index to it.value }
    private val addedTokenById = addedIds.entries.associate { (token, id) -> id to token }
    private val tokenizer = ModelTokenizer(
        TokenizerContract(
            type = "bpe",
            vocabulary = vocabulary,
            unknownToken = "<unk>",
            startToken = "<s>",
            endToken = "</s>",
            padToken = "<pad>",
            maxLength = 1024,
            bpeMerges = merges,
        ),
    )

    fun encode(prompt: String): TokenizedText {
        val taskPrompt = when {
            prompt == "<CAPTION>" -> "What does the image describe?"
            prompt == "<OCR>" -> "What is the text in the image?"
            prompt == "<OD>" -> "Locate the objects with category name in the image."
            else -> prompt
        }
        val text = tokenizer.encodeWithoutPadding(taskPrompt)
        val ids = listOf(0) + text.ids + listOf(2)
        return TokenizedText(ids, List(ids.size) { 1 }, List(ids.size) { 0 })
    }

    fun decode(tokenIds: List<Int>): String {
        val decoded = tokenIds.joinToString(separator = "") { id ->
            tokenById[id]?.takeUnless { token -> token == "<s>" || token == "</s>" || token == "<pad>" || token == "<unk>" || token == "<mask>" }
                ?: ""
        }
        return decoded
            .replace("Ġ", " ")
            .replace("Ċ", "\n")
            .trim()
    }

    fun decodeForPostProcessing(tokenIds: List<Int>): String {
        return tokenIds.joinToString(separator = "") { id ->
            tokenById[id] ?: addedTokenById[id] ?: ""
        }
            .replace("Ġ", " ")
            .replace("Ċ", "\n")
            .trim()
    }
}