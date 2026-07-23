(() => {
  const state = { data: null, mode: 'topic', loading: false, timer: null }
  const el = id => document.getElementById(id)

  document.addEventListener('DOMContentLoaded', initialize)

  async function initialize() {
    const bootstrap = await window.HermesApp.bootstrap()
    document.documentElement.dataset.theme = bootstrap.theme
    el('refresh').addEventListener('click', refresh)
    document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => {
      state.mode = button.dataset.mode
      document.querySelectorAll('[data-mode]').forEach(item => item.classList.toggle('active', item === button))
      renderHeatmap()
    }))
    await load(true)
  }

  async function load(autoRefresh) {
    if (state.loading) return
    state.loading = true
    el('refresh').classList.add('loading')
    try {
      state.data = await window.HermesApp.run('snapshot', { auto_refresh: autoRefresh })
      render()
      schedule(Boolean(state.data.refresh?.refreshing))
    } catch (error) {
      el('status').textContent = error.message || '市场数据读取失败'
    } finally {
      state.loading = false
      el('refresh').classList.remove('loading')
    }
  }

  async function refresh() {
    if (state.loading) return
    try {
      el('status').textContent = '妙想 MCP 正在后台刷新'
      await window.HermesApp.run('refresh', {})
      schedule(true, 500)
    } catch (error) {
      el('status').textContent = error.message || '刷新失败'
    }
  }

  function schedule(active, delay = 1400) {
    window.clearTimeout(state.timer)
    if (active) state.timer = window.setTimeout(() => load(false), delay)
  }

  function render() {
    const data = state.data || {}
    const refreshing = Boolean(data.refresh?.refreshing)
    el('status').textContent = `${data.as_of ? `数据 ${data.as_of}` : '等待交易数据'} · ${refreshing ? '后台刷新中' : '快照已就绪'}`
    el('headline').textContent = data.summary?.headline || '行业轮动和资金流向'
    replace(el('details'), (data.summary?.details || []).map(item => text('p', item)))
    renderBreadth()
    renderIndices()
    renderHeatmap()
    renderFlows()
    renderNorthbound()
    renderResearch()
    const gaps = (data.gaps || []).map(item => item.message).filter(Boolean)
    el('footnote').textContent = gaps.length ? `数据提示：${gaps.join('；')}` : (data.methodology?.description || '数据由妙想 MCP 提供，仅供研究参考。')
  }

  function renderBreadth() {
    const breadth = state.data?.market_breadth
    if (!breadth) return replace(el('breadth'), [text('div', '等待市场广度数据', 'empty')])
    const up = clamp(breadth.advance_ratio || 0)
    const box = document.createDocumentFragment()
    const top = node('div', 'breadth-top')
    top.append(text('small', '市场上涨占比'), text('strong', `${number(up, 1)}%`, tone(up - 50)))
    const track = node('div', 'breadth-track')
    const upBar = node('span'); upBar.style.width = `${up}%`
    const downBar = node('span'); downBar.style.width = `${100 - up}%`
    track.append(upBar, downBar)
    const values = node('div', 'breadth-values')
    values.append(text('span', `上涨 ${integer(breadth.advancers)}`, 'up'), text('span', breadth.sentiment_label || '市场广度'), text('span', `下跌 ${integer(breadth.decliners)}`, 'down'))
    box.append(top, track, values)
    replace(el('breadth'), [box])
  }

  function renderIndices() {
    const items = [...(state.data?.indices || []).slice(0, 5), { name: '全A成交额', value: state.data?.market_turnover_yi, turnover: '亿元', market: true }]
    replace(el('indices'), items.map(item => {
      const card = node('article', 'metric')
      card.append(text('label', item.name), text('strong', item.market ? money(item.value) : number(item.value, 2)), text('span', item.market ? `动态样本 ${integer(state.data?.market_sample_size)} 只` : percent(item.change_percent), tone(item.change_percent)))
      return card
    }))
  }

  function renderHeatmap() {
    const items = state.mode === 'industry' ? state.data?.industry_heatmap : state.data?.topic_heatmap
    if (!items?.length) return replace(el('heatmap'), [text('div', '等待热点聚合数据', 'empty')])
    replace(el('heatmap'), items.slice(0, 16).map(item => {
      const card = node('article', `heat ${toneName(item.avg_change_percent)}`)
      const head = node('div', 'heat-head'); head.append(text('h3', item.name), text('small', `样本 ${integer(item.sample_count)}`))
      card.append(head, text('strong', percent(item.avg_change_percent), tone(item.avg_change_percent)), text('p', (item.leaders || []).slice(0, 2).join(' · ') || `${money(item.main_net_inflow_yi)} 主力净额`))
      return card
    }))
  }

  function renderFlows() {
    const values = [...(state.data?.fund_flow || []).slice(0, 6), ...(state.data?.pressure || []).slice(0, 5)]
    const max = Math.max(1, ...values.map(item => Math.abs(item.main_net_inflow_yi || 0)))
    replace(el('flows'), values.map(item => {
      const value = item.main_net_inflow_yi || 0
      const row = node('div', 'flow-row'); const track = node('div', 'track'); const fill = node('span', `fill ${toneName(value)}`)
      fill.style.setProperty('--w', `${Math.max(3, Math.abs(value) / max * 50)}%`); track.append(fill)
      row.append(text('span', item.name), track, text('strong', money(value), tone(value)))
      return row
    }))
  }

  function renderNorthbound() {
    const data = state.data?.northbound
    if (!data?.current) return replace(el('northbound'), [text('div', '等待北向成交数据', 'empty')])
    const cards = node('div', 'north-cards')
    for (const [label, value] of [['北向成交总额', data.current.total_yi], ['沪股通成交额', data.current.sh_yi], ['深股通成交额', data.current.sz_yi]]) {
      const card = node('div', 'north-card'); card.append(text('small', label), text('strong', money(value))); cards.append(card)
    }
    replace(el('northbound'), [cards, text('p', data.note || `${data.current.activity_label || ''} · ${data.current.bias_label || ''}`, 'north-note')])
  }

  function renderResearch() {
    const items = state.data?.research || []
    if (!items.length) return replace(el('research'), [text('div', '行情已可用，研报仍在后台补充', 'empty')])
    replace(el('research'), items.slice(0, 6).map(item => {
      const card = node('article', 'article'); card.append(text('h3', item.title), text('p', item.summary), text('small', [item.source, item.published_at].filter(Boolean).join(' · '))); return card
    }))
  }

  function replace(parent, children) { parent.replaceChildren(...children) }
  function node(tag, className = '') { const item = document.createElement(tag); if (className) item.className = className; return item }
  function text(tag, value, className = '') { const item = node(tag, className); item.textContent = value == null ? '--' : String(value); return item }
  function tone(value) { return Number(value) > 0 ? 'up' : Number(value) < 0 ? 'down' : '' }
  function toneName(value) { return Number(value) >= 0 ? 'positive' : 'negative' }
  function clamp(value) { return Math.max(0, Math.min(100, Number(value) || 0)) }
  function number(value, digits = 1) { return value == null ? '--' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits }) }
  function integer(value) { return Number(value || 0).toLocaleString('zh-CN') }
  function percent(value) { return value == null ? '--' : `${Number(value) > 0 ? '+' : ''}${number(value, 2)}%` }
  function money(value) { return value == null ? '--' : `${Number(value) > 0 ? '+' : ''}${number(value, 1)}亿` }
})()
