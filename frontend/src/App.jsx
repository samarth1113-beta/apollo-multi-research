import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import ConfigPanel, { EMPTY_KEYS } from './components/ConfigPanel'

const API_BASE = 'http://localhost:8000'

const INDUSTRIAL_EXAMPLE_TOPICS = [
  'Why do Indian farmers still burn crop stubble, and which solutions are actually working?',
  'Stubble burning policy in a single small village of Fatehgarh Sahib district 2026',
]

const DOMESTIC_EXAMPLE_TOPICS = [
  'Best budget 5G phone under ₹20,000 in India 2026',
]

const DISCIPLINES = [
  'Scientific & Academic Research',
  'Financial Analysis',
  'Medical Research',
  'Product Comparison',
  'General Knowledge',
]

const DEFAULT_DOMESTIC_PLATFORMS = [
  { name: 'Reddit', domain: 'reddit.com', access: 'web search' },
  { name: 'X', domain: 'x.com', access: 'web search' },
  { name: 'Quora', domain: 'quora.com', access: 'web search' },
  { name: 'YouTube', domain: 'youtube.com', access: 'web search' },
  { name: 'Amazon', domain: 'amazon.in', access: 'web search' },
  { name: 'Flipkart', domain: 'flipkart.com', access: 'web search' },
]

const PLATFORM_MIX_ORDER = ['Reddit', 'YouTube', 'Quora', 'Amazon', 'Flipkart', 'X']
const GRAPH_DOMESTIC_PLATFORMS = ['Reddit', 'X', 'Quora', 'YouTube', 'Amazon', 'Flipkart']

// Light-theme Agent badge colors per APOLLO_SPEC.md:
// Apollo blue, Athena green, Hermes orange, Writer purple, TruthMeter teal, System grey
const AGENT_STYLES = {
  Apollo: 'bg-blue-50 text-blue-700 border-blue-200',
  Athena: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  Hermes: 'bg-orange-50 text-orange-700 border-orange-200',
  Writer: 'bg-purple-50 text-purple-700 border-purple-200',
  Judge: 'bg-pink-50 text-pink-700 border-pink-200',
  TruthMeter: 'bg-teal-50 text-teal-700 border-teal-200',
  System: 'bg-gray-100 text-gray-700 border-gray-200',
}

// Quality badge styles per APOLLO_SPEC.md:
// High green, Medium yellow, Low orange, Dropped red
const QUALITY_BADGE_STYLES = {
  High: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  Medium: 'bg-amber-50 text-amber-700 border-amber-200',
  Low: 'bg-orange-50 text-orange-700 border-orange-200',
  Dropped: 'bg-red-50 text-red-700 border-red-200',
}

const SOURCE_TYPE_TAG_STYLES = {
  'User opinion': 'bg-purple-50 text-purple-700 border-purple-200',
  Retail: 'bg-blue-50 text-blue-700 border-blue-200',
  'Expert review': 'bg-teal-50 text-teal-700 border-teal-200',
  tavily: 'bg-gray-100 text-gray-700 border-gray-200',
  arxiv: 'bg-indigo-50 text-indigo-700 border-indigo-200',
}

// Truth Meter sentence highlight styles (light theme)
const VERDICT_SENTENCE_STYLES = {
  SUPPORTED:
    'bg-emerald-100/75 hover:bg-emerald-200/80 border-b-2 border-emerald-500 text-[#1F2937] cursor-pointer',
  PARTIAL:
    'bg-amber-100/85 hover:bg-amber-200/90 border-b-2 border-amber-500 text-[#1F2937] cursor-pointer',
  UNSUPPORTED:
    'bg-red-100/85 hover:bg-red-200/90 border-b-2 border-red-500 text-[#1F2937] cursor-pointer',
}

const VERDICT_BADGE_STYLES = {
  SUPPORTED: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  PARTIAL: 'bg-amber-100 text-amber-800 border-amber-300',
  UNSUPPORTED: 'bg-red-100 text-red-800 border-red-300',
}

function formatTime(isoString) {
  if (!isoString) return ''
  try {
    const d = new Date(isoString)
    return d.toLocaleTimeString([], { hour12: false })
  } catch {
    return isoString.slice(11, 19)
  }
}

/**
 * Smoothly animated counter for live stats.
 */
function AnimatedNumber({ value, suffix = '' }) {
  const [displayVal, setDisplayVal] = useState(Number(value) || 0)
  const prevRef = useRef(Number(value) || 0)

  useEffect(() => {
    const target = Number(value)
    if (Number.isNaN(target)) return
    const start = prevRef.current
    if (start === target) {
      setDisplayVal(target)
      return
    }
    const diff = target - start
    const duration = 260
    const startTime = performance.now()
    let rafId = null

    const tick = (now) => {
      const progress = Math.min(1, (now - startTime) / duration)
      const current = Math.round(start + diff * progress)
      setDisplayVal(current)
      if (progress < 1) {
        rafId = requestAnimationFrame(tick)
      } else {
        prevRef.current = target
      }
    }

    rafId = requestAnimationFrame(tick)
    return () => {
      if (rafId) cancelAnimationFrame(rafId)
    }
  }, [value])

  return (
    <>
      {displayVal}
      {suffix}
    </>
  )
}

/**
 * Split a paragraph or list item into sentences matching backend/agents/truth_meter.py
 */
function splitParagraphIntoSentences(text) {
  const cleaned = (text || '').trim()
  if (!cleaned) return []
  const pattern = /[^.!?]+[.!?]+(?:\s*\[\d+(?:\s*,\s*\d+)*\])*\.*|[^.!?]+$/g
  const matches = cleaned.match(pattern)
  if (!matches) return [cleaned]
  return matches.map((s) => s.trim()).filter(Boolean)
}

function hasCitation(sentence) {
  return /\[\d+(?:\s*,\s*\d+)*\]/.test(sentence)
}

function extractCitationIds(sentence) {
  const ids = []
  const re = /\[(\d+(?:\s*,\s*\d+)*)\]/g
  let m
  while ((m = re.exec(sentence || '')) !== null) {
    for (const part of m[1].split(',')) {
      const n = Number(part.trim())
      if (!Number.isNaN(n) && n > 0 && !ids.includes(n)) {
        ids.push(n)
      }
    }
  }
  return ids
}

function normalizeSentenceKey(s) {
  return (s || '')
    .replace(/\s+/g, ' ')
    .replace(/[*_`]/g, '')
    .trim()
    .toLowerCase()
}

/**
 * Extract 3 to 4 key bullet points from the report's summary/introduction section
 * without calling the LLM again.
 */
function extractKeyFindingsFromReport(markdown) {
  if (!markdown) return []
  const lines = markdown.split(/\r?\n/)
  const bullets = []
  const introSentences = []
  let inFirstSection = false

  for (const raw of lines) {
    const line = raw.trim()
    if (!line) continue
    if (line.startsWith('# ')) continue
    if (line.startsWith('## ')) {
      if (!inFirstSection) {
        inFirstSection = true
        continue
      } else if (bullets.length >= 3 || introSentences.length >= 3) {
        break
      }
      continue
    }
    if (line.startsWith('#') || (line.startsWith('|') && line.endsWith('|'))) {
      continue
    }

    if (/^(?:[-*+]|\d+\.)\s+/.test(line)) {
      const cleaned = line
        .replace(/^(?:[-*+]|\d+\.)\s+/, '')
        .replace(/\*\*([^*]+)\*\*/g, '$1')
        .trim()
      if (cleaned.length > 25 && bullets.length < 4) {
        bullets.push(cleaned)
      }
    } else if (introSentences.length < 4) {
      for (const s of splitParagraphIntoSentences(line)) {
        const cleaned = s.replace(/\*\*([^*]+)\*\*/g, '$1').trim()
        if (cleaned.length > 35 && introSentences.length < 4) {
          introSentences.push(cleaned)
        }
      }
    }
  }

  const chosen = bullets.length >= 3 ? bullets.slice(0, 4) : introSentences.slice(0, 4)
  return chosen
}

/**
 * Convert raw SSE events into plain-English Activity Feed items,
 * pairing search_result with how many sources were kept from that query,
 * and grouping consecutive warnings with a ⚠️ icon.
 */
function buildActivityFeedItems(events) {
  if (!events || events.length === 0) return []

  // Count how many sources were kept per query_used or section_id
  const rows = []

  for (let i = 0; i < events.length; i++) {
    const ev = events[i]
    const { type, agent, message, data, ts } = ev

    // Group consecutive warnings into a single ⚠️ warning entry
    if (type === 'warning') {
      const warningGroup = [message]
      let lastTs = ts
      while (i + 1 < events.length && events[i + 1].type === 'warning') {
        i += 1
        warningGroup.push(events[i].message)
        lastTs = events[i].ts
      }
      const text =
        warningGroup.length === 1
          ? `⚠️ ${warningGroup[0]}`
          : `⚠️ ${warningGroup.length} platform notices: ${warningGroup.slice(0, 2).join(' · ')}${
              warningGroup.length > 2 ? ` (+${warningGroup.length - 2} more)` : ''
            }`
      rows.push({
        type: 'warning',
        agent: agent || 'Athena',
        text,
        ts: lastTs,
      })
      continue
    }

    // Skip verbose individual source_scored rows if we summarize them on search_result,
    // except show kept high-credibility highlights or summarize cleanly
    if (type === 'source_scored') {
      continue
    }

    let plainText = message

    if (type === 'plan') {
      const secCount = data?.sections?.length || 0
      const qCount =
        (data?.sections || []).reduce(
          (acc, s) => acc + (s.questions?.length || 0),
          0
        ) || 0
      plainText = `Apollo broke the research topic into ${secCount} sections with ${qCount} search queries.`
    } else if (type === 'round') {
      if ((data?.round || 1) === 1) {
        plainText = `Apollo started Round 1 with ${data?.queries_count || 0} planned searches.`
      } else {
        plainText = `Apollo started Round ${data.round} to run ${data?.queries_count || 0} follow-up searches for missing evidence.`
      }
    } else if (type === 'search_start') {
      const toolLabel = data?.platform || (data?.tool === 'arxiv' ? 'arXiv' : 'the web')
      plainText = `Athena is searching ${toolLabel} for "${data?.query || ''}"...`
    } else if (type === 'search_result') {
      const count = data?.count ?? 0
      const toolLabel = data?.platform || (data?.tool === 'arxiv' ? 'arXiv' : 'web')
      if (count === 0) {
        continue
      }
      plainText = `Athena searched "${data?.query || ''}" (${toolLabel}) and retrieved ${count} source${
        count === 1 ? '' : 's'
      }.`
    } else if (type === 'review') {
      if (data?.stop_reason) {
        plainText = `Hermes completed the search loop (${data.stop_reason}) and handed verified sources to Writer.`
      } else {
        const gCount = data?.gaps_count ?? 0
        const cCount = data?.conflicts_count ?? 0
        plainText = `Hermes reviewed Round ${data?.round || 1} sources — found ${gCount} gap${
          gCount === 1 ? '' : 's'
        } and ${cCount} conflict${cCount === 1 ? '' : 's'}.`
      }
    } else if (type === 'gap') {
      plainText = `Hermes spotted a gap in section ${data?.section_id || ''} and queued follow-up search "${
        data?.follow_up_query || ''
      }".`
    } else if (type === 'conflict') {
      plainText = `Hermes found a source disagreement on "${data?.topic || 'a key claim'}".`
    } else if (type === 'writing') {
      if (data?.stage === 'section_start') {
        plainText = `Writer is drafting section ${data?.section_id || ''} from ${
          data?.sources_count || 0
        } verified sources...`
      } else if (data?.stage === 'section_done') {
        plainText = `Writer finished drafting section ${data?.section_id || ''} with inline citations.`
      } else if (data?.stage === 'assembly_start') {
        plainText = `Writer is assembling the full report with introduction, transitions, and conclusion...`
      } else if (data?.stage === 'assembly_done') {
        plainText = `Writer completed the assembled report.`
      }
    } else if (type === 'judge') {
      if (data?.score !== undefined) {
        plainText = `Judge scored the draft ${data.score}/10 and requested ${
          data.fixes_count ?? 0
        } revision(s).`
      }
    } else if (type === 'truth_check') {
      if (data?.total_sentences) {
        plainText = `Truth Meter is fact-checking ${data.total_sentences} cited sentences against their source text...`
      } else if (data?.section) {
        plainText = `Truth Meter checked ${data?.count || 0} cited sentences in "${data.section}".`
      }
    } else if (type === 'trust_score') {
      plainText = `Truth Meter finished verification: ${data?.trust_score ?? 0}% Trust Score (${
        data?.supported ?? 0
      } supported, ${data?.partial ?? 0} partial, ${data?.unsupported ?? 0} unsupported).`
    } else if (type === 'done') {
      plainText = `Apollo completed the research run in ${data?.stats?.seconds ?? 0}s with ${
        data?.stats?.sources_kept ?? 0
      } verified sources.`
    }

    rows.push({
      type,
      agent: agent || 'System',
      text: plainText,
      ts,
      data,
    })
  }

  return rows
}

/**
 * Build a short source passage around the evidence quote and highlight the quote in yellow.
 */
