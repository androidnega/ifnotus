/** Lightweight safe Markdown for AI chat bubbles (no HTML passthrough). */

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

const FILE_EXTS =
  'html?|css|scss|less|js|jsx|ts|tsx|vue|json|md|txt|php|py|rb|go|rs|java|sql|xml|svg|yml|yaml|toml|env|ini|conf|cfg|sh|bash|log|csv|lock'

/** Highlight site file paths and make them clickable chips. */
function linkifyFiles(escaped: string): string {
  // Already inside a tag attribute? skip crude: only plain text segments
  const pathRe = new RegExp(
    String.raw`(?:^|[\s(])((?:[\w.-]+\/)*[\w.-]+\.(?:${FILE_EXTS}))(?=[\s),.;:!?]|$|")`,
    'gi',
  )
  return escaped.replace(pathRe, (full, path: string) => {
    const prefix = full.slice(0, full.length - path.length)
    const doc = /\.(html?|md|txt|pdf|docx?|csv|json)$/i.test(path)
    const cls = doc ? 'ai-file-chip is-doc' : 'ai-file-chip'
    return `${prefix}<button type="button" class="${cls}" data-ai-path="${path}">${path}</button>`
  })
}

function formatInline(text: string): string {
  let s = escapeHtml(text)
  // Backticked paths / code first
  s = s.replace(/`([^`]+)`/g, (_m, inner: string) => {
    const raw = inner
    if (new RegExp(String.raw`^[\w./-]+\.(?:${FILE_EXTS})$`, 'i').test(raw)) {
      const doc = /\.(html?|md|txt|pdf|docx?|csv|json)$/i.test(raw)
      const cls = doc ? 'ai-file-chip is-doc' : 'ai-file-chip'
      return `<button type="button" class="${cls}" data-ai-path="${escapeHtml(raw)}">${escapeHtml(raw)}</button>`
    }
    return `<code class="ai-md-code">${escapeHtml(raw)}</code>`
  })
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/__([^_]+)__/g, '<u>$1</u>')
  s = s.replace(/==([^=]+)==/g, '<mark class="ai-md-mark">$1</mark>')
  s = s.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>')
  s = linkifyFiles(s)
  return s
}

export function renderAiMarkdown(source: string): string {
  const raw = source.replace(/\r\n/g, '\n').trim()
  if (!raw) return ''

  const blocks: string[] = []
  const fence = /```([\w-]*)\n?([\s\S]*?)```/g
  let last = 0
  let match: RegExpExecArray | null
  while ((match = fence.exec(raw)) !== null) {
    if (match.index > last) {
      blocks.push(formatParagraphs(raw.slice(last, match.index)))
    }
    const lang = escapeHtml(match[1] || '')
    const code = escapeHtml(match[2].replace(/\n$/, ''))
    blocks.push(
      `<pre class="ai-md-pre"${lang ? ` data-lang="${lang}"` : ''}><code>${code}</code></pre>`,
    )
    last = match.index + match[0].length
  }
  if (last < raw.length) {
    blocks.push(formatParagraphs(raw.slice(last)))
  }
  return blocks.join('')
}

function formatParagraphs(chunk: string): string {
  const parts = chunk.trim().split(/\n{2,}/)
  return parts
    .map((p) => {
      const heading = p.match(/^(#{1,3})\s+(.+)$/)
      if (heading && !p.includes('\n')) {
        const level = heading[1].length
        return `<h${level} class="ai-md-h">${formatInline(heading[2])}</h${level}>`
      }
      const lines = p.split('\n').map((line) => {
        const h = line.match(/^(#{1,3})\s+(.+)$/)
        if (h) {
          const level = h[1].length
          return `<h${level} class="ai-md-h">${formatInline(h[2])}</h${level}>`
        }
        const bullet = line.match(/^[-*]\s+(.+)$/)
        if (bullet) return `<li>${formatInline(bullet[1])}</li>`
        const numbered = line.match(/^\d+\.\s+(.+)$/)
        if (numbered) return `<li>${formatInline(numbered[1])}</li>`
        return formatInline(line)
      })
      if (lines.every((l) => l.startsWith('<li>'))) {
        return `<ul class="ai-md-list">${lines.join('')}</ul>`
      }
      if (lines.every((l) => l.startsWith('<h'))) {
        return lines.join('')
      }
      return `<p class="ai-md-p">${lines.join('<br>')}</p>`
    })
    .join('')
}
