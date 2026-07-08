# Architecture

The application follows service-oriented orchestration from run.main.
Subsystem business logic remains inside engine packages.
Release utilities live in engine.release and are side-effect free.
