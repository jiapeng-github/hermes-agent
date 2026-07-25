(() => {
  const state = { data: null, query: '', loading: false, timer: null }
  const el = id => document.getElementById(id)

  document.addEventListener('DOMContentLoaded', initialize)

  async function initialize() {
    const [bootstrap, saved] = await Promise.all([
      window.HermesApp.bootstrap(),
      window.HermesApp.storageGet('stock-deep-analysis.last-query', '')
    ])
    document.documentElement.dataset.theme = bootstrap.theme
    state.query = typeof saved === 'string' ? saved.trim() : ''
    el('query').value = state.query
    el('search-form').addEventListener('submit', search)
    el('refresh').addEventListener('click', refresh)
    el('article-close').addEventListener('click', () => el('article-dialog').close())
    el('article-dialog').addEventListener('click', event => {
      if (event.target === el('article-dialog')) el('article-dialog').close()
    })
    if (state.query) await load(true)
  }

  async function search(event) {
    event.preventDefault()
    const query = el('query').value.trim()
    if (!query) return
    state.query = query
    await window.HermesApp.storageSet('stock-deep-analysis.last-query', query)
    await load(true)
  }

  async function refresh() {
    if (state.loading || !state.query) return
    el('status').textContent = '妙想 MCP 正在后台刷新数据'
    try {
      await window.HermesApp.run('refresh', { query: state.query })
      schedule(true, 500)
    } catch (error) {
      el('status').textContent = error.message || '刷新失败'
    }
  }

  async function load(autoRefresh) {
    if (state.loading || !state.query) return
    state.loading = true
    el('refresh').classList.add('loading')
    el('status').textContent = `正在读取 ${state.query} 的三维研究快照`
    try {
      state.data = await window.HermesApp.run('analyze', { query: state.query, auto_refresh: autoRefresh })
      render()
      schedule(Boolean(state.data.refresh?.refreshing))
    } catch (error) {
      el('status').textContent = error.message || '个股分析读取失败'
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
    const refresh = data.refresh || {}
    const name = resolved.name || quote.name || state.query
    const code = resolved.code || quote.code || ''
    const exchange = resolved.exchange || quote.exchange || ''
    el('status').textContent = `${data.as_of ? `数据 ${data.as_of}` : '等待个股数据'} · ${refresh.refreshing ? '后台刷新中' : '研究快照已就绪'}`
    el('company-name').textContent = name
    el('company-code').textContent = code ? `${code}${exchange ? `.${exchange}` : ''} · 沪深 A 股` : '未匹配股票代码'
    el('industry').textContent = resolved.industry || quote.industry || '行业待补充'
    el('business').textContent = resolved.business || quote.business || '公司画像等待补充'
    el('hero-date').textContent = data.as_of ? `数据截至 ${data.as_of}` : '等待数据'
    renderQuote(quote, data.valuation || {})
    renderScores(data)
    renderFundamentals(data)
    renderResearch(data.research || {})
    renderCapital(data.capital || {}, quote, data)
    renderValuation(data.valuation || {}, quote, data)
    renderSources(data)
    renderLinks(code, exchange)
    const gaps = safe(data.gaps).map(item => item.message).filter(Boolean)
    el('footnote').textContent = gaps.length
      ? `本报告基于公开数据自动生成，仅供研究参考，不构成任何投资建议或买卖依据。数据提示：${gaps.join('；')}`
      : '本报告基于公开数据自动生成，仅供研究与学习参考，不构成任何投资建议或买卖依据。股价受宏观、行业、政策及市场情绪等多重因素影响，历史财务与资金数据不代表未来表现。投资者应独立判断、自担风险。'
    el('report-footer').textContent = `${name}${code ? `(${code})` : ''} 个股三维深度分析报告 · ${data.as_of ? `生成于 ${data.as_of}` : '数据存在时滞'} · 请以交易所及公司公告为准`
  }

  function renderQuote(quote, valuation) {
    el('price-now').textContent = number(quote.price, 2)
    el('price-now').className = `price-now ${tone(quote.change_percent)}`
    el('price-change').textContent = `${Number(quote.change_percent) >= 0 ? '▲' : '▼'} ${signed(quote.change_amount)}　${percent(quote.change_percent)}`
    el('price-change').className = `price-chg ${tone(quote.change_percent)}`
    el('day-quote').textContent = [
      quote.open == null ? null : `今开 ${number(quote.open, 2)}`,
      quote.high == null ? null : `最高 ${number(quote.high, 2)}`,
      quote.low == null ? null : `最低 ${number(quote.low, 2)}`,
      quote.previous_close == null ? null : `昨收 ${number(quote.previous_close, 2)}`,
      quote.turnover_yi == null ? null : `成交额 ${money(quote.turnover_yi)}`
    ].filter(Boolean).join(' · ') || '日内行情明细等待补充'
    const range = valuation.price_range || {}
    const stats = [
      ['总市值', marketCap(quote.market_cap_yi)],
      ['市盈率(TTM)', plainRatio(quote.pe_ttm)],
      ['市净率', plainRatio(quote.pb)],
      ['年高低区间', range.low == null && range.high == null ? '--' : `${number(range.low, 0)}–${number(range.high, 0)}`],
      ['换手率', percent(quote.turnover_rate_percent)]
    ]
    replace(el('mini-stats'), stats.map(([label, value]) => {
      const item = node('div')
      item.append(text('span', label, 'l'), text('span', value, 'v'))
      return item
    }))
  }

  function renderScores(data) {
    const fundamental = fundamentalScore(data)
    const news = informationScore(data.research || {})
    const capital = capitalScore(data.valuation || {}, data.capital || {})
    const technical = technicalScore(data.quote || {})
    const weighted = weightedScore([[fundamental, .35], [news, .20], [capital, .35], [technical, .10]])
    const score = weighted == null ? null : weighted / 10
    el('score').textContent = score == null ? '--' : score.toFixed(1)
    el('score-ring').setAttribute('stroke-dashoffset', String(score == null ? 502.65 : 502.65 * (1 - score / 10)))
    el('grade').textContent = data.rating?.grade || verdict(weighted)
    const dimensions = [
      ['基本面', fundamental, '#b8893f'],
      ['新闻面', news, '#b8893f'],
      ['资金面', capital, '#e0a958'],
      ['技术面*', technical, '#b8893f']
    ]
    replace(el('score-bars'), dimensions.map(([label, value, color]) => {
      const row = node('div', 'bar-row')
      const track = node('div', 'bar-track')
      const fill = node('div', 'bar-fill')
      fill.style.width = `${value == null ? 0 : value}%`
      fill.style.background = color
      track.append(fill)
      row.append(text('span', label), track, text('span', value == null ? '--' : (value / 10).toFixed(1), 'bar-val'))
      return row
    }))
    el('score-summary').innerHTML = ''
    el('score-summary').append(
      text('span', `评分说明：${data.rating?.summary || data.summary?.headline || '评分仅反映当前可获得的结构化数据覆盖度与研究信号。'}`),
      document.createElement('br'),
      text('span', '*技术面为参考项，不计入核心研究结论，仅作趋势辅助判断。')
    )
  }

  function renderFundamentals(data) {
    const metrics = safe(data.core_metrics).slice(0, 8)
    replace(el('fundamental-metrics'), metrics.length ? metrics.map(metricCard) : [placeholderMetric('财务指标等待中')])
    const trend = data.financial_trend || {}
    const profit = safe(trend.net_profit_yi)
    const max = Math.max(1, ...profit.map(item => Math.abs(Number(item.value) || 0)))
    replace(el('profit-trend'), profit.length ? profit.slice(-6).map(item => {
      const col = node('div', 'col')
      const bar = node('div', 'bar')
      bar.style.height = `${Math.max(3, Math.abs(Number(item.value) || 0) / max * 100)}%`
      col.append(text('span', number(item.value, 0), 'val'), bar, text('span', item.period, 'yr'))
      return col
    }) : [text('div', '暂无归母净利润趋势', 'empty')])
    const latestRevenue = safe(trend.revenue_yi).at(-1)
    const latestProfit = profit.at(-1)
    const cash = safe(data.cash_flow?.operating_cash_flow_yi).at(-1)
    const profitability = data.profitability || {}
    const gross = safe(profitability.gross_margin_percent).at(-1)
    const roe = safe(profitability.roe_percent).at(-1)
    const supplementary = [
      ['最新营业收入', latestRevenue ? money(latestRevenue.value) : '--', latestRevenue?.period || '等待数据', 'neu'],
      ['最新归母净利润', latestProfit ? money(latestProfit.value) : '--', latestProfit?.period || '等待数据', 'neu'],
      ['销售毛利率', gross ? percent(gross.value) : '--', gross?.period || '等待数据', 'up'],
      ['加权 ROE', roe ? percent(roe.value) : '--', roe?.period || (cash ? `经营现金流 ${money(cash.value)}` : '等待数据'), 'up']
    ]
    replace(el('supplementary-metrics'), supplementary.map(([label, value, caption, className]) => simpleMetric(label, value, caption, className)))
    el('fundamental-tag').textContent = `核心来源：妙想 MCP${safe(trend.periods).at(-1) ? ` · 最新报告期 ${safe(trend.periods).at(-1)}` : ''} · 单位：人民币 / 同比口径`
  }

  function renderResearch(research) {
    const highlights = safe(research.highlights)
    const risks = safe(research.risks)
    const articles = safe(research.articles)
    const positive = Math.min(68, 34 + highlights.length * 7 + Math.min(articles.length, 4) * 2)
    const negative = Math.min(42, 14 + risks.length * 7)
    const neutral = Math.max(0, 100 - positive - negative)
    el('sentiment-donut').style.background = `conic-gradient(var(--red) 0 ${positive}%,#9ca3af ${positive}% ${positive + neutral}%,var(--green) ${positive + neutral}% 100%)`
    const legends = [
      ['var(--red)', `正面 ${positive}% — 投资亮点与积极研报信号`],
      ['#9ca3af', `中性 ${neutral}% — 行业观察与财务解读`],
      ['var(--green)', `负面 ${negative}% — 风险提示与不确定性`]
    ]
    replace(el('sentiment-legend'), legends.map(([color, label]) => {
      const item = node('div', 'it')
      const dot = node('span', 'dot')
      dot.style.background = color
      item.append(dot, text('span', label))
      return item
    }))
    const events = articles.slice(0, 6).map(article => ({
      date: article.published_at || '最新资讯',
      content: article.summary || article.title,
      tag: article.source || '资讯',
      sentiment: 'n',
      article
    }))
    if (!events.length) {
      events.push(...highlights.slice(0, 3).map(content => ({ date: '投资亮点', content, tag: '正面', sentiment: 'p' })))
      events.push(...risks.slice(0, 3).map(content => ({ date: '风险提示', content, tag: '负面', sentiment: 'd' })))
    }
    replace(el('research'), events.length ? events.map(event => {
      const item = node('div', `ev ${event.article ? 'clickable' : ''}`)
      const content = node('div', 'tx')
      content.append(text('span', event.content), text('span', event.tag, `pill ${event.sentiment}`))
      item.append(text('div', event.date, 'dt'), content)
      if (event.article) {
        item.tabIndex = 0
        item.addEventListener('click', () => openArticle(event.article))
        item.addEventListener('keydown', keyEvent => {
          if (keyEvent.key === 'Enter') openArticle(event.article)
        })
      }
      return item
    }) : [text('div', '暂无新闻与研报摘要', 'empty')])
  }

  function renderCapital(capital, quote, data) {
    const flowRows = safe(capital.main_flow || capital.main_flow_history || capital.flow_history)
    const todayFlow = capital.main_net_inflow_yi ?? flowRows.at(-1)?.net_inflow_yi
    const fiveDayFlow = capital.main_net_inflow_5d_yi ?? sum(flowRows.slice(-5).map(item => item.net_inflow_yi))
    const northShares = capital.northbound_holding_wan
    const northFlow = capital.northbound_net_inflow_20d_yi
    const metrics = [
      ['今日主力净流入', moneySigned(todayFlow), capital.main_net_ratio_percent == null ? '等待主力净比' : `主力净比 ${percent(capital.main_net_ratio_percent)}`, tone(todayFlow)],
      ['近5日主力净流入', moneySigned(fiveDayFlow), flowRows.length ? '最近可用交易日' : '等待日序列', tone(fiveDayFlow)],
      ['北向持股', northShares == null ? '--' : `${number(northShares, 0)}万股`, capital.northbound_market_value_yi == null ? '等待持股市值' : `市值约${money(capital.northbound_market_value_yi)}`, 'neu'],
      ['北向近20日', moneySigned(northFlow), capital.northbound_label || '等待北向数据', tone(northFlow)]
    ]
    replace(el('capital-metrics'), metrics.map(([label, value, caption, className]) => simpleMetric(label, value, caption, className)))
    replace(el('capital-table'), flowRows.length ? flowRows.slice(-5).map(item => {
      const row = node('tr')
      row.append(
        text('td', item.date || item.period || '--'),
        text('td', moneySigned(item.net_inflow_yi), tone(item.net_inflow_yi)),
        text('td', number(item.close ?? item.price, 2)),
        text('td', percent(item.change_percent), tone(item.change_percent))
      )
      return row
    }) : [emptyTableRow('妙想 MCP 当前未返回主力近 5 日明细')])
    replace(el('capital-total'), flowRows.length ? [(() => {
      const row = node('tr')
      row.append(text('td', '近5日合计'), text('td', moneySigned(fiveDayFlow), tone(fiveDayFlow)), text('td', '—'), text('td', '—'))
      return row
    })()] : [])
    el('capital-note').textContent = capital.northbound_summary || capital.summary || (
      northShares != null || northFlow != null
        ? `当前北向持股 ${northShares == null ? '暂无股数' : `${number(northShares, 0)} 万股`}，近 20 日净流入 ${moneySigned(northFlow)}。`
        : '妙想 MCP 当前尚未返回完整北向持股或主力近 5 日序列；成交额、换手率等可用行情数据已在页面顶部展示。'
    )
    void quote
    void data
  }

  function renderValuation(valuation, quote, data) {
    const range = valuation.price_range || {}
    const low = range.low
    const high = range.high
    const current = range.current ?? quote.price
    const midpoint = low != null && high != null ? (Number(low) + Number(high)) / 2 : null
    el('range-low').querySelector('.cap').textContent = `保守 ${number(low, 0)}`
    el('range-mid').querySelector('.cap').textContent = `中枢 ~${number(midpoint, 0)}`
    el('range-high').querySelector('.cap').textContent = `乐观 ${number(high, 0)}`
    el('valuation-signal').textContent = valuation.signal || range.label || '中性（估值中枢）'
    const pricePosition = range.percentile
    if (pricePosition != null) el('range-mid').style.left = `${clamp(pricePosition)}%`
    const latestEps = findMetric(data.core_metrics, ['EPS', '每股收益'])
    const metrics = [
      ['每股收益 EPS', latestEps ? `${number(latestEps.value, 2)}${latestEps.unit || '元'}` : '--', latestEps?.caption || '等待数据', 'neu'],
      ['当前 PE', plainRatio(quote.pe_ttm), range.percentile == null ? '等待历史分位' : `${number(range.percentile, 0)}% 分位`, tone(50 - Number(range.percentile))],
      ['当前 PB', plainRatio(quote.pb), '估值参考', 'neu'],
      ['当前价格', current == null ? '--' : number(current, 2), range.label || '近期价格区间', 'neu']
    ]
    replace(el('valuation-metrics'), metrics.map(([label, value, caption, className]) => simpleMetric(label, value, caption, className)))
    el('valuation-note').textContent = valuation.summary || valuation.signal || (
      low != null && high != null
        ? `当前价格 ${number(current, 2)}，近期参考区间 ${number(low, 2)}–${number(high, 2)}，仅作为估值位置观察。`
        : '妙想 MCP 当前未返回完整价格区间，暂无法形成合理价格区间参考。'
    )
  }

  function renderSources(data) {
    const financeReady = safe(data.core_metrics).length > 0 || safe(data.financial_trend?.net_profit_yi).length > 0
    const researchReady = safe(data.research?.articles).length > 0 || safe(data.research?.highlights).length > 0
    const capitalReady = Object.keys(data.capital || {}).length > 0
    setSource('source-quote', data.quote?.price != null)
    setSource('source-finance', financeReady)
    setSource('source-research', researchReady)
    setSource('source-capital', capitalReady)
    el('as-of').textContent = data.as_of || '以最新返回为准'
  }

  function renderLinks(code, exchange) {
    const normalized = String(code || '').replace(/\D/g, '')
    if (!normalized) return
    const market = String(exchange || '').toUpperCase().includes('SH') || normalized.startsWith('6') ? 'sh' : 'sz'
    el('quote-link').href = `https://quote.eastmoney.com/${market}${normalized}.html`
    el('f10-link').href = `https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?type=web&code=${market}${normalized}`
    el('flow-link').href = `https://data.eastmoney.com/zjlx/${normalized}.html`
  }

  function metricCard(item) {
    return simpleMetric(item.label, `${number(item.value, 1)}${item.unit || ''}`, item.caption || '最新指标', toneForMetric(item.tone))
  }
  function placeholderMetric(label) { return simpleMetric(label, '--', '等待妙想 MCP 返回', 'neu') }
  function simpleMetric(label, value, caption, className = '') {
    const item = node('div', 'm')
    item.append(text('div', label, 'l'), text('div', value, `v ${className}`), text('div', caption, `s ${className}`))
    return item
  }
  function emptyTableRow(message) {
    const row = node('tr', 'empty-row')
    const cell = text('td', message)
    cell.colSpan = 4
    row.append(cell)
    return row
  }
  function openArticle(article) {
    el('article-title').textContent = article.title || '研报摘要'
    el('article-meta').textContent = [article.source, article.published_at].filter(Boolean).join(' · ')
    el('article-body').textContent = article.summary || '暂无完整内容'
    el('article-dialog').showModal()
  }
  function fundamentalScore(data) {
    const metrics = safe(data.core_metrics)
    const gross = findMetric(metrics, ['毛利'])?.value
    const roe = findMetric(metrics, ['ROE'])?.value
    if (gross == null && roe == null) return null
    return Math.round(Math.min(100, (Math.min(Number(gross) || 0, 60) / 60 * 55) + (Math.min(Number(roe) || 0, 30) / 30 * 45)))
  }
  function informationScore(research) {
    const count = safe(research.articles).length + safe(research.highlights).length + safe(research.risks).length
    if (!count) return null
    return Math.max(20, Math.min(100, 55 + safe(research.highlights).length * 8 - safe(research.risks).length * 4))
  }
  function capitalScore(valuation, capital) {
    const percentile = Number(valuation.price_range?.percentile)
    if (Number.isFinite(percentile)) return Math.round(100 - clamp(percentile))
    return Object.keys(capital).length ? 55 : null
  }
  function technicalScore(quote) {
    const change = Number(quote.change_percent)
    return Number.isFinite(change) ? Math.round(clamp(50 + change * 5)) : null
  }
  function weightedScore(entries) {
    const available = entries.filter(([value]) => Number.isFinite(value))
    if (!available.length) return null
    const totalWeight = available.reduce((total, [, weight]) => total + weight, 0)
    return Math.round(available.reduce((total, [value, weight]) => total + value * weight, 0) / totalWeight)
  }
  function verdict(score) {
    if (score == null) return '等待数据'
    if (score >= 75) return '积极关注'
    if (score >= 55) return '中性观察'
    return '谨慎评估'
  }
  function findMetric(metrics, labels) {
    return safe(metrics).find(item => labels.some(label => String(item.label || '').toUpperCase().includes(label.toUpperCase())))
  }
  function setSource(id, ready) {
    el(id).textContent = ready ? '✅' : '待补充'
  }
  function replace(parent, children) { parent.replaceChildren(...children) }
  function node(tag, className = '') { const item = document.createElement(tag); if (className) item.className = className; return item }
  function text(tag, value, className = '') { const item = node(tag, className); item.textContent = value == null ? '--' : String(value); return item }
  function safe(value) { return Array.isArray(value) ? value : [] }
  function sum(values) { const numbers = values.filter(value => Number.isFinite(Number(value))); return numbers.length ? numbers.reduce((total, value) => total + Number(value), 0) : null }
  function clamp(value) { return Math.max(0, Math.min(100, Number(value) || 0)) }
  function tone(value) { return Number(value) > 0 ? 'up' : Number(value) < 0 ? 'down' : 'neu' }
  function toneForMetric(value) { return value === 'good' ? 'up' : value === 'bad' ? 'down' : 'neu' }
  function number(value, digits = 1) { return value == null || Number.isNaN(Number(value)) ? '--' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits:digits, minimumFractionDigits:digits }) }
  function percent(value) { return value == null || Number.isNaN(Number(value)) ? '--' : `${Number(value) > 0 ? '+' : ''}${number(value, 1)}%` }
  function money(value) { return value == null || Number.isNaN(Number(value)) ? '--' : `${number(value, 1)}亿` }
  function moneySigned(value) { return value == null || Number.isNaN(Number(value)) ? '--' : `${Number(value) > 0 ? '+' : ''}${money(value)}` }
  function marketCap(value) { return value == null || Number.isNaN(Number(value)) ? '--' : Number(value) >= 10000 ? `${number(Number(value) / 10000, 2)} 万亿` : money(value) }
  function plainRatio(value) { return value == null || Number.isNaN(Number(value)) ? '--' : number(value, 1) }
  function signed(value) { return value == null || Number.isNaN(Number(value)) ? '--' : `${Number(value) > 0 ? '+' : ''}${number(value, 2)}` }
})()
