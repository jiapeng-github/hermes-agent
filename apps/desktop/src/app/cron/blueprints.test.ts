import { describe, expect, it } from 'vitest'

import type { AutomationBlueprint } from '@/hermes'
import { zh } from '@/i18n/zh'

import { initialBlueprintValues } from './blueprints'

function blueprint(fields: AutomationBlueprint['fields']): AutomationBlueprint {
  return {
    key: 'test',
    title: 'Test',
    description: '',
    category: 'general',
    tags: [],
    command: '',
    appUrl: '',
    fields
  }
}

describe('initialBlueprintValues', () => {
  it('seeds each field from its default', () => {
    const values = initialBlueprintValues(
      blueprint([
        { name: 'time', type: 'time', label: 'Time', default: '08:00', options: [], optional: false, help: '' },
        {
          name: 'topic',
          type: 'enum',
          label: 'Topic',
          default: 'news',
          options: ['news', 'sports'],
          optional: false,
          help: ''
        }
      ])
    )

    expect(values).toEqual({ time: '08:00', topic: 'news' })
  })

  it('falls back to an empty string when a field has no default', () => {
    const values = initialBlueprintValues(
      blueprint([{ name: 'topic', type: 'text', label: 'Topic', default: null, options: [], optional: true, help: '' }])
    )

    expect(values).toEqual({ topic: '' })
  })

  it('returns an empty object for a blueprint with no fields', () => {
    expect(initialBlueprintValues(blueprint([]))).toEqual({})
  })

  it("seeds the deliver slot to 'local' when its default is the dashboard-only 'origin'", () => {
    const values = initialBlueprintValues(
      blueprint([
        {
          name: 'deliver',
          type: 'enum',
          label: 'Deliver',
          default: 'origin',
          options: ['origin', 'local', 'telegram'],
          optional: false,
          help: ''
        }
      ])
    )

    expect(values).toEqual({ deliver: 'local' })
  })

  it("seeds the deliver slot to 'local' when it has no default", () => {
    const values = initialBlueprintValues(
      blueprint([
        {
          name: 'deliver',
          type: 'enum',
          label: 'Deliver',
          default: null,
          options: ['origin', 'local'],
          optional: false,
          help: ''
        }
      ])
    )

    expect(values).toEqual({ deliver: 'local' })
  })

  it('leaves a non-origin deliver default untouched', () => {
    const values = initialBlueprintValues(
      blueprint([
        {
          name: 'deliver',
          type: 'enum',
          label: 'Deliver',
          default: 'telegram',
          options: ['origin', 'local', 'telegram'],
          optional: false,
          help: ''
        }
      ])
    )

    expect(values).toEqual({ deliver: 'telegram' })
  })

  it('localizes text defaults without changing enum values submitted to the backend', () => {
    const values = initialBlueprintValues(
      blueprint([
        {
          name: 'topic',
          type: 'text',
          label: 'Topic',
          default: 'AI and technology',
          options: [],
          optional: false,
          help: ''
        },
        {
          name: 'recurrence',
          type: 'weekdays',
          label: 'Repeat on',
          default: 'weekdays',
          options: ['everyday', 'weekdays', 'weekends'],
          optional: false,
          help: ''
        }
      ]),
      (field, value) => (field === 'topic' ? '人工智能与科技' : value)
    )

    expect(values).toEqual({ recurrence: 'weekdays', topic: '人工智能与科技' })
  })
})

describe('Chinese automation blueprint copy', () => {
  it('translates catalog titles by key and legacy job titles by their English source title', () => {
    expect(zh.cron.blueprints.titleFor('morning-brief', 'Morning briefing')).toBe('晨间简报')
    expect(zh.cron.blueprints.titleFor('', 'Morning briefing')).toBe('晨间简报')
    expect(zh.cron.blueprints.titleFor('unknown', 'Custom title')).toBe('Custom title')
  })

  it('translates descriptions, field labels, help, options, and text defaults', () => {
    expect(zh.cron.blueprints.descriptionFor('price-watch', 'fallback')).toContain('价格')
    expect(zh.cron.blueprints.fieldLabelFor('price-watch', 'item', 'fallback')).toBe('具体监控什么？')
    expect(zh.cron.blueprints.fieldHelpFor('price-watch', 'item', 'fallback')).toContain('网址')
    expect(zh.cron.blueprints.optionLabelFor('meal-plan', 'diet', 'vegetarian')).toBe('素食')
    expect(zh.cron.blueprints.textDefaultFor('news-digest', 'topic', 'AI and technology')).toBe('人工智能与科技')
  })
})
