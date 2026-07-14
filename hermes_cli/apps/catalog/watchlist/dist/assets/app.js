(() => {
  const state = {
    snapshot: null,
    sort: { key: 'change', direction: 'desc' },
    selected: null,
    detail: null,
    analysis: null,
    loading: false,
    timer: null
  }

  const elements = {
    addForm: document.querySelector('#add-form'),
    autoRefresh: document.querySelector('#auto-refresh'),
    detailClose: document.querySelector('#detail-close'),
    detailCode: document.querySelector('#detail-code'),
    detailContent: document.querySelector('#detail-content'),
    detailDialog: document.querySelector('#detail-dialog'),
    detailTitle: document.querySelector('#detail-title'),
    empty: document.querySelector('#empty'),
    gapList: document.querySelector('#gap-list'),
    headline: document.querySelector('#headline'),
    indices: document.querySelector('#indices'),
    marketStatus: document.querySelector('#market-status'),
    notice: document.querySelector('#notice'),
    query: document.querySelector('#stock-query'),
    refresh: document.querySelector('#refresh-button'),
    rows: document.querySelector('#stock-rows'),
    sectors: document.querySelector('#sector-bars'),
    summary: document.querySelector('#summary-grid')
  }

  document.addEventListener('DOMContentLoaded', initialize)

  async function initialize() {
    bindEvents()
    try {
      const [bootstrap, preferences] = await Promise.all([
        window.HermesApp.bootstrap(),
        window.HermesApp.storageGet('watchlist.preferences', null)
      ])
      document.documentElement.dataset.theme = bootstrap.theme
      if (preferences?.sort) state.sort = preferences.sort
      if (typeof preferences?.autoRefresh === 'boolean') elements.autoRefresh.checked = preferences.autoRefresh
      await loadSnapshot(true)
      scheduleRefresh()
    } catch (error) {
      showNotice(error.message, true)
      elements.marketStatus.textContent = '行情服务暂不可用'
    }
  }

  function bindEvents() {
    elements.refresh.addEventListener('click', refreshSnapshot)
    elements.addForm.addEventListener('submit', addStock)
    elements.autoRefresh.addEventListener('change', () => {
      persistPreferences()
      scheduleRefresh()
    })
    elements.detailClose.addEventListener('click', () => elements.detailDialog.close())
    elements.detailDialog.addEventListener('click', event => {
      if (event.target === elements.detailDialog) elements.detailDialog.close()
    })
    document.querySelectorAll('th[data-sort]').forEach(header => {
      header.addEventListener('click', () => changeSort(header.dataset.sort))
    })
    document.querySelectorAll('.dialog-tabs button').forEach(tab => {
      tab.addEventListener('click', () => selectDetailTab(tab.dataset.tab))
    })
  }

  async function loadSnapshot(autoRefresh = false) {
    if (state.loading) return
    state.loading = true
    elements.refresh.disabled = true
    elements.marketStatus.textContent = '正在读取最新行情'
    try {
      state.snapshot = await window.HermesApp.run('snapshot', { auto_refresh: autoRefresh })
      render()
      const asOf = state.snapshot.as_of ? `数据 ${state.snapshot.as_of}` : '等待交易数据'
      elements.marketStatus.textContent = `${asOf} · ${statusLabel(state.snapshot)}`
    } catch (error) {
      showNotice(error.message, true)
      elements.marketStatus.textContent = '行情读取失败，保留上次结果'
    } finally {
      state.loading = false
      elements.refresh.disabled = false
    }
  }

  async function refreshSnapshot() {
    if (state.loading) return
    state.loading = true
    elements.refresh.disabled = true
    elements.marketStatus.textContent = '妙想数据刷新中'
    try {
      await window.HermesApp.run('refresh', {})
      await wait(900)
    } catch (error) {
      showNotice(error.message, true)
    } finally {
      state.loading = false
      elements.refresh.disabled = false
    }
    await loadSnapshot(false)
  }

  async function addStock(event) {
    event.preventDefault()
    const query = elements.query.value.trim()
    if (!query) return
    elements.query.disabled = true
    try {
      const result = await window.HermesApp.run('add_stock', { query })
      elements.query.value = ''
      showNotice(result.added === false ? '该股票已在自选股中' : `已添加 ${result.item?.name || query}`)
      await wait(300)
      await loadSnapshot(false)
    } catch (error) {
      showNotice(error.message, true)
    } finally {
      elements.query.disabled = false
      elements.query.focus()
    }
  }

  async function removeStock(stock) {
    if (!window.confirm(`从自选股中删除 ${stock.name}（${stock.code}）？`)) return
    try {
      await window.HermesApp.run('remove_stock', { code: stock.code })
      showNotice(`已删除 ${stock.name}`)
      await loadSnapshot(false)
    } catch (error) {
      showNotice(error.message, true)
    }
  }

  function render() {
    renderIndices()
    renderSummary()
    renderRows()
    renderSectors()
    renderInsight()
  }

  function renderIndices() {
    clear(elements.indices)
    for (const index of (state.snapshot?.indices || []).slice(0, 5)) {
      const card = node('article', 'index-card')
      const top = node('div', 'index-top')
      top.append(text('span', index.name), text('span', index.turnover || ''))
      const value = text('div', index.value == null ? '--' : number(index.value, 2), 'index-value')
      const bottom = node('div', 'index-bottom')
      const change = text('strong', percent(index.change_percent), tone(index.change_percent))
      bottom.append(change, sparkline(index.sparkline || [], index.change_percent))
      card.append(top, value, bottom)
      elements.indices.append(card)
    }
  }

  function renderSummary() {
    clear(elements.summary)
    const summary = state.snapshot?.summary || {}
    const cards = [
      ['自选股总数', `${summary.total || 0} 只`, `${summary.rising || 0} 涨 · ${summary.falling || 0} 跌`, ''],
      ['今日上涨家数', `${summary.rising || 0} / ${summary.priced || 0}`, `${summary.flat || 0} 只平盘`, tone((summary.rising || 0) - (summary.falling || 0))],
      ['主力净流入合计', money(summary.main_net_flow_yi), '当前自选股样本合计', tone(summary.main_net_flow_yi)],
      ['最强板块', summary.strongest_sector?.name || '--', percent(summary.strongest_sector?.avg_change_percent), tone(summary.strongest_sector?.avg_change_percent)]
    ]
    for (const [label, value, caption, className] of cards) {
      const card = node('article', 'summary-card')
      card.append(text('span', label), text('strong', value, className), text('small', caption))
      elements.summary.append(card)
    }
  }

  function renderRows() {
    clear(elements.rows)
    const items = sortedItems()
    elements.empty.hidden = items.length > 0
    for (const stock of items) {
      const row = document.createElement('tr')
      const identity = document.createElement('td')
      const stockButton = text('button', '', 'stock-button')
      stockButton.type = 'button'
      stockButton.append(text('strong', stock.name), text('span', `${stock.code} · ${stock.exchange}`))
      stockButton.addEventListener('click', () => openDetail(stock))
      identity.append(stockButton)

      const price = text('td', stock.price == null ? '--' : currency(stock.price, stock.currency))
      const change = document.createElement('td')
      change.append(text('span', percent(stock.change_percent), `change-pill ${tone(stock.change_percent)}`))
      const flow = text('td', money(stock.main_net_flow_yi), tone(stock.main_net_flow_yi))
      const trend = document.createElement('td')
      trend.append(sparkline(stock.sparkline || [], stock.change_percent))
      const sector = document.createElement('td')
      sector.append(text('span', stock.sector || stock.industry || '--', 'sector-pill'))
      const actions = document.createElement('td')
      const remove = text('button', '×', 'delete-button')
      remove.type = 'button'
      remove.title = '删除自选股'
      remove.setAttribute('aria-label', `删除 ${stock.name}`)
      remove.addEventListener('click', () => removeStock(stock))
      actions.append(remove)
      row.append(identity, price, change, flow, trend, sector, actions)
      elements.rows.append(row)
    }
  }

  function renderSectors() {
    clear(elements.sectors)
    const sectors = (state.snapshot?.sectors || []).slice(0, 8)
    const max = Math.max(1, ...sectors.map(item => Math.abs(item.avg_change_percent || 0)))
    for (const sector of sectors) {
      const row = node('div', 'sector-row')
      const track = node('div', 'sector-track')
      const value = sector.avg_change_percent || 0
      const fill = node('span', `sector-fill ${value >= 0 ? 'positive' : 'negative'}`)
      fill.style.setProperty('--width', `${Math.max(2, Math.abs(value) / max * 48)}%`)
      fill.style.setProperty('--bar', value >= 0 ? 'var(--up)' : 'var(--down)')
      track.append(fill)
      row.append(text('span', sector.name), track, text('strong', percent(value), tone(value)))
      elements.sectors.append(row)
    }
    if (!sectors.length) elements.sectors.append(text('p', '等待板块行情', 'gap'))
  }

  function renderInsight() {
    elements.headline.textContent = state.snapshot?.summary?.headline || '等待自选股行情'
    clear(elements.gapList)
    for (const gap of (state.snapshot?.gaps || []).slice(0, 4)) {
      elements.gapList.append(text('p', `${gap.title}：${gap.message}`, 'gap'))
    }
  }

  function changeSort(key) {
    state.sort = {
      key,
      direction: state.sort.key === key && state.sort.direction === 'desc' ? 'asc' : 'desc'
    }
    persistPreferences()
    renderRows()
  }

  function sortedItems() {
    const values = [...(state.snapshot?.items || [])]
    const keyMap = { name: 'name', price: 'price', change: 'change_percent', flow: 'main_net_flow_yi' }
    const field = keyMap[state.sort.key] || 'change_percent'
    const direction = state.sort.direction === 'asc' ? 1 : -1
    return values.sort((left, right) => {
      const a = left[field]
      const b = right[field]
      if (typeof a === 'string') return a.localeCompare(b, 'zh-CN') * direction
      return ((a ?? Number.NEGATIVE_INFINITY) - (b ?? Number.NEGATIVE_INFINITY)) * direction
    })
  }

  async function openDetail(stock) {
    state.selected = stock
    state.detail = null
    state.analysis = null
    elements.detailCode.textContent = `${stock.code} · ${stock.sector || stock.industry || 'A 股'}`
    elements.detailTitle.textContent = stock.name
    selectDetailTab('market')
    elements.detailDialog.showModal()
    renderLoading()
    try {
      state.detail = await window.HermesApp.run('detail', { code: stock.code, force: false })
      renderMarketDetail()
    } catch (error) {
      renderDialogError(error.message)
    }
  }

  async function selectDetailTab(tab) {
    document.querySelectorAll('.dialog-tabs button').forEach(button => {
      button.classList.toggle('active', button.dataset.tab === tab)
    })
    if (tab === 'market') {
      if (state.detail) renderMarketDetail()
      else renderLoading()
      return
    }
    if (state.analysis) {
      renderAnalysis()
      return
    }
    renderLoading('正在整理公司分析')
    try {
      state.analysis = await window.HermesApp.run('analyze', { query: state.selected.code })
      renderAnalysis()
    } catch (error) {
      renderDialogError(error.message)
    }
  }

  function renderMarketDetail() {
    const detail = state.detail
    clear(elements.detailContent)
    const quote = node('section', 'detail-quote')
    const price = node('div')
    price.append(
      text('strong', detail.stock.price == null ? '--' : currency(detail.stock.price, detail.stock.currency)),
      text('p', detail.summary || '等待技术指标')
    )
    quote.append(price, text('strong', percent(detail.stock.change_percent), tone(detail.stock.change_percent)))
    const chart = node('section', 'chart-card')
    const canvas = document.createElement('canvas')
    canvas.id = 'kline-canvas'
    canvas.setAttribute('aria-label', `${detail.stock.name} K 线图`)
    chart.append(canvas)
    const grid = node('section', 'technical-grid')
    const technicals = [
      ['MA5', detail.technicals.ma5], ['MA20', detail.technicals.ma20],
      ['支撑位', detail.technicals.support], ['压力位', detail.technicals.resistance],
      ['区间涨跌', percent(detail.technicals.period_change_percent)],
      ['区间振幅', percent(detail.technicals.amplitude_percent)], ['趋势', detail.technicals.trend_label]
    ]
    for (const [label, value] of technicals) {
      const card = node('article', 'technical')
      card.append(text('span', label), text('strong', typeof value === 'number' ? number(value, 2) : value || '--'))
      grid.append(card)
    }
    elements.detailContent.append(quote, chart, grid)
    window.requestAnimationFrame(() => drawKline(canvas, detail.kline || []))
  }

  function renderAnalysis() {
    const analysis = state.analysis
    clear(elements.detailContent)
    const summary = node('section', 'analysis-summary')
    summary.append(text('strong', analysis.summary?.headline || analysis.rating?.summary || '综合分析'))
    for (const line of (analysis.summary?.details || []).slice(0, 3)) summary.append(text('p', line))
    const grid = node('section', 'analysis-grid')
    const cards = [
      ['综合评级', analysis.rating?.grade || '--'],
      ['最新价', analysis.quote?.price == null ? '--' : currency(analysis.quote.price, analysis.quote.currency)],
      ['市盈率', analysis.quote?.pe_ttm == null ? '--' : `${number(analysis.quote.pe_ttm, 1)}x`],
      ['市净率', analysis.quote?.pb == null ? '--' : `${number(analysis.quote.pb, 1)}x`]
    ]
    for (const [label, value] of cards) {
      const card = node('article', 'analysis-card')
      card.append(text('span', label), text('strong', value))
      grid.append(card)
    }
    const highlights = document.createElement('ul')
    highlights.className = 'analysis-list'
    const points = [
      ...(analysis.research?.highlights || []).slice(0, 4),
      ...(analysis.research?.risks || []).slice(0, 3).map(item => `风险：${item}`)
    ]
    for (const point of points) highlights.append(text('li', point))
    elements.detailContent.append(summary, grid, highlights)
  }

  function drawKline(canvas, points) {
    const ratio = window.devicePixelRatio || 1
    const width = canvas.clientWidth
    const height = canvas.clientHeight
    canvas.width = Math.floor(width * ratio)
    canvas.height = Math.floor(height * ratio)
    const context = canvas.getContext('2d')
    context.scale(ratio, ratio)
    context.clearRect(0, 0, width, height)
    if (!points.length) {
      context.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--muted')
      context.fillText('暂无 K 线数据', 18, 28)
      return
    }
    const padding = { top: 18, right: 12, bottom: 24, left: 48 }
    const prices = points.flatMap(point => [point.high, point.low]).filter(Number.isFinite)
    const low = Math.min(...prices)
    const high = Math.max(...prices)
    const range = Math.max(0.01, high - low)
    const chartWidth = width - padding.left - padding.right
    const chartHeight = height - padding.top - padding.bottom
    const step = chartWidth / points.length
    const candleWidth = Math.max(2, Math.min(9, step * 0.56))
    const y = value => padding.top + (high - value) / range * chartHeight
    const styles = getComputedStyle(document.documentElement)
    context.strokeStyle = styles.getPropertyValue('--line')
    context.fillStyle = styles.getPropertyValue('--muted')
    context.font = '11px system-ui'
    for (let line = 0; line <= 4; line += 1) {
      const lineY = padding.top + chartHeight * line / 4
      context.beginPath(); context.moveTo(padding.left, lineY); context.lineTo(width - padding.right, lineY); context.stroke()
      context.fillText(number(high - range * line / 4, 2), 2, lineY + 4)
    }
    points.forEach((point, index) => {
      const x = padding.left + step * index + step / 2
      const rising = point.close >= point.open
      const color = styles.getPropertyValue(rising ? '--up' : '--down')
      context.strokeStyle = color; context.fillStyle = color
      context.beginPath(); context.moveTo(x, y(point.high)); context.lineTo(x, y(point.low)); context.stroke()
      const top = Math.min(y(point.open), y(point.close))
      const bodyHeight = Math.max(1, Math.abs(y(point.open) - y(point.close)))
      context.fillRect(x - candleWidth / 2, top, candleWidth, bodyHeight)
    })
  }

  function sparkline(values, delta) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    svg.classList.add('sparkline')
    svg.setAttribute('viewBox', '0 0 84 28')
    const usable = values.filter(Number.isFinite)
    if (usable.length < 2) return svg
    const low = Math.min(...usable); const high = Math.max(...usable); const range = Math.max(0.01, high - low)
    const points = usable.map((value, index) => `${2 + index * 80 / (usable.length - 1)},${25 - (value - low) / range * 22}`).join(' ')
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline')
    line.setAttribute('points', points); line.setAttribute('fill', 'none')
    line.setAttribute('stroke', delta != null && delta < 0 ? 'var(--down)' : 'var(--up)')
    line.setAttribute('stroke-width', '2'); line.setAttribute('vector-effect', 'non-scaling-stroke')
    svg.append(line)
    return svg
  }

  function renderLoading(label = '正在读取股票详情') {
    clear(elements.detailContent)
    elements.detailContent.append(text('div', label, 'loading'))
  }

  function renderDialogError(message) {
    clear(elements.detailContent)
    elements.detailContent.append(text('div', message, 'loading'))
  }

  function showNotice(message, error = false) {
    elements.notice.textContent = message
    elements.notice.classList.toggle('error', error)
    elements.notice.hidden = false
    window.setTimeout(() => { elements.notice.hidden = true }, 3200)
  }

  function scheduleRefresh() {
    window.clearInterval(state.timer)
    state.timer = elements.autoRefresh.checked ? window.setInterval(() => loadSnapshot(true), 20000) : null
  }

  function persistPreferences() {
    void window.HermesApp.storageSet('watchlist.preferences', {
      autoRefresh: elements.autoRefresh.checked,
      sort: state.sort
    }).catch(() => {})
  }

  function statusLabel(snapshot) {
    if (snapshot.refresh?.refreshing) return '后台刷新中'
    if (snapshot.status === 'missing-server') return '妙想 MCP 未连接'
    return snapshot.refresh?.cache_state === 'warm' ? '缓存可用' : '实时盯盘'
  }

  function node(tag, className = '') { const value = document.createElement(tag); if (className) value.className = className; return value }
  function text(tag, value, className = '') { const element = node(tag, className); element.textContent = String(value ?? ''); return element }
  function clear(element) { element.replaceChildren() }
  function wait(milliseconds) { return new Promise(resolve => window.setTimeout(resolve, milliseconds)) }
  function number(value, digits = 2) { return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits }) }
  function percent(value) { return value == null ? '--' : `${value > 0 ? '+' : ''}${number(value, 2)}%` }
  function money(value) {
    if (value == null) return '--'
    const sign = value > 0 ? '+¥' : value < 0 ? '-¥' : '¥'
    return `${sign}${number(Math.abs(value), 2)}亿`
  }
  function currency(value, unit) { return `${unit === 'HKD' ? 'HK$' : unit === 'USD' ? '$' : '¥'}${number(value, 2)}` }
  function tone(value) { return value == null || value === 0 ? '' : value > 0 ? 'up' : 'down' }
})()
