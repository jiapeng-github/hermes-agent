window.HermesApp = (() => {
  let bootstrapPromise

  async function bootstrap() {
    bootstrapPromise ??= request('/__hermes/bootstrap')
    return bootstrapPromise
  }

  async function runTracked(actionId, input) {
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
      if (snapshot.status === 'completed') return { run_id: accepted.run_id, result: snapshot.result }
      if (snapshot.status === 'failed') throw new Error(snapshot.error?.message || '应用操作失败')
      if (snapshot.status === 'cancelled') throw new Error('应用操作已取消')
      await new Promise(resolve => window.setTimeout(resolve, 120))
    }
  }

  async function run(actionId, input) {
    return (await runTracked(actionId, input)).result
  }

  async function publishCurrentPage(runId, { title, summary, snapshot = {} }) {
    const config = await bootstrap()
    const html = await snapshotDocument()
    return request(`/api/runs/${encodeURIComponent(runId)}/artifacts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Hermes-App-CSRF': config.csrf_token },
      body: JSON.stringify({ title, summary, html, snapshot })
    })
  }

  async function snapshotDocument() {
    await new Promise(resolve => window.requestAnimationFrame(() => window.requestAnimationFrame(resolve)))
    const clone = document.documentElement.cloneNode(true)
    const sourceCanvases = [...document.querySelectorAll('canvas')]
    const clonedCanvases = [...clone.querySelectorAll('canvas')]
    sourceCanvases.forEach((canvas, index) => {
      try {
        const image = document.createElement('img')
        image.src = canvas.toDataURL('image/png')
        image.alt = canvas.getAttribute('aria-label') || '图表快照'
        image.style.cssText = canvas.style.cssText
        image.width = canvas.width
        image.height = canvas.height
        clonedCanvases[index]?.replaceWith(image)
      } catch {
        clonedCanvases[index]?.remove()
      }
    })
    clone.querySelectorAll('script,iframe,frame,object,embed,base').forEach(node => node.remove())
    clone.querySelectorAll('meta[http-equiv]').forEach(node => {
      if ((node.getAttribute('http-equiv') || '').toLowerCase() === 'refresh') node.remove()
    })
    clone.querySelectorAll('form').forEach(node => node.removeAttribute('action'))
    clone.querySelectorAll('button,input,select,textarea').forEach(node => {
      node.setAttribute('disabled', '')
      node.removeAttribute('name')
    })
    clone.querySelectorAll('*').forEach(node => {
      for (const attribute of [...node.attributes]) {
        const name = attribute.name.toLowerCase()
        const value = attribute.value.trim().toLowerCase()
        if (name.startsWith('on') || value.startsWith('javascript:')) node.removeAttribute(attribute.name)
      }
    })
    return `<!doctype html>\n${clone.outerHTML}`
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

  return { bootstrap, publishCurrentPage, run, runTracked, storageGet, storageSet }
})()
