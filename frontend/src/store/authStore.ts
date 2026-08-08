import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '../types'

interface AuthState {
  token: string | null
  user: User | null
  setAuth: (token: string, user: User) => void
  setUser: (user: User) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setAuth: (token, user) => set({ token, user }),
      setUser: (user) => set({ user }),
      logout: () => {
        set({ token: null, user: null })
        // The refresh credential is HttpOnly, so the server clears it.
        void fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(() => undefined)
      },
    }),
    { name: 'auth-storage' },
  ),
)
