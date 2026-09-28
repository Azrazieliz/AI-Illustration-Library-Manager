# Asterion Core — Character Knowledge / Resolver Integration Checkpoint

**Purpose:** durable recovery checkpoint for conversation failures. This file is the authoritative working handoff for the current Character Knowledge + automation rewrite until this work is merged into `standalone-android`.

**Repository:** `Azrazieliz/AI-Illustration-Library-Manager`  
**Working branch:** `asterion-character-resolver-v1`  
**Parent/intermediate branch:** `asterion-import-pass1`  
**Final target branch:** `standalone-android`  
**Checkpoint date:** 2026-09-28

**Merge status:** COMPLETE. The full `asterion-import-pass1` + `asterion-character-resolver-v1` history has been fast-forwarded into `standalone-android`. `standalone-android` is now the authoritative implementation branch. Final standalone CI run `36386648585` completed successfully at commit `fa61d7ff59b46507849862f14eb43d351d11ebef`, including the full Android regression suite, debug APK build and artifact upload.

---

## 1. User intent / architecture that must not drift

Asterion Core is the intelligence center for the illustration library application. It must be correct internally before any future ecosystem API is designed.

### Knowledge vs Fusion

There are two fundamentally different data systems:

1. **Knowledge**
   - Externally curated by the user / authoring workflow.
   - Frozen and immutable to the running app.
   - Defines legal taxonomy IDs/values, series, Character Knowledge, transformations, aliases, canonical traits and canonical character sheets.
   - The app may load/replace an externally supplied release, but automation/review/learning must never modify the active Knowledge corpus.

2. **Fusion**
   - Asterion Core's own mutable operational database.
   - Stores observed images, per-subject observations, resolved identities, illustration tags, confidence, visual evidence, corrections, OC clusters, automation state and review state.
   - Review corrections improve Fusion-side evidence.
   - Fusion must never silently rewrite immutable Knowledge.

`Fusion_Database.xlsx` is an archive/example only. It is not the application database and must not be used as an implementation target.

### Automation behavior

`Run Automation` processes images **one by one**. One image must complete its full analysis/review/organization transaction before the next starts.

For each image:

1. detect/describe visible subjects;
2. extract only taxonomy-bound visually observable character attributes;
3. extract illustration-level tags;
4. use observed canonical attributes to reduce the Character Knowledge candidate space;
5. rerank candidates with canonical character-sheet visual evidence + validated Fusion images;
6. resolve the character(s) using probabilistic coherence;
7. derive series from the resolved Character Knowledge entry — never invent/guess a series independently in autonomous organization;
8. tag Fusion with character canonical traits and visible illustration tags;
9. above confidence threshold: rename/move to canonical path;
10. below confidence threshold: leave the file in place and create editable Review;
11. only then move to the next file.

**Safe Pause:** a pause request finishes the current image and then stops before the next image.  
**Stop:** remains a separate hard stop behavior.

### Character identity model

Three distinct concepts:

- **Ordinary appearance variation:** same character entry. Examples: hairstyle change, ordinary hair-colour variation, clothes, cosplay.
- **Visually meaningful transformation of the same character:** child resolver entry `CHxxxxxx-n` under the same base character. Lore-only forms with effectively identical visuals should not be split merely for lore.
- **Distinct identity/persona:** distinct base `CHxxxxxx`. Fate-style Artoria / Artoria Alter / Lancetoria / Castoria are separate identities when they are treated as distinct actual identities.

Transformations can inherit base traits and override only visually changed traits.

Aliases are lookup-only. Canonical names are the only names used in paths/output. Character aliases may legitimately be ambiguous; an alias must not be forced globally unique. Automatic alias resolution only succeeds when a canonical Character ID is explicit or when alias + series context yields one unique identity.

### Multi-character paths

Single character:

```
Series/
  Character/
    Character - Series N.ext
```

Several characters from the same series:

```
Series/
  Character 1 - Character 2 - ... - Series N.ext
```

Inter-series:

```
Primary Character's Series/
  Primary Character/
    Character 1 - Character 2 - ... - Primary Series N.ext
```

The most visually prominent character owns the physical path in an inter-series image. All other resolved characters remain attached in Fusion and stay in the multi-character filename.

### Original characters

