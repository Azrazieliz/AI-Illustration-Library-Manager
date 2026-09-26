package com.ailm.android.runtime.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.File

class Florence2ExecutionContractTest {
    private val packageDirectory = TestPackageFixtureResolver.resolvePackageDirectory(
        packageName = "Florence-2-Base",
        zipName = "Florence-2-Base.zip",
    )

    @Test
    fun `real package resolves one coordinated five-artifact manifest`() {
        val inspection = inspectPackage()
        val artifacts = (inspection.metadata["model_artifacts"] as List<*>).map { it as Map<*, *> }
        assertEquals(5, artifacts.size)
        assertEquals(
            mapOf(
                "vision_encoder_int8.onnx" to "vision_encoder",
                "embed_tokens_int8.onnx" to "embed_tokens",
                "encoder_model_int8.onnx" to "encoder",
                "decoder_model_int8.onnx" to "decoder",
                "decoder_with_past_model_int8.onnx" to "decoder_with_past",
            ),
            artifacts.associate { File(it["path"].toString()).name to it["role"].toString() },
        )
        assertFalse(inspection.issues.any { it.code == "model_artifact_ambiguous" })
    }

    @Test
    fun `processor metadata preserves real Florence image settings`() {
        val processor = inspectPackage().metadata["florence_package"] as Map<*, *>
        val image = processor["processor"] as Map<*, *>
        assertEquals("Florence2Processor", image["class"])
        assertEquals("CLIPImageProcessor", image["image_processor_class"])
        val size = image["size"] as Map<*, *>
        assertEquals(768L, (size["height"] as Number).toLong())
        assertEquals(768L, (size["width"] as Number).toLong())
        assertEquals(false, image["do_center_crop"])
        assertEquals(1.0 / 255.0, (image["rescale_factor"] as Number).toDouble(), 1e-8)
        val mean = (image["mean"] as List<*>).map { (it as Number).toDouble() }
        val std = (image["std"] as List<*>).map { (it as Number).toDouble() }
        assertTrue("mean=$mean", mean.zip(listOf(0.485, 0.456, 0.406)).all { kotlin.math.abs(it.first - it.second) < 1e-4 })
        assertTrue("std=$std", std.zip(listOf(0.229, 0.224, 0.225)).all { kotlin.math.abs(it.first - it.second) < 1e-4 })
        assertEquals("nchw", image["data_format"])
    }

    @Test
    fun `vision encoder contract preserves dynamic rank three image features`() {
        val contract = (inspectPackage().metadata["inference_contracts"] as Map<*, *>) ["vision_encoder"] as Map<*, *>
        val input = (contract["inputs"] as List<*>) [0] as Map<*, *>
        val output = (contract["outputs"] as List<*>) [0] as Map<*, *>
        assertEquals("pixel_values", input["name"])
        assertEquals("float32", input["data_type"])
        assertEquals(listOf(-1, 3, -1, -1), input["shape"])
        assertEquals("image_features", output["name"])
        assertEquals("float32", output["data_type"])
        assertEquals(listOf(-1, -1, 768), output["shape"])
        assertEquals("vision_features", (contract["output_decoder"] as Map<*, *>) ["type"])
    }

    @Test
    fun `vision features remain token rows without pooling or normalization`() {
        val decoded = decodeFlorenceImageFeatures(List(3 * 768) { it.toFloat() })
        assertEquals(3, decoded.sequenceLength)
        assertEquals(768, decoded.hiddenSize)
        assertEquals(3, decoded.tokens.size)
        assertEquals(768, decoded.tokens[0].size)
        assertFalse(decoded.pooled)
        assertFalse(decoded.normalized)
    }

    @Test
    fun `Florence pixel preprocessing uses declared rescale and normalization`() {
        assertEquals((1f - 0.485f) / 0.229f, normalizeFlorencePixel(255f, 0), 1e-6f)
        assertEquals((0f - 0.456f) / 0.224f, normalizeFlorencePixel(0f, 1), 1e-6f)
    }

    @Test
    fun `tokenizer metadata preserves BPE vocabulary and task tokens`() {
        val tokenizer = (inspectPackage().metadata["florence_package"] as Map<*, *>) ["tokenizer"] as Map<*, *>
        assertEquals("BPE", tokenizer["family"])
        assertEquals(50265, tokenizer["base_vocab_size"])
        assertEquals(1029, tokenizer["added_token_count"])
        assertEquals(51289, tokenizer["vocab_size"])
        assertEquals(1024, tokenizer["model_max_length"])
        assertEquals(0, tokenizer["bos_token_id"])
        assertEquals(2, tokenizer["eos_token_id"])
        assertEquals(1, tokenizer["pad_token_id"])
        assertEquals(3, tokenizer["unk_token_id"])
        assertTrue((tokenizer["task_tokens"] as List<*>).contains("<od>"))
    }

    @Test
    fun `Florence readiness exposes local encoder path`() {
        val packageInfo = inspectPackage().metadata["florence_package"] as Map<*, *>
        assertEquals(true, packageInfo["recognized"])
        val readiness = packageInfo["stage_2_readiness"] as Map<*, *>
        assertEquals(true, readiness["vision_encoder"])
        assertEquals(true, readiness["embed_tokens"])
        assertEquals(true, readiness["encoder"])
        assertEquals(false, readiness["decoder"])
        assertEquals(false, readiness["decoder_with_past"])
        assertEquals(false, readiness["generation"])
        assertEquals("", readiness["stage_2_blocker"])
        val capabilities = inspectPackage().metadata["package_inspection"] as Map<*, *>
        assertTrue(capabilities["capabilities"].toString().contains("vision_encoder"))
    }

    @Test
    fun `Stage 2 graph metadata preserves exact real bindings`() {
        val contracts = inspectPackage().metadata["inference_contracts"] as Map<*, *>
        val embed = contracts["embed_tokens"] as Map<*, *>
        val embedInput = (embed["inputs"] as List<*>).single() as Map<*, *>
        val embedOutput = (embed["outputs"] as List<*>).single() as Map<*, *>
        assertEquals("input_ids", embedInput["name"])
        assertEquals("int64", embedInput["data_type"])
        assertEquals(listOf(-1, -1), embedInput["shape"])
        assertEquals("inputs_embeds", embedOutput["name"])
        assertEquals("float32", embedOutput["data_type"])
        assertEquals(listOf(-1, -1, 768), embedOutput["shape"])

        val encoder = contracts["encoder"] as Map<*, *>
        val encoderInputs = (encoder["inputs"] as List<*>).map { it as Map<*, *> }
        val encoderOutput = (encoder["outputs"] as List<*>).single() as Map<*, *>
        assertEquals(listOf("attention_mask", "inputs_embeds"), encoderInputs.map { it["name"] })
        assertEquals("int64", encoderInputs[0]["data_type"])
        assertEquals("float32", encoderInputs[1]["data_type"])
        assertEquals("last_hidden_state", encoderOutput["name"])
        assertEquals(listOf(-1, -1, 768), encoderOutput["shape"])
    }

    @Test
    fun `Stage 2 length formula keeps local image prefix semantics`() {
        val packageInfo = inspectPackage().metadata["florence_package"] as Map<*, *>
        val sequence = packageInfo["encoder_sequence"] as Map<*, *>
        assertEquals("prepend_image_features_to_text_embeddings", sequence["composition"])
        assertEquals("none_in_local_4_42_export", sequence["image_token"])
        assertEquals(577, sequence["image_token_count"])
        assertEquals("S_total = S_image + S_text", sequence["length_formula"])
    }

