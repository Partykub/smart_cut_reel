# Face Stability Strategy

## Problem

The current pipeline lets face detection replace the primary subject track whenever a face is found.

That makes the crop react to small head motion, detector jitter, and subtle pose changes. The result is a frame that feels nervous instead of stable.

## Root Cause

1. `body_detection` promotes `face_bbox` to the active `bbox`.
2. `reframe_planning` uses `track.center.x` directly as the crop anchor.
3. `easing_smoothing` only smooths the final crop path, so it still receives a noisy target.

## Recommended Rule

Use the body box as the primary anchor and treat face detection as a bounded composition hint.

This experiment has been rolled back for the current path. The planner is back to using the detected face center directly, with a dead zone to suppress tiny frame-to-frame changes.

In practice:

1. Start from `body_bbox` center.
2. Compute `face_center_x - body_center_x`.
3. Ignore tiny offset changes with a dead zone.
4. Clamp the remaining offset to a small fraction of body width.
5. Apply only a fraction of that offset to the planned crop center.

This keeps the framing aware of the face without letting every head movement drag the crop.

## Current Defaults

- `face hint strength`: `0.18`
- `face hint max ratio of body width`: `0.1`
- `face hint dead zone`: `48 px`
- `face hint smoothing strength`: `0.9`

These defaults are intentionally conservative.

## First Implementation Scope

1. Preserve `body_bbox` and `face_bbox` through `track_interpolation`.
2. Update `reframe_planning` to prefer `body_bbox` as the anchor.
3. Apply bounded face offset only when both body and face boxes are present.
4. Keep existing easing/smoothing as-is for now.

Status:

- Implemented: debug boxes now survive interpolation.
- Implemented: planner is back on direct face anchoring.
- Implemented: planner keeps the previous anchor while the detected center stays inside the dead zone.

Current debug fields in `reframe_plan_raw.keyframes`:

- `anchor_center_x`
- `face_offset_x`
- `face_offset_smoothed_x`
- `stable_zone`

## Later Improvements

1. Require face stability across multiple frames before applying face influence.
2. Expose `face hint strength`, `dead zone`, and `max ratio` in config/frontend.
3. Expose `face hint smoothing strength` in config/frontend.
4. Add stronger subject-state tracking for profile turns and occlusions.