'use client'

import { useMemo, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { useGLTF, OrbitControls } from '@react-three/drei'
import type { Group } from 'three'

interface LocalAvatarGLBProps {
  speaking?: boolean
  onWebGLUnavailable?: () => void
}

function GLBModel({ speaking }: { speaking: boolean }) {
  const { scene } = useGLTF('/avatars/avatar.glb')
  const groupRef = useRef<Group>(null)

  useFrame((state) => {
    if (!groupRef.current) return

    // Gentle Y-axis bob (breathing effect)
    groupRef.current.position.y = Math.sin(state.clock.elapsedTime * 0.8) * 0.05

    // Subtle rotation
    groupRef.current.rotation.y += 0.003

    // Speaking pulse — faster and more pronounced when speaking
    if (speaking) {
      const pulse = 1 + Math.sin(state.clock.elapsedTime * 4) * 0.03
      groupRef.current.scale.setScalar(pulse)
    }
  })

  return <primitive ref={groupRef} object={scene} />
}

export default function LocalAvatarGLB({ speaking = false }: LocalAvatarGLBProps) {
  const webglOk = useMemo(() => {
    try {
      const canvas = document.createElement('canvas')
      return !!(canvas.getContext('webgl') || canvas.getContext('webgl2'))
    } catch {
      return false
    }
  }, [])

  if (!webglOk) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-[#1a1a2e] text-xs text-muted-foreground">
        3D rendering unavailable — audio-only mode active
      </div>
    )
  }

  return (
    <div className="h-full w-full">
      <Canvas
        camera={{ position: [0, 0, 2.5], fov: 50 }}
        style={{ background: '#1a1a2e' }}
      >
        <ambientLight intensity={0.8} />
        <directionalLight position={[5, 5, 5]} intensity={1} />
        <GLBModel speaking={speaking} />
        <OrbitControls />
      </Canvas>
    </div>
  )
}
