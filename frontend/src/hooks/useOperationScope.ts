import { useCallback, useLayoutEffect, useMemo, useRef } from 'react'

/** Async callbacks belong to one mounted document/modal lifetime. */
export function useOperationScope(key: string | number) {
  const scope = useMemo(() => ({ key, active: true }), [key])
  const current = useRef(scope)
  current.current = scope
  useLayoutEffect(() => {
    scope.active = true
    return () => { scope.active = false }
  }, [scope])
  return useCallback(() => scope.active && current.current === scope, [scope])
}
