# Design: Local GLB Avatar

## Technical Approach

Replace the LiveAvatar (external API + LiveKit WebRTC) pipeline with a self-contained client-side 3D avatar rendered via React Three Fiber + a GLB model. Backend loses all LiveAvatar orchestration complexity but keeps the existing `/speak` TTS flow unchanged. The new `local-avatar-connect` endpoint is a pure validation gate — session exists and is active → `{status: "ok"}`.

## Architecture Decisions

### Decision: Backend endpoint scope

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Validate + external API call | Pro: reuse liveavatar-connect logic. Con: still depends on LiveAvatar | ❌ |
| Pure session validation | Pro: no external dependency, zero cost, instant response. Con: no token/URL to return | ✅ |

**Rationale**: The GLB model lives entirely client-side. The backend only needs to confirm the session is valid and active before the frontend proceeds to render. No tokens, no WebSocket URLs, no API calls.

### Decision: Three.js loading strategy

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Static import | Pro: simple. Con: Three.js (~200KB gzipped) blocks initial bundle | ❌ |
| `next/dynamic` with `ssr: false` | Pro: lazy-loaded, no SSR issues with WebGL. Con: brief loading state | ✅ |

**Rationale**: Already the codebase pattern — see `page.tsx` dynamic import of `AvatarSession`. Three.js is the single largest dependency addition; dynamic import prevents it from blocking first paint.

### Decision: Idle animation approach

| Option | Tradeoff | Decision |
|--------|----------|----------|
| GLB animation clips | Pro: realistic. Con: needs animated model, animation pipeline | ❌ |
| Procedural via `useFrame` | Pro: zero model dependency, lightweight, works with any static GLB. Con: less realistic | ✅ |

**Rationale**: v1 has no lip-sync or gesture system. A procedural Y-axis bob (sin wave) + slow rotation produces a natural "alive" feel without model authoring complexity.

### Decision: Audio playback

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Reuse existing `playAudioLocally` | Pro: zero new code, proven pattern. Con: none | ✅ |
| Web Audio API | Pro: sample-level control. Con: overkill for simple WAV playback | ❌ |

**Rationale**: The existing `playAudioLocally()` at `AvatarSession.tsx:543` already handles WAV playback via HTMLAudioElement + Object URL. Keep it.

## Component Architecture

```
SessionPage (page.tsx — unchanged)
 └── LocalAvatarSession (rewritten from AvatarSession.tsx)
      ├── LocalAvatarGLB (new — LocalAvatarGLB.tsx)
      │    ├── <Canvas>          ← R3F, responsive container
      │    ├── <GLBModel>        ← useGLTF("/avatars/avatar.glb")
      │    ├── IdleAnimation     ← useFrame → rotation + Y bob
      │    └── SpeakingIndicator ← CSS scale pulse when audio plays
      ├── ChatBubble (unchanged)
      ├── PushToTalk button (unchanged)
      └── AudioPlayer (inline — HTMLAudioElement from existing pattern)
```

## Data Flow

```
User holds mic → MediaRecorder (same as before)
     ↓
User releases → audio blob
     ↓
POST /sessions/{sessionId}/speak → backend (unchanged)
     ↓
Backend returns WAV audio (unchanged /speak pipeline)
     ↓
Frontend: playAudioLocally(wavBuffer) → HTMLAudioElement
     ↓
Frontend: setSpeaking(true) → LocalAvatarGLB shows speaking pulse
     ↓
Frontend: getSessionHistory(sessionId) → update chat bubble list
```