function HighlightedSourcePassage({ sourceContent, evidenceQuote }) {
  const content = (sourceContent || '').trim()
  const quote = (evidenceQuote || '').trim()

  if (!content && !quote) {
    return (
      <p className="text-xs text-[#6B7280] italic">
        No source text snippet available.
      </p>
    )
  }

  if (!content) {
    return (
      <div className="text-sm text-[#31333F] leading-relaxed bg-[#F9FAFB] p-3.5 rounded-[8px] border border-[#E5E7EB]">
        <mark className="bg-yellow-200/90 text-[#31333F] px-1 py-0.5 rounded font-medium">
          &ldquo;{quote}&rdquo;
        </mark>
      </div>
    )
  }

  if (!quote || quote.startsWith('Cited source ID')) {
    return (
      <div className="text-sm text-[#31333F] leading-relaxed bg-[#F9FAFB] p-3.5 rounded-[8px] border border-[#E5E7EB]">
        {content.slice(0, 520)}
        {content.length > 520 ? '...' : ''}
      </div>
    )
  }

  const lowerContent = content.toLowerCase()
  const lowerQuote = quote.toLowerCase()
  const matchIdx = lowerContent.indexOf(lowerQuote)

  if (matchIdx !== -1) {
    const start = Math.max(0, matchIdx - 140)
    const end = Math.min(content.length, matchIdx + quote.length + 160)
    const prefix = (start > 0 ? '...' : '') + content.slice(start, matchIdx)
    const matched = content.slice(matchIdx, matchIdx + quote.length)
    const suffix =
      content.slice(matchIdx + quote.length, end) +
      (end < content.length ? '...' : '')

    return (
      <div className="text-sm text-[#31333F] leading-relaxed bg-[#F9FAFB] p-3.5 rounded-[8px] border border-[#E5E7EB]">
        <span>{prefix}</span>
        <mark className="bg-yellow-200 text-[#31333F] px-1 py-0.5 rounded font-medium">
          {matched}
        </mark>
        <span>{suffix}</span>
      </div>
    )
  }

  // If the LLM slightly trimmed or paraphrased the quote, highlight the quote at top of the passage
  return (
    <div className="space-y-2.5">
      <div className="text-sm text-[#31333F] leading-relaxed bg-yellow-50/70 p-3 rounded-[8px] border border-yellow-200">
        <span className="block text-[11px] font-bold uppercase tracking-wider text-amber-800 mb-1">
          Matched Evidence Quote
        </span>
        <mark className="bg-yellow-200 text-[#31333F] px-1 py-0.5 rounded font-medium">
          &ldquo;{quote}&rdquo;
        </mark>
      </div>
      <div className="text-xs text-[#6B7280] leading-relaxed bg-[#F9FAFB] p-3 rounded-[8px] border border-[#E5E7EB]">
        <span className="block text-[11px] font-bold uppercase tracking-wider text-[#31333F] mb-1">
          Source Passage
        </span>
        {content.slice(0, 420)}
        {content.length > 420 ? '...' : ''}
      </div>
    </div>
  )
}

/**
 * Render inline text with clickable [n] citation pills and basic bold markdown.
 */
function InlineSentenceContent({ text, verdictInfo, onTraceOpen }) {
  const expanded = (text || '').replace(
    /\[(\d+(?:\s*,\s*\d+)+)\]/g,
    (_, nums) =>
      nums
        .split(',')
        .map((n) => `[${n.trim()}]`)
        .join(' ')
  )

  const tokens = expanded.split(/(\[\d+\]|\*\*[^*]+\*\*)/g)

  return (
    <>
      {tokens.map((tok, idx) => {
        if (!tok) return null
        const citeMatch = tok.match(/^\[(\d+)\]$/)
        if (citeMatch) {
          const num = Number(citeMatch[1])
          return (
            <button
              key={idx}
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onTraceOpen({
                  sourceId: num,
                  sentenceText: text,
                  verdictInfo,
                })
              }}
              title={`Inspect Source [${num}] & Evidence`}
              className="inline-flex items-center px-1.5 py-0.5 mx-0.5 text-xs font-bold rounded bg-blue-50 text-blue-700 border border-blue-200 hover:bg-[#FF4B4B] hover:text-white hover:border-[#FF4B4B] transition cursor-pointer align-baseline"
            >
              [{num}]
            </button>
          )
        }
        const boldMatch = tok.match(/^\*\*([^*]+)\*\*$/)
        if (boldMatch) {
          return (
            <strong key={idx} className="font-bold text-[#31333F]">
              {boldMatch[1]}
            </strong>
          )
        }
        return <React.Fragment key={idx}>{tok}</React.Fragment>
      })}
    </>
  )
}

/**
 * Renders the full markdown report (including Markdown comparison tables) with
 * sentence-level Truth Meter highlights, click-to-trace drawer trigger,
 * hover popovers, and "Show only problems" dimming of SUPPORTED sentences.
 */
