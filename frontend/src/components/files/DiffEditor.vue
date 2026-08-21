<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as monaco from 'monaco-editor'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import cssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker'
import htmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker'
import tsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker'
import { useThemeStore } from '@/stores/theme'

const props = withDefaults(
  defineProps<{
    original: string
    modified: string
    path: string
    colorMode?: 'auto' | 'light' | 'dark'
    fontSize?: number
    wordWrap?: boolean
  }>(),
  { colorMode: 'auto', fontSize: 14, wordWrap: true },
)

const theme = useThemeStore()
const host = ref<HTMLDivElement | null>(null)
const changeSummary = ref('')

let diffEditor: monaco.editor.IStandaloneDiffEditor | null = null
let originalModel: monaco.editor.ITextModel | null = null
let modifiedModel: monaco.editor.ITextModel | null = null
let workersReady = false
let themesReady = false

const LANGUAGE_MAP: Record<string, string> = {
  ts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  vue: 'html',
  py: 'python',
  php: 'php',
  html: 'html',
  htm: 'html',
  css: 'css',
  scss: 'scss',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  md: 'markdown',
  sh: 'shell',
  sql: 'sql',
  env: 'ini',
  conf: 'ini',
}

function languageFromPath(path: string): string {
  const base = path.split('/').pop()?.toLowerCase() || ''
  const ext = base.includes('.') ? base.slice(base.lastIndexOf('.') + 1) : ''
  return LANGUAGE_MAP[ext] || 'plaintext'
}

function ensureWorkers() {
  if (workersReady) return
  ;(globalThis as typeof globalThis & { MonacoEnvironment?: MonacoEnvironment }).MonacoEnvironment = {
    getWorker(_: string, label: string) {
      if (label === 'json') return new jsonWorker()
      if (label === 'css' || label === 'scss' || label === 'less') return new cssWorker()
      if (label === 'html' || label === 'handlebars' || label === 'razor') return new htmlWorker()
      if (label === 'typescript' || label === 'javascript') return new tsWorker()
      return new editorWorker()
    },
  }
  workersReady = true
}

function ensureDiffThemes() {
  if (themesReady) return
  monaco.editor.defineTheme('ifnotus-diff-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [],
    colors: {
      'diffEditor.insertedTextBackground': '#22c55e55',
      'diffEditor.removedTextBackground': '#ef444455',
      'diffEditor.insertedLineBackground': '#14532d55',
      'diffEditor.removedLineBackground': '#7f1d1d55',
      'diffEditorGutter.insertedLineBackground': '#22c55e88',
      'diffEditorGutter.removedLineBackground': '#ef444488',
      'diffEditorOverview.insertedForeground': '#4ade80',
      'diffEditorOverview.removedForeground': '#f87171',
      'diffEditor.diagonalFill': '#33415555',
    },
  })
  monaco.editor.defineTheme('ifnotus-diff-light', {
    base: 'vs',
    inherit: true,
    rules: [],
    colors: {
      'diffEditor.insertedTextBackground': '#86efac99',
      'diffEditor.removedTextBackground': '#fca5a599',
      'diffEditor.insertedLineBackground': '#dcfce7cc',
      'diffEditor.removedLineBackground': '#fee2e2cc',
      'diffEditorGutter.insertedLineBackground': '#22c55eaa',
      'diffEditorGutter.removedLineBackground': '#ef4444aa',
      'diffEditorOverview.insertedForeground': '#16a34a',
      'diffEditorOverview.removedForeground': '#dc2626',
      'diffEditor.diagonalFill': '#cbd5e155',
    },
  })
  themesReady = true
}

function monacoTheme() {
  const dark = props.colorMode === 'dark' || (props.colorMode === 'auto' && theme.isDark)
  return dark ? 'ifnotus-diff-dark' : 'ifnotus-diff-light'
}

function lineHeightFor(size: number) {
  return Math.round(size * 1.55)
}

function updateChangeSummary() {
  if (!diffEditor) {
    changeSummary.value = ''
    return
  }
  const result = (diffEditor as monaco.editor.IStandaloneDiffEditor & {
    getDiffComputationResult?: () => { changes?: monaco.editor.ILineChange[] } | null
  }).getDiffComputationResult?.()
  const changes = result?.changes || diffEditor.getLineChanges() || []
  let added = 0
  let removed = 0
  for (const change of changes) {
    if (change.modifiedEndLineNumber > 0 && change.modifiedStartLineNumber > 0) {
      added += change.modifiedEndLineNumber - change.modifiedStartLineNumber + 1
    }
    if (change.originalEndLineNumber > 0 && change.originalStartLineNumber > 0) {
      removed += change.originalEndLineNumber - change.originalStartLineNumber + 1
    }
  }
  if (!changes.length) {
    changeSummary.value = 'No changes vs server'
    return
  }
  const bits = []
  if (added) bits.push(`+${added}`)
  if (removed) bits.push(`−${removed}`)
  changeSummary.value = `${bits.join('  ')} · ${changes.length} block${changes.length === 1 ? '' : 's'}`
}

