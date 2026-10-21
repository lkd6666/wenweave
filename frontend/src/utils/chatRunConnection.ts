export type ChatRunConnectionPhase = 'starting' | 'streaming'

export interface ChatRunConnection {
  controller: AbortController
  phase: ChatRunConnectionPhase
  detached: boolean
  stopRequested: boolean
}

export function createChatRunConnection(): ChatRunConnection {
  return {
    controller: new AbortController(),
    phase: 'starting',
    detached: false,
    stopRequested: false,
  }
}

export function ownsChatRunConnection(
  connection: ChatRunConnection,
  currentConnection: ChatRunConnection | null,
  documentId: number,
  attachedDocumentId: number | null,
): boolean {
  return currentConnection === connection && !connection.detached && documentId === attachedDocumentId
}

/** Release page-owned resources without cancelling a run accepted by the server. */
export function detachChatRunConnection(connection: ChatRunConnection | null): void {
  if (!connection) return
  connection.detached = true
  if (connection.phase === 'streaming') connection.controller.abort()
}

/** Retire a superseded local subscription. This never represents a user cancellation. */
export function retireChatRunConnection(connection: ChatRunConnection | null): void {
  if (!connection) return
  connection.detached = true
  connection.controller.abort()
}

export function requestChatRunStop(connection: ChatRunConnection | null): void {
  if (!connection) return
  connection.stopRequested = true
  // Before acceptance there is no run id to cancel. Keep the POST alive so
  // the caller can cancel the exact durable run as soon as the server replies.
  if (connection.phase === 'streaming') connection.controller.abort()
}
