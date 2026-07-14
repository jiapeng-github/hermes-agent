import { describe, expect, it } from 'vitest'

import { skillOptionsFromCatalog } from './skill-picker'

describe('skillOptionsFromCatalog', () => {
  it('keeps catalog skills while excluding built-ins and user quick commands', () => {
    expect(
      skillOptionsFromCatalog({
        categories: [
          { name: 'Session', pairs: [['/new', 'Start a new session']] },
          { name: 'User commands', pairs: [['/morning-brief', 'Run morning briefing']] }
        ],
        pairs: [
          ['/new', 'Start a new session'],
          ['/morning-brief', 'Run morning briefing'],
          ['/dashi-ppt', 'Create presentation decks'],
          ['/mx-data', 'Query market data'],
          ['/DASHI-PPT', 'Duplicate entry']
        ]
      })
    ).toEqual([
      { command: '/dashi-ppt', description: 'Create presentation decks' },
      { command: '/mx-data', description: 'Query market data' }
    ])
  })
})
