(() => {
  const state = { data: null, query: '', loading: false, timer: null, capturePending: false }
  const el = id => document.getElementById(id)

  document.addEventListener('DOMContentLoaded', initialize)

  async function initialize() {
    const bootstrap = await window.HermesApp.bootstrap()
    document.documentElement.dataset.theme = bootstrap.theme
    state.query = ''
    el('query').value = ''
    el('search-form').addEventListener('submit', search)
    el('refresh').addEventListener('click', refresh)
  }

  async function search(event) {
    event.preventDefault()
    const query = el('query').value.trim()
    if (!query) return
    state.query = query
    state.capturePending = true
    await load(true)
  }

  async function refresh() {
    if (state.loading || !state.query) return
    el('status').textContent = '妙想 MCP 正在后台刷新数据'
    state.capturePending = true
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
      const tracked = await window.HermesApp.runTracked('analyze', { query: state.query, auto_refresh: autoRefresh })
      state.data = tracked.result
      render()
      const refreshing = Boolean(state.data.refresh?.refreshing)
      schedule(refreshing)
      if (state.capturePending && !refreshing) {
        state.capturePending = false
        await publishArtifact(tracked.run_id)
      }
    } catch (error) {
      el('status').textContent = error.message || '个股分析读取失败'
    } finally {
      state.loading = false
      el('refresh').classList.remove('loading')
    }
  }

  async function publishArtifact(runId) {
    const data = state.data || {}
    const resolved = data.resolved || {}
    const name = resolved.name || data.quote?.name || state.query
    try {
      await window.HermesApp.publishCurrentPage(runId, {
        title: `${name} 个股三维深度分析`,
        summary: `${name} 的公司质地、舆情摘要与交易活跃度三维研究快照`,
        snapshot: { query: state.query, name, code: resolved.code || '', as_of: data.as_of || null }
      })
    } catch (error) {
      console.warn('应用产物保存失败', error)
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
    renderCapital(data.capital || {}, quote, data.valuation || {})
    renderValuation(data.valuation || {}, quote)
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
    const capital = capitalScore(data.capital || {}, data.quote || {})
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
    const quote = data.quote || {}
    const core = safe(data.core_metrics).filter(metric => hasNumber(metric.value))
    const quoteMetrics = [
      { label: '总市值', value: quote.market_cap_yi, unit: '亿元', caption: '公司规模', tone: 'neutral' },
      { label: '流通市值', value: quote.float_market_cap_yi, unit: '亿元', caption: '流通规模', tone: 'neutral' },
      { label: 'PE(TTM)', value: quote.pe_ttm, unit: '倍', caption: '当前估值', tone: 'neutral' },
      { label: 'PB', value: quote.pb, unit: '倍', caption: '当前估值', tone: 'neutral' },
      { label: '毛利率', value: quote.gross_margin_percent, unit: '%', caption: '盈利能力', tone: 'good' },
      { label: 'ROE', value: quote.roe_percent, unit: '%', caption: '资本回报', tone: 'good' }
    ].filter(metric => hasNumber(metric.value))
    const metrics = uniqueMetrics([...core, ...quoteMetrics]).slice(0, 8)

    replace(el('fundamental-metrics'), metrics.length
      ? metrics.map(metricCard)
      : [text('div', '当前暂无可展示的结构化基本面指标。', 'data-empty')])

    const peers = safe(data.peers).filter(peer =>
      peer.name && [peer.market_cap_yi, peer.pe_ttm, peer.pb, peer.gross_margin_percent, peer.roe_percent].some(hasNumber)
    ).slice(0, 6)
    const detail = el('fundamental-detail')

    if (peers.length) {
      const table = node('table', 'peer-table')
      const head = node('thead')
      const headRow = node('tr')
      ;['公司', '总市值', 'PE(TTM)', 'PB', '毛利率', 'ROE'].forEach(label => headRow.append(text('th', label)))
      head.append(headRow)
      const body = node('tbody')
      peers.forEach(peer => {
        const row = node('tr', peer.is_target ? 'target-peer' : '')
        row.append(
          text('td', peer.name),
          text('td', marketCap(peer.market_cap_yi)),
          text('td', plainRatio(peer.pe_ttm)),
          text('td', plainRatio(peer.pb)),
          text('td', unsignedPercent(peer.gross_margin_percent)),
          text('td', unsignedPercent(peer.roe_percent))
        )
        body.append(row)
      })
      table.append(head, body)
      replace(detail, [table])
      el('fundamental-detail-note').textContent = `已获取 ${peers.length} 家可比公司`
    } else {
      replace(detail, [text('div', '同行列表暂未返回，已优先展示当前可用的公司画像和估值指标。', 'data-empty')])
      el('fundamental-detail-note').textContent = '当前公司指标'
    }

    const resolved = data.resolved || {}
    const summaryParts = [
      resolved.industry ? `所属行业：${resolved.industry}` : null,
      resolved.business ? `主营画像：${shortText(resolved.business, 110)}` : null,
      safe(resolved.concepts).length ? `相关概念：${safe(resolved.concepts).slice(0, 5).join(' / ')}` : null,
      data.rating?.summary ? shortText(data.rating.summary, 140) : null
    ].filter(Boolean)
    replace(el('fundamental-summary'), summaryParts.length
      ? summaryParts.map(item => text('p', item))
      : [text('p', '公司画像正在补充。')])

    const reportPeriod = safe(data.financial_trend?.periods).at(-1)
    el('fundamental-tag').textContent = `核心来源：妙想 MCP${reportPeriod ? ` · 最新报告期 ${reportPeriod}` : ''} · 仅展示已返回指标`
  }

  function renderResearch(research) {
    const highlights = safe(research.highlights)
    const risks = safe(research.risks)
    const articles = safe(research.articles)
    const latest = articles[0] || {}
    const positivePoint = highlights[0] || firstSentence(latest.summary || latest.title)
    const riskPoint = risks[0]
    const stance = risks.length > highlights.length
      ? { label: '谨慎关注', className: 'cautious' }
      : highlights.length > risks.length
        ? { label: '偏积极', className: 'positive' }
        : { label: '中性观察', className: 'neutral' }
    const summary = node('div', 'research-brief')
    const heading = node('div', 'research-brief-heading')
    heading.append(
      text('span', stance.label, `sentiment-badge ${stance.className}`),
      text('span', articles.length ? `已汇总 ${articles.length} 条公开资讯` : '暂无可用资讯样本', 'research-meta')
    )
    summary.append(heading)

    if (positivePoint) {
      summary.append(text('p', `核心摘要：${shortText(positivePoint, 150)}`, 'research-copy'))
    } else {
      summary.append(text('p', '妙想 MCP 当前未返回可提炼的新闻或研报摘要。', 'research-copy muted'))
    }
    if (riskPoint) {
      summary.append(text('p', `风险提示：${shortText(riskPoint, 130)}`, 'research-risk'))
    }

    const sourceLine = [latest.source, latest.published_at].filter(Boolean).join(' · ')
    if (sourceLine) summary.append(text('div', `最新样本：${sourceLine}`, 'research-source'))
    replace(el('research-summary'), [summary])
  }

  function renderCapital(capital, quote, valuation) {
    const turnover = capital.turnover_yi ?? quote.turnover_yi
    const turnoverRate = capital.turnover_rate_percent ?? quote.turnover_rate_percent
    const volumeRatio = capital.volume_ratio ?? quote.volume_ratio
    const turnoverToCap = capital.turnover_to_market_cap_percent
    const metricCandidates = [
      hasNumber(turnover) ? ['当日成交额', money(turnover), '交易规模', 'neu'] : null,
      hasNumber(turnoverRate) ? ['换手率', unsignedPercent(turnoverRate), '筹码交换速度', activityTone(turnoverRate, 1, 4)] : null,
      hasNumber(volumeRatio) ? ['量比', `${number(volumeRatio, 2)}x`, '相对近5日成交活跃度', activityTone(volumeRatio, .8, 1.5)] : null,
      hasNumber(turnoverToCap) ? ['成交额/总市值', unsignedPercent(turnoverToCap), '资金周转强度', activityTone(turnoverToCap, .3, 2)] : null,
      hasNumber(quote.float_market_cap_yi) ? ['流通市值', marketCap(quote.float_market_cap_yi), '可交易市值', 'neu'] : null,
      hasNumber(quote.change_percent) ? ['当日涨跌幅', percent(quote.change_percent), '短线价格动能', tone(quote.change_percent)] : null
    ].filter(Boolean).slice(0, 4)

    replace(el('capital-metrics'), metricCandidates.length
      ? metricCandidates.map(([label, value, caption, className]) => simpleMetric(label, value, caption, className))
      : [text('div', '当前暂无可展示的交易活跃度指标。', 'data-empty')])

    const percentile = valuation.price_range?.percentile
    const signals = [
      {
        label: '交易活跃度',
        value: capital.activity_label || activityLabel(turnoverRate, volumeRatio),
        description: activityDescription(turnoverRate, volumeRatio)
      },
      {
        label: '价格动能',
        value: capital.momentum_label || momentumLabel(quote.change_percent),
        description: hasNumber(quote.change_percent) ? `当日涨跌幅 ${percent(quote.change_percent)}` : '等待当日行情'
      },
      {
        label: '近期价格位置',
        value: valuation.signal || valuation.price_range?.label || '区间观察',
        description: hasNumber(percentile) ? `处于近期区间约 ${number(percentile, 0)}% 位置` : '估值区间待补充'
      }
    ]
    replace(el('capital-signals'), signals.map(signal => {
      const item = node('div', 'signal-card')
      item.append(text('div', signal.label, 'signal-label'), text('div', signal.value, 'signal-value'), text('div', signal.description, 'signal-description'))
      return item
    }))

    const notes = [
      hasNumber(turnover) ? `当日成交额 ${money(turnover)}` : null,
      hasNumber(turnoverRate) ? `换手率 ${unsignedPercent(turnoverRate)}` : null,
      hasNumber(volumeRatio) ? `量比 ${number(volumeRatio, 2)}x` : null
    ].filter(Boolean)
    el('capital-note').textContent = notes.length
      ? `${notes.join('，')}。本模块仅根据已返回的交易活跃度和价格数据解读，不以缺失的主力或北向序列作推断。`
      : '妙想 MCP 当前未返回成交额、换手率或量比，资金面暂不作方向判断。'
  }

  function renderValuation(valuation, quote) {
    const range = valuation.price_range || {}
    const low = range.low
    const high = range.high
    const current = range.current ?? quote.price
    const midpoint = low != null && high != null ? (Number(low) + Number(high)) / 2 : null
    const hasRange = hasNumber(low) && hasNumber(high) && Number(high) > Number(low)
    el('valuation-range').classList.toggle('is-hidden', !hasRange)
    el('range-low').querySelector('.cap').textContent = `保守 ${number(low, 0)}`
    el('range-mid').querySelector('.cap').textContent = `中枢 ~${number(midpoint, 0)}`
    el('range-high').querySelector('.cap').textContent = `乐观 ${number(high, 0)}`
    el('valuation-signal').textContent = valuation.signal || range.label || '中性（估值中枢）'
    const pricePosition = range.percentile
    el('range-mid').style.left = `${hasNumber(pricePosition) ? clamp(pricePosition) : 50}%`
    const metrics = [
      hasNumber(quote.pe_ttm) ? ['当前 PE', plainRatio(quote.pe_ttm), hasNumber(pricePosition) ? `${number(pricePosition, 0)}% 价格位置` : '当前估值', 'neu'] : null,
      hasNumber(quote.pb) ? ['当前 PB', plainRatio(quote.pb), '净资产估值', 'neu'] : null,
      hasNumber(valuation.peer_median_pe) ? ['同行 PE 中位', plainRatio(valuation.peer_median_pe), valuation.signal || '同行比较', 'neu'] : null,
      hasNumber(current) ? ['当前价格', number(current, 2), range.label || '近期价格观察', 'neu'] : null
    ].filter(Boolean)
    replace(el('valuation-metrics'), metrics.length
      ? metrics.map(([label, value, caption, className]) => simpleMetric(label, value, caption, className))
      : [text('div', '当前暂无可展示的估值指标。', 'data-empty')])
    el('valuation-note').textContent = valuation.summary || valuation.signal || (
      hasRange
        ? `当前价格 ${number(current, 2)}，近期参考区间 ${number(low, 2)}–${number(high, 2)}，仅作为估值位置观察。`
        : '近期价格序列不足，已改为展示当前 PE、PB 与同行估值信息。'
    )
  }

  function renderSources(data) {
    const financeReady = safe(data.core_metrics).some(metric => hasNumber(metric.value)) || safe(data.peers).length > 0
    const researchReady = safe(data.research?.articles).length > 0 || safe(data.research?.highlights).length > 0
    const capital = data.capital || {}
    const capitalReady = [
      capital.turnover_yi,
      capital.turnover_rate_percent,
      capital.volume_ratio,
      capital.turnover_to_market_cap_percent,
      data.quote?.change_percent
    ].some(hasNumber)
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
  function simpleMetric(label, value, caption, className = '') {
    const item = node('div', 'm')
    item.append(text('div', label, 'l'), text('div', value, `v ${className}`), text('div', caption, `s ${className}`))
    return item
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
  function capitalScore(capital, quote) {
    let score = 50
    let observations = 0
    const turnoverRate = capital.turnover_rate_percent ?? quote.turnover_rate_percent
    const volumeRatio = capital.volume_ratio ?? quote.volume_ratio
    if (hasNumber(turnoverRate)) {
      score += Number(turnoverRate) >= 2 ? 8 : Number(turnoverRate) <= .3 ? -5 : 2
      observations += 1
    }
    if (hasNumber(volumeRatio)) {
      score += Number(volumeRatio) >= 1.5 ? 10 : Number(volumeRatio) < .8 ? -6 : 2
      observations += 1
    }
    if (hasNumber(quote.change_percent)) {
      score += Math.max(-15, Math.min(15, Number(quote.change_percent) * 4))
      observations += 1
    }
    return observations ? Math.round(clamp(score)) : null
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
  function uniqueMetrics(metrics) {
    const labels = new Set()
    return metrics.filter(metric => {
      const label = String(metric.label || '').toUpperCase()
      if (!label || labels.has(label)) return false
      labels.add(label)
      return true
    })
  }
  function activityTone(value, low, high) {
    if (!hasNumber(value)) return 'neu'
    return Number(value) >= high ? 'up' : Number(value) < low ? 'down' : 'neu'
  }
  function activityLabel(turnoverRate, volumeRatio) {
    if (hasNumber(volumeRatio) && Number(volumeRatio) >= 1.5) return '显著放量'
    if (hasNumber(turnoverRate) && Number(turnoverRate) >= 2) return '交易活跃'
    if (hasNumber(volumeRatio) || hasNumber(turnoverRate)) return '活跃度一般'
    return '等待数据'
  }
  function activityDescription(turnoverRate, volumeRatio) {
    const parts = []
    if (hasNumber(turnoverRate)) parts.push(`换手率 ${unsignedPercent(turnoverRate)}`)
    if (hasNumber(volumeRatio)) parts.push(`量比 ${number(volumeRatio, 2)}x`)
    return parts.join(' · ') || '成交活跃度待补充'
  }
  function momentumLabel(change) {
    if (!hasNumber(change)) return '等待行情'
    if (Number(change) >= 3) return '强势上行'
    if (Number(change) <= -3) return '承压回落'
    return '震荡'
  }
  function firstSentence(value) {
    return String(value || '').split(/[。；;\n]/).map(item => item.trim()).find(item => item.length >= 6) || ''
  }
  function shortText(value, maxLength) {
    const content = String(value || '').replace(/\s+/g, ' ').trim()
    return content.length <= maxLength ? content : `${content.slice(0, maxLength - 1)}…`
  }
  function hasNumber(value) { return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) }
  function setSource(id, ready) {
    el(id).textContent = ready ? '✅' : '待补充'
  }
  function replace(parent, children) { parent.replaceChildren(...children) }
  function node(tag, className = '') { const item = document.createElement(tag); if (className) item.className = className; return item }
  function text(tag, value, className = '') { const item = node(tag, className); item.textContent = value == null ? '--' : String(value); return item }
  function safe(value) { return Array.isArray(value) ? value : [] }
  function clamp(value) { return Math.max(0, Math.min(100, Number(value) || 0)) }
  function tone(value) { return Number(value) > 0 ? 'up' : Number(value) < 0 ? 'down' : 'neu' }
  function toneForMetric(value) { return value === 'good' ? 'up' : value === 'bad' ? 'down' : 'neu' }
  function number(value, digits = 1) { return value == null || Number.isNaN(Number(value)) ? '--' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits:digits, minimumFractionDigits:digits }) }
  function percent(value) { return value == null || Number.isNaN(Number(value)) ? '--' : `${Number(value) > 0 ? '+' : ''}${number(value, 1)}%` }
  function unsignedPercent(value) { return value == null || Number.isNaN(Number(value)) ? '--' : `${number(value, 1)}%` }
  function money(value) { return value == null || Number.isNaN(Number(value)) ? '--' : `${number(value, 1)}亿` }
  function marketCap(value) { return value == null || Number.isNaN(Number(value)) ? '--' : Number(value) >= 10000 ? `${number(Number(value) / 10000, 2)} 万亿` : money(value) }
  function plainRatio(value) { return value == null || Number.isNaN(Number(value)) ? '--' : number(value, 1) }
  function signed(value) { return value == null || Number.isNaN(Number(value)) ? '--' : `${Number(value) > 0 ? '+' : ''}${number(value, 2)}` }
})()
