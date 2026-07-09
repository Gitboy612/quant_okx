import { useEffect, useRef } from 'react'
import bgVideo from '../assets/bg.mp4'
import { usePerformanceMode } from '../hooks/usePerformanceMode'

export default function VideoBackground() {
  const { performanceMode } = usePerformanceMode()
  const videoRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    if (performanceMode) {
      video.pause()
    } else {
      video.play().catch(() => {})
    }
  }, [performanceMode])

  return (
    <div className="fixed inset-0 z-[-1] overflow-hidden">
      <video
        ref={videoRef}
        src={bgVideo}
        autoPlay
        loop
        muted
        playsInline
        className="w-full h-full object-cover"
        style={{ opacity: performanceMode ? 0 : 0.35, transition: 'opacity 0.5s ease' }}
      />
      <div className="absolute inset-0 bg-[#050711]/50" />
    </div>
  )
}