function VerifiedReportView({
  markdown,
  sentencesWithVerdicts,
  showOnlyProblems,
  onTraceOpen,
}) {
  const { byIndex, byNormText } = useMemo(() => {
    const idxMap = {}
    const textMap = {}
    for (const item of sentencesWithVerdicts || []) {
      if (item.sentence_index !== undefined) {
        idxMap[item.sentence_index] = item
      }
      if (item.sentence) {
        textMap[normalizeSentenceKey(item.sentence)] = item
      }
    }
    return { byIndex: idxMap, byNormText: textMap }
  }, [sentencesWithVerdicts])

  const blocks = useMemo(() => {
    const lines = (markdown || '').split(/\r?\n/)
    const parsedBlocks = []
    let citedCounter = 0
    let i = 0

    while (i < lines.length) {
      const raw = lines[i].trim()
      if (!raw) {
        i++
        continue
      }

      if (raw.startsWith('|') && raw.endsWith('|')) {
        const tableLines = []
        while (i < lines.length) {
          const tLine = lines[i].trim()
          if (tLine.startsWith('|') && tLine.endsWith('|')) {
            tableLines.push(tLine)
            i++
          } else {
            break
          }
        }
        const rows = tableLines
          .filter((l) => !/^\|[\s\-:|]+\|$/.test(l))
          .map((l) =>
            l
              .slice(1, -1)
              .split('|')
              .map((cell) => cell.trim())
          )
        if (rows.length > 0) {
          parsedBlocks.push({
            type: 'table',
            headers: rows[0],
            rows: rows.slice(1),
          })
        }
        continue
      }

      if (raw.startsWith('# ')) {
        parsedBlocks.push({ type: 'h1', text: raw.slice(2).trim() })
        i++
        continue
      }
      if (raw.startsWith('## ')) {
        parsedBlocks.push({ type: 'h2', text: raw.slice(3).trim() })
        i++
        continue
      }
      if (raw.startsWith('### ')) {
        parsedBlocks.push({ type: 'h3', text: raw.slice(4).trim() })
        i++
        continue
      }
      if (raw.startsWith('#### ')) {
        parsedBlocks.push({ type: 'h4', text: raw.slice(5).trim() })
        i++
        continue
      }

      const isBullet = /^[-*+]\s+/.test(raw)
      const isNumbered = /^\d+\.\s+/.test(raw)
      const bodyText = raw.replace(/^(?:[-*+]|\d+\.)\s+/, '').trim()

      const rawSentences = splitParagraphIntoSentences(bodyText)
      const sentenceObjs = rawSentences.map((sText) => {
        if (!hasCitation(sText)) {
          return { text: sText, verdictInfo: null }
        }
        const currentIdx = citedCounter
        citedCounter += 1
        const match =
          byIndex[currentIdx] || byNormText[normalizeSentenceKey(sText)] || null
        return {
          text: sText,
          verdictInfo: match,
        }
      })

      parsedBlocks.push({
        type: isBullet ? 'ul-item' : isNumbered ? 'ol-item' : 'p',
        sentences: sentenceObjs,
      })
      i++
    }

    return parsedBlocks
  }, [markdown, byIndex, byNormText])

  const renderSentences = (sentences) =>
    sentences.map((sObj, idx) => {
      const vInfo = sObj.verdictInfo
      const citedIds = vInfo?.citations?.length
        ? vInfo.citations
        : extractCitationIds(sObj.text)

      if (!vInfo || !vInfo.verdict) {
        return (
          <span
            key={idx}
            onClick={() => {
              if (citedIds.length > 0) {
                onTraceOpen({
                  sourceId: citedIds[0],
                  sentenceText: sObj.text,
                  verdictInfo: null,
                })
              }
            }}
            className={`mr-1.5 transition-opacity ${
              showOnlyProblems ? 'opacity-40' : ''
            }`}
          >
            <InlineSentenceContent
              text={sObj.text}
              verdictInfo={null}
              onTraceOpen={onTraceOpen}
            />
          </span>
        )
      }

      const verdict = vInfo.verdict
      const highlightCls =
        VERDICT_SENTENCE_STYLES[verdict] || VERDICT_SENTENCE_STYLES.SUPPORTED
      const badgeCls =
        VERDICT_BADGE_STYLES[verdict] || VERDICT_BADGE_STYLES.SUPPORTED
      const dimmed = showOnlyProblems && verdict === 'SUPPORTED'
      const evidenceText =
        vInfo.evidence ||
        (verdict === 'UNSUPPORTED'
          ? 'No supporting quote found in the cited source text.'
          : 'Verified against cited source text.')

      return (
        <span
          key={idx}
          onClick={() => {
            onTraceOpen({
              sourceId: citedIds[0] || null,
              sentenceText: sObj.text,
              verdictInfo: vInfo,
            })
          }}
          title="Click to inspect source & evidence quote"
          className={`relative group/sent inline rounded px-1.5 py-0.5 mr-1.5 leading-8 transition-all ${highlightCls} ${
            dimmed ? 'opacity-25 hover:opacity-80' : 'opacity-100'
          }`}
        >
          <InlineSentenceContent
            text={sObj.text}
            verdictInfo={vInfo}
            onTraceOpen={onTraceOpen}
          />

          {/* Hover Popover Card with Verdict & Evidence Quote */}
          <span className="pointer-events-none hidden group-hover/sent:block absolute left-0 bottom-full mb-2 w-80 md:w-96 p-3.5 rounded-[8px] bg-white border border-[#E5E7EB] shadow-lg z-30 text-left">
            <span className="flex items-center justify-between gap-2 mb-1.5">
              <span
                className={`text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border ${badgeCls}`}
              >
                {verdict}
              </span>
              <span className="text-[11px] text-[#6B7280]">
                Click sentence or [n] to trace source →
              </span>
            </span>
            <span className="block text-xs text-[#31333F] italic leading-relaxed border-l-2 border-teal-500 pl-2.5 mt-1">
              &ldquo;{evidenceText}&rdquo;
            </span>
          </span>
        </span>
      )
    })

  return (
    <article className="space-y-3 text-[#31333F]">
      {blocks.map((b, bIdx) => {
        if (b.type === 'table') {
          return (
            <div
              key={bIdx}
              className="my-4 overflow-x-auto rounded-[8px] border border-[#E5E7EB]"
            >
              <table className="w-full text-left border-collapse text-sm">
                <thead className="bg-[#F0F2F6] text-[#31333F] border-b border-[#E5E7EB]">
                  <tr>
                    {b.headers.map((h, hIdx) => (
                      <th key={hIdx} className="px-4 py-2.5 font-bold">
                        <InlineSentenceContent
                          text={h}
                          verdictInfo={null}
                          onTraceOpen={onTraceOpen}
                        />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#E5E7EB] bg-white">
                  {b.rows.map((r, rIdx) => (
                    <tr key={rIdx} className="hover:bg-[#F9FAFB]">
                      {r.map((cell, cIdx) => (
                        <td key={cIdx} className="px-4 py-2.5 text-[#31333F]">
                          <InlineSentenceContent
                            text={cell}
                            verdictInfo={null}
                            onTraceOpen={onTraceOpen}
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
        if (b.type === 'h1') {
          return (
            <h1
              key={bIdx}
              className="text-2xl font-bold text-[#31333F] border-b border-[#E5E7EB] pb-3 mb-4"
            >
              {b.text}
            </h1>
          )
        }
        if (b.type === 'h2') {
          return (
            <h2
              key={bIdx}
              className="text-xl font-bold text-[#31333F] mt-7 mb-2.5"
            >
              {b.text}
            </h2>
          )
        }
        if (b.type === 'h3' || b.type === 'h4') {
          return (
            <h3
              key={bIdx}
              className="text-lg font-semibold text-[#31333F] mt-5 mb-2"
            >
              {b.text}
            </h3>
          )
        }
        if (b.type === 'ul-item') {
          return (
            <div key={bIdx} className="flex items-start gap-2.5 pl-2">
              <span className="text-[#FF4B4B] font-bold mt-1">•</span>
              <p className="text-base leading-8 flex-1">
                {renderSentences(b.sentences)}
              </p>
            </div>
          )
        }
        if (b.type === 'ol-item') {
          return (
            <div key={bIdx} className="flex items-start gap-2.5 pl-2">
              <span className="text-[#FF4B4B] font-bold mt-1">▪</span>
              <p className="text-base leading-8 flex-1">
                {renderSentences(b.sentences)}
              </p>
            </div>
          )
        }
        return (
          <p key={bIdx} className="text-base leading-8 mb-3">
            {renderSentences(b.sentences)}
          </p>
        )
      })}
    </article>
  )
}

export default function App() {
  // Configuration & Sidebar State
  const [apiKeys, setApiKeys] = useState({ ...EMPTY_KEYS })
  const [isConfigOpen, setIsConfigOpen] = useState(false)
  const [configStatusMessage, setConfigStatusMessage] = useState(null)
  const [searchType, setSearchType] = useState('industrial')
  const [platformsInfo, setPlatformsInfo] = useState(DEFAULT_DOMESTIC_PLATFORMS)
  const [discipline, setDiscipline] = useState('Scientific & Academic Research')
  const [evaluationMode, setEvaluationMode] = useState('Standard')
  const [maxRounds, setMaxRounds] = useState(3)

  // Research Query & Additional Context State (UI + passed to POST /api/research)
  const [topic, setTopic] = useState('')
  const [uploadedFiles, setUploadedFiles] = useState([])
  const [isDraggingFile, setIsDraggingFile] = useState(false)
  const [doiOrArxiv, setDoiOrArxiv] = useState('')
  const [youtubeUrl, setYoutubeUrl] = useState('')

  // Run State
  const [isRunning, setIsRunning] = useState(false)
  const [runId, setRunId] = useState(null)
  const [activeRunSearchType, setActiveRunSearchType] = useState('industrial')

  // Live streamed state
  const [events, setEvents] = useState([])
  const [currentRound, setCurrentRound] = useState(0)
  const [searchesCount, setSearchesCount] = useState(0)
  const [keptSources, setKeptSources] = useState([])
  const [droppedSources, setDroppedSources] = useState([])
  const [planSections, setPlanSections] = useState([])
  const [conflicts, setConflicts] = useState([])
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [liveTrustStats, setLiveTrustStats] = useState(null)
  const [stoppedAtTimeLimit, setStoppedAtTimeLimit] = useState(false)

  // Final result & UI navigation state
  const [result, setResult] = useState(null)
  const [activeTab, setActiveTab] = useState('report')
  const [highlightedSourceId, setHighlightedSourceId] = useState(null)
  const [showDropped, setShowDropped] = useState(false)
  const [showOnlyProblems, setShowOnlyProblems] = useState(false)
  const [uiError, setUiError] = useState(null)

  // Click-to-trace right-side panel state
  const [tracePanelData, setTracePanelData] = useState(null)

  const feedContainerRef = useRef(null)
  const resultsSectionRef = useRef(null)
  const fileInputRef = useRef(null)
  const eventSourceRef = useRef(null)
  const timerRef = useRef(null)
  const startTimeRef = useRef(null)

  const isDomestic = searchType === 'domestic'
  const judgeMode = evaluationMode === 'Judge Mode (Critique)'

  // Fetch GET /api/platforms so Domestic banner reflects real API vs web search access
  const fetchPlatforms = useCallback(() => {
    fetch(`${API_BASE}/api/platforms`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        const list = Array.isArray(data) ? data : data?.platforms
        if (Array.isArray(list) && list.length > 0) {
          setPlatformsInfo(list)
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    fetchPlatforms()
  }, [fetchPlatforms, searchType])

  // Active Agents banner text based on searchType and chosen discipline
  const activeAgentsList = useMemo(() => {
    if (isDomestic) {
      const iconMap = {
        Reddit: '🟠',
        X: '✖️',
        Quora: '💬',
        YouTube: '▶️',
        Amazon: '🛒',
        Flipkart: '🛍️',
      }
      return platformsInfo
        .map((p) => {
          const icon = iconMap[p.name] || '🔎'
          let label = p.access || 'web search'
          if (p.name === 'X' && label === 'web search') {
            label = 'web search, limited'
          } else if (p.name === 'YouTube' && label === 'api') {
            label = 'API + transcripts'
          } else if (label === 'api') {
            label = 'API'
          }
          return `${icon} ${p.name} (${label})`
        })
        .join(' · ')
    }
    if (discipline === 'Scientific & Academic Research') {
      return '🔍 Tavily Search, 🎓 arXiv, ⚖️ Hermes Reviewer, 🧪 Truth Meter'
    }
    return '🔍 Tavily Search, ⚖️ Hermes Reviewer, 🧪 Truth Meter'
  }, [isDomestic, platformsInfo, discipline])

  const exampleTopics = isDomestic
    ? DOMESTIC_EXAMPLE_TOPICS
    : INDUSTRIAL_EXAMPLE_TOPICS

  const queryPlaceholder = isDomestic
    ? 'e.g., iPhone 15 vs Samsung S24 for an Indian buyer under ₹70,000'
    : 'e.g., Why do Indian farmers still burn crop stubble, and which solutions are actually working?'

  // Compute Platform Mix counts for Domestic runs
  const platformMixCounts = useMemo(() => {
    const counts = {
      Reddit: 0,
      YouTube: 0,
      Quora: 0,
      Amazon: 0,
      Flipkart: 0,
      X: 0,
    }
    for (const s of keptSources) {
      const p = (s.platform || '').trim()
      const d = (s.domain || '').toLowerCase()
      if (p in counts) {
        counts[p] += 1
      } else if (d.includes('reddit.com')) {
        counts.Reddit += 1
      } else if (d.includes('youtube.com') || d.includes('youtu.be')) {
        counts.YouTube += 1
      } else if (d.includes('quora.com')) {
        counts.Quora += 1
      } else if (d.includes('amazon.')) {
        counts.Amazon += 1
      } else if (d.includes('flipkart.com')) {
        counts.Flipkart += 1
      } else if (d.includes('x.com') || d.includes('twitter.com')) {
        counts.X += 1
      }
    }
    return counts
  }, [keptSources])

  // Auto-scroll Activity Feed inside its container so the page never jumps
  useEffect(() => {
    if (feedContainerRef.current) {
      feedContainerRef.current.scrollTop = feedContainerRef.current.scrollHeight
    }
  }, [events])

  // Clean up SSE and timer on unmount
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close()
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [])

  // Scroll to and highlight a source card when user clicks from Both Sides tab
  useEffect(() => {
    if (activeTab === 'sources' && highlightedSourceId !== null) {
      const timer = setTimeout(() => {
        const el = document.getElementById(`source-card-${highlightedSourceId}`)
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
      }, 80)
      return () => clearTimeout(timer)
    }
  }, [activeTab, highlightedSourceId])

  // Lookup map for kept sources by integer ID
  const sourceByIdMap = useMemo(() => {
    const map = {}
    for (const s of keptSources) {
      if (s.id !== null && s.id !== undefined) {
        map[Number(s.id)] = s
      }
    }
    return map
  }, [keptSources])

  // Open the right-side Click-to-Trace drawer (does not jump to Sources tab)
  const handleTraceOpen = useCallback(
    ({ sourceId, sentenceText, verdictInfo }) => {
      const citedIds = verdictInfo?.citations?.length
        ? verdictInfo.citations
        : extractCitationIds(sentenceText)
      const activeId = Number(sourceId || citedIds[0] || 0)
      setTracePanelData({
        activeSourceId: activeId,
        citedIds: citedIds.length > 0 ? citedIds : activeId ? [activeId] : [],
        sentenceText: sentenceText || verdictInfo?.sentence || '',
        verdictInfo: verdictInfo || null,
      })
    },
    []
  )

  const handleFilesSelected = (fileList) => {
    if (!fileList) return
    const names = Array.from(fileList).map((f) => f.name)
    setUploadedFiles((prev) => Array.from(new Set([...prev, ...names])))
  }

  const startResearch = async (selectedTopic) => {
    const cleanTopic = (selectedTopic ?? topic).trim()
    if (!cleanTopic) {
      setUiError('Please enter a research question or click one of the example topics.')
      return
    }
    if (isRunning) return

    const hasOpenRouter = Boolean((apiKeys.OPENROUTER_API_KEY || '').trim())
    const hasTavily = Boolean((apiKeys.TAVILY_API_KEY || '').trim())
    if (!hasOpenRouter || !hasTavily) {
      setIsConfigOpen(true)
      setConfigStatusMessage({
        type: 'warning',
        text: 'Add your OpenRouter and Tavily keys to start.',
      })
      return
    }

    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }

    setUiError(null)
    setTracePanelData(null)
    setIsRunning(true)
    setRunId(null)
    setActiveRunSearchType(searchType)
    setEvents([])
    setCurrentRound(1)
    setSearchesCount(0)
    setKeptSources([])
    setDroppedSources([])
    setPlanSections([])
    setConflicts([])
    setLiveTrustStats(null)
    setStoppedAtTimeLimit(false)
    setResult(null)
    setElapsedSeconds(0)
    setHighlightedSourceId(null)
    setShowOnlyProblems(false)

    startTimeRef.current = Date.now()
    timerRef.current = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startTimeRef.current) / 1000))
    }, 500)

    try {
      const resp = await fetch(`${API_BASE}/api/research`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: cleanTopic,
          max_rounds: Number(maxRounds),
          judge_mode: Boolean(judgeMode),
          search_type: searchType,
          discipline: isDomestic ? 'Product & Consumer' : discipline,
          evaluation_mode: evaluationMode,
          uploaded_files: uploadedFiles,
          doi_or_arxiv: doiOrArxiv.trim(),
          youtube_url: youtubeUrl.trim(),
        }),
      })
      if (!resp.ok) {
        throw new Error(`Backend returned HTTP ${resp.status}`)
      }
      const data = await resp.json()
      const newRunId = data.run_id
      setRunId(newRunId)

      const es = new EventSource(`${API_BASE}/api/research/${newRunId}/stream`)
      eventSourceRef.current = es

      es.onmessage = (evt) => {
        try {
          const payload = JSON.parse(evt.data)
          setEvents((prev) => [...prev, payload])

          const { type, data: evData } = payload

          if (type === 'plan' && evData?.sections) {
            setPlanSections(evData.sections)
          } else if (type === 'round' && evData?.round) {
            setCurrentRound(evData.round)
            if (evData.gaps && Array.isArray(evData.gaps)) {
              setPlanSections((prev) =>
                prev.map((sec) => {
                  const matchingGaps = evData.gaps.filter((g) => g.section_id === sec.id)
                  if (matchingGaps.length === 0) return sec
                  const existingHistory = sec.question_history || []
                  const additions = matchingGaps.map((g) => ({
                    query: g.follow_up_query,
                    round: evData.round,
                    reason: g.reason,
                  }))
                  return {
                    ...sec,
                    question_history: [...existingHistory, ...additions],
                  }
                })
              )
            }
          } else if (type === 'search_start') {
            setSearchesCount((prev) => prev + 1)
          } else if (type === 'source_scored' && evData) {
            if (evData.kept) {
              setKeptSources((prev) => [...prev, evData])
            } else {
              setDroppedSources((prev) => [...prev, evData])
            }
          } else if (type === 'conflict' && evData?.topic) {
            setConflicts((prev) => {
              const normNew = evData.topic.trim().toLowerCase()
              if (prev.some((c) => (c.topic || '').trim().toLowerCase() === normNew)) {
                return prev
              }
              return [...prev, evData]
            })
          } else if (type === 'review' && evData?.stopped_at_time_limit) {
            setStoppedAtTimeLimit(true)
          } else if (type === 'trust_score' && evData) {
            setLiveTrustStats(evData)
          } else if (type === 'done' && evData) {
            setResult(evData)
            if (evData.search_type) setActiveRunSearchType(evData.search_type)
            if (evData.plan) setPlanSections(evData.plan)
            if (evData.sources) setKeptSources(evData.sources)
            if (evData.dropped_sources) setDroppedSources(evData.dropped_sources)
            if (Array.isArray(evData.conflicts)) setConflicts(evData.conflicts)
            if (evData.rounds_used) setCurrentRound(evData.rounds_used)
            if (evData.stopped_at_time_limit) setStoppedAtTimeLimit(true)
            if (evData.stats?.searches !== undefined) setSearchesCount(evData.stats.searches)
            if (evData.stats?.seconds !== undefined) {
              setElapsedSeconds(Math.round(evData.stats.seconds))
            }
            setIsRunning(false)
            setActiveTab('report')
            if (timerRef.current) clearInterval(timerRef.current)
            es.close()
          } else if (type === 'error') {
            setUiError(payload.message || 'Pipeline encountered an error.')
            setIsRunning(false)
            if (timerRef.current) clearInterval(timerRef.current)
            es.close()
          }
        } catch (parseErr) {
          console.error('Failed to parse SSE event:', parseErr)
        }
      }

      es.onerror = () => {
        fetch(`${API_BASE}/api/research/${newRunId}/result`)
          .then((r) => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`)
            return r.json()
          })
          .then((resData) => {
            if (resData && resData.report_markdown !== undefined) {
              setResult(resData)
              if (resData.search_type) setActiveRunSearchType(resData.search_type)
              if (resData.plan) setPlanSections(resData.plan)
              if (resData.sources) setKeptSources(resData.sources)
              if (resData.dropped_sources) setDroppedSources(resData.dropped_sources)
              if (Array.isArray(resData.conflicts)) setConflicts(resData.conflicts)
              if (resData.stopped_at_time_limit) setStoppedAtTimeLimit(true)
              setIsRunning(false)
              if (timerRef.current) clearInterval(timerRef.current)
              es.close()
            } else {
              setUiError(
                'Live stream interrupted before completion. Please verify the backend server is still running on port 8000.'
              )
              setIsRunning(false)
              if (timerRef.current) clearInterval(timerRef.current)
              es.close()
            }
          })
          .catch(() => {
            setUiError(
              'Connection to the backend server (http://localhost:8000) was lost mid-run. Please restart the backend server and try again.'
            )
            setIsRunning(false)
            if (timerRef.current) clearInterval(timerRef.current)
            es.close()
          })
      }
    } catch (err) {
      setUiError(err.message || 'Failed to connect to backend.')
      setIsRunning(false)
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }

  // Group kept sources by section for the Sources tab
  const sourcesBySection = useMemo(() => {
    const groups = {}
    for (const sec of planSections) {
      groups[sec.id] = {
        id: sec.id,
        title: sec.title,
        items: [],
      }
    }
    const ungrouped = []
    for (const src of keptSources) {
      const secId = src.section_id
      if (secId && groups[secId]) {
        groups[secId].items.push(src)
      } else {
        ungrouped.push(src)
      }
    }
    const list = Object.values(groups)
    if (ungrouped.length > 0) {
      list.push({
        id: 'other',
        title: 'Additional Sources',
        items: ungrouped,
      })
    }
    return list
  }, [planSections, keptSources])

  // Compute Truth Meter summary counts & ring styling
  const truthSummary = useMemo(() => {
    const verdicts = result?.sentences_with_verdicts || []
    if (verdicts.length > 0) {
      const supported = verdicts.filter((v) => v.verdict === 'SUPPORTED').length
      const partial = verdicts.filter((v) => v.verdict === 'PARTIAL').length
      const unsupported = verdicts.filter((v) => v.verdict === 'UNSUPPORTED').length
      const score =
        result?.trust_score !== undefined && result?.trust_score !== null
          ? result.trust_score
          : Math.round((supported * 100) / verdicts.length)
      return {
        hasData: true,
        score,
        supported,
        partial,
        unsupported,
        total: verdicts.length,
      }
    }
    if (liveTrustStats && liveTrustStats.trust_score !== null) {
      return {
        hasData: true,
        score: liveTrustStats.trust_score,
        supported: liveTrustStats.supported || 0,
        partial: liveTrustStats.partial || 0,
        unsupported: liveTrustStats.unsupported || 0,
        total: liveTrustStats.total || 0,
      }
    }
    return {
      hasData: false,
      score: null,
      supported: 0,
      partial: 0,
      unsupported: 0,
      total: 0,
    }
  }, [result, liveTrustStats])

  // Extract 3 to 4 Key Findings bullets from the report's summary section (no extra LLM call)
  const keyFindings = useMemo(
    () => extractKeyFindingsFromReport(result?.report_markdown),
    [result?.report_markdown]
  )

  // Derive Live Agent Graph node states and live numbers strictly from real SSE events
  const graphState = useMemo(() => {
    const hasRunStarted = isRunning || events.length > 0 || Boolean(result)
    if (!hasRunStarted) {
      return {
        apollo: { status: 'waiting', metric: '0 sections' },
        athena: { status: 'waiting', metric: '0 sources' },
        hermes: { status: 'waiting', metric: '0 gaps · 0 conflicts' },
        writer: { status: 'waiting', metric: '0/0 sections' },
        truthMeter: { status: 'waiting', metric: '—' },
        loopActive: false,
        loopRound: 1,
        domesticPlatformStatus: {},
      }
    }

    let hasPlan = false
    let hasSearchStart = false
    let hasReview = false
    let hasWriting = false
    let hasAssemblyDone = false
    let hasTruthCheck = false
    let hasTrustScore = false
    let hasDone = Boolean(result)
    let latestRound = 1
    let totalGaps = 0
    let sectionsDrafted = 0
    const domesticPlatformStatus = {}

    for (const ev of events) {
      if (ev.type === 'plan') hasPlan = true
      if (ev.type === 'search_start') {
        hasSearchStart = true
        if (ev.data?.platform && !(ev.data.platform in domesticPlatformStatus)) {
          domesticPlatformStatus[ev.data.platform] = 'searching'
        }
      }
      if (ev.type === 'search_result' && ev.data?.platform) {
        const c = ev.data.count ?? 0
        if (c > 0 || domesticPlatformStatus[ev.data.platform] === 'green') {
          domesticPlatformStatus[ev.data.platform] = 'green'
        } else {
          domesticPlatformStatus[ev.data.platform] = 'grey'
        }
      }
      if (ev.type === 'review') {
        hasReview = true
        if (ev.data?.gaps_count !== undefined) {
          totalGaps = ev.data.gaps_count
        }
      }
      if (ev.type === 'round' && (ev.data?.round || 1) > 1) {
        latestRound = ev.data.round
      }
      if (ev.type === 'writing') {
        hasWriting = true
        if (ev.data?.stage === 'section_done' || ev.data?.stage === 'section_empty') {
          sectionsDrafted += 1
        }
        if (ev.data?.stage === 'assembly_done') {
          hasAssemblyDone = true
        }
      }
      if (ev.type === 'truth_check') hasTruthCheck = true
      if (ev.type === 'trust_score') hasTrustScore = true
      if (ev.type === 'done') hasDone = true
    }

    const lastEvent = events[events.length - 1]
    const lastType = lastEvent?.type || ''

    // Determine each node's status ('waiting' | 'running' | 'done' | 'warning')
    const apolloStatus = hasDone || hasPlan ? 'done' : isRunning ? 'running' : 'waiting'

    let athenaStatus = 'waiting'
    if (hasDone || hasWriting || hasTruthCheck) {
      athenaStatus = keptSources.length > 0 ? 'done' : 'warning'
    } else if (
      lastType === 'search_start' ||
      lastType === 'search_result' ||
      lastType === 'source_scored' ||
      lastType === 'round'
    ) {
      athenaStatus = 'running'
    } else if (hasSearchStart) {
      athenaStatus = 'done'
    }

    let hermesStatus = 'waiting'
    if (hasDone || hasWriting || hasTruthCheck) {
      hermesStatus = 'done'
    } else if (lastType === 'review' || lastType === 'gap' || lastType === 'conflict') {
      hermesStatus = 'running'
    } else if (hasReview) {
      hermesStatus = 'done'
    }

    let writerStatus = 'waiting'
    if (hasDone || hasTruthCheck || hasAssemblyDone) {
      writerStatus = 'done'
    } else if (hasWriting) {
      writerStatus = 'running'
    }

    let truthStatus = 'waiting'
    if (hasDone || hasTrustScore) {
      truthStatus = 'done'
    } else if (hasTruthCheck) {
      truthStatus = 'running'
    }

    const totalSec = planSections.length
    const shownDrafted = hasDone || hasAssemblyDone ? totalSec : Math.min(sectionsDrafted, totalSec)

    return {
      apollo: {
        status: apolloStatus,
        metric: `${totalSec} section${totalSec === 1 ? '' : 's'}`,
      },
      athena: {
        status: athenaStatus,
        metric: `${keptSources.length} source${keptSources.length === 1 ? '' : 's'}`,
      },
      hermes: {
        status: hermesStatus,
        metric: `${totalGaps} gap${totalGaps === 1 ? '' : 's'} · ${conflicts.length} conflict${
          conflicts.length === 1 ? '' : 's'
        }`,
      },
      writer: {
        status: writerStatus,
        metric: `${shownDrafted}/${totalSec} sections`,
      },
      truthMeter: {
        status: truthStatus,
        metric:
          truthSummary.score !== null
            ? `${truthSummary.score}% trusted`
            : hasTruthCheck
            ? 'Checking...'
            : '—',
      },
      loopActive: latestRound > 1,
      loopRound: latestRound,
      domesticPlatformStatus,
    }
  }, [
    isRunning,
    events,
    result,
    planSections.length,
    keptSources.length,
    conflicts.length,
    truthSummary.score,
  ])

  const activityFeedItems = useMemo(() => buildActivityFeedItems(events), [events])

  // Ring color per spec: green 80+, yellow 60 to 79, red below 60
  const getTrustRingTheme = (score) => {
    if (score === null || score === undefined) {
      return {
        stroke: '#9CA3AF',
        text: 'text-[#6B7280]',
        border: 'border-[#E5E7EB]',
        bg: 'bg-[#F9FAFB]',
        label: 'Awaiting Verification',
      }
    }
    if (score >= 80) {
      return {
        stroke: '#16A34A',
        text: 'text-[#16A34A]',
        border: 'border-[#C8E6C9]',
        bg: 'bg-[#E8F5E9]/60',
        label: 'High Trust',
      }
    }
    if (score >= 60) {
      return {
        stroke: '#D97706',
        text: 'text-amber-700',
        border: 'border-amber-200',
        bg: 'bg-amber-50/70',
        label: 'Moderate Trust',
      }
    }
    return {
      stroke: '#DC2626',
      text: 'text-red-700',
      border: 'border-red-200',
      bg: 'bg-red-50/70',
      label: 'Low Trust',
    }
  }

  const ringTheme = getTrustRingTheme(truthSummary.score)
  const circumference = 2 * Math.PI * 28
  const strokeDashoffset =
    truthSummary.score !== null
      ? circumference - (Math.max(0, Math.min(100, truthSummary.score)) / 100) * circumference
      : circumference

  // Export handlers (Phase 5)
  const handleDownloadMarkdown = () => {
    if (!result?.report_markdown) return
    const trustLine = truthSummary.hasData
      ? `> **Trust Score: ${truthSummary.score}%** (${truthSummary.supported} supported, ${truthSummary.partial} partial, ${truthSummary.unsupported} unsupported)\n\n`
      : ''
    const refLines =
      keptSources.length > 0
        ? '\n\n---\n\n## References\n\n' +
          keptSources
            .map(
              (s) =>
                `[${s.id}] **${s.title || s.url}** (${s.domain}, ${
                  s.published_date || 'Date unknown'
                }, Score: ${s.score}/100 ${s.badge}) — ${s.url}`
            )
            .join('\n\n')
        : ''
    const fullMd = `${trustLine}${result.report_markdown}${refLines}\n`
    const blob = new Blob([fullMd], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `apollo-report-${runId || 'export'}.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const handleDownloadPDF = () => {
    window.print()
  }

  // Helper to render clickable source chips with Quality badges inside Both Sides cards
  const renderSourceChips = (sourceIds = [], claimText = '') => {
    return (
      <div className="flex flex-wrap gap-2 mt-3 pt-2.5 border-t border-[#E5E7EB]">
        {sourceIds.map((rawId) => {
          const sid = Number(rawId)
          const src = sourceByIdMap[sid]
          const badge = src?.badge || 'High'
          const score = src?.score
          const domain = src?.domain || `Source #${sid}`
          const qStyle = QUALITY_BADGE_STYLES[badge] || QUALITY_BADGE_STYLES.Medium

          return (
            <button
              key={sid}
              type="button"
              onClick={() =>
                handleTraceOpen({
                  sourceId: sid,
                  sentenceText: claimText,
                  verdictInfo: null,
                })
              }
              title={
                src
                  ? `Inspect [${sid}] ${src.title} (${badge} ${score}/100)`
                  : `Inspect Source [${sid}]`
              }
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[8px] bg-white hover:bg-[#F0F2F6] border border-[#E5E7EB] hover:border-[#FF4B4B] transition cursor-pointer text-xs group"
            >
              <span className="font-bold text-blue-700">[{sid}]</span>
              <span className="text-[#31333F] font-mono truncate max-w-[140px]">
                {domain}
              </span>
              {src && (
                <span
                  className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${qStyle}`}
                >
                  {badge} {score}
                </span>
              )}
            </button>
          )
        })}
      </div>
    )
  }

  const hasRunActivity = isRunning || events.length > 0 || Boolean(result)
  const isResultsDomestic =
    (hasRunActivity ? activeRunSearchType : searchType) === 'domestic'
  const totalSourcesRead = keptSources.length + droppedSources.length

  // Node visual helper for Live Agent Graph
  const renderGraphNode = (title, roleLabel, nodeObj, extraFooter = null) => {
    const st = nodeObj.status
    let boxStyle = 'border-[#E5E7EB] bg-white text-[#6B7280]'
    let statusBadge = (
      <span className="text-[11px] font-medium text-[#6B7280]">Waiting</span>
    )

    if (st === 'running') {
      boxStyle = 'border-[#2563EB] bg-[#EFF6FF] text-[#1E3A8A]'
      statusBadge = (
        <span className="inline-flex items-center gap-1.5 text-[11px] font-bold text-[#2563EB]">
          <span className="h-2 w-2 rounded-full bg-[#2563EB] animate-ping" />
          Running
        </span>
      )
    } else if (st === 'done') {
      boxStyle = 'border-[#16A34A] bg-[#F0FDF4] text-[#166534]'
      statusBadge = (
        <span className="inline-flex items-center gap-1 text-[11px] font-bold text-[#16A34A]">
          <span>✓</span> Done
        </span>
      )
    } else if (st === 'warning') {
      boxStyle = 'border-[#D97706] bg-amber-50 text-amber-800'
      statusBadge = (
        <span className="inline-flex items-center gap-1 text-[11px] font-bold text-[#D97706]">
          ⚠ Warning
        </span>
      )
    }

    return (
      <div className="flex-1 min-w-[140px] flex flex-col items-center">
        <div
          className={`w-full rounded-[8px] border-2 px-3 py-2.5 text-center transition ${boxStyle}`}
        >
          <div className="text-sm font-bold text-[#31333F]">{title}</div>
          <div className="text-[11px] text-[#6B7280]">{roleLabel}</div>
          <div className="mt-1.5 flex items-center justify-center">
            {statusBadge}
          </div>
        </div>
        <div className="mt-1.5 text-xs font-semibold text-[#31333F]">
          {nodeObj.metric}
        </div>
        {extraFooter}
      </div>
    )
  }

  const tracedSource =
    tracePanelData?.activeSourceId != null
      ? sourceByIdMap[Number(tracePanelData.activeSourceId)] || null
      : null

  return (
    <div className="min-h-screen bg-white text-[#31333F] font-sans overflow-x-hidden">
      <div className="no-print flex min-h-screen">
        {/* 1. LEFT SIDEBAR (fixed ~280px-300px wide, scrolls on its own, #F0F2F6 background) */}
        <aside className="w-[280px] xl:w-[300px] shrink-0 bg-[#F0F2F6] border-r border-[#E5E7EB] h-screen sticky top-0 overflow-y-auto px-5 py-6 flex flex-col gap-5">
          {/* ⚙️ Configuration + 🔑 API Keys Collapsible White Card */}
          <ConfigPanel
            apiBase={API_BASE}
            keys={apiKeys}
            setKeys={setApiKeys}
            isOpen={isConfigOpen}
            setIsOpen={setIsConfigOpen}
            statusMessage={configStatusMessage}
            setStatusMessage={setConfigStatusMessage}
            onKeysSaved={fetchPlatforms}
          />

          {/* Thin Divider */}
          <hr className="border-t border-[#E5E7EB]" />

          {/* 📚 Research Discipline */}
          <div>
            <h2 className="text-[17px] font-bold text-[#31333F] mb-2.5">
              📚 Research Discipline
            </h2>
            <label
              htmlFor="discipline-select"
              className="block text-xs font-normal text-[#31333F] mb-1.5"
            >
              Select Discipline
            </label>
            {isDomestic ? (
              <select
                id="discipline-select"
                value="Product & Consumer"
                disabled
                className="w-full rounded-[8px] bg-white/70 border border-[#E5E7EB] px-3 py-2.5 text-sm text-[#6B7280] cursor-not-allowed"
              >
                <option value="Product & Consumer">Product &amp; Consumer</option>
              </select>
            ) : (
              <select
                id="discipline-select"
                value={discipline}
                onChange={(e) => setDiscipline(e.target.value)}
                disabled={isRunning}
                className="w-full rounded-[8px] bg-white border border-transparent focus:border-[#FF4B4B] px-3 py-2.5 text-sm text-[#31333F] focus:outline-none cursor-pointer transition"
              >
                {DISCIPLINES.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* ⚖️ Evaluation Mode */}
          <div>
            <h2 className="text-[17px] font-bold text-[#31333F] mb-2.5">
              ⚖️ Evaluation Mode
            </h2>
            <label
              htmlFor="eval-mode-select"
              className="block text-xs font-normal text-[#31333F] mb-1.5"
            >
              Mode
            </label>
            <select
              id="eval-mode-select"
              value={evaluationMode}
              onChange={(e) => setEvaluationMode(e.target.value)}
              disabled={isRunning}
              className="w-full rounded-[8px] bg-white border border-transparent focus:border-[#FF4B4B] px-3 py-2.5 text-sm text-[#31333F] focus:outline-none cursor-pointer transition"
            >
              <option value="Standard">Standard</option>
              <option value="Judge Mode (Critique)">Judge Mode (Critique)</option>
              <option value="Debate Mode (Pro/Con)" disabled>
                Debate Mode (Pro/Con) (coming soon)
              </option>
            </select>
          </div>

          {/* Max Review Rounds Slider (compact in sidebar) */}
          <div className="pt-2 border-t border-[#E5E7EB]">
            <div className="flex items-center justify-between text-xs font-medium text-[#31333F] mb-1.5">
              <span>Max Review Rounds</span>
              <span className="font-bold text-[#FF4B4B]">{maxRounds}</span>
            </div>
            <input
              type="range"
              min={1}
              max={3}
              step={1}
              value={maxRounds}
              onChange={(e) => setMaxRounds(Number(e.target.value))}
              disabled={isRunning}
              className="w-full accent-[#FF4B4B] cursor-pointer"
            />
            <div className="flex justify-between text-[11px] text-[#6B7280] mt-0.5">
              <span>1</span>
              <span>2</span>
              <span>3</span>
            </div>
          </div>
        </aside>

        {/* 2. MAIN AREA (centered, max width ~1040px, generous padding, fits 1366x768 cleanly) */}
        <main className="flex-1 min-w-0 bg-white overflow-y-auto">
          <div className="max-w-[1040px] mx-auto px-6 md:px-10 py-8">
            {/* Title & Subtitle */}
            <h1 className="text-4xl font-bold text-[#31333F] tracking-tight mb-2.5">
              🏛️ Apollo
            </h1>
            <p className="text-lg font-bold text-[#31333F] mb-5">
              Deep, multi-agent research you can trust.
            </p>

            {/* Green Active Agents Banner (#E8F5E9 bg, #2E7D32 text, 8px radius) */}
            <div className={isDomestic ? 'mb-2' : 'mb-6'}>
              <div className="w-full rounded-[8px] bg-[#E8F5E9] text-[#2E7D32] px-4 py-3 text-sm font-medium">
                <span className="font-bold">✅ Active Agents: </span>
                <span>{activeAgentsList}</span>
              </div>
              {isDomestic && (
                <p className="text-xs text-[#6B7280] mt-1.5 px-1">
                  No API key for some platforms, so Apollo searches them through site-limited web search. X and Amazon may return fewer results.
                </p>
              )}
            </div>

            {/* 1. "How Apollo works" strip (above Search Type, only shown before a run starts) */}
            {!hasRunActivity && (
              <div className="mb-6 mt-4 flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                <div className="flex-1 rounded-[8px] border border-[#E5E7EB] bg-white px-3.5 py-2.5 flex items-center gap-2.5">
                  <span className="text-base">💬</span>
                  <div>
                    <div className="text-xs font-bold text-[#31333F]">
                      1. You ask
                    </div>
                    <div className="text-xs text-[#6B7280]">
                      one research question
                    </div>
                  </div>
                </div>

                <span className="hidden sm:inline text-[#6B7280] text-sm px-1">
                  →
                </span>

                <div className="flex-1 rounded-[8px] border border-[#E5E7EB] bg-white px-3.5 py-2.5 flex items-center gap-2.5">
                  <span className="text-base">⚙️</span>
                  <div>
                    <div className="text-xs font-bold text-[#31333F]">
                      2. Agents research
                    </div>
                    <div className="text-xs text-[#6B7280]">
                      plan, search, review, fact-check, live on screen
                    </div>
                  </div>
                </div>

                <span className="hidden sm:inline text-[#6B7280] text-sm px-1">
                  →
                </span>

                <div className="flex-1 rounded-[8px] border border-[#E5E7EB] bg-white px-3.5 py-2.5 flex items-center gap-2.5">
                  <span className="text-base">🛡️</span>
                  <div>
                    <div className="text-xs font-bold text-[#31333F]">
                      3. You get a trusted report
                    </div>
                    <div className="text-xs text-[#6B7280]">
                      citations, Trust Score, both sides
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Choose Search Type (ABOVE Research Query) */}
            <div className="mb-7">
              <h2 className="text-lg font-bold text-[#31333F] mb-2.5">
                Choose Search Type
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Domestic Search Card */}
                <button
                  type="button"
                  disabled={isRunning}
                  onClick={() => setSearchType('domestic')}
                  className={`text-left p-4 rounded-[8px] border transition cursor-pointer disabled:opacity-60 ${
                    searchType === 'domestic'
                      ? 'border-[#FF4B4B] bg-[#FFF1F1]'
                      : 'border-[#E5E7EB] bg-white hover:bg-[#F9FAFB]'
                  }`}
                >
                  <div className="text-lg font-bold text-[#31333F]">
                    🏠 Domestic Search
                  </div>
                  <div className="text-sm font-medium text-[#31333F] mt-0.5">
                    Products, reviews and real user opinions
                  </div>
                  <div className="text-xs text-[#6B7280] mt-1">
                    Reddit · X · Quora · YouTube · Amazon · Flipkart
                  </div>
                </button>

                {/* Industrial Search Card */}
                <button
                  type="button"
                  disabled={isRunning}
                  onClick={() => setSearchType('industrial')}
                  className={`text-left p-4 rounded-[8px] border transition cursor-pointer disabled:opacity-60 ${
                    searchType === 'industrial'
                      ? 'border-[#FF4B4B] bg-[#FFF1F1]'
                      : 'border-[#E5E7EB] bg-white hover:bg-[#F9FAFB]'
                  }`}
                >
                  <div className="text-lg font-bold text-[#31333F]">
                    🏭 Industrial Search
                  </div>
                  <div className="text-sm font-medium text-[#31333F] mt-0.5">
                    Research, papers, markets and policy
                  </div>
                  <div className="text-xs text-[#6B7280] mt-1">
                    Web · arXiv · official sources
                  </div>
                </button>
              </div>
            </div>

            {/* Two Columns: Research Query (left 60%) & Additional Context (right 40%) */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-7 items-start">
              {/* Left Column (~60% -> 7 of 12 cols) */}
              <div className="lg:col-span-7 flex flex-col">
                <h2 className="text-2xl font-bold text-[#31333F] mb-1.5">
                  Research Query
                </h2>
                <label
                  htmlFor="topic-textarea"
                  className="text-xs text-[#6B7280] mb-2"
                >
                  Enter your complex research question here...
                </label>

                <div className="relative">
                  <textarea
                    id="topic-textarea"
                    rows={8}
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    onKeyDown={(e) => {
                      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !isRunning) {
                        startResearch()
                      }
                    }}
                    disabled={isRunning}
                    placeholder={queryPlaceholder}
                    className="w-full rounded-[8px] bg-[#F0F2F6] border border-transparent focus:border-[#FF4B4B] p-4 text-base text-[#31333F] placeholder-[#6B7280] focus:outline-none resize-y leading-relaxed transition"
                  />
                  <span className="pointer-events-none absolute right-3 bottom-2.5 text-[11px] text-[#6B7280]">
                    Press Ctrl+Enter to apply
                  </span>
                </div>

                {/* Example Topic Chips styled as small grey pills */}
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="text-xs text-[#6B7280] font-medium">
                    Examples:
                  </span>
                  {exampleTopics.map((ex, idx) => (
                    <button
                      key={idx}
                      type="button"
                      disabled={isRunning}
                      onClick={() => setTopic(ex)}
                      className={`text-xs text-left px-3 py-1.5 rounded-full transition cursor-pointer disabled:opacity-50 ${
                        topic === ex
                          ? 'bg-[#FF4B4B]/10 text-[#FF4B4B] border border-[#FF4B4B]/40 font-medium'
                          : 'bg-[#F0F2F6] hover:bg-[#E5E7EB] text-[#31333F]'
                      }`}
                    >
                      {ex}
                    </button>
                  ))}
                </div>
              </div>

              {/* Right Column (~40% -> 5 of 12 cols) */}
              <div className="lg:col-span-5 flex flex-col">
                <h2 className="text-2xl font-bold text-[#31333F] mb-1.5">
                  Additional Context
                </h2>
                <label className="text-xs text-[#31333F] mb-2">
                  Upload Notes/Docs (PDF, md, txt)
                </label>

                {/* Drag and drop box */}
                <div
                  onDragOver={(e) => {
                    e.preventDefault()
                    setIsDraggingFile(true)
                  }}
                  onDragLeave={() => setIsDraggingFile(false)}
                  onDrop={(e) => {
                    e.preventDefault()
                    setIsDraggingFile(false)
                    handleFilesSelected(e.dataTransfer.files)
                  }}
                  className={`rounded-[8px] bg-[#F8F9FB] border p-4 mb-4 transition ${
                    isDraggingFile
                      ? 'border-[#FF4B4B] bg-[#FFF5F5]'
                      : 'border-transparent'
                  }`}
                >
                  <p className="text-sm font-medium text-[#31333F]">
                    Drag and drop file here
                  </p>
                  <p className="text-xs text-[#6B7280] mt-0.5 mb-3">
                    Limit 200MB per file • PDF, TXT, MD
                  </p>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.txt,.md"
                    multiple
                    onChange={(e) => handleFilesSelected(e.target.files)}
                    className="hidden"
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="px-3.5 py-1.5 rounded-[8px] bg-white hover:bg-[#F0F2F6] border border-[#E5E7EB] text-sm font-medium text-[#31333F] transition cursor-pointer"
                  >
                    Browse files
                  </button>

                  {uploadedFiles.length > 0 && (
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {uploadedFiles.map((fname, i) => (
                        <span
                          key={i}
                          className="inline-flex items-center gap-1 text-xs bg-white border border-[#E5E7EB] rounded px-2 py-0.5 text-[#31333F]"
                        >
                          📄 {fname}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <p className="text-sm text-[#31333F] mb-2.5">Or provide links:</p>

                <div className="space-y-3">
                  <div>
                    <label
                      htmlFor="doi-input"
                      className="block text-xs text-[#31333F] mb-1.5"
                    >
                      DOI or arXiv ID (Optional)
                    </label>
                    <input
                      id="doi-input"
                      type="text"
                      value={doiOrArxiv}
                      onChange={(e) => setDoiOrArxiv(e.target.value)}
                      disabled={isRunning}
                      className="w-full rounded-[8px] bg-[#F0F2F6] border border-transparent focus:border-[#FF4B4B] px-3 py-2 text-sm text-[#31333F] focus:outline-none transition"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="youtube-input"
                      className="block text-xs text-[#31333F] mb-1.5"
                    >
                      YouTube Video URL (Optional)
                    </label>
                    <input
                      id="youtube-input"
                      type="text"
                      value={youtubeUrl}
                      onChange={(e) => setYoutubeUrl(e.target.value)}
                      disabled={isRunning}
                      className="w-full rounded-[8px] bg-[#F0F2F6] border border-transparent focus:border-[#FF4B4B] px-3 py-2 text-sm text-[#31333F] focus:outline-none transition"
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* Full-Width Red Start Button */}
            <div className="mt-7">
              <button
                type="button"
                onClick={() => startResearch()}
                disabled={isRunning}
                className="w-full py-3.5 px-6 rounded-[8px] bg-[#FF4B4B] hover:bg-[#E03E3E] active:bg-[#CC3333] disabled:opacity-60 text-white font-bold text-base transition flex items-center justify-center gap-2 cursor-pointer disabled:cursor-not-allowed"
              >
                {isRunning ? (
                  <>
                    <span className="h-4 w-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    <span>Running Deep Research...</span>
                  </>
                ) : (
                  <span>🚀 Start Deep Research</span>
                )}
              </button>
            </div>

            {uiError && (
              <div className="mt-4 rounded-[8px] border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                <strong>Error:</strong> {uiError}
              </div>
            )}

            {/* 3. RESULTS AREA (Below Start Button) */}
            <div
              ref={resultsSectionRef}
              className="mt-8 pt-7 border-t border-[#E5E7EB] space-y-6"
            >
              {!hasRunActivity ? (
                /* Empty state placeholder before a run */
                <div className="rounded-[8px] border border-[#E5E7EB] bg-[#F9FAFB] py-12 px-6 text-center">
                  <p className="text-base text-[#6B7280] font-medium">
                    Your report will appear here. Watch the agents work live once you start.
                  </p>
                </div>
              ) : (
                <>
                  {/* 4. Bigger & Clearer Live Counters Row */}
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                    <div className="rounded-[8px] border border-[#E5E7EB] bg-white px-4 py-3">
                      <div className="text-xs font-medium text-[#6B7280]">
                        Sources read
                      </div>
                      <div className="text-2xl font-bold text-[#31333F] mt-0.5">
                        <AnimatedNumber value={totalSourcesRead} />
                      </div>
                      <div className="text-[11px] text-[#2E7D32] font-medium">
                        {keptSources.length} kept
                      </div>
                    </div>

                    <div className="rounded-[8px] border border-[#E5E7EB] bg-white px-4 py-3">
                      <div className="text-xs font-medium text-[#6B7280]">
                        Sources dropped
                      </div>
                      <div className="text-2xl font-bold text-orange-600 mt-0.5">
                        <AnimatedNumber value={droppedSources.length} />
                      </div>
                      <div className="text-[11px] text-[#6B7280]">
                        score &lt; 35
                      </div>
                    </div>

                    <div className="rounded-[8px] border border-[#E5E7EB] bg-white px-4 py-3">
                      <div className="text-xs font-medium text-[#6B7280]">
                        Round
                      </div>
                      <div className="text-2xl font-bold text-[#31333F] mt-0.5">
                        {currentRound || 1}/{maxRounds}
                      </div>
                      <div className="text-[11px] text-[#6B7280]">
                        <AnimatedNumber value={searchesCount} /> searches
                      </div>
                    </div>

                    <div className="rounded-[8px] border border-[#E5E7EB] bg-white px-4 py-3">
                      <div className="text-xs font-medium text-[#6B7280]">
                        Time
                      </div>
                      <div className="text-2xl font-bold text-[#31333F] mt-0.5">
                        <AnimatedNumber value={elapsedSeconds} suffix="s" />
                      </div>
                      <div className="text-[11px] text-[#6B7280]">
                        {isRunning ? 'in progress' : 'completed'}
                      </div>
                    </div>

                    <div className="rounded-[8px] border border-[#E5E7EB] bg-white px-4 py-3">
                      <div className="text-xs font-medium text-[#6B7280]">
                        Trust Score
                      </div>
                      <div
                        className={`text-2xl font-bold mt-0.5 ${
                          truthSummary.score !== null
                            ? ringTheme.text
                            : 'text-[#6B7280]'
                        }`}
                      >
                        {truthSummary.score !== null ? (
                          <AnimatedNumber value={truthSummary.score} suffix="%" />
                        ) : (
                          '—'
                        )}
                      </div>
                      <div className="text-[11px] text-[#6B7280]">
                        {truthSummary.score !== null
                          ? `${truthSummary.supported}/${truthSummary.total} verified`
                          : 'verifying at end'}
                      </div>
                    </div>
                  </div>

                  {/* 2. Live Agent Graph Card (above results tabs, full width) */}
                  <section className="rounded-[8px] border border-[#E5E7EB] bg-white p-5">
                    <div className="flex items-center justify-between mb-4">
                      <h2 className="text-base font-bold text-[#31333F]">
                        Live agent graph
                      </h2>
                      {graphState.loopActive && (
                        <span className="text-xs font-bold px-2.5 py-0.5 rounded-full bg-blue-50 text-[#2563EB] border border-blue-200">
                          Round {graphState.loopRound} loop active
                        </span>
                      )}
                    </div>

                    {/* Nodes Row: Apollo -> Athena -> Hermes -> Writer -> Truth Meter */}
                    <div className="flex flex-wrap lg:flex-nowrap items-start justify-between gap-2">
                      {renderGraphNode(
                        'Apollo',
                        'Planner',
                        graphState.apollo
                      )}

                      <div className="hidden lg:flex items-center pt-7 text-[#6B7280] font-bold">
                        →
                      </div>

                      {renderGraphNode(
                        'Athena',
                        'Search',
                        graphState.athena,
                        isResultsDomestic && (
                          <div className="mt-2 flex flex-wrap justify-center gap-1 max-w-[190px]">
                            {GRAPH_DOMESTIC_PLATFORMS.map((pName) => {
                              const count = platformMixCounts[pName] || 0
                              const st = graphState.domesticPlatformStatus[pName]
                              const isGreen = count > 0 || st === 'green'
                              return (
                                <span
                                  key={pName}
                                  className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${
                                    isGreen
                                      ? 'border-[#16A34A] bg-[#E8F5E9] text-[#2E7D32]'
                                      : 'border-[#E5E7EB] bg-[#F0F2F6] text-[#6B7280]'
                                  }`}
                                >
                                  {pName}
                                </span>
                              )
                            })}
                          </div>
                        )
                      )}

                      <div className="hidden lg:flex items-center pt-7 text-[#6B7280] font-bold">
                        →
                      </div>

                      {renderGraphNode(
                        'Hermes',
                        'Review',
                        graphState.hermes
                      )}

                      <div className="hidden lg:flex items-center pt-7 text-[#6B7280] font-bold">
                        →
                      </div>

                      {renderGraphNode(
                        'Writer',
                        'Draft & Assemble',
                        graphState.writer
                      )}

                      <div className="hidden lg:flex items-center pt-7 text-[#6B7280] font-bold">
                        →
                      </div>

                      {renderGraphNode(
                        'Truth Meter',
                        'Fact Check',
                        graphState.truthMeter
                      )}
                    </div>

                    {/* Curved dashed arrow from Hermes back to Athena */}
                    <div className="mt-3 pt-2 flex flex-col items-center">
                      <svg
                        viewBox="0 0 500 34"
                        className="w-full max-w-[460px] h-8 overflow-visible"
                      >
                        <path
                          d="M 345 4 Q 250 32 155 4"
                          fill="none"
                          stroke={graphState.loopActive ? '#2563EB' : '#9CA3AF'}
                          strokeWidth={graphState.loopActive ? '2' : '1.5'}
                          strokeDasharray="5,4"
                        />
                        <polygon
                          points="155,4 163,2 160,10"
                          fill={graphState.loopActive ? '#2563EB' : '#9CA3AF'}
                        />
                      </svg>
                      <span
                        className={`text-xs -mt-2 px-2 py-0.5 rounded ${
                          graphState.loopActive
                            ? 'bg-[#EFF6FF] text-[#2563EB] font-bold border border-blue-200'
                            : 'text-[#6B7280]'
                        }`}
                      >
                        {graphState.loopActive
                          ? `Round ${graphState.loopRound} · gap found, search again`
                          : 'gap found, search again'}
                      </span>
                    </div>
                  </section>

                  {/* 3. Activity Feed Card */}
                  <section className="rounded-[8px] border border-[#E5E7EB] bg-white overflow-hidden">
                    <div className="border-b border-[#E5E7EB] px-5 py-3 bg-[#F9FAFB] flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span
                          className={`h-2.5 w-2.5 rounded-full ${
                            isRunning
                              ? 'bg-[#16A34A] animate-pulse'
                              : 'bg-blue-600'
                          }`}
                        />
                        <h2 className="text-base font-bold text-[#31333F]">
                          Activity feed
                        </h2>
                      </div>
                      {runId && (
                        <span className="text-xs font-mono text-[#6B7280]">
                          run: {runId}
                        </span>
                      )}
                    </div>

                    <div
                      ref={feedContainerRef}
                      className="max-h-56 overflow-y-auto p-4 space-y-2 bg-white"
                    >
                      {activityFeedItems.length === 0 ? (
                        <p className="text-sm text-[#6B7280] py-4 text-center">
                          Initializing research agents...
                        </p>
                      ) : (
                        activityFeedItems.map((item, idx) => {
                          const badgeStyle =
                            AGENT_STYLES[item.agent] || AGENT_STYLES.System
                          const isWarning = item.type === 'warning'
                          const isConflict = item.type === 'conflict'

                          return (
                            <div
                              key={idx}
                              className={`rounded-[8px] border px-3.5 py-2 flex items-center justify-between gap-3 text-sm ${
                                isWarning
                                  ? 'border-amber-200 bg-amber-50/70 text-amber-900'
                                  : isConflict
                                  ? 'border-orange-200 bg-orange-50/70 text-orange-950'
                                  : 'border-[#E5E7EB] bg-[#F9FAFB] text-[#31333F]'
                              }`}
                            >
                              <div className="flex items-center gap-2.5 min-w-0">
                                <span
                                  className={`text-xs font-bold px-2 py-0.5 rounded border shrink-0 ${badgeStyle}`}
                                >
                                  {item.agent}
                                </span>
                                {isConflict && (
                                  <span className="text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-orange-100 text-orange-800 border border-orange-300 shrink-0">
                                    Conflict found
                                  </span>
                                )}
                                <span className="text-sm leading-snug break-words">
                                  {item.text}
                                </span>
                              </div>
                              <span className="text-xs font-mono text-[#6B7280] shrink-0">
                                {formatTime(item.ts)}
                              </span>
                            </div>
                          )
                        })
                      )}
                    </div>
                  </section>

                  {/* Platform Mix Row (above the tabs for Domestic runs) */}
                  {isResultsDomestic && (
                    <div className="rounded-[8px] border border-[#E5E7EB] bg-[#F9FAFB] px-4 py-3 flex flex-wrap items-center gap-2">
                      <span className="text-xs font-bold uppercase tracking-wider text-[#31333F] mr-1">
                        Platform Mix:
                      </span>
                      {PLATFORM_MIX_ORDER.map((pName) => {
                        const count = platformMixCounts[pName] || 0
                        const isZero = count === 0
                        return (
                          <span
                            key={pName}
                            className={`text-xs px-2.5 py-1 rounded-full border font-medium ${
                              isZero
                                ? 'bg-[#F0F2F6] text-[#9CA3AF] border-[#E5E7EB] opacity-60'
                                : 'bg-white text-[#31333F] border-[#D1D5DB] font-semibold'
                            }`}
                          >
                            {pName} {count}
                          </span>
                        )
                      })}
                    </div>
                  )}

                  {/* Results Tabs (Report, Both Sides, Sources, Plan) */}
                  <section className="rounded-[8px] border border-[#E5E7EB] bg-white overflow-hidden">
                    <div className="border-b border-[#E5E7EB] bg-[#F9FAFB] px-4 pt-2.5 flex items-center justify-between gap-2 overflow-x-auto">
                      <div className="flex items-center gap-2">
                        {[
                          { id: 'report', label: 'Report', badgeCount: null },
                          {
                            id: 'both_sides',
                            label: 'Both Sides',
                            badgeCount: conflicts.length,
                            badgeColor:
                              conflicts.length > 0
                                ? 'bg-orange-100 text-orange-800 border-orange-300'
                                : 'bg-gray-100 text-[#6B7280] border-gray-200',
                          },
                          {
                            id: 'sources',
                            label: 'Sources',
                            badgeCount: keptSources.length,
                            badgeColor:
                              'bg-emerald-100 text-emerald-800 border-emerald-300',
                          },
                          {
                            id: 'plan',
                            label: 'Plan',
                            badgeCount: planSections.length,
                            badgeColor:
                              'bg-blue-100 text-blue-800 border-blue-300',
                          },
                        ].map((tab) => {
                          const active = activeTab === tab.id
                          return (
                            <button
                              key={tab.id}
                              type="button"
                              onClick={() => setActiveTab(tab.id)}
                              className={`px-4 py-2.5 text-sm font-semibold rounded-t-[8px] border-b-2 transition cursor-pointer whitespace-nowrap inline-flex items-center gap-2 ${
                                active
                                  ? 'border-[#FF4B4B] text-[#FF4B4B] bg-white'
                                  : 'border-transparent text-[#6B7280] hover:text-[#31333F]'
                              }`}
                            >
                              <span>{tab.label}</span>
                              {tab.badgeCount !== null && (
                                <span
                                  className={`text-xs font-bold px-2 py-0.5 rounded-full border ${tab.badgeColor}`}
                                >
                                  {tab.badgeCount}
                                </span>
                              )}
                            </button>
                          )
                        })}
                      </div>

                      {/* Export Buttons */}
                      {result?.report_markdown && (
                        <div className="flex items-center gap-2 pb-2 shrink-0">
                          <button
                            type="button"
                            onClick={handleDownloadMarkdown}
                            className="px-3 py-1.5 rounded-[8px] bg-white hover:bg-[#F0F2F6] border border-[#E5E7EB] text-xs font-medium text-[#31333F] transition cursor-pointer"
                          >
                            ⬇ Download Markdown
                          </button>
                          <button
                            type="button"
                            onClick={handleDownloadPDF}
                            className="px-3 py-1.5 rounded-[8px] bg-[#FF4B4B] hover:bg-[#E03E3E] text-xs font-medium text-white transition cursor-pointer"
                          >
                            🖨 Download PDF
                          </button>
                        </div>
                      )}
                    </div>

                    {/* Tab Content */}
                    <div className="p-6">
                      {/* TAB 1: REPORT */}
                      {activeTab === 'report' && (
                        <div className="space-y-6">
                          {!result?.report_markdown ? (
                            /* Soft Skeleton in the Report tab during research/writing */
                            <div className="space-y-5 py-4">
                              <div className="flex items-center gap-3 text-sm font-medium text-[#31333F]">
                                <span className="h-4 w-4 border-2 border-[#FF4B4B] border-t-transparent rounded-full animate-spin" />
                                <span>
                                  Agents are researching, writing sections, and verifying every cited sentence...
                                </span>
                              </div>
                              <div className="rounded-[8px] border border-[#E5E7EB] bg-[#F9FAFB] p-5 space-y-3 animate-pulse">
                                <div className="h-4 w-36 bg-[#E5E7EB] rounded" />
                                <div className="h-3 w-full bg-[#E5E7EB] rounded" />
                                <div className="h-3 w-11/12 bg-[#E5E7EB] rounded" />
                                <div className="h-3 w-4/5 bg-[#E5E7EB] rounded" />
                              </div>
                              <div className="space-y-3 animate-pulse pt-2">
                                <div className="h-6 w-2/3 bg-[#F0F2F6] rounded" />
                                <div className="h-4 w-full bg-[#F0F2F6] rounded" />
                                <div className="h-4 w-full bg-[#F0F2F6] rounded" />
                                <div className="h-4 w-5/6 bg-[#F0F2F6] rounded" />
                                <div className="h-5 w-1/2 bg-[#F0F2F6] rounded mt-6" />
                                <div className="h-4 w-full bg-[#F0F2F6] rounded" />
                                <div className="h-4 w-11/12 bg-[#F0F2F6] rounded" />
                              </div>
                            </div>
                          ) : (
                            <>
                              {/* 6. Key Findings Box (first 3 to 4 bullet points from summary, no extra LLM call) */}
                              {keyFindings.length > 0 && (
                                <div className="rounded-[8px] border border-[#E5E7EB] bg-[#F9FAFB] p-5">
                                  <h3 className="text-sm font-bold uppercase tracking-wider text-[#31333F] mb-2.5">
                                    📌 Key findings
                                  </h3>
                                  <ul className="space-y-2">
                                    {keyFindings.map((item, kIdx) => (
                                      <li
                                        key={kIdx}
                                        className="flex items-start gap-2.5 text-sm md:text-base text-[#31333F] leading-relaxed"
                                      >
                                        <span className="text-[#FF4B4B] font-bold mt-0.5">
                                          •
                                        </span>
                                        <span className="flex-1">
                                          <InlineSentenceContent
                                            text={item}
                                            verdictInfo={null}
                                            onTraceOpen={handleTraceOpen}
                                          />
                                        </span>
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}

                              {/* Trust Score Card + Small Legend */}
                              <div
                                className={`rounded-[8px] border p-4 md:p-5 ${ringTheme.border} ${ringTheme.bg}`}
                              >
                                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                                  <div className="flex items-center gap-4">
                                    <div className="relative h-16 w-16 shrink-0 flex items-center justify-center">
                                      <svg
                                        className="h-16 w-16 -rotate-90"
                                        viewBox="0 0 64 64"
                                      >
                                        <circle
                                          cx="32"
                                          cy="32"
                                          r="28"
                                          stroke="#E5E7EB"
                                          strokeWidth="6"
                                          fill="transparent"
                                        />
                                        <circle
                                          cx="32"
                                          cy="32"
                                          r="28"
                                          stroke={ringTheme.stroke}
                                          strokeWidth="6"
                                          strokeDasharray={circumference}
                                          strokeDashoffset={strokeDashoffset}
                                          strokeLinecap="round"
                                          fill="transparent"
                                        />
                                      </svg>
                                      <span
                                        className={`absolute text-base font-bold ${ringTheme.text}`}
                                      >
                                        {truthSummary.score !== null
                                          ? `${truthSummary.score}%`
                                          : '—'}
                                      </span>
                                    </div>

                                    <div>
                                      <div className="flex items-center gap-2 flex-wrap">
                                        <span className="text-xs font-bold uppercase tracking-wider text-[#31333F]">
                                          Truth Meter — Trust Score
                                        </span>
                                        <span
                                          className={`text-xs font-bold px-2 py-0.5 rounded-full bg-white border border-[#E5E7EB] ${ringTheme.text}`}
                                        >
                                          {ringTheme.label}
                                        </span>
                                        {stoppedAtTimeLimit && (
                                          <span className="text-xs font-bold px-2.5 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-300">
                                            Stopped at time limit
                                          </span>
                                        )}
                                      </div>

                                      {truthSummary.hasData && (
                                        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs md:text-sm">
                                          <span className="font-bold text-[#31333F]">
                                            Trust Score {truthSummary.score}%:
                                          </span>
                                          <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 border border-emerald-300 font-semibold">
                                            {truthSummary.supported} supported
                                          </span>
                                          <span className="px-2 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-300 font-semibold">
                                            {truthSummary.partial} partial
                                          </span>
                                          <span className="px-2 py-0.5 rounded bg-red-100 text-red-800 border border-red-300 font-semibold">
                                            {truthSummary.unsupported} unsupported
                                          </span>
                                        </div>
                                      )}

                                      {/* Small Highlight Legend */}
                                      <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-[#6B7280]">
                                        <span className="inline-flex items-center gap-1.5">
                                          <span className="h-2.5 w-2.5 rounded-sm bg-emerald-400 inline-block" />
                                          green = supported
                                        </span>
                                        <span className="inline-flex items-center gap-1.5">
                                          <span className="h-2.5 w-2.5 rounded-sm bg-amber-400 inline-block" />
                                          yellow = partial
                                        </span>
                                        <span className="inline-flex items-center gap-1.5">
                                          <span className="h-2.5 w-2.5 rounded-sm bg-red-400 inline-block" />
                                          red = unsupported
                                        </span>
                                      </div>

                                      {/* Run stats line under Trust Score */}
                                      {result?.stats && (
                                        <div className="mt-2 pt-2 border-t border-[#E5E7EB] flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[#6B7280]">
                                          <span>
                                            Searches:{' '}
                                            <strong className="text-[#31333F]">
                                              {result.stats.searches}
                                            </strong>
                                          </span>
                                          <span>•</span>
                                          <span>
                                            Sources kept:{' '}
                                            <strong className="text-[#2E7D32]">
                                              {result.stats.sources_kept}
                                            </strong>
                                          </span>
                                          <span>•</span>
                                          <span>
                                            Sources dropped:{' '}
                                            <strong className="text-orange-600">
                                              {result.stats.sources_dropped}
                                            </strong>
                                          </span>
                                          <span>•</span>
                                          <span>
                                            Rounds used:{' '}
                                            <strong className="text-[#31333F]">
                                              {result.rounds_used ?? currentRound}
                                            </strong>
                                          </span>
                                          <span>•</span>
                                          <span>
                                            LLM calls:{' '}
                                            <strong className="text-[#31333F]">
                                              {result.stats.llm_calls}
                                            </strong>
                                          </span>
                                          <span>•</span>
                                          <span>
                                            Time:{' '}
                                            <strong className="text-[#31333F]">
                                              {result.stats.seconds}s
                                            </strong>
                                          </span>
                                        </div>
                                      )}
                                    </div>
                                  </div>

                                  {truthSummary.hasData && (
                                    <div className="flex flex-col items-start sm:items-end justify-center shrink-0">
                                      <label className="inline-flex items-center gap-2 cursor-pointer select-none px-3 py-1.5 rounded-[8px] bg-white border border-[#E5E7EB] hover:border-[#D1D5DB] transition">
                                        <input
                                          type="checkbox"
                                          checked={showOnlyProblems}
                                          onChange={(e) =>
                                            setShowOnlyProblems(
                                              e.target.checked
                                            )
                                          }
                                          className="h-4 w-4 accent-[#FF4B4B] rounded cursor-pointer"
                                        />
                                        <span className="text-xs font-medium text-[#31333F]">
                                          Show only problems
                                        </span>
                                      </label>
                                      <span className="text-[11px] text-[#6B7280] mt-1">
                                        Click any [n] or colored sentence to trace source
                                      </span>
                                    </div>
                                  )}
                                </div>
                              </div>

                              {/* Full Verified Report */}
                              <VerifiedReportView
                                markdown={result.report_markdown}
                                sentencesWithVerdicts={
                                  result.sentences_with_verdicts || []
                                }
                                showOnlyProblems={showOnlyProblems}
                                onTraceOpen={handleTraceOpen}
                              />
                            </>
                          )}
                        </div>
                      )}

                      {/* TAB 2: BOTH SIDES */}
                      {activeTab === 'both_sides' && (
                        <div className="space-y-5">
                          {conflicts.length === 0 ? (
                            <div className="rounded-[8px] border border-[#E5E7EB] bg-[#F9FAFB] p-10 text-center">
                              <p className="text-base font-semibold text-[#31333F]">
                                Sources agreed on all checked points.
                              </p>
                            </div>
                          ) : (
                            <div className="space-y-5">
                              {conflicts.map((conflict, cIdx) => (
                                <div
                                  key={cIdx}
                                  className="rounded-[8px] border border-[#E5E7EB] bg-white overflow-hidden"
                                >
                                  <div className="px-5 py-3 bg-[#FFF8E1] border-b border-[#E5E7EB] flex items-center justify-between gap-3">
                                    <h3 className="text-base font-bold text-[#31333F]">
                                      {conflict.topic}
                                    </h3>
                                    <span className="shrink-0 text-[11px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-full bg-orange-100 text-orange-800 border border-orange-300">
                                      Disagreement #{cIdx + 1}
                                    </span>
                                  </div>

                                  <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-[#E5E7EB]">
                                    <div className="p-5 flex flex-col justify-between">
                                      <div>
                                        <div className="text-xs font-bold uppercase tracking-wider text-blue-700 mb-2">
                                          Side A
                                        </div>
                                        <p className="text-sm md:text-base text-[#31333F] leading-relaxed">
                                          {conflict.side_a?.claim}
                                        </p>
                                      </div>
                                      {renderSourceChips(
                                        conflict.side_a?.source_ids,
                                        conflict.side_a?.claim
                                      )}
                                    </div>

                                    <div className="p-5 flex flex-col justify-between">
                                      <div>
                                        <div className="text-xs font-bold uppercase tracking-wider text-purple-700 mb-2">
                                          Side B
                                        </div>
                                        <p className="text-sm md:text-base text-[#31333F] leading-relaxed">
                                          {conflict.side_b?.claim}
                                        </p>
                                      </div>
                                      {renderSourceChips(
                                        conflict.side_b?.source_ids,
                                        conflict.side_b?.claim
                                      )}
                                    </div>
                                  </div>

                                  <div className="px-5 py-3 bg-[#F9FAFB] border-t border-[#E5E7EB] flex items-start gap-2 text-xs md:text-sm">
                                    <span className="font-bold text-[#31333F] shrink-0">
                                      Why they differ:
                                    </span>
                                    <span className="text-[#6B7280]">
                                      {conflict.why_different}
                                    </span>
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* TAB 3: SOURCES */}
                      {activeTab === 'sources' && (
                        <div className="space-y-6">
                          {keptSources.length === 0 ? (
                            <p className="text-sm text-[#6B7280] text-center py-10">
                              No verified sources collected yet.
                            </p>
                          ) : (
                            sourcesBySection.map((group) => {
                              if (group.items.length === 0) return null
                              return (
                                <div key={group.id} className="space-y-3">
                                  <h3 className="text-sm font-bold uppercase tracking-wider text-[#31333F] border-b border-[#E5E7EB] pb-1.5">
                                    {group.title} ({group.items.length})
                                  </h3>
                                  <div className="space-y-2.5">
                                    {group.items.map((src) => {
                                      const isHighlighted =
                                        highlightedSourceId === Number(src.id)
                                      const badgeCls =
                                        QUALITY_BADGE_STYLES[src.badge] ||
                                        QUALITY_BADGE_STYLES.Medium
                                      const reasonsText = (
                                        src.reasons || []
                                      ).join(' • ')
                                      const sourceTag =
                                        src.source_type &&
                                        SOURCE_TYPE_TAG_STYLES[src.source_type]
                                          ? src.source_type
                                          : null

                                      return (
                                        <div
                                          key={src.id || src.url}
                                          id={`source-card-${src.id}`}
                                          className={`rounded-[8px] border p-4 transition relative group ${
                                            isHighlighted
                                              ? 'border-[#FF4B4B] bg-[#FFF5F5] ring-1 ring-[#FF4B4B]'
                                              : 'border-[#E5E7EB] bg-white hover:border-[#D1D5DB]'
                                          }`}
                                        >
                                          <div className="flex items-start justify-between gap-3">
                                            <div className="flex items-start gap-2.5 min-w-0">
                                              <span className="px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 text-xs font-bold shrink-0">
                                                [{src.id}]
                                              </span>
                                              <div className="min-w-0">
                                                <a
                                                  href={src.url}
                                                  target="_blank"
                                                  rel="noopener noreferrer"
                                                  className="text-sm md:text-base font-semibold text-[#31333F] hover:text-[#FF4B4B] transition line-clamp-2 break-words"
                                                >
                                                  {src.title || src.url}
                                                </a>
                                                <div className="flex flex-wrap items-center gap-2 mt-1 text-xs text-[#6B7280]">
                                                  {src.platform && (
                                                    <>
                                                      <span className="font-semibold text-[#31333F]">
                                                        {src.platform}
                                                      </span>
                                                      <span>•</span>
                                                    </>
                                                  )}
                                                  <span className="font-mono text-[#31333F]">
                                                    {src.domain}
                                                  </span>
                                                  <span>•</span>
                                                  <span>
                                                    {src.published_date
                                                      ? `Published: ${src.published_date}`
                                                      : 'Date unknown'}
                                                  </span>
                                                </div>
                                              </div>
                                            </div>

                                            <div
                                              title={reasonsText}
                                              className="relative shrink-0 flex items-center gap-1.5"
                                            >
                                              {sourceTag && (
                                                <span
                                                  className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${SOURCE_TYPE_TAG_STYLES[sourceTag]}`}
                                                >
                                                  {sourceTag}
                                                </span>
                                              )}
                                              <span
                                                className={`inline-flex items-center gap-1.5 text-xs font-bold px-2.5 py-1 rounded-full border cursor-help ${badgeCls}`}
                                              >
                                                <span>{src.badge}</span>
                                                <span>{src.score}/100</span>
                                              </span>

                                              {src.reasons &&
                                                src.reasons.length > 0 && (
                                                  <div className="hidden group-hover:block absolute right-0 top-full mt-2 w-72 p-3 rounded-[8px] bg-white border border-[#E5E7EB] shadow-lg z-20 text-xs text-[#31333F] space-y-1">
                                                    <div className="font-bold mb-1">
                                                      Credibility Score Breakdown:
                                                    </div>
                                                    {src.reasons.map(
                                                      (r, rIdx) => (
                                                        <div
                                                          key={rIdx}
                                                          className="text-[#6B7280] leading-snug"
                                                        >
                                                          • {r}
                                                        </div>
                                                      )
                                                    )}
                                                  </div>
                                                )}
                                            </div>
                                          </div>
                                        </div>
                                      )
                                    })}
                                  </div>
                                </div>
                              )
                            })
                          )}

                          {/* Collapsed Dropped Sources List */}
                          <div className="pt-4 border-t border-[#E5E7EB]">
                            <button
                              type="button"
                              onClick={() => setShowDropped((v) => !v)}
                              className="flex items-center justify-between w-full px-4 py-2.5 rounded-[8px] bg-[#F0F2F6] text-xs font-medium text-[#31333F] hover:bg-[#E5E7EB] cursor-pointer"
                            >
                              <span>
                                Dropped Sources (Below 35 credibility threshold):{' '}
                                {droppedSources.length}
                              </span>
                              <span>{showDropped ? '▲ Hide' : '▼ Show'}</span>
                            </button>

                            {showDropped && (
                              <div className="mt-3 space-y-2">
                                {droppedSources.length === 0 ? (
                                  <p className="text-xs text-[#6B7280] px-2 py-2">
                                    No sources were dropped during this run.
                                  </p>
                                ) : (
                                  droppedSources.map((dSrc, idx) => (
                                    <div
                                      key={idx}
                                      title={(dSrc.reasons || []).join(' • ')}
                                      className="rounded-[8px] border border-red-200 bg-red-50/50 p-3 flex items-center justify-between gap-3 text-xs"
                                    >
                                      <div className="min-w-0">
                                        <a
                                          href={dSrc.url}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="font-medium text-[#31333F] hover:underline truncate block"
                                        >
                                          {dSrc.title || dSrc.url}
                                        </a>
                                        <span className="text-[#6B7280] font-mono">
                                          {dSrc.domain} —{' '}
                                          {(dSrc.reasons || []).join(', ')}
                                        </span>
                                      </div>
                                      <span
                                        className={`shrink-0 px-2 py-0.5 rounded-full border font-bold ${QUALITY_BADGE_STYLES.Dropped}`}
                                      >
                                        Dropped ({dSrc.score}/100)
                                      </span>
                                    </div>
                                  ))
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      {/* TAB 4: PLAN */}
                      {activeTab === 'plan' && (
                        <div className="space-y-4">
                          {planSections.length === 0 ? (
                            <p className="text-sm text-[#6B7280] text-center py-10">
                              Apollo has not generated a research plan yet.
                            </p>
                          ) : (
                            planSections.map((sec, idx) => {
                              const history =
                                sec.question_history &&
                                sec.question_history.length > 0
                                  ? sec.question_history
                                  : (sec.questions || []).map((q) => ({
                                      query: q,
                                      round: 1,
                                    }))

                              return (
                                <div
                                  key={sec.id || idx}
                                  className="rounded-[8px] border border-[#E5E7EB] bg-[#F9FAFB] p-4 space-y-3"
                                >
                                  <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2.5">
                                      <span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200">
                                        {sec.id}
                                      </span>
                                      <h3 className="text-base font-bold text-[#31333F]">
                                        {sec.title}
                                      </h3>
                                    </div>
                                    <span className="text-xs text-[#6B7280]">
                                      {history.length} queries
                                    </span>
                                  </div>

                                  <div className="space-y-2">
                                    {history.map((qItem, qIdx) => {
                                      const isFollowUp = (qItem.round || 1) > 1
                                      return (
                                        <div
                                          key={qIdx}
                                          className="rounded-[8px] border border-[#E5E7EB] bg-white p-2.5 flex items-start justify-between gap-3 text-xs md:text-sm"
                                        >
                                          <div className="space-y-1">
                                            <div className="text-[#31333F] font-medium">
                                              🔍 {qItem.query}
                                            </div>
                                            {qItem.reason && (
                                              <div className="text-xs text-orange-700">
                                                Hermes gap reason: {qItem.reason}
                                              </div>
                                            )}
                                          </div>
                                          <span
                                            className={`shrink-0 text-xs font-bold px-2.5 py-0.5 rounded-full border ${
                                              isFollowUp
                                                ? 'bg-orange-50 text-orange-700 border-orange-200'
                                                : 'bg-blue-50 text-blue-700 border-blue-200'
                                            }`}
                                          >
                                            Round {qItem.round || 1}
                                          </span>
                                        </div>
                                      )
                                    })}
                                  </div>
                                </div>
                              )
                            })
                          )}
                        </div>
                      )}
                    </div>
                  </section>
                </>
              )}
            </div>
          </div>
        </main>

        {/* 5. Click-to-Trace Citation Right Side Slide-In Panel (380px, white) */}
        {tracePanelData && (
          <div className="fixed inset-y-0 right-0 w-full max-w-[380px] bg-white border-l border-[#E5E7EB] shadow-2xl z-50 flex flex-col">
            {/* Panel Header */}
            <div className="px-5 py-4 border-b border-[#E5E7EB] bg-[#F9FAFB] flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold text-[#31333F]">
                  🔍 Source &amp; Citation Trace
                </span>
                {tracePanelData.citedIds?.length > 1 && (
                  <div className="flex items-center gap-1 ml-1">
                    {tracePanelData.citedIds.map((cid) => (
                      <button
                        key={cid}
                        type="button"
                        onClick={() =>
                          setTracePanelData((prev) => ({
                            ...prev,
                            activeSourceId: Number(cid),
                          }))
                        }
                        className={`text-xs font-bold px-2 py-0.5 rounded border cursor-pointer ${
                          Number(tracePanelData.activeSourceId) === Number(cid)
                            ? 'bg-[#FF4B4B] text-white border-[#FF4B4B]'
                            : 'bg-white text-[#31333F] border-[#E5E7EB]'
                        }`}
                      >
                        [{cid}]
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={() => setTracePanelData(null)}
                aria-label="Close source panel"
                className="h-7 w-7 rounded-[8px] border border-[#E5E7EB] bg-white hover:bg-[#F0F2F6] text-[#31333F] flex items-center justify-center text-sm font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            {/* Panel Body */}
            <div className="flex-1 overflow-y-auto p-5 space-y-5">
              {/* Source Metadata */}
              {tracedSource ? (
                <div className="space-y-2.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 text-xs font-bold">
                      Source [{tracedSource.id}]
                    </span>
                    <span
                      className={`text-xs font-bold px-2.5 py-0.5 rounded-full border ${
                        QUALITY_BADGE_STYLES[tracedSource.badge] ||
                        QUALITY_BADGE_STYLES.Medium
                      }`}
                    >
                      {tracedSource.badge} {tracedSource.score}/100
                    </span>
                    {tracedSource.source_type && (
                      <span
                        className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${
                          SOURCE_TYPE_TAG_STYLES[tracedSource.source_type] ||
                          'bg-gray-100 text-gray-700 border-gray-200'
                        }`}
                      >
                        {tracedSource.source_type}
                      </span>
                    )}
                  </div>

                  <h3 className="text-base font-bold text-[#31333F] leading-snug">
                    {tracedSource.title || tracedSource.url}
                  </h3>

                  <div className="text-xs text-[#6B7280] flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[#31333F] font-semibold">
                      {tracedSource.domain}
                    </span>
                    {tracedSource.platform && (
                      <>
                        <span>•</span>
                        <span>{tracedSource.platform}</span>
                      </>
                    )}
                    <span>•</span>
                    <span>
                      {tracedSource.published_date || 'Date unknown'}
                    </span>
                  </div>

                  <div className="pt-1">
                    <a
                      href={tracedSource.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[8px] bg-[#FF4B4B] hover:bg-[#E03E3E] text-white text-xs font-semibold transition"
                    >
                      <span>Open source ↗</span>
                    </a>
                  </div>
                </div>
              ) : (
                <div className="rounded-[8px] border border-red-200 bg-red-50 p-3 text-xs text-red-700">
                  Source [{tracePanelData.activeSourceId}] was not found in the verified sources list.
                </div>
              )}

              {/* Truth Meter Verdict for the Clicked Sentence */}
              {tracePanelData.sentenceText && (
                <div className="pt-3 border-t border-[#E5E7EB] space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase tracking-wider text-[#6B7280]">
                      Checked Report Claim
                    </span>
                    {tracePanelData.verdictInfo?.verdict && (
                      <span
                        className={`text-xs font-bold uppercase px-2.5 py-0.5 rounded border ${
                          VERDICT_BADGE_STYLES[
                            tracePanelData.verdictInfo.verdict
                          ] || VERDICT_BADGE_STYLES.SUPPORTED
                        }`}
                      >
                        {tracePanelData.verdictInfo.verdict}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-[#31333F] bg-[#F9FAFB] border border-[#E5E7EB] rounded-[8px] p-3 leading-relaxed">
                    {tracePanelData.sentenceText}
                  </p>
                </div>
              )}

              {/* Evidence Quote Highlighted in Yellow inside Source Passage */}
              <div className="pt-3 border-t border-[#E5E7EB] space-y-2">
                <span className="block text-xs font-bold uppercase tracking-wider text-[#31333F]">
                  Evidence in Source Text
                </span>
                <HighlightedSourcePassage
                  sourceContent={tracedSource?.content || ''}
                  evidenceQuote={tracePanelData.verdictInfo?.evidence || ''}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Print-Only View for Download PDF (window.print) */}
      <div className="print-only p-8">
        <div className="border-b pb-4 mb-6">
          <h1 className="text-2xl font-bold">Apollo — Deep Research Report</h1>
          <p className="text-sm mt-1">
            <strong>Topic:</strong> {result?.topic || topic}
          </p>
          {truthSummary.hasData && (
            <p className="text-sm mt-1">
              <strong>Trust Score: {truthSummary.score}%</strong> (
              {truthSummary.supported} supported, {truthSummary.partial}{' '}
              partial, {truthSummary.unsupported} unsupported)
            </p>
          )}
          {result?.stats && (
            <p className="text-xs mt-1">
              Searches: {result.stats.searches} | Sources kept:{' '}
              {result.stats.sources_kept} | Sources dropped:{' '}
              {result.stats.sources_dropped} | Rounds used:{' '}
              {result.rounds_used} | LLM calls: {result.stats.llm_calls} |
              Time: {result.stats.seconds}s
            </p>
          )}
        </div>

        {result?.report_markdown && (
          <VerifiedReportView
            markdown={result.report_markdown}
            sentencesWithVerdicts={result.sentences_with_verdicts || []}
            showOnlyProblems={false}
            onTraceOpen={() => {}}
          />
        )}

        {keptSources.length > 0 && (
          <div className="mt-8 pt-4 border-t">
            <h2 className="text-lg font-bold mb-3">References</h2>
            <ol className="space-y-2 text-xs">
              {keptSources.map((src) => (
                <li key={src.id}>
                  <strong>[{src.id}]</strong> {src.title || src.url} (
                  {src.domain}, {src.published_date || 'Date unknown'}, Quality:{' '}
                  {src.badge} {src.score}/100) — <span>{src.url}</span>
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </div>
  )
}