function create() {
  if (!host.value) return
  ensureWorkers()
  ensureDiffThemes()
  const lang = languageFromPath(props.path)
  originalModel = monaco.editor.createModel(props.original, lang, monaco.Uri.parse(`inmemory://original/${props.path}`))
  modifiedModel = monaco.editor.createModel(props.modified, lang, monaco.Uri.parse(`inmemory://modified/${props.path}`))
  diffEditor = monaco.editor.createDiffEditor(host.value, {
    theme: monacoTheme(),
    automaticLayout: true,
    readOnly: true,
    renderSideBySide: true,
    enableSplitViewResizing: true,
    fontSize: props.fontSize,
    fontFamily: "'JetBrains Mono', 'SF Mono', 'Fira Code', Menlo, Monaco, Consolas, monospace",
    fontLigatures: true,
    lineHeight: lineHeightFor(props.fontSize),
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    renderIndicators: true,
    renderMarginRevertIcon: false,
    ignoreTrimWhitespace: false,
    originalEditable: false,
    padding: { top: 12, bottom: 12 },
    diffWordWrap: props.wordWrap ? 'on' : 'off',
    wordWrap: props.wordWrap ? 'on' : 'off',
    wrappingStrategy: 'advanced',
    renderOverviewRuler: true,
    diffAlgorithm: 'advanced',
    useInlineViewWhenSpaceIsLimited: false,
  })
  diffEditor.setModel({ original: originalModel, modified: modifiedModel })
  // Wait a tick for diff computation
  window.setTimeout(updateChangeSummary, 80)
  diffEditor.onDidUpdateDiff(() => updateChangeSummary())
}

function dispose() {
  diffEditor?.dispose()
  originalModel?.dispose()
  modifiedModel?.dispose()
  diffEditor = null
  originalModel = null
  modifiedModel = null
}

onMounted(create)
onBeforeUnmount(dispose)

watch(
  () => [props.original, props.modified],
  () => {
    if (!originalModel || !modifiedModel) return
    if (originalModel.getValue() !== props.original) originalModel.setValue(props.original)
    if (modifiedModel.getValue() !== props.modified) modifiedModel.setValue(props.modified)
    window.setTimeout(updateChangeSummary, 80)
  },
)

watch(
  () => [props.colorMode, theme.isDark],
  () => {
    ensureDiffThemes()
    monaco.editor.setTheme(monacoTheme())
  },
)

watch(
  () => [props.fontSize, props.wordWrap],
  () => {
    diffEditor?.updateOptions({
      fontSize: props.fontSize,
      lineHeight: lineHeightFor(props.fontSize),
      diffWordWrap: props.wordWrap ? 'on' : 'off',
      wordWrap: props.wordWrap ? 'on' : 'off',
    })
  },
)
</script>

<template>
  <div class="diff-editor">
    <div class="diff-labels">
      <span class="label-server">
        <i class="swatch removed" />
        On server
      </span>
      <span class="label-current">
        <i class="swatch added" />
        Your edits
        <em v-if="changeSummary">{{ changeSummary }}</em>
      </span>
    </div>
    <div ref="host" class="diff-host" />
  </div>
</template>

<style scoped>
.diff-editor {
  display: flex;
  min-height: 0;
  flex: 1 1 auto;
  width: 100%;
  height: 100%;
  flex-direction: column;
  overflow: hidden;
  border-radius: 0.75rem;
  border: 1px solid color-mix(in srgb, var(--color-border) 85%, transparent);
  background: var(--color-surface-raised);
}
.diff-labels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
  border-bottom: 1px solid var(--color-border);
  padding: 0.45rem 0.85rem;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}
.label-server,
.label-current {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-width: 0;
}
.label-current em {
  margin-left: auto;
  font-style: normal;
  font-weight: 500;
  letter-spacing: 0;
  text-transform: none;
  color: #0f766e;
  font-variant-numeric: tabular-nums;
}
.swatch {
  display: inline-block;
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 0.15rem;
}
.swatch.removed { background: #ef4444; }
.swatch.added { background: #22c55e; }
.diff-host {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
}
.diff-host :deep(.monaco-diff-editor),
.diff-host :deep(.monaco-editor),
.diff-host :deep(.overflow-guard) {
  width: 100% !important;
  height: 100% !important;
}
</style>