Connection phase (simplified from current):
```
LocalAvatarSession mounts
     ↓
POST /sessions/{sessionId}/local-avatar-connect
     ↓
{status: "ok"} or 404 (invalid/ended session)
     ↓
Render LocalAvatarGLB (dynamic import, ssr: false)
     ↓
Ready for push-to-talk — no WebSocket, no keep-alive, no 5-min timeout
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `services/backend/routers/sessions.py` | Modify | Add `POST /{session_id}/local-avatar-connect` — validate session exists and not ended, return `{status: "ok", session_id}` |
| `services/backend/tests/test_sessions.py` | Modify | Add 3 tests: valid session → 200, non-existent session → 404, ended session → 404 |
| `services/frontend/package.json` | Modify | Replace `livekit-client` with `three`, `@react-three/fiber`, `@react-three/drei` |
| `services/frontend/src/lib/api.ts` | Modify | Add `localAvatarConnect()`, remove `connectLiveAvatar()` and `stopLiveAvatarSession()`, remove `LiveAvatarConnect` interface |
| `services/frontend/src/components/student/AvatarSession.tsx` | Rewrite | Strip all LiveKit/WebSocket/keep-alive code. Keep mic recording, speakInSession, playAudioLocally, ChatBubble, history. Replace video element with `<LocalAvatarGLB />`. Simplify status to `loading | ready | error`. |
| `services/frontend/src/components/student/LocalAvatarGLB.tsx` | Create | R3F `Canvas` with dark background (`#111`), centered GLB model, procedural idle animation, speaking state prop |
| `services/frontend/public/avatars/` | Create | Directory + free CC0/CC-BY GLB model file (e.g. from Ready Player Me or Sketchfab) |
| `services/frontend/src/app/session/[id]/page.tsx` | Modify | Update dynamic import path if component file renamed (keep same ssr:false pattern) |

## Interfaces / Contracts

### Backend — new endpoint

```python
@router.post("/{session_id}/local-avatar-connect")
async def local_avatar_connect(session_id: UUID, db: AsyncSession = Depends(get_db)):
    # Returns: {status: "ok", session_id: str}
    # Raises 404 if session not found or ended
```

### Frontend — new function in api.ts

```typescript
export async function localAvatarConnect(sessionId: string): Promise<{ status: string; session_id: string }>
```

### Frontend — LocalAvatarGLB props

```typescript
interface LocalAvatarGLBProps {
  speaking: boolean  // true while TTS audio is playing
}
```

## Bundle Size Considerations

| Package | Estimated size (gzipped) | Impact |
|---------|-------------------------|--------|
| `three` | ~150 KB | Largest addition — dynamically imported |
| `@react-three/fiber` | ~15 KB | R3F reconciler |
| `@react-three/drei` | ~50 KB | Helpers (useGLTF, Environment, etc.) |
| **Total added** | **~215 KB** | Loaded lazily, not in critical path |
| `livekit-client` removal | ~80 KB removed | Net increase ~135 KB |

**Mitigations**:
- Dynamic import with `ssr: false` (existing pattern)
- Suspend rendering until `useGLTF` resolves → show loading skeleton
- GLB model should be Draco-compressed (typically 1-3 MB → 500 KB-1 MB gzipped)

## WebGL Error Fallback

Checked at `LocalAvatarSession` mount:

1. `typeof WebGLRenderingContext !== 'undefined'` — basic WebGL check
2. Try creating a temp canvas and calling `getContext('webgl')` or `getContext('webgl2')`
3. If either fails → set status to `webgl-unavailable`

**Fallback UX**: Show a message "Your browser doesn't support 3D rendering. Audio-only mode is available." with a button to dismiss the avatar area. The session continues with push-to-talk + chat bubble only — no visual avatar. This reuses the existing `audio-only` status path from the current component.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Backend unit | local-avatar-connect endpoint | Valid session → 200 + `{status: "ok"}`. Non-existent session → 404. Ended session → 404. |
| Frontend integration | LocalAvatarSession renders | Mount with mock sessionId, verify no LiveKit calls made |
| Frontend integration | Push-to-talk flow | Record → POST /speak → play audio → avatar shows speaking indicator |
| E2E | Full session | Open session, see avatar, hold mic, release, hear response, see chat bubble |

## Migration / Rollout

No migration required. The existing `liveavatar-connect`/`liveavatar-stop` endpoints remain active alongside `local-avatar-connect`. Frontend is switched at deploy time — old sessions using LiveAvatar are unaffected. The cleanup change (removing LiveAvatar code) is deferred to a follow-up.

## Open Questions

- [ ] Source of the GLB model file — needs a free CC0/CC-BY humanoid GLB. Options: Ready Player Me (avatar creator), Sketchfab (CC0 models), or Mixamo (requires FBX→GLB conversion). Recommended: start with a Ready Player Me GLB placeholder.
- [ ] Model file path: `public/avatars/avatar.glb` — confirm naming convention.
- [ ] Should we keep the `AvatarSession` filename or rename to `LocalAvatarSession`? Proposal says "rewrite" — keeping the same filename avoids changing the dynamic import path in `page.tsx`.