Unregistered OCs stay in mutable Fusion and are clustered with visual/attribute evidence under local OC IDs. They do not become canonical `CH...` entries automatically.

A deliberately invented/feminized character may later produce a **proposed** Character Knowledge record + sheet, but it requires user approval and an external Knowledge-authoring/versioning step before it becomes an immutable canonical Knowledge entry.

### Ecosystem integration

The future shared Core API / FlowLink / ecosystem contract is **frozen and explicitly deferred**. Do not implement point 10 now. The API should be designed only after the other applications have real designs/releases. Core must merely remain architecturally reusable.

---

## 2. Character Knowledge authoring / delivery intent

Do not author hundreds of thousands of character entries directly as raw JSON.

Planned authoring model:

- human-readable structured XLSX/CSV/workbook batches;
- one row per resolver identity/transformation;
- validator/compiler resolves every taxonomy ID against the frozen Knowledge release;
- final compiled delivery is JSON/JSONL or equivalent machine-readable release;
- canonical character visual sheets remain separate assets referenced by `sheet_asset_id`.

Important Character Knowledge fields include:

- `character_id`
- `parent_character_id`
- `identity_group_id`
- `entry_type`
- `canonical_name`
- `primary_series_code`
- aliases
- canonical attribute IDs
- canonical weapon IDs
- canonical outfit IDs
- sheet asset reference
- provenance/metadata during authoring

Character Knowledge stores stable/canonical identification traits, not every transient appearance seen in an illustration.

---

## 3. Multi-value attribute semantics — IMPORTANT

The taxonomy is intentionally coarse enough to avoid subjective distinctions. Do not invent excessive shades/centimeter-scale bins.

Some attribute families legitimately encode **multiple IDs simultaneously**, especially:

- **Hair colour** (`HC...`)
- **Eye colour** (`EC...`)

Examples:

- multicoloured hair may be encoded as multiple canonical colour IDs;
- heterochromia may encode two eye-colour IDs plus a canonical heterochromia eye-trait ID;
- a character like Luminous can therefore legitimately carry multiple IDs in one attribute family.

Rules now implemented:

- multiple canonical IDs in the same family are first-class, not duplicates/errors;
- if two exact colours are visible, vision should emit both specific IDs;
- generic `Multicolored` is only a fallback when multiple colours are clearly visible but exact components cannot be resolved safely;
- a candidate with multiple canonical colours is not contradicted when only one of those colours is visible in the current image;
- if two colours are visibly observed and a candidate only explains one, coherence drops;
- aggregate multicolour values and exact component colour sets are treated compatibly when appropriate;
- contradiction scoring works by attribute family rather than naïvely treating same-family extra IDs as mutually exclusive.

Do not regress this behavior.

---

## 4. Current implemented components

### Immutable Knowledge store

Added `KnowledgeDatabase.kt`.

It contains separate immutable runtime tables for:

- Knowledge releases;
- series;
- series aliases;
- taxonomy tags;
- taxonomy aliases;
- characters;
- character aliases;
- character feature index;
- character-sheet manifest.

Normal automation/review does not write canonical Knowledge.

Knowledge release replacement is explicit and atomic. Replacing taxonomy invalidates dependent Character Knowledge rather than silently keeping stale references.

### Character Knowledge import

`ReferenceKnowledgeImporter.kt` / parser supports:

- heterogeneous current taxonomy JSONs;
- series data;
- character entries;
- aliases;
- parent relationships;
- character `attributes` objects;
- arrays with several IDs in the same attribute family;
- canonical weapon/outfit IDs;
- transformation parent fields.

Taxonomy/series are loaded into immutable Knowledge, not Fusion.

### Character aliases

Character alias index was changed from global uniqueness to many-to-many alias lookup.

Rationale: aliases such as “Saber” may legitimately be ambiguous.

- `resolveCharacters(alias)` returns all matches;
- `resolveCharacter(alias, seriesCode)` resolves only if exactly one identity remains;
- direct `CHxxxxxx` lookup remains unambiguous;
- character-sheet filename resolution uses series context.

### Character resolver

Added `CharacterResolver.kt`.

Current autonomous recognition does **not** trust a free-form model character name.

Pipeline:

- Qwen/VLM returns taxonomy-bound per-subject visual observations;
- candidate filtering from immutable Character Knowledge;
- family-aware attribute coherence;
- contradiction penalty;
- canonical-sheet / validated Fusion visual similarity;
- combined final confidence;
- threshold decides automatic resolution vs Review.

### Attribute semantics

Added `CanonicalAttributeSemantics.kt`.

It provides:

- attribute-family grouping;
- explicit multi-value handling for hair/eyes;
- multicolour aggregate compatibility;
- family-aware coverage score;
- contradiction fraction that does not punish legitimate multi-ID profiles.

Unit tests were added for these cases.

### Per-subject vision observations

The character-recognition prompt now asks for structured JSON roughly like:

```json
{
  "subjects": [
    {
      "subject_index": 0,
      "prominence": 0.0,
      "bbox": [0.0, 0.0, 1.0, 1.0],
      "attributes": [
        {"id": "HC001", "confidence": 0.0}
      ]
    }
  ]
}
```

Rules in the prompt:

- do not guess character names;
- do not guess series;
- use only supplied canonical taxonomy IDs;
- omit hidden/unsafe/subjective attributes;
- multiple same-family IDs are allowed when genuinely visible;
- for heterochromia, emit both eye colours and the canonical trait when justified.

### Series recognition

Autonomous organization no longer uses free-form `series_recognition`.

Series is derived from the resolved Character Knowledge entry.

A standalone diagnostic series-recognition task may still exist for manual tooling, but it is not authoritative for automation/path organization.

### Illustration tags

Illustration-level visible tags are constrained to immutable Knowledge taxonomy IDs.

Examples: current outfit/accessories, visible weapon, pose, gesture, expression, eye/mouth state, action, environment/weather, framing/camera/lighting, rating when safely inferable.

Canonical character weapons/outfits are useful as **recognition evidence**, but they are not asserted as visibly present illustration tags unless actually observed.

### Mutable Fusion resolution store

Added `FusionResolutionStore.kt` and Local DB schema extensions.

Fusion now tracks:

- per-image subjects;
- subject observations;
- candidate lists;
- resolved character IDs/confidence;
- canonical per-image tags;
- character visual evidence;
- automation state;
- review state/corrections;
- OC clusters;
- character-sheet visual-index queue/state.

### Review

Character-resolution Review now contains candidate/evidence context and supports manual correction.

Corrections can:

- select canonical Character Knowledge identities;
- select multiple characters;
- mark an image/subject as Original Character.

Approved corrections become validated Fusion visual evidence and the corrected identity is used to reorganize the file.

Knowledge stays unchanged.

### Original-character clustering

Mutable OC clustering exists in Fusion and uses canonical attribute observations + visual embedding evidence.

### Safe Pause / Resume

Automation now has a safe pause flag.

The worker checks before the next image and after completing the current image. A requested pause completes the current image before entering paused state.

### Organization state / retry

Pipeline completion and organization completion are tracked separately.

A successfully analyzed image with a file-move failure is no longer lost from subsequent processing. Organization errors can enter retry/review state.

### Canonical path policy

Added `AutomationPathPolicy.kt` and unit tests.

It fixes:

- single-character path;
- same-series multi-character path;
- inter-series prominent-character ownership;
- filename ordering by detected subject order;
- Original Characters folder behavior.

`StandaloneRuntime` now consumes this tested policy rather than duplicating path logic inline.

### Character sheets

Added `CharacterSheetArchiveImporter.kt`.

The Character Sheet workflow is **completely external to Asterion Core**. The user can provide a character image to that workflow; it performs its own research/canonical reconstruction and generates one complete final Character Sheet in one external image-generation call. Core does not collect, curate, require, or construct a multi-image reference set for sheet creation.

A finished Character Sheet is one canonical visual baseline for one Character Knowledge identity/form. Core:

- associates the externally generated sheet with Character Knowledge;
- stores it separately from Character JSON;
- compresses/stores it for scale;
- registers it via `sheet_asset_id`;
- queues it for background visual indexing;
- uses its derived visual evidence during identity reranking.

Normal illustration-library images are a separate source of visual evidence. As Core resolves and organizes real library images into character folders, those images can also contribute Fusion-side visual evidence after validation/correction.

The filename form `Character - Series N.ext` is reserved for ordinary library images that Core itself renames and organizes. It must not be reinterpreted as a Character Sheet naming convention.