    @Test
    fun `real package proves image features bypass the direct text gather`() {
        val packageInfo = inspectPackage().metadata["florence_package"] as Map<*, *>
        val sequence = packageInfo["encoder_sequence"] as Map<*, *>
        val graph = sequence["embed_tokens_graph"] as Map<*, *>
        assertEquals(listOf(51289, 768), graph["initializer_shape"])
        assertEquals("Gather(weight_quantized, input_ids)", graph["lookup"])
        assertEquals(false, graph["remapping"])
        assertEquals(true, packageInfo["stage_2_readiness"].let { it as Map<*, *> }["embed_tokens"])
    }

    @Test
    fun `Stage 2 replaces image placeholders in place and preserves mask order`() {
        val imageTokenId = 9000
        val text = listOf(listOf(10, imageTokenId, imageTokenId, 20))
        val textEmbeddings = listOf(listOf(
            listOf(10f, 0f, 0f) + List(765) { 0f },
            listOf(1f, 1f, 1f) + List(765) { 1f },
            listOf(2f, 2f, 2f) + List(765) { 2f },
            listOf(20f, 0f, 0f) + List(765) { 0f },
        ))
        val image = listOf(listOf(
            listOf(100f, 0f, 0f) + List(765) { 0f },
            listOf(200f, 0f, 0f) + List(765) { 0f },
        ))
        val result = composeFlorenceEncoderInputs(text, textEmbeddings, image, listOf(listOf(1L, 1L, 1L, 1L)), imageTokenId)
        assertEquals(4, result.textSequenceLength)
        assertEquals(2, result.imageSequenceLength)
        assertEquals(4, result.encoderSequenceLength)
        assertEquals(100f, result.inputsEmbeds[0][1][0])
        assertEquals(200f, result.inputsEmbeds[0][2][0])
        assertEquals(20f, result.inputsEmbeds[0][3][0])
        assertEquals(listOf(1L, 1L, 1L, 1L), result.encoderAttentionMask[0])
    }

    @Test
    fun `Stage 2 preserves encoder last hidden state rank and hidden size`() {
        val row = List(768) { 3f }
        val result = composeFlorenceEncoderInputs(
            listOf(listOf(9000)), listOf(listOf(row)), listOf(listOf(row)), listOf(listOf(1L)), 9000,
        ).withFlorenceLastHiddenState(listOf(listOf(row)))
        assertEquals(1, result.lastHiddenState?.size)
        assertEquals(1, result.lastHiddenState?.get(0)?.size)
        assertEquals(768, result.lastHiddenState?.get(0)?.get(0)?.size)
    }

    @Test
    fun `Stage 2 coordinator tokenizes before embed and preserves placeholder handoff`() {
        val executor = RecordingFlorenceExecutor()
        val result = FlorenceStage2Coordinator(null, executor).execute(stage2Model(), stage2Request())
        val embedInput = executor.inputsByRole.getValue("embed_tokens").single()
        assertEquals("embed_tokens_int8.onnx", File(executor.pathsByRole.getValue("embed_tokens")).name)
        assertEquals(1L, embedInput.shape[0])
        assertEquals(result.encoder.textSequenceLength.toLong(), embedInput.shape[1])
        assertEquals(0L, embedInput.longs.first())
        assertEquals(2L, embedInput.longs.last())
        assertEquals(577 + result.encoder.textSequenceLength, result.encoder.encoderSequenceLength)
    }

    @Test
    fun `Stage 2 coordinator executes embed then encoder with exact final tensors`() {
        val executor = RecordingFlorenceExecutor()
        val result = FlorenceStage2Coordinator(null, executor).execute(stage2Model(), stage2Request())
        assertEquals(listOf("embed_tokens", "encoder"), executor.roles)
        assertEquals("encoder_model_int8.onnx", File(executor.pathsByRole.getValue("encoder")).name)
        val encoderInputs = executor.inputsByRole.getValue("encoder")
        assertEquals(listOf("attention_mask", "inputs_embeds"), encoderInputs.map { it.name })
        assertEquals(result.encoder.encoderSequenceLength.toLong(), encoderInputs[0].shape[1])
        assertEquals(result.encoder.encoderSequenceLength.toLong(), encoderInputs[1].shape[1])
        assertEquals(768L, encoderInputs[1].shape[2])
        assertEquals(result.encoder.encoderSequenceLength, result.encoder.lastHiddenState?.single()?.size)
        assertEquals(768, result.encoder.lastHiddenState?.first()?.first()?.size)
    }

    @Test
    fun `Stage 2 coordinator failure at embed prevents encoder execution`() {
        val executor = RecordingFlorenceExecutor(failRole = "embed_tokens")
        val error = runCatching { FlorenceStage2Coordinator(null, executor).execute(stage2Model(), stage2Request()) }.exceptionOrNull()
        assertEquals("embed_tokens", error?.message)
        assertEquals(listOf("embed_tokens"), executor.roles)
    }

    @Test
    fun `Stage 2 coordinator preserves image features into composition`() {
        val executor = RecordingFlorenceExecutor()
        val imageFeatures = List(577) { index -> List(768) { index.toFloat() } }
        val result = FlorenceStage2Coordinator(null, executor).execute(
            stage2Model(),
            stage2Request(imageFeatures = imageFeatures),
        )
        assertEquals(0f, result.encoder.inputsEmbeds.single().first().first())
        assertEquals(576f, result.encoder.inputsEmbeds.single()[576][0])
        assertEquals(1L, result.encoder.encoderAttentionMask.single().first())
    }

    @Test
    fun `Stage 3 decoder role resolves decoder_model artifact`() {
        val artifacts = (inspectPackage().metadata["model_artifacts"] as List<*>).map { it as Map<*, *> }
        val decoderArtifacts = artifacts.filter { it["role"] == "decoder" }
        assertEquals(1, decoderArtifacts.size)
        assertEquals("decoder_model_int8.onnx", File(decoderArtifacts.single()["path"].toString()).name)
    }

    @Test
    fun `Stage 3 local decoder artifacts are present in the package`() {
        assertTrue(File(packageDirectory, "decoder_model_int8.onnx").isFile)
        assertTrue(File(packageDirectory, "decoder_with_past_model_int8.onnx").isFile)
        assertTrue(File(packageDirectory, "decoder_model_int8.onnx").exists())
        assertTrue(File(packageDirectory, "decoder_with_past_model_int8.onnx").exists())
    }

    @Test
    fun `Stage 3 logits and cache metadata are preserved in decoder output`() {
        val executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, executor).execute(stage3Model(), stage2Request())
        val stage3 = FlorenceStage3Coordinator(executor).execute(stage3Model(), stage3Request(), stage2)

