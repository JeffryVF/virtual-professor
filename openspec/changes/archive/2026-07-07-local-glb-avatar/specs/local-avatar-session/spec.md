# local-avatar-session Specification

## Purpose

Client-side 3D GLB avatar rendered via Three.js with idle animation, dark scene, and audio playback. Replaces the external LiveAvatar/LiveKit pipeline with zero external API calls and no WebSocket keep-alive.

## Requirements

### Requirement: local-avatar-connect Endpoint

The backend MUST expose `POST /sessions/{session_id}/local-avatar-connect`.

- **Input**: `session_id` UUID path param (no body)
- **Success 200**: `{"status": "ok", "session_id": "<uuid>"}`
- **Error 404**: Session not found or `ended_at` is not null
- **Constraints**: No external API calls, no tokens, no WebSocket URLs, no DB mutations. Pure validation.

#### Scenario: Active session connects

- GIVEN a session with `ended_at IS NULL`
- WHEN POST to endpoint
- THEN status 200 AND body equals `{"status": "ok", "session_id": "<id>"}`

#### Scenario: Non-existent session

- GIVEN a session_id not in the database
- WHEN POST to endpoint
- THEN status 404

#### Scenario: Ended session

- GIVEN a session with `ended_at` set
- WHEN POST to endpoint
- THEN status 404

### Requirement: LocalAvatarGLB Component

The frontend MUST provide a `LocalAvatarGLB` component rendering a GLB model in React Three Fiber.

- **Source**: GLB from `/avatars/` public directory
- **Scene**: Dark background (`#111`), responsive to parent container
- **Animation**: Gentle Y-axis oscillation (bobbing/breathing) + subtle rotation
- **Loading**: Dynamic import (`next/dynamic`, `ssr: false`) — no WebGL on server
- **Error**: Renders empty fragment if WebGL unavailable or canvas fails

#### Scenario: WebGL renders avatar

- GIVEN WebGL support and GLB at `/avatars/`
- WHEN component mounts
- THEN dark canvas appears with animated 3D model

#### Scenario: WebGL unavailable

- GIVEN browser without WebGL or canvas creation fails
- WHEN component mounts
- THEN empty fragment rendered
- AND parent AvatarSession detects this → audio-only fallback

### Requirement: AvatarSession Local Mode

AvatarSession SHALL replace LiveKit video with LocalAvatarGLB.

- **Connection**: `localAvatarConnect()` → `POST .../local-avatar-connect` (removes `connectLiveAvatar`, `stopLiveAvatarSession`, LiveKit Room/WS)
- **Avatar**: `<LocalAvatarGLB />` replaces `<video ref={videoRef}>`
- **Audio**: TTS from `/speak` plays via `playAudioLocally()` (removes LiveKit track attachment and WebSocket audio streaming)
- **Push-to-talk**: Unchanged — mic → MediaRecorder → speakInSession
- **Conversation panel**: Unchanged — ChatBubble + history fetch
- **End session**: Unchanged — endSession() → onEnded()
- **Fallback**: If connection fails or LocalAvatarGLB errors, set status `audio-only`

#### Scenario: Normal local session

- GIVEN active session with WebGL support
- WHEN AvatarSession mounts
- THEN it connects via local-avatar-connect
- AND renders LocalAvatarGLB
- AND push-to-talk recording functions
- AND conversation panel shows history

#### Scenario: Avatar unavailable falls back to audio-only

- GIVEN WebGL unsupported or local-avatar-connect returns error
- WHEN avatar component fails
- THEN status becomes `audio-only`
- AND recording, /speak, and playAudioLocally() continue working

#### Scenario: Ended session from avatar page

- GIVEN user clicks end-session button
- WHEN handleEndSession runs
- THEN endSession() is called
- AND onEnded() fires (redirects to home)

## Data Contracts

### POST /sessions/{session_id}/local-avatar-connect

Request body: (none)
Success 200: `{"status": "ok", "session_id": "uuid"}`
Error 404: `{"detail": "Session not found or already ended"}`

### api.ts type changes

Add:
```typescript
interface LocalAvatarConnect { status: 'ok'; session_id: string }
export const localAvatarConnect = (sessionId: string) =>
  authRequest<LocalAvatarConnect>(`/sessions/${sessionId}/local-avatar-connect`, { method: 'POST' })
```

Remove: `LiveAvatarConnect` interface, `connectLiveAvatar()`, `stopLiveAvatarSession()`.
