import { useState, useEffect, useRef } from 'react'
import type { LogEntry } from '../types/trading'
import { useWebSocket } from './useWebSocket'

const MAX_LINES = 1000

export function useLogs() {
  const [lines, setLines] = useState<LogEntry[]>([])
  const linesRef = useRef<LogEntry[]>([])

  useEffect(() => {
    fetch('/api/logs?n=200')
      .then(r => r.json())
      .then(data => {
        linesRef.current = data.lines ?? []
        setLines([...linesRef.current])
      })
      .catch(() => {})
  }, [])

  useWebSocket('log', (data) => {
    const entry = data as LogEntry
    linesRef.current = [...linesRef.current.slice(-(MAX_LINES - 1)), entry]
    setLines([...linesRef.current])
  })

  return lines
}
