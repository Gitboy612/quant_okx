import { useEffect, useRef, useState } from 'react'
import { useSpring, animated } from 'framer-motion'

export function useCountUp(end: number, duration: number = 1.5) {
  const spring = useSpring(0, { stiffness: 80, damping: 20, duration: duration * 1000 })
  const [display, setDisplay] = useState(0)

  useEffect(() => {
    spring.set(end)
  }, [end, spring])

  useEffect(() => {
    const unsub = spring.on('change', (latest) => {
      setDisplay(Math.round(latest * 100) / 100)
    })
    return unsub
  }, [spring])

  return display
}
