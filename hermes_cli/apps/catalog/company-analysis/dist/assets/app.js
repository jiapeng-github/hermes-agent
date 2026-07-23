(() => {
  const state = { data: null, query: '', loading: false, timer: null }
  const el = id => document.getElementById(id)

  document.addEventListener('DOMContentLoaded', initialize)

  async function initialize() {
    const [bootstrap, saved] = await Promise.all([
      window.HermesApp.bootstrap(),
      window.HermesApp.storageGet('company-analysis.last-query', '')
    ])
    document.documentElement.dataset.theme = bootstrap.theme
    state.query = typeof saved === 'string' && saved.trim() ? saved.trim() : ''
    el('query').value = state.query
    el('search-form').addEventListener('submit', search)
    el('refresh').addEventListener('click', refresh)
    el('article-close').addEventListener('click', () => el('article-dialog').close())
    el('article-dialog').addEventListener('click', event => { if (event.target === el('article-dialog')) el('article-dialog').close() })
    if (state.query) {
      await load(true)
    } else {
      el('status').textContent = '请输入公司名称或股票代码'
    }
  }

  async function search(event) {
    event.preventDefault()
    const query = el('query').value.trim()
    if (!query) return
    state.query = query
    await window.HermesApp.storageSet('company-analysis.last-query', query)
    await load(true)
  }

  async function refresh() {
    if (state.loading || !state.query) return
    el('status').textContent = '妙想 MCP 正在后台刷新'
    try {
      await window.HermesApp.run('refresh', { query: state.query })
      schedule(true, 500)
    } catch (error) {
      el('status').textContent = error.message || '刷新失败'
    }
  }

  async function load(autoRefresh) {
    if (state.loading || !state.query) {
      if (!state.query) el('status').textContent = '请输入公司名称或股票代码'
      return
    }
    state.loading = true
    el('refresh').classList.add('loading')
    el('status').textContent = `正在读取 ${state.query} 的分析快照`
    try {
      state.data = await window.HermesApp.run('analyze', { query: state.query, auto_refresh: autoRefresh })
      render()
      schedule(Boolean(state.data.refresh?.refreshing))
    } catch (error) {
      el('status').textContent = error.message || '公司分析读取失败'
    } finally {
      state.loading = false
      el('refresh').classList.remove('loading')
    }
  }

  function schedule(active, delay = 1400) {
    window.clearTimeout(state.timer)
    if (active) state.timer = window.setTimeout(() => load(false), delay)
  }

  function render() {
    const data = state.data || {}
    const quote = data.quote || {}
    const resolved = data.resolved || {}
    const refreshing = Boolean(data.refresh?.refreshing)
    el('status').textContent = `${data.as_of ? `数据 ${data.as_of}` : '等待公司数据'} · ${refreshing ? '后台刷新中' : '分析已就绪'}`
    el('company-name').textContent = resolved.name || quote.name || data.query || state.query
    el('company-code').textContent = resolved.code ? `${resolved.code}${resolved.exchange ? `.${resolved.exchange}` : ''}` : '未匹配代码'
    el('industry').textContent = resolved.industry || quote.industry || '行业待补充'
    el('business').textContent = resolved.business || quote.business || '等待妙想 MCP 返回主营业务与公司画像。'
    replace(el('concepts'), (resolved.concepts || quote.concepts || []).slice(0, 8).map(item => text('span', item)))
    renderQuote(quote)
    renderMetrics(data.core_metrics || [])
    renderFinancial(data.financial_trend || {})
    renderProfitability(data.profitability || {}, data.operating_metrics || [])
    renderValuation(data.valuation || {})
    renderCapital(data.capital || {}, data.cash_flow || {})
    renderPeers(data.peers || [])
    renderBullets('highlights', data.research?.highlights || [], '暂无明确投资亮点')
    renderBullets('risks', data.research?.risks || [], '暂无完整风险原文，等待研报数据补充')
    renderResearch(data.research?.articles || [])
    renderRating(data.rating || {}, data.summary || {})
    const gaps = (data.gaps || []).map(item => item.message).filter(Boolean)
    el('footnote').textContent = gaps.length ? `数据提示：${gaps.join('；')}` : (data.methodology?.description || '数据由妙想 MCP 提供，仅供研究参考。')
  }

  function renderQuote(quote) {
    const card = document.createDocumentFragment()
    card.append(text('small', '最新价'))
    const main = node('div', 'quote-main')
    main.append(text('strong', price(quote.price)), text('b', `${percent(quote.change_percent)}  ${signed(quote.change_amount)}`, tone(quote.change_percent)))
    card.append(main)
    const grid = node('div', 'quote-grid')
    for (const [label, value] of [['总市值', money(quote.market_cap_yi)], ['PE(TTM)', ratio(quote.pe_ttm)], ['PB', ratio(quote.pb)], ['成交额', money(quote.turnover_yi)]]) {
      const item = node('div'); item.append(text('small', label), text('b', value)); grid.append(item)
    }
    card.append(grid); replace(el('quote'), [card])
  }

  function renderMetrics(metrics) {
    if (!metrics.length) return replace(el('metrics'), [text('div', '核心指标等待中', 'empty')])
    replace(el('metrics'), metrics.slice(0, 4).map(item => {
      const card = node('article', 'metric'); card.append(text('label', item.label), text('strong', `${number(item.value, 1)}${item.unit || ''}`), text('span', item.caption || '最新指标', item.tone === 'good' ? 'down' : item.tone === 'bad' ? 'up' : '')); return card
    }))
  }

  function renderFinancial(trend) {
    const revenue = trend.revenue_yi || []; const profit = trend.net_profit_yi || []
    const periods = unique([...revenue, ...profit].map(item => item.period))
    const max = Math.max(1, ...revenue.concat(profit).map(item => Math.abs(item.value || 0)))
    if (!periods.length) return replace(el('financial-chart'), [text('div', '暂无收入与利润序列', 'empty')])
    replace(el('financial-chart'), periods.map(period => {
      const group = node('div', 'bar-group'); group.style.position = 'relative'
      const revenueValue = point(revenue, period); const profitValue = point(profit, period)
      group.append(bar(revenueValue, max, '营业收入'), bar(profitValue, max, '净利润', 'profit'), text('label', period)); return group
    }))
  }

  function bar(value, max, label, className = '') {
    const item = node('div', `bar ${className}`); item.style.height = `${Math.max(3, Math.abs(value || 0) / max * 180)}px`; item.title = `${label} ${number(value, 1)} 亿元`; item.append(text('span', number(value, 1))); return item
  }

  function renderProfitability(data, operating) {
    const series = [
      ['毛利率', data.gross_margin_percent || [], ''],
      ['ROE', data.roe_percent || [], 'roe']
    ]
    const rows = []
    for (const [label, values, className] of series) {
      const max = Math.max(1, ...values.map(item => Math.abs(item.value || 0)))
      for (const item of values) {
        const row = node('div', `series-row ${className}`); const track = node('div', 'series-track'); const fill = node('span'); fill.style.setProperty('--w', `${Math.max(2, Math.abs(item.value || 0) / max * 100)}%`); track.append(fill); row.append(text('span', `${label} ${item.period}`), track, text('strong', percent(item.value))); rows.push(row)
      }
    }
    replace(el('profitability'), rows.length ? rows : [text('div', '暂无盈利能力序列', 'empty')])
    replace(el('operating'), operating.slice(0, 4).map(item => { const box = node('div'); box.append(text('small', item.label), text('b', `${number(item.value, 1)}${item.unit || ''}`)); return box }))
  }

  function renderValuation(valuation) {
    const range = valuation.price_range || {}
    const shell = document.createDocumentFragment(); const track = node('div', 'valuation-range'); const marker = node('span', 'valuation-marker'); marker.style.setProperty('--x', `${clamp(range.percentile)}%`); marker.dataset.label = price(range.current); track.append(marker)
    const labels = node('div', 'valuation-labels'); labels.append(text('span', `区间低位 ${price(range.low)}`), text('span', range.label || valuation.signal || '估值位置'), text('span', `区间高位 ${price(range.high)}`))
    shell.append(track, labels); replace(el('valuation'), [shell])
  }

  function renderCapital(capital, cashFlow) {
    const cash = (cashFlow.operating_cash_flow_yi || []).at(-1)?.value
    const items = [['成交额', money(capital.turnover_yi)], ['换手率', percent(capital.turnover_rate_percent)], ['量比', ratio(capital.volume_ratio)], ['经营现金流', money(cash)]]
    replace(el('capital'), items.map(([label, value]) => { const card = node('article', 'metric'); card.append(text('label', label), text('strong', value), text('span', capital.activity_label || capital.momentum_label || '最新指标')); return card }))
  }

  function renderPeers(peers) {
    replace(el('peers'), peers.slice(0, 10).map(item => {
      const row = node('tr', item.is_target ? 'target' : ''); for (const value of [`${item.name || '--'} ${item.code || ''}`, money(item.market_cap_yi), percent(item.gross_margin_percent), percent(item.roe_percent), ratio(item.pe_ttm)]) row.append(text('td', value)); return row
    }))
  }

  function renderBullets(id, values, fallback) {
    replace(el(id), (values.length ? values : [fallback]).map(value => text('div', value, 'bullet')))
  }

  function renderResearch(items) {
    if (!items.length) return replace(el('research'), [text('div', '暂无研报摘要', 'empty')])
    replace(el('research'), items.slice(0, 8).map(item => {
      const card = node('article', 'article'); card.tabIndex = 0; card.append(text('h3', item.title), text('p', item.summary), text('small', [item.source, item.published_at, '点击查看完整内容'].filter(Boolean).join(' · '))); card.addEventListener('click', () => openArticle(item)); card.addEventListener('keydown', event => { if (event.key === 'Enter') openArticle(item) }); return card
    }))
  }

  function openArticle(article) {
    el('article-title').textContent = article.title || '研报摘要'
    el('article-meta').textContent = [article.source, article.published_at].filter(Boolean).join(' · ')
    el('article-body').textContent = article.summary || '暂无完整内容'
    el('article-dialog').showModal()
  }

  function renderRating(rating, summary) {
    const shell = document.createDocumentFragment(); shell.append(text('div', rating.grade || '--', 'grade'))
    const content = node('div'); content.append(text('h2', `综合评价 · ${rating.score == null ? '等待评分' : `${number(rating.score, 0)} 分`}`), text('p', rating.summary || summary.headline || '等待公司综合评价'))
    const tags = node('div', 'rating-tags'); for (const tag of rating.tags || []) tags.append(text('span', tag)); content.append(tags); shell.append(content); replace(el('rating'), [shell])
  }

  function replace(parent, children) { parent.replaceChildren(...children) }
  function node(tag, className = '') { const item = document.createElement(tag); if (className) item.className = className; return item }
  function text(tag, value, className = '') { const item = node(tag, className); item.textContent = value == null ? '--' : String(value); return item }
  function unique(values) { return [...new Set(values.filter(Boolean))] }
  function point(values, period) { return values.find(item => item.period === period)?.value || 0 }
  function clamp(value) { return Math.max(0, Math.min(100, Number(value) || 0)) }
  function tone(value) { return Number(value) > 0 ? 'up' : Number(value) < 0 ? 'down' : '' }
  function number(value, digits = 1) { return value == null ? '--' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits }) }
  function percent(value) { return value == null ? '--' : `${Number(value) > 0 ? '+' : ''}${number(value, 1)}%` }
  function money(value) { return value == null ? '--' : `${number(value, 1)}亿` }
  function price(value) { return value == null ? '--' : `¥${number(value, 2)}` }
  function ratio(value) { return value == null ? '--' : `${number(value, 1)}x` }
  function signed(value) { return value == null ? '--' : `${Number(value) > 0 ? '+' : ''}${number(value, 2)}` }
})()
