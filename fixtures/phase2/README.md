# Phase 2 fixtures — dead-air cutting

Three canned scenarios, each containing the artifacts the dead-air pipeline
produces between `voice_activity_detection` and `render_plan_compiler`. All
files validate against the Phase 2 contract schemas under `contracts/`.

## Variants

| Folder       | Source duration | Kept seconds | Cuts | Use case                                       |
| ------------ | --------------- | ------------ | ---- | ---------------------------------------------- |
| `heavy_cut/` | 60.000 s        | ~22.500 s    | 3    | Long pauses dominate; renderer trims aggressively |
| `light_cut/` | 60.000 s        | ~57.000 s    | 1    | One small gap; renderer trims a single 3 s window |
| `no_cut/`    | 60.000 s        | 60.000 s     | 0    | `remove_dead_air = false` → identity cut plan   |

Each folder ships:

- `vad_segments.json` — speech/silence segments covering the full duration
- `cut_plan.json` — `keep_segments` derived from the VAD output (or identity)
- `reframe_plan_smooth.json` — keyframes 0..source_duration that the
  `render_plan_compiler` projects onto each keep segment

The fixtures are consumed by the integration test in
`tests/integration/test_phase2_pipeline_integration.py` and by future smoke
tests for the renderer.
