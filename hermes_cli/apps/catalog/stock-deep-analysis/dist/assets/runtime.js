window.HermesApp = (() => {
  let bootstrapPromise

  async function bootstrap() {
    bootstrapPromise ??= request('/__hermes/bootstrap')
    return bootstrapPromise
  }

  async function run(actionId, input) {
    const config = await bootstrap()
    const accepted = await request(`/api/actions/${encodeURIComponent(actionId)}/runs`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': crypto.randomUUID(),
        'X-Hermes-App-CSRF': config.csrf_token
      },
      body: JSON.stringify({ input })
    })

    for (;;) {
      const snapshot = await request(`/api/runs/${encodeURIComponent(accepted.run_id)}`)
      if (snapshot.status === 'completed') return snapshot.result
      if (snapshot.status === 'failed') throw new Error(snapshot.error?.message || '应用操作失败')
      if (snapshot.status === 'cancelled') throw new Error('应用操作已取消')
      await new Promise(resolve => window.setTimeout(resolve, 120))
    }
  }

  async function storageGet(key, fallback = null) {
    try {
      return (await request(`/api/storage/${encodeURIComponent(key)}`)).value
    } catch (error) {
      if (error.status === 404) return fallback
      throw error
    }
  }

  async function storageSet(key, value) {
    const config = await bootstrap()
    return request(`/api/storage/${encodeURIComponent(key)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-Hermes-App-CSRF': config.csrf_token },
      body: JSON.stringify({ value })
    })
  }

  async function request(path, options) {
    const response = await fetch(path, options)
    let body
    try {
      body = await response.json()
    } catch {
      body = null
    }
    if (!response.ok) {
      const error = new Error(body?.error?.message || `请求失败 (${response.status})`)
      error.code = body?.error?.code
      error.status = response.status
      throw error
    }
    return body
  }

  return { bootstrap, run, storageGet, storageSet }
})()
