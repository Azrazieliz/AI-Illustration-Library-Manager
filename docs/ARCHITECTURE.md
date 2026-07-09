# AI Illustration Library Manager

## Specification v1.1 (Frozen)

This document is the definitive architecture and behavior specification.
All frozen rules are defined here exactly once.

## Scope

- Clarifies existing architecture and responsibilities.
- Preserves all frozen subsystem boundaries.
- Defines canonical terminology and behavioral rules.

## Non-Goals

- No architectural redesign.
- No new backend layers.
- No subsystem merge or split.
- No UI business-logic ownership.

## Layered Architecture (Frozen)

Repository
-> Engine
-> Service
-> Worker
-> UI

### Layer Responsibilities

- Repository: persistence access and durable state operations.
- Engine: domain orchestration and core business behavior.
- Service: application-facing coordination and policy entrypoints.
- Worker: background execution, checkpoints, and resumable processing.
- UI: consumer-only presentation and user interaction.

### Layer Rules

- Business logic remains in Repository, Engine, Service, and Worker layers.
- UI does not implement domain rules.
- UI communicates through established service and bridge contracts.

## Canonical Terminology (Frozen)

- Fusion Database
- Canonical Character Database
- Illustration Metadata
- Knowledge Packs
- Recognition Engine
- Adaptive Learning
- Corporal Tags
- Outfits and Accessories

Older or ambiguous names are obsolete and not normative.

## Data Authority Model

### Fusion Database

- The Fusion Database is the only manually maintained source of truth.
- It stores structured canonical knowledge only.
- Generated outputs must never become independent authorities.

### Generated Resources

- SQLite
- JSON
- Android databases
- Desktop databases
- Knowledge Packs
- Search indexes

Generated resources are derived artifacts of the Fusion Database.

## Worksheet and Identifier Consistency

Each worksheet owns an immutable identifier space after freeze.
Identifiers do not change after freeze, including after renames.

Frozen worksheet domains include:

- Series
- Characters
- Corporal Tags
- Weapons
- Outfits and Accessories
- Recognition Rules

Obsolete worksheet fields are non-normative and must be removed from specifications.

## Recognition Responsibilities (Clarified)

Recognition first determines:

- Character
- Recognition confidence

After character identification, the application loads canonical data from the Character Database:

- Series
- Canonical appearance
- Canonical tags

Only after canonical loading does illustration analysis determine image-specific metadata, including:

- Expressions
- Poses
- Environment
- SFW or NSFW status
- Other illustration-specific details

This clarifies existing responsibilities between canonical knowledge and illustration knowledge.
It does not define a new subsystem.

## Canonical vs Illustration Knowledge (Frozen)

- Canonical knowledge belongs exclusively to the Fusion Database.
- Illustration knowledge belongs to per-image Illustration Metadata.
- Illustrations never automatically modify canonical character data.

Canonical tags and illustration tags are separate concepts.

## Character Data Rules (Frozen)

- Character entries store canonical data only.
- Illustration variations do not redefine canonical appearance.
- Multiple canonical appearances are allowed when canonically valid.

Example clarification:

- Multiple canonical hair colors, styles, or lengths are allowed as distinct canonical appearances.
- This is not equivalent to a multicolored hair tag.
- Multicolored appearance remains an independent tag.

## Tag System Rules (Frozen)

- Canonical tags belong to the Canonical Character Database.
- Illustration tags belong to image-level Illustration Metadata.
- Corporal Tags describe permanent canonical physical characteristics.
- Illustration tags describe temporary visual characteristics.

Illustration tags include expressions, poses, environment, and SFW or NSFW states.
NSFW refers exclusively to explicit sexual content.

## Species and Color Modeling

### Species

- Species uses hierarchical inheritance.
- Example: Species -> Elf -> Dark Elf or High Elf.
- Species entries are not flattened into unrelated peers.
- Only anatomically meaningful attributes apply per species branch.

### Colors

- Color tags are a flat taxonomy.
- Color inheritance is not used.
- Canonical colors remain limited to clearly distinguishable recognition categories.

## Confidence and Visibility Semantics

- Recognition confidence thresholds are configurable application settings.
- Default thresholds may be recommended by specification.
- Threshold values are not stored in the Fusion Database.

Visibility semantics:

- Unknown: confidence is insufficient to determine feature state.
- Not Visible: feature state cannot be observed due to occlusion or framing.

## Adaptive Learning Boundaries (Frozen)

Adaptive Learning may improve:

- Recognition confidence
- Embeddings
- Recognition behavior
- Threshold tuning

Adaptive Learning must never auto-modify canonical database entities, including:

- Character data
- Series data
- Corporal Tags
- Weapons
- Outfits and Accessories
- Recognition Rules

The Fusion Database remains manually maintained.

## Character Reference Image Policy

- Each character requires at least 1 reference image.
- Each character supports up to 5 reference images.
- Reference images are stored as application assets, not workbook binaries.
- Workbook content remains structured knowledge only.
- Character IDs are immutable keys for reference association.

## Knowledge Pack Positioning

- Knowledge Packs are generated canonical distribution artifacts.
- Knowledge Packs are not independent authoritative sources.
- Canonical authority remains the Fusion Database.

## Validation Requirements for Specifications

A valid specification state must satisfy all of the following:

- No architectural contradictions.
- No duplicated frozen rules.
- No obsolete worksheet definitions.
- No obsolete database field definitions.
- All frozen decisions represented once in canonical wording.
- Layered architecture remains unchanged.
- Responsibilities are consistent across all documents.
