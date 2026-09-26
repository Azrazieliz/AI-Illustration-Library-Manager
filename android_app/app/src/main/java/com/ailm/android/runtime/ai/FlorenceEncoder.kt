package com.ailm.android.runtime.ai

internal data class FlorenceEncoderResult(
    val inputIds: List<List<Int>>,
    val textSequenceLength: Int,
    val imageSequenceLength: Int,
    val encoderSequenceLength: Int,
    val encoderAttentionMask: List<List<Long>>,
    val inputsEmbeds: List<List<List<Float>>>,
    val lastHiddenState: List<List<List<Float>>>? = null,
    val hiddenSize: Int = FLORENCE_HIDDEN_SIZE,
)

internal fun composeFlorenceEncoderInputs(
    inputIds: List<List<Int>>,
    textEmbeddings: List<List<List<Float>>>,
    imageFeatures: List<List<List<Float>>>,
    attentionMask: List<List<Long>>,
    imageTokenId: Int,
): FlorenceEncoderResult {
    require(inputIds.isNotEmpty()) { "Florence input_ids must contain a batch" }
    require(inputIds.size == textEmbeddings.size && inputIds.size == imageFeatures.size) {
        "Florence batch size must match input_ids, text embeddings, and image features"
    }
    require(inputIds.size == attentionMask.size) { "Florence attention mask batch size must match input_ids" }
    val textSequenceLength = inputIds.first().size
    require(textSequenceLength > 0 && inputIds.all { it.size == textSequenceLength }) {
        "Florence input_ids must have one consistent rank-2 sequence length"
    }
    require(textEmbeddings.all { it.size == textSequenceLength }) {
        "Florence text embeddings must preserve [B,S_text,768]"
    }
    require(attentionMask.all { it.size == textSequenceLength }) {
        "Florence attention mask length must match text sequence length"
    }
    require(textEmbeddings.flatten().all { it.size == FLORENCE_HIDDEN_SIZE }) {
        "Florence text embeddings must have hidden size 768"
    }
    require(imageFeatures.all { it.isNotEmpty() && it.all { row -> row.size == FLORENCE_HIDDEN_SIZE } }) {
        "Florence image features must preserve [B,S_image,768]"
    }
    val imageSequenceLength = imageFeatures.first().size
    require(imageFeatures.all { it.size == imageSequenceLength }) {
        "Florence image feature sequence length must be consistent across the batch"
    }
    val placeholderCounts = inputIds.map { ids -> ids.count { it == imageTokenId } }
    require(placeholderCounts.all { it == imageSequenceLength }) {
        "Florence image features must match the number of image placeholders"
    }
    require(attentionMask.flatten().all { it == 0L || it == 1L }) {
        "Florence encoder attention_mask must contain only 0 or 1"
    }
    require(inputIds.zip(attentionMask).all { (ids, mask) ->
        ids.indices.all { index -> ids[index] != imageTokenId || mask[index] == 1L }
    }) {
        "Florence image placeholders must be active in attention_mask"
    }

    val inputsEmbeds = inputIds.indices.map { batchIndex ->
        var imageIndex = 0
        inputIds[batchIndex].indices.map { tokenIndex ->
            if (inputIds[batchIndex][tokenIndex] == imageTokenId) {
                imageFeatures[batchIndex][imageIndex++]
            } else {
                textEmbeddings[batchIndex][tokenIndex]
            }
        }
    }
    return FlorenceEncoderResult(
        inputIds = inputIds,
        textSequenceLength = textSequenceLength,
        imageSequenceLength = imageSequenceLength,
        encoderSequenceLength = textSequenceLength,
        encoderAttentionMask = attentionMask,
        inputsEmbeds = inputsEmbeds,
    )
}

internal fun composeFlorencePrefixEncoderInputs(
    inputIds: List<List<Int>>,
    textEmbeddings: List<List<List<Float>>>,
    imageFeatures: List<List<List<Float>>>,
    attentionMask: List<List<Long>>,
): FlorenceEncoderResult {
    require(inputIds.isNotEmpty()) { "Florence input_ids must contain a batch" }
    require(inputIds.size == textEmbeddings.size && inputIds.size == imageFeatures.size && inputIds.size == attentionMask.size) {
        "Florence prefix composition batch sizes must match"
    }
    val textSequenceLength = inputIds.first().size
    require(textSequenceLength > 0 && inputIds.all { it.size == textSequenceLength }) {
        "Florence input_ids must have one consistent rank-2 sequence length"
    }
    require(textEmbeddings.all { it.size == textSequenceLength && it.all { row -> row.size == FLORENCE_HIDDEN_SIZE } }) {
        "Florence text embeddings must preserve [B,S_text,768]"
    }
    require(attentionMask.all { it.size == textSequenceLength && it.all { value -> value == 0L || value == 1L } }) {
        "Florence text attention mask must preserve [B,S_text] with binary values"
    }
    require(imageFeatures.all { it.isNotEmpty() && it.all { row -> row.size == FLORENCE_HIDDEN_SIZE } }) {
        "Florence image features must preserve [B,S_image,768]"
    }
    val imageSequenceLength = imageFeatures.first().size
    require(imageFeatures.all { it.size == imageSequenceLength }) {
        "Florence image feature sequence length must be consistent across the batch"
    }
    val inputsEmbeds = inputIds.indices.map { batchIndex ->
        imageFeatures[batchIndex] + textEmbeddings[batchIndex]
    }
    val encoderAttentionMask = inputIds.indices.map { batchIndex ->
        List(imageSequenceLength) { 1L } + attentionMask[batchIndex]
    }
    return FlorenceEncoderResult(
        inputIds = inputIds,
        textSequenceLength = textSequenceLength,
        imageSequenceLength = imageSequenceLength,
        encoderSequenceLength = imageSequenceLength + textSequenceLength,
        encoderAttentionMask = encoderAttentionMask,
        inputsEmbeds = inputsEmbeds,
    )
}

internal fun FlorenceEncoderResult.withFlorenceLastHiddenState(
    lastHiddenState: List<List<List<Float>>>,
): FlorenceEncoderResult {
    require(lastHiddenState.size == inputsEmbeds.size) {
        "Florence last_hidden_state batch size must match encoder inputs"
    }
    require(lastHiddenState.all { it.size == encoderSequenceLength && it.all { row -> row.size == FLORENCE_HIDDEN_SIZE } }) {
        "Florence last_hidden_state must preserve [B,S_total,768]"
    }
    return copy(lastHiddenState = lastHiddenState)
}

internal const val FLORENCE_HIDDEN_SIZE = 768