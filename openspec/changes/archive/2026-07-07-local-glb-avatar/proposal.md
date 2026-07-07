# Proposal: Local GLB Avatar

## Intent

Remove dependency on LiveAvatar (external API + LiveKit WebRTC streaming). Replace with a self-contained GLB 3D model rendered client-side in Three.js. Eliminates external API costs, LiveKit complexity, WebSocket keep-alive, and the 5-min inactivity timeout constraint.

## Scope

### In Scope
- Backend: `POST /sessions/{session_id}/local-avatar-connect` → `{status: "ok", session_id}`
- Backend: Tests for new endpoint (TDD — write first)
- Frontend: Replace `livekit-client` with `three`, `@react-three/fiber`, `@react-three/drei`
- Frontend: New `LocalAvatarGLB` component — loads GLB from `/avatars/`, idle breathing/bobbing animation, dark background, responsive
- Frontend: Rewrite `AvatarSession.tsx` to use local GLB instead of LiveAvatar/LiveKit/WebSocket
- Frontend: Update `api.ts` — add `localAvatarConnect()`, remove `connectLiveAvatar()`/`stopLiveAvatarSession()`
- Frontend: Keep push-to-talk flow (mic → record → send → play WAV audio)

### Out of Scope
- Lip-sync or viseme animation (v1)
- Multiple avatar models or model selector
- Animation customization UI
- Full removal of `liveavatar.py`, `liveavatar-connect`/`liveavatar-stop` endpoints, LiveAvatar config — deferred to a follow-up cleanup change

## Capabilities

### New Capabilities
- `local-avatar-session`: Client-side 3D avatar rendered via Three.js with idle animation, dark scene, and audio playback

### Modified Capabilities
None — this is a pure implementation replacement. No spec-level behavior changes.

## Approach

**Backend**: Add a lightweight endpoint that validates the session exists and is active, then returns `{status: "ok", session_id}`. No external API calls, no token creation, no WebSocket URL generation. No new database state.

**Frontend**: 
1. Install `three`, `@react-three/fiber`, `@react-three/drei`, remove `livekit-client`
2. Create `LocalAvatarGLB` — a React Three Fiber canvas with responsive sizing, dark background (`#111`), centered GLB model with gentle Y-axis oscillation (idle bobbing) and subtle rotation
3. Place the GLB model file at `public/avatars/` (one model for v1)
4. Rewrite `AvatarSession.tsx`: drop all LiveKit room/connection/WebSocket code, videoRef, keep-alive. Replace the video element with `<LocalAvatarGLB />`. Keep mic recording, `speakInSession` call, `playAudioLocally` for response playback. Keep conversation panel unchanged.
5. Update `session/[id]/page.tsx` — dynamic import stays but loads the new component

**Tests**: Backend test for `local-avatar-connect`: valid session returns 200 with expected body; non-existent session returns 404; ended session returns 404.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `services/backend/routers/sessions.py` | Modified | Add `local-avatar-connect` endpoint |
| `services/backend/tests/test_sessions.py` | Modified | Add tests for new endpoint |
| `services/frontend/package.json` | Modified | Replace `livekit-client` with `three`, `@react-three/fiber`, `@react-three/drei` |
| `services/frontend/src/lib/api.ts` | Modified | Add `localAvatarConnect`, remove `connectLiveAvatar`/`stopLiveAvatarSession` |
| `services/frontend/src/components/student/AvatarSession.tsx` | Rewritten | Replace LiveKit/liveavatar logic with local GLB |
| `services/frontend/src/components/student/LocalAvatarGLB.tsx` | New | Three.js component for GLB rendering + idle animation |
| `services/frontend/public/avatars/` | New | Directory for GLB model file |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| GLB model file size (bloats initial load) | Medium | Compress with Draco; lazy-load via `useGLTF` suspense |
| Three.js bundle size impact | Medium | Dynamic import with `ssr: false` (already pattern in codebase) |
| WebGL compatibility on older devices | Low | Graceful fallback to audio-only if canvas fails to render |
| Missing `public/` directory in Next.js setup | Low | Create it; Next.js serves `public/` at root by default |

## Rollback Plan

Revert the frontend commit to restore `livekit-client` dependency and LiveAvatar connection. Revert the backend commit to remove the new endpoint. The `liveavatar-connect`/`liveavatar-stop` endpoints remain active during the transition — no service interruption.

## Dependencies

- GLB model file (source TBD — free model from Sketchfab/Ready Player Me or similar)
- `three`, `@react-three/fiber`, `@react-three/drei` npm packages

## Success Criteria

- [ ] `local-avatar-connect` returns `{status: "ok", session_id}` for active sessions, 404 for invalid/ended ones
- [ ] GLB model renders on the session page with idle animation
- [ ] Push-to-talk records audio, sends to `/speak`, plays WAV response, avatar animates
- [ ] No LiveKit connection, no WebSocket, no LiveAvatar API calls during session
- [ ] Conversation history panel unchanged
- [ ] Build succeeds with no TypeScript errors
