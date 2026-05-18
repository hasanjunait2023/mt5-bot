import { useEffect, useRef, useCallback } from 'react'
import type { WSMessage } from '../types/trading'

type Listener = (data: unknown) => void
type ConnectionState = 'connecting' | 'open' | 'closed'

const WS_URL = '/ws'
const MAX_RETRY_MS = 30_000

let socket: WebSocket | null = null
let retryTimeout: ReturnType<typeof setTimeout> | null = null
let retryDelay = 1000
const listeners = new Map<string, Set<Listener>>()
const stateListeners = new Set<(s: ConnectionState) => void>()
let currentState: ConnectionState = 'closed'

function setConnState(s: ConnectionState) {
  currentState = s
  stateListeners.forEach(cb => cb(s))
}

function connect() {
  if (socket && socket.readyState <= 1) return
  setConnState('connecting')

  socket = new WebSocket(WS_URL)

  socket.onopen = () => {
    retryDelay = 1000
    setConnState('open')
  }

  socket.onmessage = (ev) => {
    try {
      const msg: WSMessage = JSON.parse(ev.data)
      const cbs = listeners.get(msg.type)
      if (cbs) cbs.forEach(cb => cb(msg.data))
    } catch { /* ignore parse errors */ }
  }

  socket.onclose = () => {
    setConnState('closed')
    retryTimeout = setTimeout(() => {
      retryDelay = Math.min(retryDelay * 2, MAX_RETRY_MS)
      connect()
    }, retryDelay)
  }

  socket.onerror = () => socket?.close()
}

connect()

export function useWebSocket(
  type: string,
  callback: Listener,
) {
  const cbRef = useRef(callback)
  cbRef.current = callback

  useEffect(() => {
    const stable: Listener = (data) => cbRef.current(data)
    if (!listeners.has(type)) listeners.set(type, new Set())
    listeners.get(type)!.add(stable)
    return () => { listeners.get(type)?.delete(stable) }
  }, [type])
}

export function useConnectionState(cb: (s: ConnectionState) => void) {
  const cbRef = useRef(cb)
  cbRef.current = cb
  useEffect(() => {
    const stable = (s: ConnectionState) => cbRef.current(s)
    stateListeners.add(stable)
    stable(currentState)
    return () => { stateListeners.delete(stable) }
  }, [])
}

export function sendWS(msg: object) {
  if (socket?.readyState === 1) {
    socket.send(JSON.stringify(msg))
  }
}
