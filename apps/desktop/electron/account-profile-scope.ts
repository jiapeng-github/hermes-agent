function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function requestPathOf(request: unknown): string {
  return isRecord(request) ? String(request.path || '').split('?')[0] : ''
}

export function scopeApiRequestToAccountProfile<T>(input: T, allowedProfile: string | null): T {
  if (!allowedProfile || !isRecord(input)) {
    return input
  }

  const request: Record<string, unknown> = { ...input }
  const url = new URL(String(request.path || '/'), 'http://stocksense.desktop')
  const requestPath = url.pathname
  const method = String(request.method || 'GET').toUpperCase()

  if (
    (requestPath === '/api/profiles' && method !== 'GET') ||
    (requestPath === '/api/profiles/active' && method !== 'GET') ||
    (/^\/api\/profiles\/[^/]+$/.test(requestPath) && ['DELETE', 'PATCH', 'POST'].includes(method))
  ) {
    throw new Error('账号模式下由 Finance Mate 管理 Profile，不能在桌面端创建、切换、重命名或删除。')
  }

  const profilePathMatch = requestPath.match(/^\/api\/profiles\/([^/]+)(?:\/|$)/)
  const profilePathSegment = profilePathMatch ? decodeURIComponent(profilePathMatch[1]) : null

  if (
    profilePathSegment &&
    !['active', 'sessions'].includes(profilePathSegment) &&
    profilePathSegment !== allowedProfile
  ) {
    throw new Error('当前账号不能访问其他用户的 Profile。')
  }

  if (
    url.searchParams.has('profile') ||
    requestPath === '/api/profiles/sessions' ||
    requestPath === '/api/profiles/sessions/sidebar'
  ) {
    url.searchParams.set('profile', allowedProfile)
    request.path = `${url.pathname}${url.search}`
  }

  if (requestPath === '/api/profiles/sessions/sidebar') {
    url.searchParams.set('recents_profile', allowedProfile)
    request.path = `${url.pathname}${url.search}`
  }

  if (isRecord(request.body) && 'profile' in request.body) {
    request.body = { ...request.body, profile: allowedProfile }
  }

  request.profile = allowedProfile

  return request as T
}

export function scopeApiResponseToAccountProfile<T>(request: unknown, response: T, allowedProfile: string | null): T {
  if (!allowedProfile || !isRecord(response)) {
    return response
  }

  const requestPath = requestPathOf(request)

  if (requestPath === '/api/profiles' && Array.isArray(response.profiles)) {
    return {
      ...response,
      profiles: response.profiles.filter(profile => isRecord(profile) && String(profile.name || '') === allowedProfile)
    } as T
  }

  if (requestPath === '/api/profiles/active') {
    return { ...response, active: allowedProfile, current: allowedProfile } as T
  }

  if (requestPath === '/api/profiles/sessions/sidebar') {
    const scopeSection = (value: unknown): unknown => {
      if (!isRecord(value)) {
        return value
      }

      const sessions = Array.isArray(value.sessions)
        ? value.sessions.filter(row => !isRecord(row) || !row.profile || String(row.profile) === allowedProfile)
        : []

      return {
        ...value,
        ...(isRecord(value.profile_totals)
          ? {
              profile_totals: {
                [allowedProfile]: Number(value.profile_totals[allowedProfile]) || sessions.length
              }
            }
          : {}),
        sessions,
        ...(typeof value.total === 'number' ? { total: sessions.length } : {})
      }
    }

    return {
      ...response,
      cron: scopeSection(response.cron),
      messaging: scopeSection(response.messaging),
      recents: scopeSection(response.recents)
    } as T
  }

  return response
}