The exact packaging/naming convention for externally generated Character Sheets is not conceptually required by Core. Stable Character Knowledge IDs such as `CH000001.webp` / `CS-CH000001.webp` are supported as an unambiguous association method, and an unnumbered canonical `Character - Series.ext` form can also resolve when unique. A later packaging workflow may use manifest/sidecar metadata without changing the visible Character Sheet.

### Scalable character-sheet visual indexing

Character-sheet indexing is resumable/background work rather than a single giant blocking import.

There is a dedicated Fusion indexing queue and worker. Completed canonical sheet embeddings become visual evidence available to the character resolver.

---

## 5. Current tests / CI state at checkpoint

CI workflow now gates the resolver work with Android JVM regression tests and APK build.

Relevant tests include:

- existing model import/runtime regressions;
- `ReferenceKnowledgeParserTest`;
- `CanonicalAttributeSemanticsTest`;
- `AutomationPathPolicyTest`.

A failed run at commit `8d3c06b231cb...` completed **74 tests, with 1 failure and 4 skipped**.

The single failure was:

`ReferenceKnowledgeParserTest > character parser preserves multiple ids in one attribute family`

at `ReferenceKnowledgeParserTest.kt:53`.

The Kotlin build itself compiled; the failure was a test assertion/order problem, not a compile crash.

Commit `d53098de493a...` changes that test to make the multi-ID assertion order-independent.

Resolver CI run `36363591774` for `d53098de493a...` completed successfully. The combined history was then fast-forwarded into `standalone-android`.

Final authoritative validation: standalone CI run `36386648585` completed successfully at `fa61d7ff59b46507849862f14eb43d351d11ebef`. The regression/build step succeeded and GitHub uploaded artifact `AsterionCore-debug-apk` (artifact id `10954757125`).

---

## 6. Branch topology / merge instruction

Historical development ancestry:

`standalone-android` (old base)
→ `asterion-import-pass1`
→ `asterion-character-resolver-v1`

The validated combined history has now been fast-forwarded back into `standalone-android`; the two named pass branches are historical recovery branches, not the authoritative application branch.

`asterion-import-pass1` is already strictly ahead of `standalone-android`, and the resolver branch is built on top of it.

User instruction:

- **Do not leave either intermediate pass as the final product.**
- Once the resolver branch is validated, directly fuse/fast-forward the complete result into `standalone-android`.
- Preserve recovery safety until the target branch is verified.
- After successful final validation, intermediate branches are no longer the authoritative implementation.

The final standalone branch must therefore contain both the import-pass fixes and the character-resolver/Knowledge/Fusion work.

---

## 7. What still must be done before finalizing

Completed before final merge:

- Resolver regression/build gate: green.
- Full history fast-forwarded into `standalone-android`.
- Final standalone regression/build gate: green.
- Debug APK artifact uploaded successfully.

Remaining work belongs to the **next character-population/device-validation phase**, not this code-integration phase. Preserve the following audit areas during future changes:
   - Knowledge/Fusion boundary;
   - Review correction path;
   - safe pause;
   - retry/organization state;
   - multi-value attributes;
   - ambiguous aliases;
   - canonical path policy;
   - strict separation between externally generated Character Sheets and Core-organized ordinary library images;
   - sheet indexing.
5. Verify the current user taxonomy archive imports cleanly into the immutable Knowledge DB.
6. Exercise a minimal synthetic Character Knowledge release containing:
   - normal identity;
   - transformation `CHxxxxxx-n`;
   - distinct identity;
   - ambiguous alias;
   - multi-colour hair;
   - heterochromia;
   - canonical weapon/outfit;
   - multiple characters / multiple series.
7. Confirm Review correction creates validated Fusion evidence without changing Knowledge.
8. Build the final debug APK from the validated commit.
9. Fast-forward/fuse the validated resolver HEAD into `standalone-android`.
10. Run final standalone branch CI after the merge.
11. Only then call this architecture frozen for the character-population phase.

---

## 8. Known design cautions

