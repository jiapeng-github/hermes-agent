function normalizeAppLaunchUrl(rawUrl) {
  let parsed
  try {
    parsed = new URL(String(rawUrl || '').trim())
  } catch {
    throw new Error('Invalid application launch URL.')
  }
  if (
    parsed.protocol !== 'http:' ||
    parsed.hostname !== '127.0.0.1' ||
    !parsed.port ||
    parsed.username ||
    parsed.password ||
    !parsed.pathname.startsWith('/launch/')
  ) {
    throw new Error('Application launch URL must use a dedicated local AppHost.')
  }
  return parsed.toString()
}

async function openAppLaunchUrl(rawUrl, openExternal) {
  const url = normalizeAppLaunchUrl(rawUrl)
  await openExternal(url)
  return true
}

module.exports = { normalizeAppLaunchUrl, openAppLaunchUrl }
