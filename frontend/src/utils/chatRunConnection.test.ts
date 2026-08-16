import { describe, expect, it } from 'vitest'
import {
  createChatRunConnection,
  detachChatRunConnection,
  requestChatRunStop,
  retireChatRunConnection,
} from './chatRunConnection'

describe('chat run connection lifecycle', () => {
  it('keeps an in-flight start request alive when the editor page detaches', () => {
    const connection = createChatRunConnection()

    detachChatRunConnection(connection)

    expect(connection.detached).toBe(true)
    expect(connection.stopRequested).toBe(false)
    expect(connection.controller.signal.aborted).toBe(false)
  })

  it('disconnects an established event stream without requesting run cancellation', () => {
    const connection = createChatRunConnection()
    connection.phase = 'streaming'

    detachChatRunConnection(connection)

    expect(connection.detached).toBe(true)
    expect(connection.stopRequested).toBe(false)
    expect(connection.controller.signal.aborted).toBe(true)
  })

  it('keeps the start request alive until an explicit stop can target its run id', () => {
    const connection = createChatRunConnection()

    requestChatRunStop(connection)

    expect(connection.stopRequested).toBe(true)
    expect(connection.controller.signal.aborted).toBe(false)
  })

  it('aborts the local stream when stopping an accepted run', () => {
    const connection = createChatRunConnection()
    connection.phase = 'streaming'

    requestChatRunStop(connection)

    expect(connection.stopRequested).toBe(true)
    expect(connection.controller.signal.aborted).toBe(true)
  })

  it('marks a superseded connection as detached before aborting it', () => {
    const connection = createChatRunConnection()

    retireChatRunConnection(connection)

    expect(connection.detached).toBe(true)
    expect(connection.stopRequested).toBe(false)
    expect(connection.controller.signal.aborted).toBe(true)
  })
})