- Do not make hair/eye colour single-valued.
- Do not make character aliases globally unique.
- Do not treat generic `Multicolored` as superior to exact component colours.
- Do not infer hidden height/breast/body traits from close-ups.
- Do not let soft evidence such as height/breast size override strong sheet/face/species/weapon evidence.
- Do not let canonical outfit/weapon knowledge masquerade as “visible now” unless vision observed it.
- Do not derive series independently when character identity is resolved.
- Do not organize below-threshold files; leave them for Review.
- Do not write Review corrections into immutable Knowledge.
- Do not invent a pre-curated or manually renamed reference-image set for Character Sheet creation. Character Sheets are generated externally; ordinary library images are organized by Core as `Character - Series N.ext` and may later contribute Fusion visual evidence.
- Do not redesign the future ecosystem API now.
- Do not renumber existing Character IDs merely to keep related identities adjacent.

---

## 9. Recovery instruction for a future conversation

If conversation state is damaged:

1. Read this file first.
2. Inspect `standalone-android`, `asterion-import-pass1`, and `asterion-character-resolver-v1` branch heads.
3. Inspect the latest Actions run on the resolver/standalone branch.
4. Continue from the latest validated commit, not from memory.
5. Preserve every architectural rule in sections 1–8 unless the user explicitly changes it.
6. Update this checkpoint whenever a material rule, schema, unresolved defect or merge status changes.



---

## 10. Correction recorded after user review — Character Sheet workflow

A previous implementation explanation incorrectly invented a workflow in which the user would provide a curated/numbered reference-image set that would then be converted into a Character Sheet. **That model is rejected and must not reappear.**

Authoritative interpretation from the Character Sheet V5 workflow and the user's clarification:

1. The Character Sheet workflow is external to Asterion Core.
2. The user may provide a character image directly to that workflow.
3. The workflow performs its own internal research and canonical reconstruction.
4. It generates **one complete 9:16 Character Sheet in one image-generation call**.
5. That finished sheet is later supplied to Asterion as a canonical visual baseline for the corresponding Character Knowledge identity/form.
6. Asterion does not require the user to curate, rename, or package a set of source reference images for sheet creation.
7. Ordinary library images are handled by Asterion automation and are renamed `Character - Series N.ext`, organized into canonical folders, tagged, and used as additional Fusion-side visual evidence when appropriate.
8. Character Sheets are references among the resolver's visual evidence, not the only references.
9. The exact external packaging convention for generated sheets may later use filename association, manifest/sidecar metadata, or another explicit mapping, but this packaging detail must not be confused with the ordinary library filename scheme.
10. Any future code/documentation that describes `Character - Series N.ext` as sheet-source material is wrong.



---

## 11. Final pre-Character-Knowledge alignment — transformation names and Asterion-ready sheets

Before beginning Character Knowledge population, the runtime was aligned with the final external Character Sheet naming contract.

### Explicit transformation naming

Character Knowledge transformation entries now carry:
- `canonical_name`: base character name, e.g. `Goku`;
- `form_name`: visual transformation label, e.g. `Super Saiyan 3`;
- computed `display_name`: `Goku (Super Saiyan 3)`.

Rules:
- `form_name` is required for `entry_type=transformation`;
- it is forbidden for non-transformation entries;
- `display_name` is indexed as a character lookup alias;
- therefore an external finished sheet named `Goku (Super Saiyan 3) - Dragon Ball.webp` resolves directly to the corresponding `CHxxxxxx-n` entry;
- ordinary organized transformation illustrations use the form-aware filename `Goku (Super Saiyan 3) - Dragon Ball N.ext`;
- their physical folder remains the base character folder `Dragon Ball/Goku/`, because transformations belong to the same individual character family.

Distinct identities remain separate base `CHxxxxxx` records and do not use `form_name` merely because they are related in lore.

### Character Sheet WebP handling

The external Character Sheet workflow now exports finished sheets as:
- `Character - Series.webp`;
- `Character (Transformation) - Series.webp` for transformations.

Asterion's sheet importer:
- resolves these filenames against immutable Character Knowledge;
- recognizes the transformation form through `display_name`;
- stores already-WebP input bytes unchanged, avoiding an unnecessary second lossy encode;
- still supports conversion of legacy non-WebP sheets only as a compatibility path;
- keeps `Character - Series N.ext` reserved for ordinary library images organized by Core.

This section supersedes any older wording that implied Character Sheets needed pre-renaming to `CH...` filenames. Stable ID filenames remain supported as an optional unambiguous packaging method, but are not required from the external Character Sheet workflow.
