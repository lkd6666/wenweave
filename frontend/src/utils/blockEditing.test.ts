import { describe, expect, it } from 'vitest'
import { nextBlockSelection } from './blockEditing'

describe('nextBlockSelection', () => {
  it('replaces a previous selection for a normal block tap', () => {
    expect(nextBlockSelection(['first', 'second'], 'third', 'replace')).toEqual(['third'])
  })

  it('adds and removes blocks for mobile multi-select', () => {
    expect(nextBlockSelection(['first'], 'second', 'toggle')).toEqual(['first', 'second'])
    expect(nextBlockSelection(['first', 'second'], 'first', 'toggle')).toEqual(['second'])
  })

  it('clears stale selection on an explicit finish, mode switch, or external refresh', () => {
    expect(nextBlockSelection(['first', 'second'], null, 'clear')).toEqual([])
    expect(nextBlockSelection(['first'], null, 'replace')).toEqual([])
  })
})