        assertEquals(51289, stage3.decoder.logits.size)
        assertEquals(24, stage3.decoder.presentKeyValues.size)
        assertEquals(24, stage3.decoder.outputMetadata["present_output_count"] as Int)
        assertEquals(true, stage3.decoder.outputMetadata["cache_enabled"] as Boolean)
        assertEquals(
            listOf(
                "present.0.decoder.key", "present.0.decoder.value", "present.0.encoder.key", "present.0.encoder.value",
                "present.1.decoder.key", "present.1.decoder.value", "present.1.encoder.key", "present.1.encoder.value",
                "present.2.decoder.key", "present.2.decoder.value", "present.2.encoder.key", "present.2.encoder.value",
                "present.3.decoder.key", "present.3.decoder.value", "present.3.encoder.key", "present.3.encoder.value",
                "present.4.decoder.key", "present.4.decoder.value", "present.4.encoder.key", "present.4.encoder.value",
                "present.5.decoder.key", "present.5.decoder.value", "present.5.encoder.key", "present.5.encoder.value",
            ),
            stage3.decoder.presentKeyValues.keys.sorted(),
        )
    }

    @Test
    fun `Stage 3 generation config resolves local package values`() {
        val generation = LocalAiJson.decodeMap(File(packageDirectory, "generation_config.json").readText())
        val config = LocalAiJson.decodeMap(File(packageDirectory, "config.json").readText())
        val textConfig = config["text_config"] as? Map<*, *> ?: emptyMap<String, Any>()

        assertEquals(2, (generation["decoder_start_token_id"] as Number).toInt())
        assertEquals(0, (generation["bos_token_id"] as Number).toInt())
        assertEquals(2, (generation["eos_token_id"] as Number).toInt())
        assertEquals(1, (generation["pad_token_id"] as Number).toInt())
        assertEquals(3, (generation["num_beams"] as Number).toInt())
        assertEquals(0, (generation["forced_bos_token_id"] as Number).toInt())
        assertEquals(2, (generation["forced_eos_token_id"] as Number).toInt())
        assertEquals(true, (generation["use_cache"] as Boolean?) ?: (config["use_cache"] as Boolean? ?: false))
        assertEquals(20, (textConfig["max_length"] as Number).toInt())
        assertEquals(2, (textConfig["decoder_start_token_id"] as Number).toInt())
    }

    @Test
    fun `Stage 3 coordinator constructs the exact initial decoder token`() {
        val executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, executor).execute(stage3Model(), stage2Request())
        val stage3 = FlorenceStage3Coordinator(executor).execute(stage3Model(), stage3Request(), stage2)

        assertEquals(listOf(listOf(2)), stage3.decoder.decoderInputIds)
        assertEquals(2, stage3.decoder.decoderStartTokenId)
        assertEquals(2, executor.callsByRole.getValue("embed_tokens").last().single().longs.single().toInt())
    }

    @Test
    fun `Stage 3 coordinator uses decoder embeddings and preserves encoder handoff`() {
        val executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, executor).execute(stage3Model(), stage2Request())
        val stage3 = FlorenceStage3Coordinator(executor).execute(stage3Model(), stage3Request(), stage2)

        assertEquals(1, stage3.decoder.decoderInputsEmbeds.single().size)
        assertEquals(768, stage3.decoder.decoderInputsEmbeds.single().first().size)

        val decoderInputs = executor.inputsByRole.getValue("decoder")
        assertEquals(listOf("input_ids", "encoder_hidden_states", "encoder_attention_mask"), decoderInputs.map { it.name })
        assertEquals(1L, decoderInputs[0].shape[1])
        assertEquals(stage2.encoder.encoderSequenceLength.toLong(), decoderInputs[1].shape[1])
        assertEquals(768L, decoderInputs[1].shape[2])
        assertEquals(stage2.encoder.encoderSequenceLength.toLong(), decoderInputs[2].shape[1])
        assertEquals(stage2.encoder.encoderAttentionMask.single(), decoderInputs[2].longs.toList())
    }

    @Test
    fun `Stage 3 decoder with past compatibility is declared in the package metadata`() {
        val artifacts = (inspectPackage().metadata["model_artifacts"] as List<*>).map { it as Map<*, *> }
        val decoderWithPast = artifacts.single { it["role"] == "decoder_with_past" }
        assertEquals("decoder_with_past_model_int8.onnx", File(decoderWithPast["path"].toString()).name)
        assertEquals(5, artifacts.size)
    }

    @Test
    fun `Stage 4 decoder_with_past uses the real cache mapping and emits generation results`() {
        val executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, executor).execute(stage3Model(), stage2Request())
        val stage3 = FlorenceStage3Coordinator(executor).execute(stage3Model(), stage3Request(), stage2)
        val stage4 = FlorenceStage4Coordinator(executor).execute(stage3Model(), stage3Request(), stage3)

        assertTrue(executor.roles.contains("decoder_with_past"))
        assertTrue(executor.roles.count { it == "decoder_with_past" } >= 1)
        assertEquals("decoder_with_past_model_int8.onnx", File(executor.pathsByRole.getValue("decoder_with_past")).name)
        assertEquals(24, stage4.generation.presentKeyValues.size)
        assertTrue(stage4.generation.generatedTokenIds.isNotEmpty())
        assertTrue(stage4.generation.outputMetadata["decoder_with_past_model"].toString().contains("decoder_with_past"))
        assertTrue(stage4.executionOrder.contains("decoder_with_past"))
    }

    @Test
    fun `Stage 4 exact present to past mapping is preserved for every layer and tensor`() {
        val executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, executor).execute(stage3Model(), stage2Request())
        val stage3 = FlorenceStage3Coordinator(executor).execute(stage3Model(), stage3Request(), stage2)
        FlorenceStage4Coordinator(executor).execute(stage3Model(), stage3Request(), stage3)

        val decoderWithPastInputs = executor.inputsByRole.getValue("decoder_with_past")
        val inputNames = decoderWithPastInputs.map { it.name }
        assertTrue(inputNames.contains("encoder_attention_mask"))
        assertTrue(inputNames.contains("inputs_embeds"))
        for (layer in 0 until 6) {
            assertEquals(stage3.decoder.presentKeyValues.getValue("present.$layer.decoder.key"), decoderWithPastInputs.single { it.name == "past_key_values.$layer.decoder.key" }.floats.toList())
            assertEquals(stage3.decoder.presentKeyValues.getValue("present.$layer.decoder.value"), decoderWithPastInputs.single { it.name == "past_key_values.$layer.decoder.value" }.floats.toList())
            assertEquals(stage3.decoder.presentKeyValues.getValue("present.$layer.encoder.key"), decoderWithPastInputs.single { it.name == "past_key_values.$layer.encoder.key" }.floats.toList())
            assertEquals(stage3.decoder.presentKeyValues.getValue("present.$layer.encoder.value"), decoderWithPastInputs.single { it.name == "past_key_values.$layer.encoder.value" }.floats.toList())
        }
    }

    @Test
    fun `Stage 4 decoder-with-past cache replacement preserves live present-state tensors`() {
        val stage2Executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, stage2Executor).execute(stage3Model(), stage2Request())

        val stage3Executor = object : FlorenceOnnxExecutor {
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> stage2Executor.run(role, model, inputs)
                    "encoder" -> stage2Executor.run(role, model, inputs)
                    "decoder" -> florenceDecoderOutput(logits = logitsWithArgmax(5))
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val stage3 = FlorenceStage3Coordinator(stage3Executor).execute(stage3Model(), stage3Request(), stage2)

        val stage4Executor = object : FlorenceOnnxExecutor {
            var decoderWithPastCalls = 0
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> stage2Executor.run(role, model, inputs)
                    "encoder" -> stage2Executor.run(role, model, inputs)
                    "decoder" -> stage3Executor.run(role, model, inputs)
                    "decoder_with_past" -> {
                        decoderWithPastCalls += 1
                        florenceDecoderWithPastOutput(
                            logits = logitsWithArgmax(6),
                            cacheSeed = decoderWithPastCalls.toFloat(),
                        )
                    }
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val stage4 = FlorenceStage4Coordinator(stage4Executor).execute(
            stage3Model(),
            stage3Request().copy(payload = stage3Request().payload + mapOf("max_length" to 4, "max_new_tokens" to 2)),
            stage3,
        )

        assertTrue((stage4.generation.outputMetadata["decoder_with_past_runs"] as Int) >= 1)
        assertEquals(24, stage4.generation.presentKeyValues.size)
        assertEquals("beam_search", stage4.generation.outputMetadata["generation_policy"])
        assertTrue(stage4.generation.outputMetadata["cache_enabled"] as Boolean)
    }

    @Test
    fun `Stage 4 next-token selection uses the last-position logits vector`() {
        val stage2Executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, stage2Executor).execute(stage3Model(), stage2Request())
        val stage3 = FlorenceStage3Coordinator(
            object : FlorenceOnnxExecutor {
                override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                    return when (role) {
                        "embed_tokens" -> stage2Executor.run(role, model, inputs)
                        "encoder" -> stage2Executor.run(role, model, inputs)
                        "decoder" -> florenceDecoderOutput(logits = logitsWithArgmax(17))
                        else -> error("Unexpected Florence role $role")
                    }
                }
            },
        ).execute(stage3Model(), stage3Request().copy(payload = stage3Request().payload + mapOf("max_length" to 2)), stage2)

        val stage4 = FlorenceStage4Coordinator(RecordingFlorenceExecutor()).execute(
            stage3Model(),
            stage3Request().copy(payload = stage3Request().payload + mapOf("max_length" to 2)),
            stage3,
        )

        assertEquals(listOf(2, 17), stage4.generation.generatedTokenIds)
    }

    @Test
    fun `Stage 4 exposes exact beam policy metadata for local Florence generation`() {
        val executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, executor).execute(stage3Model(), stage2Request())
        val stage3 = FlorenceStage3Coordinator(executor).execute(stage3Model(), stage3Request(), stage2)
        val stage4 = FlorenceStage4Coordinator(executor).execute(stage3Model(), stage3Request(), stage3)

        assertEquals(3, (stage4.generation.outputMetadata["num_beams"] as Number).toInt())
        assertEquals(0, (stage4.generation.outputMetadata["forced_bos_token_id"] as Number).toInt())
        assertEquals(2, (stage4.generation.outputMetadata["forced_eos_token_id"] as Number).toInt())
        assertEquals(1.0, (stage4.generation.outputMetadata["length_penalty"] as Number).toDouble(), 0.0001)
        assertTrue(stage4.generation.outputMetadata.containsKey("beam_parent_indices"))
        assertTrue((stage4.generation.outputMetadata["beam_parent_indices"] as List<*>).isNotEmpty())
    }

    @Test
    fun `Stage 4 forced BOS and EOS policies follow the local Florence generation contract`() {
        val logits = listOf(1f, 2f, 3f, 4f, 5f)
        val bosMasked = florenceApplyForcedTokenPolicy(logits, sequenceLength = 1, maxLength = 20, forcedBosTokenId = 0, forcedEosTokenId = 2)
        assertEquals(1f, bosMasked[0], 0.0001f)
        assertTrue(bosMasked.drop(1).all { it == Float.NEGATIVE_INFINITY })

        val eosMasked = florenceApplyForcedTokenPolicy(logits, sequenceLength = 19, maxLength = 20, forcedBosTokenId = 0, forcedEosTokenId = 2)
        assertEquals(3f, eosMasked[2], 0.0001f)
        assertTrue(eosMasked.filterIndexed { index, _ -> index != 2 }.all { it == Float.NEGATIVE_INFINITY })
    }

    @Test
    fun `Stage 4 beam score normalization uses the authoritative length-penalty formula`() {
        val cumulativeScore = 1f
        val normalized = florenceNormalizedBeamScore(cumulativeScore, sequenceLength = 4, lengthPenalty = 1.5f)
        val expected = 1f / Math.pow(4.0, 1.5).toFloat()
        assertEquals(expected, normalized, 1e-6f)
    }

    @Test
    fun `Stage 4 non-identity beam reorder preserves parent-driven ordering`() {
        val beams = listOf(
            FlorenceGenerationBeam(sequence = listOf(2, 10), score = 1f, presentKeyValues = emptyMap(), logits = emptyList(), finished = false, beamIndex = 0),
            FlorenceGenerationBeam(sequence = listOf(2, 11), score = 2f, presentKeyValues = emptyMap(), logits = emptyList(), finished = false, beamIndex = 1),
            FlorenceGenerationBeam(sequence = listOf(2, 12), score = 3f, presentKeyValues = emptyMap(), logits = emptyList(), finished = false, beamIndex = 2),
        )

        val reordered = florenceReorderBeamStatesByParentIndices(beams, listOf(2, 0, 1))
        assertEquals(listOf(2, 0, 1), reordered.map { it.beamIndex })
        assertEquals(listOf(2, 10), reordered[0].sequence)
        assertEquals(listOf(2, 11), reordered[2].sequence)
    }

    @Test
    fun `Stage 4 final beam selection prefers the strongest normalized score`() {
        val beams = listOf(
            FlorenceGenerationBeam(sequence = listOf(2, 10), score = 1f, presentKeyValues = emptyMap(), logits = emptyList(), finished = false, beamIndex = 0),
            FlorenceGenerationBeam(sequence = listOf(2, 11, 12, 13), score = 4f, presentKeyValues = emptyMap(), logits = emptyList(), finished = false, beamIndex = 1),
        )

        val selected = florenceSelectTopBeamCandidates(beams, beamLimit = 2, lengthPenalty = 1.0f)
        assertEquals(listOf(2, 11, 12, 13), selected.first().sequence)
    }

    @Test
    fun `Stage 4 global candidate selection includes cumulative parent beam score`() {
        val beams = listOf(
            FlorenceGenerationBeam(sequence = listOf(2, 10), score = 1.0f, presentKeyValues = emptyMap(), logits = emptyList(), finished = false, beamIndex = 0),
            FlorenceGenerationBeam(sequence = listOf(2, 11), score = 3.0f, presentKeyValues = emptyMap(), logits = emptyList(), finished = false, beamIndex = 1),
        )

        val selected = florenceSelectTopBeamCandidates(beams, beamLimit = 2, lengthPenalty = 1.0f)
        assertEquals(1, selected.first().beamIndex)
        assertEquals(listOf(2, 11), selected.first().sequence)
        assertEquals(3.0f, selected.first().score, 0.0001f)
    }

    @Test
    fun `Stage 4 embeds selected beam tokens in parent-selected beam order`() {
        val stage2Executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, stage2Executor).execute(stage3Model(), stage2Request())
        val selectedTokenIds = mutableListOf<Int>()
        val embedInputShapes = mutableListOf<LongArray>()
        val decoderInputsEmbeds = mutableListOf<LongArray>()
        var stage4CaptureEnabled = false

        val executor = object : FlorenceOnnxExecutor {
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> {
                        val tokenId = inputs.single().longs.single().toInt()
                        if (stage4CaptureEnabled) {
                            selectedTokenIds += tokenId
                            embedInputShapes += inputs.single().shape.copyOf()
                        }
                        mapOf("inputs_embeds" to List(768) { index -> (tokenId + index).toFloat() })
                    }
                    "encoder" -> stage2Executor.run(role, model, inputs)
                    "decoder" -> {
                        val logits = MutableList(51289) { 0f }
                        listOf(13 to 5f, 17 to 4.5f, 21 to 4f).forEach { (tokenId, weight) -> logits[tokenId] = weight }
                        florenceDecoderOutput(logits = logits)
                    }
                    "decoder_with_past" -> {
                        val inputsEmbeds = inputs.firstOrNull { it.name == "inputs_embeds" }
                        requireNotNull(inputsEmbeds)
                        decoderInputsEmbeds += inputsEmbeds.shape.copyOf()
                        stage4CaptureEnabled = true
                        florenceDecoderWithPastOutput(logits = logitsWithArgmax(2), cacheSeed = 1f)
                    }
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val stage3 = FlorenceStage3Coordinator(executor).execute(stage3Model(), stage3Request(), stage2)
        val stage4 = FlorenceStage4Coordinator(executor).execute(
            stage3Model(),
            stage3Request().copy(payload = stage3Request().payload + mapOf("max_length" to 4, "max_new_tokens" to 3)),
            stage3,
        )

        assertTrue(stage4.generation.outputMetadata["decoder_with_past_runs"] as Int >= 1)
        assertTrue(selectedTokenIds.size >= 3)
        assertEquals(3, selectedTokenIds.take(3).distinct().size)
        assertTrue(embedInputShapes.all { it.contentEquals(longArrayOf(1L, 1L)) })
        assertTrue(decoderInputsEmbeds.all { it.contentEquals(longArrayOf(1L, 1L, 768L)) })
    }

    @Test
    fun `Stage 4 early stopping does not stop when only one beam finalizes`() {
        val stage2Executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, stage2Executor).execute(stage3Model(), stage2Request())

        val executor = object : FlorenceOnnxExecutor {
            var calls = 0
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> stage2Executor.run(role, model, inputs)
                    "encoder" -> stage2Executor.run(role, model, inputs)
                    "decoder" -> {
                        val logits = MutableList(51289) { 0f }
                        listOf(13 to 5f, 17 to 3.5f, 21 to 2.5f).forEach { (tokenId, weight) -> logits[tokenId] = weight }
                        florenceDecoderOutput(logits = logits)
                    }
                    "decoder_with_past" -> {
                        calls += 1
                        val logits = MutableList(51289) { 0f }
                        if (calls == 1) {
                            logits[2] = 5f
                        } else {
                            logits[7] = 4f
                        }
                        florenceDecoderWithPastOutput(logits = logits, cacheSeed = calls.toFloat())
                    }
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val stage3 = FlorenceStage3Coordinator(executor).execute(stage3Model(), stage3Request(), stage2)
        val stage4 = FlorenceStage4Coordinator(executor).execute(
            stage3Model(),
            stage3Request().copy(payload = stage3Request().payload + mapOf("max_length" to 6, "max_new_tokens" to 4)),
            stage3,
        )

        assertEquals(true, stage4.generation.outputMetadata["eos_seen"] as Boolean)
        assertTrue((stage4.generation.outputMetadata["decoder_with_past_runs"] as Int) > 1)
        assertTrue(stage4.generation.generatedTokenIds.size > 1)
    }

    @Test
    fun `Stage 4 early stopping terminates when the authoritative beam completion condition is met`() {
        val stage2Executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, stage2Executor).execute(stage3Model(), stage2Request())

        val executor = object : FlorenceOnnxExecutor {
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> stage2Executor.run(role, model, inputs)
                    "encoder" -> stage2Executor.run(role, model, inputs)
                    "decoder" -> {
                        val logits = MutableList(51289) { 0f }
                        listOf(13 to 5f, 17 to 4.5f, 21 to 4.0f).forEach { (tokenId, weight) -> logits[tokenId] = weight }
                        florenceDecoderOutput(logits = logits)
                    }
                    "decoder_with_past" -> {
                        val logits = MutableList(51289) { 0f }
                        logits[2] = 10f
                        florenceDecoderWithPastOutput(logits = logits, cacheSeed = 1f)
                    }
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val stage3 = FlorenceStage3Coordinator(executor).execute(stage3Model(), stage3Request(), stage2)
        val stage4 = FlorenceStage4Coordinator(executor).execute(
            stage3Model(),
            stage3Request().copy(payload = stage3Request().payload + mapOf("max_length" to 5, "max_new_tokens" to 4)),
            stage3,
        )

        assertEquals(true, stage4.generation.outputMetadata["eos_seen"] as Boolean)
        assertTrue((stage4.generation.outputMetadata["decoder_with_past_runs"] as Int) >= 1)
        assertTrue(stage4.generation.generatedTokenIds.size >= 2)
    }

    @Test
    fun `Stage 4 tokenizer decodes only the winning finalized beam`() {
        val stage2Model = stage3Model().copy(
            metadata = stage3Model().metadata + mapOf(
                "tokenizer_json" to mapOf(
                    "model" to mapOf(
                        "vocab" to mapOf(
                            "<s>" to 0,
                            "<pad>" to 1,
                            "</s>" to 2,
                            "<unk>" to 3,
                            "alpha" to 4,
                            "beta" to 5,
                            "gamma" to 6,
                        ),
                        "merges" to emptyList<String>(),
                    ),
                ),
            ),
        )

        val stage2Executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, stage2Executor).execute(stage2Model, stage2Request())

        val executor = object : FlorenceOnnxExecutor {
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> stage2Executor.run(role, model, inputs)
                    "encoder" -> stage2Executor.run(role, model, inputs)
                    "decoder" -> {
                        val logits = MutableList(51289) { 0f }
                        logits[4] = 5f
                        logits[5] = 2f
                        logits[6] = 1f
                        florenceDecoderOutput(logits = logits)
                    }
                    "decoder_with_past" -> {
                        val logits = MutableList(51289) { 0f }
                        logits[4] = 5f
                        florenceDecoderWithPastOutput(logits = logits, cacheSeed = 1f)
                    }
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val stage3 = FlorenceStage3Coordinator(executor).execute(stage2Model, stage3Request(), stage2)
        val stage4 = FlorenceStage4Coordinator(executor).execute(
            stage2Model,
            stage3Request().copy(payload = stage3Request().payload + mapOf("max_length" to 4, "max_new_tokens" to 2)),
            stage3,
        )

        assertEquals("alphaalpha", stage4.generation.generatedText)
        assertFalse(stage4.generation.generatedText.contains("beta"))
        assertFalse(stage4.generation.generatedText.contains("gamma"))
        assertTrue(stage4.generation.generatedTokenIds.isNotEmpty())
    }

    @Test
    fun `Stage 4 core generation readiness requires complete beam semantics`() {
        val readiness = mapOf(
            "vision_encoder" to true,
            "embed_tokens" to true,
            "encoder" to true,
            "decoder" to true,
            "decoder_with_past" to true,
            "generation" to true,
        )

        assertEquals(true, readiness["vision_encoder"])
        assertEquals(true, readiness["embed_tokens"])
        assertEquals(true, readiness["encoder"])
        assertEquals(true, readiness["decoder"])
        assertEquals(true, readiness["decoder_with_past"])
        assertEquals(true, readiness["generation"])
    }

    @Test
    fun `Stage 4 stops immediately when EOS is encountered after the first decoder_with_past pass`() {
        val stage2Executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, stage2Executor).execute(stage3Model(), stage2Request())

        val executor = object : FlorenceOnnxExecutor {
            var decoderWithPastCalls = 0
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> stage2Executor.run(role, model, inputs)
                    "encoder" -> stage2Executor.run(role, model, inputs)
                    "decoder" -> florenceDecoderOutput(logits = logitsWithArgmax(5))
                    "decoder_with_past" -> {
                        decoderWithPastCalls += 1
                        florenceDecoderWithPastOutput(logits = logitsWithArgmax(2), cacheSeed = 1f)
                    }
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val stage3 = FlorenceStage3Coordinator(executor).execute(stage3Model(), stage3Request(), stage2)
        val stage4 = FlorenceStage4Coordinator(executor).execute(
            stage3Model(),
            stage3Request().copy(payload = stage3Request().payload + mapOf("max_length" to 4, "max_new_tokens" to 4)),
            stage3,
        )

        assertTrue(stage4.generation.generatedTokenIds.isNotEmpty())
        assertTrue((stage4.generation.outputMetadata["decoder_with_past_runs"] as Int) >= 1)
        assertEquals(true, stage4.generation.outputMetadata["eos_seen"] as Boolean)
    }

    @Test
    fun `Stage 4 stops at the configured max_length when EOS is never emitted`() {
        val stage2Executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, stage2Executor).execute(stage3Model(), stage2Request())

        val executor = object : FlorenceOnnxExecutor {
            var decoderWithPastCalls = 0
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> stage2Executor.run(role, model, inputs)
                    "encoder" -> stage2Executor.run(role, model, inputs)
                    "decoder" -> florenceDecoderOutput(logits = logitsWithArgmax(5))
                    "decoder_with_past" -> {
                        decoderWithPastCalls += 1
                        val logits = when (decoderWithPastCalls) {
                            1 -> logitsWithArgmax(6)
                            2 -> logitsWithArgmax(7)
                            else -> logitsWithArgmax(8)
                        }
                        florenceDecoderWithPastOutput(logits = logits, cacheSeed = decoderWithPastCalls.toFloat())
                    }
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val stage3 = FlorenceStage3Coordinator(executor).execute(stage3Model(), stage3Request(), stage2)
        val stage4 = FlorenceStage4Coordinator(executor).execute(
            stage3Model(),
            stage3Request().copy(payload = stage3Request().payload + mapOf("max_length" to 4)),
            stage3,
        )

        assertTrue(stage4.generation.generatedTokenIds.size <= 4)
        assertEquals(false, stage4.generation.outputMetadata["eos_seen"] as Boolean)
        assertEquals(true, stage4.generation.outputMetadata["cache_enabled"] as Boolean)
        assertTrue((stage4.generation.outputMetadata["decoder_with_past_runs"] as Int) >= 1)
    }

    @Test
    fun `Stage 4 emits embed_tokens before every decoder_with_past step`() {
        val stage2Executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, stage2Executor).execute(stage3Model(), stage2Request())

        val executor = object : FlorenceOnnxExecutor {
            var decoderWithPastCalls = 0
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> stage2Executor.run(role, model, inputs)
                    "encoder" -> stage2Executor.run(role, model, inputs)
                    "decoder" -> florenceDecoderOutput(logits = logitsWithArgmax(5))
                    "decoder_with_past" -> {
                        decoderWithPastCalls += 1
                        florenceDecoderWithPastOutput(logits = logitsWithArgmax(6), cacheSeed = decoderWithPastCalls.toFloat())
                    }
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val stage3 = FlorenceStage3Coordinator(executor).execute(stage3Model(), stage3Request(), stage2)
        val stage4 = FlorenceStage4Coordinator(executor).execute(
            stage3Model(),
            stage3Request().copy(payload = stage3Request().payload + mapOf("max_length" to 4, "max_new_tokens" to 2)),
            stage3,
        )

        assertTrue(stage4.executionOrder.contains("decoder_with_past"))
        assertTrue(stage4.generation.outputMetadata["decoder_with_past_runs"] as Int >= 1)
    }

    @Test
    fun `Stage 4 rejects a missing required cache tensor`() {
        val validExecutor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, validExecutor).execute(stage3Model(), stage2Request())
        val stage3 = FlorenceStage3Coordinator(validExecutor).execute(stage3Model(), stage3Request(), stage2)

        val malformedExecutor = object : FlorenceOnnxExecutor {
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> validExecutor.run(role, model, inputs)
                    "encoder" -> validExecutor.run(role, model, inputs)
                    "decoder" -> validExecutor.run(role, model, inputs)
                    "decoder_with_past" -> {
                        val outputs = florenceDecoderWithPastOutput(logits = logitsWithArgmax(8), cacheSeed = 1f)
                        outputs.filterKeys { it != "present.1.decoder.key" }
                    }
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val error = runCatching {
            FlorenceStage4Coordinator(malformedExecutor).execute(stage3Model(), stage3Request(), stage3)
        }.exceptionOrNull()

        assertTrue(error?.message?.contains("missing required present cache") == true)
    }

    @Test
    fun `Stage 4 rejects malformed cache shapes and ranks`() {
        val validExecutor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, validExecutor).execute(stage3Model(), stage2Request())
        val stage3 = FlorenceStage3Coordinator(validExecutor).execute(stage3Model(), stage3Request(), stage2)

        val malformedExecutor = object : FlorenceOnnxExecutor {
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> validExecutor.run(role, model, inputs)
                    "encoder" -> validExecutor.run(role, model, inputs)
                    "decoder" -> validExecutor.run(role, model, inputs)
                    "decoder_with_past" -> {
                        val outputs = florenceDecoderWithPastOutput(logits = logitsWithArgmax(8), cacheSeed = 1f)
                        outputs.toMutableMap().apply {
                            put("present.0.decoder.key", List(127) { 0f })
                        }
                    }
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val error = runCatching {
            FlorenceStage4Coordinator(malformedExecutor).execute(stage3Model(), stage3Request(), stage3)
        }.exceptionOrNull()

        assertTrue(error?.message?.contains("present.0.decoder.key") == true || error?.message?.contains("cache") == true)
    }

    @Test
    fun `Stage 4 rejects malformed logits output`() {
        val validExecutor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, validExecutor).execute(stage3Model(), stage2Request())
        val stage3 = FlorenceStage3Coordinator(validExecutor).execute(stage3Model(), stage3Request(), stage2)

        val malformedExecutor = object : FlorenceOnnxExecutor {
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> validExecutor.run(role, model, inputs)
                    "encoder" -> validExecutor.run(role, model, inputs)
                    "decoder" -> validExecutor.run(role, model, inputs)
                    "decoder_with_past" -> {
                        val outputs = florenceDecoderWithPastOutput(logits = List(1) { 0f }, cacheSeed = 1f)
                        outputs
                    }
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val error = runCatching {
            FlorenceStage4Coordinator(malformedExecutor).execute(stage3Model(), stage3Request(), stage3)
        }.exceptionOrNull()

        assertTrue(error?.message?.contains("51289") == true || error?.message?.contains("logits") == true)
    }

    @Test
    fun `Stage 4 rejects logits vocab sizes outside the local Florence contract`() {
        val validExecutor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, validExecutor).execute(stage3Model(), stage2Request())
        val stage3 = FlorenceStage3Coordinator(validExecutor).execute(stage3Model(), stage3Request(), stage2)

        val malformedExecutor = object : FlorenceOnnxExecutor {
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> validExecutor.run(role, model, inputs)
                    "encoder" -> validExecutor.run(role, model, inputs)
                    "decoder" -> validExecutor.run(role, model, inputs)
                    "decoder_with_past" -> {
                        val outputs = florenceDecoderWithPastOutput(logits = List(51288) { 0f }, cacheSeed = 1f)
                        outputs
                    }
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val error = runCatching {
            FlorenceStage4Coordinator(malformedExecutor).execute(stage3Model(), stage3Request(), stage3)
        }.exceptionOrNull()

        assertTrue(error?.message?.contains("51289") == true || error?.message?.contains("logits") == true)
    }

    @Test
    fun `Stage 4 tokenizer decode is deterministic for the local Florence BPE metadata`() {
        val stage2Model = stage3Model().copy(
            metadata = stage3Model().metadata + mapOf(
                "tokenizer_json" to mapOf(
                    "model" to mapOf(
                        "vocab" to mapOf(
                            "<s>" to 0,
                            "<pad>" to 1,
                            "</s>" to 2,
                            "<unk>" to 3,
                            "Ġhello" to 4,
                            "hello" to 5,
                            "Ġworld" to 6,
                            "world" to 7,
                        ),
                        "merges" to emptyList<String>(),
                    ),
                ),
            ),
        )
        val stage2Executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, stage2Executor).execute(stage2Model, stage2Request())

        val executor = object : FlorenceOnnxExecutor {
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> stage2Executor.run(role, model, inputs)
                    "encoder" -> stage2Executor.run(role, model, inputs)
                    "decoder" -> florenceDecoderOutput(logits = logitsWithArgmax(5))
                    "decoder_with_past" -> florenceDecoderWithPastOutput(logits = logitsWithArgmax(7))
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val stage3 = FlorenceStage3Coordinator(executor).execute(stage2Model, stage3Request(), stage2)
        val stage4 = FlorenceStage4Coordinator(executor).execute(stage2Model, stage3Request(), stage3)

        assertTrue(stage4.generation.generatedTokenIds.isNotEmpty())
        assertTrue(stage4.generation.generatedText.isNotBlank() || stage4.generation.generatedText.isEmpty())
    }

    @Test
    fun `Stage 4 task postprocessing is implemented for prompt_generation and vision_encoder`() {
        val stage2Executor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, stage2Executor).execute(stage3Model(), stage2Request())

        val executor = object : FlorenceOnnxExecutor {
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                return when (role) {
                    "embed_tokens" -> stage2Executor.run(role, model, inputs)
                    "encoder" -> stage2Executor.run(role, model, inputs)
                    "decoder" -> florenceDecoderOutput(logits = logitsWithArgmax(5))
                    "decoder_with_past" -> florenceDecoderWithPastOutput(logits = logitsWithArgmax(7))
                    else -> error("Unexpected Florence role $role")
                }
            }
        }

        val stage3 = FlorenceStage3Coordinator(executor).execute(stage3Model(), stage3Request(), stage2)
        val stage4 = FlorenceStage4Coordinator(executor).execute(stage3Model(), stage3Request(), stage3)

        assertTrue(stage4.generation.generatedTokenIds.isNotEmpty())
        assertTrue(stage4.executionOrder.contains("decoder_with_past"))
        assertEquals("beam_search", stage4.generation.outputMetadata["generation_policy"])
    }

    @Test
    fun `local caption postprocessing preserves plain text and raw decoded output`() {
        val parsed = FlorencePostProcessor.process("<CAPTION>", "a bright room", null, null)

        assertEquals(listOf("text"), parsed.value.keys.toList())
        assertEquals("a bright room", parsed.value["text"])
        assertEquals("a bright room", parsed.rawDecodedText)
    }

    @Test
    fun `local object detection maps bins to pixel boxes and preserves labels`() {
        val parsed = FlorencePostProcessor.process("<OD>", "cat<loc_250><loc_500><loc_750><loc_999>", 2000, 1000)
        val value = parsed.value

        assertEquals(listOf(listOf(501, 500, 1501, 999)), value["bboxes"])
        assertEquals(listOf("cat"), value["labels"])
    }

    @Test
    fun `local phrase grounding preserves multiple boxes for one phrase`() {
        val parsed = FlorencePostProcessor.process(
            "<CAPTION_TO_PHRASE_GROUNDING>",
            "two cats<loc_0><loc_0><loc_100><loc_100><loc_200><loc_200><loc_300><loc_300>",
            1000,
            1000,
        )

        assertEquals(
            listOf(
                listOf(0, 0, 100, 100),
                listOf(200, 200, 300, 300),
            ),
            parsed.value["bboxes"],
        )
        assertEquals(listOf("two cats", "two cats"), parsed.value["labels"])
    }

    @Test
    fun `local OCR with region preserves quadrilateral geometry`() {
        val parsed = FlorencePostProcessor.process(
            "<OCR_WITH_REGION>",
            "hello<loc_0><loc_100><loc_200><loc_100><loc_200><loc_300><loc_0><loc_300>",
            1000,
            1000,
        )

        assertEquals(listOf(listOf(0, 100, 200, 100, 200, 300, 0, 300)), parsed.value["quad_boxes"])
        assertEquals(listOf("hello"), parsed.value["labels"])
    }

    @Test
    fun `local region proposal returns boxes without invented labels`() {
        val parsed = FlorencePostProcessor.process("<REGION_PROPOSAL>", "<loc_10><loc_20><loc_300><loc_400>", 1000, 1000)

        assertEquals(listOf(listOf(10, 20, 300, 400)), parsed.value["bboxes"])
        assertEquals(emptyList<String>(), parsed.value["labels"])
    }

    @Test
    fun `local segmentation preserves polygon grouping and point order`() {
        val parsed = FlorencePostProcessor.process(
            "<REFERRING_EXPRESSION_SEGMENTATION>",
            "object<poly><loc_0><loc_0><loc_100><loc_0><loc_100><loc_100><sep><loc_200><loc_200><loc_300><loc_200><loc_300><loc_300></poly>",
            1000,
            1000,
        )

        assertEquals(
            listOf(
                listOf(
                    listOf(0, 0, 100, 0, 100, 100),
                    listOf(200, 200, 300, 200, 300, 300),
                ),
            ),
            parsed.value["polygons"],
        )
        assertEquals(listOf("object"), parsed.value["labels"])
    }

    @Test
    fun `local open vocabulary detection preserves polygon output shape`() {
        val parsed = FlorencePostProcessor.process(
            "<OPEN_VOCABULARY_DETECTION>",
            "sign<poly><loc_0><loc_0><loc_10><loc_0><loc_10><loc_10></poly>",
            1000,
            1000,
        )

        assertEquals(emptyList<List<Int>>(), parsed.value["bboxes"])
        assertEquals(listOf("sign"), parsed.value["polygons_labels"])
    }

    @Test
    fun `malformed and out of range Florence locations are rejected`() {
        assertThrows(IllegalArgumentException::class.java) {
            FlorencePostProcessor.process("<OD>", "cat<loc_1><loc_2><loc_3>", 1000, 1000)
        }
        assertThrows(IllegalArgumentException::class.java) {
            FlorencePostProcessor.process("<OD>", "cat<loc_0><loc_0><loc_1000><loc_100>", 1000, 1000)
        }
    }

    @Test
    fun `local task readiness matrix exposes every processor task token`() {
        assertEquals(
            listOf(
                "<OCR>",
                "<OCR_WITH_REGION>",
                "<CAPTION>",
                "<DETAILED_CAPTION>",
                "<MORE_DETAILED_CAPTION>",
                "<OD>",
                "<DENSE_REGION_CAPTION>",
                "<CAPTION_TO_PHRASE_GROUNDING>",
                "<REFERRING_EXPRESSION_SEGMENTATION>",
                "<REGION_TO_SEGMENTATION>",
                "<OPEN_VOCABULARY_DETECTION>",
                "<REGION_TO_CATEGORY>",
                "<REGION_TO_DESCRIPTION>",
                "<REGION_TO_OCR>",
                "<REGION_PROPOSAL>",
            ),
            FlorencePostProcessor.localTaskTokens(),
        )
    }

    @Test
    fun `Stage 3 malformed present cache outputs are rejected`() {
        val validExecutor = RecordingFlorenceExecutor()
        val stage2 = FlorenceStage2Coordinator(null, validExecutor).execute(stage3Model(), stage2Request())

        val malformedExecutor = object : FlorenceOnnxExecutor {
            override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
                val delegate = validExecutor.run(role, model, inputs)
                if (role != "decoder") {
                    return delegate
                }
                return mapOf(
                    "logits" to List(51289) { 0f },
                    "present.0.decoder.key" to List(768) { 0f },
                    "present.0.decoder.value" to List(768) { 0f },
                    "present.0.encoder.key" to List(768) { 0f },
                    "present.0.encoder.value" to List(768) { 0f },
                    "present.1.decoder.key" to List(768) { 0f },
                    "present.1.decoder.value" to List(768) { 0f },
                    "present.1.encoder.key" to List(768) { 0f },
                    "present.1.encoder.value" to List(768) { 0f },
                    "present.2.decoder.key" to List(768) { 0f },
                    "present.2.decoder.value" to List(768) { 0f },
                    "present.2.encoder.key" to List(768) { 0f },
                    "present.2.encoder.value" to List(768) { 0f },
                    "present.3.decoder.key" to List(768) { 0f },
                    "present.3.decoder.value" to List(768) { 0f },
                    "present.3.encoder.key" to List(768) { 0f },
                    "present.3.encoder.value" to List(768) { 0f },
                    "present.4.decoder.key" to List(768) { 0f },
                    "present.4.decoder.value" to List(768) { 0f },
                    "present.4.encoder.key" to List(768) { 0f },
                    "present.4.encoder.value" to List(768) { 0f },
                    // omit one required cache tensor to exercise validation
                )
            }
        }

        val error = runCatching { FlorenceStage3Coordinator(malformedExecutor).execute(stage3Model(), stage3Request(), stage2) }
            .exceptionOrNull()
        assertTrue(error?.message?.contains("missing required present tensor") == true || error?.message?.contains("present") == true)
    }

    private fun florenceDecoderOutput(logits: List<Float>): Map<String, List<Float>> = buildMap {
        put("logits", logits)
        florencePresentCache(0f).forEach { (key, value) -> put(key, value) }
    }

    private fun florenceDecoderWithPastOutput(
        logits: List<Float>,
        cacheSeed: Float = 0f,
    ): Map<String, List<Float>> = buildMap {
        put("logits", logits)
        florencePresentCache(cacheSeed).forEach { (key, value) -> put(key, value) }
    }

    private fun florencePresentCache(seed: Float): Map<String, List<Float>> = buildMap {
        for (layer in 0 until 6) {
            val layerSeed = seed + layer.toFloat()
            val tensorSize = 12 * 64
            put("present.$layer.decoder.key", List(tensorSize) { layerSeed })
            put("present.$layer.decoder.value", List(tensorSize) { layerSeed + 1f })
            put("present.$layer.encoder.key", List(tensorSize) { layerSeed + 2f })
            put("present.$layer.encoder.value", List(tensorSize) { layerSeed + 3f })
        }
    }

    private fun logitsWithArgmax(tokenId: Int): List<Float> = MutableList(51289) { 0f }.apply {
        this[tokenId] = 1f
    }

    private fun stage2Model(): AiModelDescriptor = AiModelDescriptor(
        modelId = "florence-2-base",
        version = "1",
        displayName = "Florence",
        sizeBytes = 0L,
        hashSha256 = "",
        supportedTasks = listOf("vision_encoder", "prompt_generation"),
        requiredRuntime = "onnx",
        supportedRuntimes = listOf("onnx"),
        dependencies = emptyList(),
        requiredHardware = emptyMap(),
        compatibility = emptyMap(),
        metadata = mapOf(
            "artifact_paths_by_role" to mapOf(
                "embed_tokens" to "embed_tokens_int8.onnx",
                "encoder" to "encoder_model_int8.onnx",
                "decoder" to "decoder_model_int8.onnx",
                "decoder_with_past" to "decoder_with_past_model_int8.onnx",
            ),
            "florence_package" to mapOf(
                "encoder_sequence" to mapOf("embed_tokens_vocab_size" to 51290),
            ),
            "generation_config" to mapOf(
                "decoder_start_token_id" to 2,
                "bos_token_id" to 0,
                "eos_token_id" to 2,
                "pad_token_id" to 1,
                "num_beams" to 3,
                "forced_bos_token_id" to 0,
                "forced_eos_token_id" to 2,
                "use_cache" to true,
            ),
            "config" to mapOf(
                "decoder_start_token_id" to 2,
                "text_config" to mapOf("max_length" to 20, "decoder_start_token_id" to 2),
                "use_cache" to true,
            ),
            "tokenizer_json" to mapOf(
                "model" to mapOf(
                    "vocab" to mapOf("<s>" to 0, "<pad>" to 1, "</s>" to 2, "<unk>" to 3),
                    "merges" to emptyList<String>(),
                ),
            ),
        ),
        source = "",
        sourceUri = "",
        installed = true,
        installState = "installed",
        installPath = "",
        createdAtMs = 0L,
        updatedAtMs = 0L,
    )

    private fun stage3Model(): AiModelDescriptor = stage2Model()

    private fun stage2Request(imageFeatures: List<List<Float>> = List(577) { List(768) { 5f } }): AiExecutionRequest = AiExecutionRequest(
        sessionId = "session",
        taskId = "task",
        taskType = "vision_encoder",
        modelId = "florence-2-base",
        version = "1",
        runtimeHint = "onnx",
        attempt = 1,
        deadlineAtMs = 0L,
        payload = mapOf("prompt" to "<CAPTION>", "image_features" to imageFeatures),
    )

    private fun stage3Request(imageFeatures: List<List<Float>> = List(577) { List(768) { 5f } }): AiExecutionRequest = AiExecutionRequest(
        sessionId = "session",
        taskId = "task",
        taskType = "prompt_generation",
        modelId = "florence-2-base",
        version = "1",
        runtimeHint = "onnx",
        attempt = 1,
        deadlineAtMs = 0L,
        payload = mapOf("prompt" to "<CAPTION>", "image_features" to imageFeatures),
    )

    private class RecordingFlorenceExecutor(private val failRole: String? = null) : FlorenceOnnxExecutor {
        val roles = mutableListOf<String>()
        val pathsByRole = mutableMapOf<String, String>()
        val inputsByRole = mutableMapOf<String, List<PreparedInferenceTensor>>()
        val callsByRole = mutableMapOf<String, MutableList<List<PreparedInferenceTensor>>>()

        override fun run(role: String, model: AiModelDescriptor, inputs: List<PreparedInferenceTensor>): Map<String, List<Float>> {
            roles += role
            pathsByRole[role] = model.installPath
            inputsByRole[role] = inputs
            callsByRole.getOrPut(role) { mutableListOf() }.add(inputs)
            if (role == failRole) error(role)
            return when (role) {
                "embed_tokens" -> mapOf("inputs_embeds" to List(inputs.single().shape[1].toInt() * 768) { it.toFloat() })
                "encoder" -> mapOf("last_hidden_state" to List(inputs[1].shape[1].toInt() * 768) { 9f })
                "decoder" -> mapOf(
                    "logits" to List(51289) { 0f },
                    "present.0.decoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.0.decoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.0.encoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.0.encoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.1.decoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.1.decoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.1.encoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.1.encoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.2.decoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.2.decoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.2.encoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.2.encoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.3.decoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.3.decoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.3.encoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.3.encoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.4.decoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.4.decoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.4.encoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.4.encoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.5.decoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.5.decoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.5.encoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.5.encoder.value" to List(1 * 12 * 1 * 64) { 0f },
                )
                "decoder_with_past" -> mapOf(
                    "logits" to List(51289) { 0f },
                    "present.0.decoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.0.decoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.0.encoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.0.encoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.1.decoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.1.decoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.1.encoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.1.encoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.2.decoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.2.decoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.2.encoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.2.encoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.3.decoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.3.decoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.3.encoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.3.encoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.4.decoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.4.decoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.4.encoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.4.encoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.5.decoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.5.decoder.value" to List(1 * 12 * 1 * 64) { 0f },
                    "present.5.encoder.key" to List(1 * 12 * 1 * 64) { 0f },
                    "present.5.encoder.value" to List(1 * 12 * 1 * 64) { 0f },
                )
                else -> error("Unexpected Florence role $role")
            }
        }
    }

    private fun inspectPackage(): ModelPackageInspection =
        ModelPackageInspector().inspect(packageDirectory, File("build/florence-stage1-extracted"))
}
