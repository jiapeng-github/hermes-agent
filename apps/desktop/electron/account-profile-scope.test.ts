import { describe, expect, it } from 'vitest'

import { scopeApiRequestToAccountProfile, scopeApiResponseToAccountProfile } from './account-profile-scope'

const PROFILE = 'stocksense-u_123'

describe('StockSense account profile scoping', () => {
  it('clamps query, body, and route profile values to the signed-in account', () => {
    const request = scopeApiRequestToAccountProfile(
      {
        body: { profile: 'default', title: '分析会话' },
        method: 'POST',
        path: '/api/sessions?profile=default'
      },
      PROFILE
    )

    expect(request).toEqual({
      body: { profile: PROFILE, title: '分析会话' },
      method: 'POST',
      path: `/api/sessions?profile=${PROFILE}`,
      profile: PROFILE
    })
  })

  it('scopes sidebar parameters and rejects profile mutation or cross-account access', () => {
    const request = scopeApiRequestToAccountProfile(
      { method: 'GET', path: '/api/profiles/sessions/sidebar?recents_profile=default' },
      PROFILE
    )

    expect(request.path).toBe(`/api/profiles/sessions/sidebar?recents_profile=${PROFILE}&profile=${PROFILE}`)
    expect(() =>
      scopeApiRequestToAccountProfile({ method: 'PATCH', path: `/api/profiles/${PROFILE}` }, PROFILE)
    ).toThrow('不能在桌面端创建、切换、重命名或删除')
    expect(() =>
      scopeApiRequestToAccountProfile({ method: 'GET', path: '/api/profiles/stocksense-u_999/config' }, PROFILE)
    ).toThrow('不能访问其他用户的 Profile')
  })

  it('filters profile and sidebar responses to the signed-in account', () => {
    const profiles = scopeApiResponseToAccountProfile(
      { path: '/api/profiles' },
      { profiles: [{ name: PROFILE }, { name: 'default' }] },
      PROFILE
    )

    const active = scopeApiResponseToAccountProfile(
      { path: '/api/profiles/active' },
      { active: 'default', current: 'default' },
      PROFILE
    )

    const sidebar = scopeApiResponseToAccountProfile(
      { path: '/api/profiles/sessions/sidebar' },
      {
        cron: null,
        messaging: { sessions: [], total: 0 },
        recents: {
          profile_totals: { default: 1, [PROFILE]: 2 },
          sessions: [
            { id: 'mine', profile: PROFILE },
            { id: 'other', profile: 'default' }
          ],
          total: 2
        }
      },
      PROFILE
    )

    expect(profiles.profiles).toEqual([{ name: PROFILE }])
    expect(active).toEqual({ active: PROFILE, current: PROFILE })
    expect(sidebar.recents).toEqual({
      profile_totals: { [PROFILE]: 2 },
      sessions: [{ id: 'mine', profile: PROFILE }],
      total: 1
    })
  })
})
