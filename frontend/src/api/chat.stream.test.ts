import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { streamChatRunEvents } from './chat'

beforeEach(() => {
  vi.stubGlobal('window', { setTimeout, clearTimeout })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function openEventStream() {
  const cancel = vi.fn()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('id: 1\nevent: text_delta\ndata: {"text":"hello"}\n\n'))
    },
    cancel,
  })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, {
    headers: { 'Content-Type': 'text/event-stream' },
  })))
  return { body, cancel }
}

describe('chat stream cleanup', () => {
  it('cancels the response body when the consumer stops after a yielded event', async () => {
    const { body, cancel } = openEventStream()

    for await (const event of streamChatRunEvents(12, 'run-1', 0)) {
      expect(event.event).toBe('text_delta')
      break
    }

    expect(cancel).toHaveBeenCalledOnce()
    expect(body.locked).toBe(false)
  })

  it('cancels the established response when aborted while waiting for the next event', async () => {
    const { body, cancel } = openEventStream()
    const controller = new AbortController()
    const events = streamChatRunEvents(12, 'run-1', 0, controller.signal)
    await events.next()

    const pendingEvent = events.next()
    controller.abort()

    await expect(pendingEvent).rejects.toMatchObject({ name: 'AbortError' })
    expect(cancel).toHaveBeenCalledOnce()
    expect(body.locked).toBe(false)
  })
})
