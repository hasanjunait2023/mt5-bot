import { useEffect, useState } from 'react'

// Favourite (pinned) nav routes — user-customisable so the pages they care
// about float to the top of the sidebar and become the mobile bottom tabs.
// Backed by localStorage and shared across every component in the tab via a
// tiny pub/sub store (the native `storage` event only fires cross-tab).

const KEY = 'mt5.nav.favorites'

function load(): string[] {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? arr.filter(x => typeof x === 'string') : []
  } catch {
    return []
  }
}

let store: string[] = load()
const listeners = new Set<(v: string[]) => void>()

function commit(next: string[]) {
  store = next
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    /* ignore quota / disabled storage */
  }
  listeners.forEach(fn => fn(store))
}

export function useFavorites() {
  const [favorites, setFavorites] = useState<string[]>(store)

  useEffect(() => {
    const fn = (v: string[]) => setFavorites(v)
    listeners.add(fn)
    // adopt any value written by another hook instance before mount
    setFavorites(store)
    return () => {
      listeners.delete(fn)
    }
  }, [])

  const isFavorite = (to: string) => favorites.includes(to)

  const toggle = (to: string) =>
    commit(favorites.includes(to) ? favorites.filter(t => t !== to) : [...favorites, to])

  /** Reorder within the favourites list (drag handle). */
  const move = (from: number, to: number) => {
    if (from === to || from < 0 || to < 0 || from >= store.length || to >= store.length) return
    const next = [...store]
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    commit(next)
  }

  return { favorites, isFavorite, toggle, move }
}
