# Tasks: Local GLB Avatar

## Overview

6 ordered tasks replacing the LiveAvatar/LiveKit pipeline with a client-side GLB avatar via React Three Fiber. Total estimated delta: ~475 lines (excluding binary GLB asset). Single PR recommended.

---

## Dependency Graph

```
Task 1 (backend endpoint) ──┬── no frontend dep
                            │
Task 2 (npm deps) ─────────┤
                            │
Task 3 (public/avatars/) ───┤
                            │
Task 4 (LocalAvatarGLB) ◄──┴── requires Task 2, 3
                            │
Task 5 (api.ts) ◄───────────── requires Task 1 (contract known)
                            │
Task 6 (AvatarSession rewrite) ◄── requires Tasks 4, 5
```

---

## Task 1: Backend — `local-avatar-connect` endpoint

**ID**: `task-1-backend-endpoint`

**Description**: Add `POST /sessions/{session_id}/local-avatar-connect` to validate session exists and is active. Pure validation — no external API calls, no tokens, no WebSocket URLs, no DB mutations.

**Files touched**:
- `services/backend/routers/sessions.py` — add endpoint (~30 lines, after line 320, before `liveavatar-connect`)
- `services/backend/tests/test_sessions.py` — add 3 test functions (~50 lines)

**Test strategy**:
```bash
conda run -n aiedu python -m pytest services/backend/tests/test_sessions.py -v -k "local_avatar"
```
Tests (all in `test_sessions.py`):
1. `test_local_avatar_connect_active` — create student + session, POST to endpoint → 200 + `{status: "ok", session_id: "..."}` 
2. `test_local_avatar_connect_not_found` — random UUID → 404
3. `test_local_avatar_connect_ended` — create session, end it via DELETE, then POST → 404

**Estimated lines changed**: +80
**Review workload**: Low (simple validation, well-understood pattern)

**Status**: ✅ COMPLETE

---

## Task 2: Frontend — Dependency swap

**ID**: `task-2-npm-deps`

**Description**: Remove `livekit-client`, add `three`, `@react-three/fiber`, `@react-three/drei`. Run `npm install`.

**Files touched**:
- `services/frontend/package.json` — 4 lines changed

**Verification**:
```bash
cd services/frontend && npm run build
```
Build must succeed with no missing module errors.

**Estimated lines changed**: 4 (package.json only)
**Review workload**: Trivial

**Status**: ✅ COMPLETE

---

## Task 3: Frontend — `public/avatars/` directory + GLB model

**ID**: `task-3-avatars-asset`

**Description**: Create `services/frontend/public/avatars/` directory and place a placeholder GLB model file.

**Files touched**:
- `services/frontend/public/avatars/` — new directory
- `services/frontend/public/avatars/avatar.glb` — binary GLB file

**Verification**: File is accessible at `http://localhost:3000/avatars/avatar.glb` in dev.

**Estimated lines changed**: N/A (binary asset)
**Review workload**: Verify license + file size < 5MB

**Status**: ✅ COMPLETE

---

## Task 4: Frontend — `LocalAvatarGLB` component

**ID**: `task-4-local-avatar-component`

**Description**: Create new React Three Fiber component that renders the GLB model with idle animation and WebGL error fallback.

**New file**: `services/frontend/src/components/student/LocalAvatarGLB.tsx`

**Estimated lines changed**: ~80 (new file)
**Review workload**: Medium — first R3F component in codebase

**Status**: ✅ COMPLETE

---

## Task 5: Frontend — `api.ts` updates

**ID**: `task-5-api-ts`

**Description**: Add `localAvatarConnect()` function, remove `connectLiveAvatar()`, `stopLiveAvatarSession()`, and the `LiveAvatarConnect` interface.

**File**: `services/frontend/src/lib/api.ts`

**Estimated lines changed**: ~15 (remove 3, add 5)
**Review workload**: Low

**Status**: ✅ COMPLETE

---

## Task 6: Frontend — Rewrite `AvatarSession.tsx`

**ID**: `task-6-rewrite-avatar-session`

**Description**: Major rewrite of AvatarSession.tsx — strip all LiveKit/WebSocket/keep-alive code, integrate LocalAvatarGLB. Keep push-to-talk, speakInSession, playAudioLocally, ChatBubble, conversation panel, endSession.

**File**: `services/frontend/src/components/student/AvatarSession.tsx`

**Estimated lines changed**: ~280 (721 → ~440 lines)
**Review workload**: High — most of the change surface

**Status**: ✅ COMPLETE

---

## Summary

| Task | Files | Est. Lines | Dependencies | Risk | Status |
|------|-------|-----------|-------------|------|--------|
| 1. Backend endpoint | sessions.py, test_sessions.py | +80 | None | Low | ✅ |
| 2. npm deps | package.json | 4 | None | Low | ✅ |
| 3. GLB asset | public/avatars/* | binary | None | Low | ✅ |
| 4. LocalAvatarGLB | src/components/student/LocalAvatarGLB.tsx | +80 | Task 2, 3 | Medium | ✅ |
| 5. api.ts | src/lib/api.ts | ~15 | Task 1 | Low | ✅ |
| 6. AvatarSession rewrite | src/components/student/AvatarSession.tsx | ~280 | Task 4, 5 | High | ✅ |

**Total estimated delta**: ~460 lines code + 1 binary asset
**Review workload**: ~400 lines of meaningful code change
**All tasks**: ✅ 6/6 COMPLETE
