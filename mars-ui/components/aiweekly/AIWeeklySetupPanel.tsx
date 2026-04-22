'use client'

import React, { useState, useCallback, useRef } from 'react'
import { Sparkles, Calendar, Settings2, Plus, X, Upload, Link, Rss, FileText } from 'lucide-react'
import { Button } from '@/components/core'
import type { UseAIWeeklyTaskReturn } from '@/hooks/useAIWeeklyTask'
import { useModelConfig } from '@/hooks/useModelConfig'
import { getApiUrl } from '@/lib/config'

interface AIWeeklySetupPanelProps {
    hook: UseAIWeeklyTaskReturn
    onNext: () => void
}

const AVAILABLE_TOPICS = [
    { id: 'llm', label: 'Large Language Models' },
    { id: 'cv', label: 'Computer Vision' },
    { id: 'rl', label: 'Reinforcement Learning' },
    { id: 'robotics', label: 'Robotics' },
    { id: 'quantum', label: 'Quantum Computing' },
    { id: 'ml-open-ai', label: 'Machine Learning Open AI' },
    { id: 'ai', label: 'Artificial Intelligence' },
    { id: 'ai-innovation', label: 'AI Innovation' },
    { id: 'gpt-models', label: 'GPT Models' },
    { id: 'nvidia', label: 'Nvidia & GPU AI' },
    { id: 'ml-models', label: 'ML Models & Foundation Models' },
]

const AVAILABLE_SOURCES = [
    { id: 'github', label: 'GitHub Releases' },
    { id: 'press-releases', label: 'Press Releases' },
    { id: 'company-announcements', label: 'Company Announcements' },
    { id: 'curated-ai-websites', label: 'Curated AI Websites / Blogs' },
]

export default function AIWeeklySetupPanel({ hook, onNext }: AIWeeklySetupPanelProps) {
    const { createTask, executeStage, isLoading, stageConfig, setStageConfig } = hook
    const { availableModels } = useModelConfig()

    const [dateFrom, setDateFrom] = useState(() => {
        const d = new Date(); d.setDate(d.getDate() - 7)
        return d.toISOString().split('T')[0]
    })
    const [dateTo, setDateTo] = useState(() => new Date().toISOString().split('T')[0])
    const [topics, setTopics] = useState<string[]>(['llm', 'cv'])
    const [sources, setSources] = useState<string[]>([
        'github', 'press-releases', 'company-announcements', 'major-releases', 'curated-ai-websites',
    ])
    const [style, setStyle] = useState<'concise' | 'detailed' | 'technical'>('concise')
    const [submitted, setSubmitted] = useState(false)
    const [showModelSettings, setShowModelSettings] = useState(false)
    const [customSources, setCustomSources] = useState<{ type: 'url' | 'rss' | 'text'; value: string }[]>([])
    const [uploadedFiles, setUploadedFiles] = useState<{ name: string; size: number }[]>([])
    const [newSourceType, setNewSourceType] = useState<'url' | 'rss' | 'text'>('url')
    const [newSourceValue, setNewSourceValue] = useState('')
    const fileInputRef = useRef<HTMLInputElement>(null)
    const pendingFilesRef = useRef<File[]>([])

    const toggle = (arr: string[], id: string, setter: (v: string[]) => void) => {
        setter(arr.includes(id) ? arr.filter(x => x !== id) : [...arr, id])
    }

    const canSubmit = topics.length > 0 && sources.length > 0 && dateFrom && dateTo && dateFrom <= dateTo && !isLoading && !submitted

    const addCustomSource = useCallback(() => {
        const v = newSourceValue.trim()
        if (!v) return
        setCustomSources(prev => [...prev, { type: newSourceType, value: v }])
        setNewSourceValue('')
    }, [newSourceType, newSourceValue])

    const removeCustomSource = useCallback((idx: number) => {
        setCustomSources(prev => prev.filter((_, i) => i !== idx))
    }, [])

    const removeUploadedFile = useCallback((idx: number) => {
        setUploadedFiles(prev => prev.filter((_, i) => i !== idx))
    }, [])

    const handleSubmit = useCallback(async () => {
        if (!canSubmit) return
        setSubmitted(true)
        const id = await createTask({
            date_from: dateFrom, date_to: dateTo, topics, sources, style,
            custom_sources: customSources.length > 0 ? customSources : undefined,
        })
        if (id) {
            // Upload pending files
            for (const file of pendingFilesRef.current) {
                const formData = new FormData()
                formData.append('file', file)
                try {
                    await fetch(getApiUrl(`/api/aiweekly/${id}/upload`), {
                        method: 'POST',
                        body: formData,
                    })
                } catch { /* upload error — non-blocking */ }
            }
            pendingFilesRef.current = []
            await executeStage(1, id)
        }
        onNext()
    }, [canSubmit, dateFrom, dateTo, topics, sources, style, customSources, createTask, executeStage, onNext])

    const handleFileUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files
        if (!files || files.length === 0) return
        // Files will be uploaded after task creation; store metadata for now
        const newFiles = Array.from(files).map(f => ({ name: f.name, size: f.size, file: f }))
        setUploadedFiles(prev => [...prev, ...newFiles.map(f => ({ name: f.name, size: f.size }))])
        // Store actual File objects for later upload
        pendingFilesRef.current.push(...newFiles.map(f => f.file))
        if (fileInputRef.current) fileInputRef.current.value = ''
    }, [])

    const chipClass = (active: boolean) =>
        `px-3 py-1.5 rounded-mars-sm text-xs font-medium cursor-pointer transition-colors border ${active
            ? 'bg-[var(--mars-color-primary)] text-white border-transparent'
            : 'border-[var(--mars-color-border)] text-[var(--mars-color-text-secondary)]'
        }`

    return (
        <div className="max-w-3xl mx-auto space-y-6">
            {/* Date range */}
            <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--mars-color-text)' }}>
                    <Calendar className="w-4 h-4 inline mr-1.5" />
                    Coverage Window
                </label>
                <div className="flex items-center gap-3">
                    <input
                        type="date" value={dateFrom}
                        onChange={e => setDateFrom(e.target.value)}
                        className="rounded-mars-md border px-3 py-2 text-sm outline-none"
                        style={{ backgroundColor: 'var(--mars-color-surface)', borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text)' }}
                    />
                    <span style={{ color: 'var(--mars-color-text-secondary)' }}>to</span>
                    <input
                        type="date" value={dateTo}
                        onChange={e => setDateTo(e.target.value)}
                        className="rounded-mars-md border px-3 py-2 text-sm outline-none"
                        style={{ backgroundColor: 'var(--mars-color-surface)', borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text)' }}
                    />
                </div>
            </div>

            {/* Topics */}
            <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--mars-color-text)' }}>
                    Topics
                </label>
                <div className="flex flex-wrap gap-2">
                    {AVAILABLE_TOPICS.map(t => (
                        <button key={t.id} className={chipClass(topics.includes(t.id))} onClick={() => toggle(topics, t.id, setTopics)}>
                            {t.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Sources */}
            <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--mars-color-text)' }}>
                    Sources
                </label>
                <div className="flex flex-wrap gap-2">
                    {AVAILABLE_SOURCES.map(s => (
                        <button key={s.id} className={chipClass(sources.includes(s.id))} onClick={() => toggle(sources, s.id, setSources)}>
                            {s.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Style */}
            <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--mars-color-text)' }}>
                    Report Style
                </label>
                <div className="flex gap-2">
                    {([
                        { id: 'concise' as const, label: 'Concise', tooltip: 'Short & direct — 2-3 sentences per item (≤80 words). News-wire style with key facts only.' },
                        { id: 'detailed' as const, label: 'Detailed', tooltip: 'Comprehensive — ≥130 words per item with business context, market impact, and strategic recommendations.' },
                        { id: 'technical' as const, label: 'Technical', tooltip: 'Deep-dive — ≥130 words per item with architecture details, metrics, benchmarks, and technical trade-offs.' },
                    ]).map(s => (
                        <button key={s.id} className={chipClass(style === s.id)} onClick={() => setStyle(s.id)} title={s.tooltip}>
                            {s.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Custom Data Sources */}
            <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--mars-color-text)' }}>
                    <Upload className="w-4 h-4 inline mr-1.5" />
                    Data Sources <span className="text-xs font-normal" style={{ color: 'var(--mars-color-text-tertiary)' }}>(optional)</span>
                </label>
                <p className="text-xs mb-3" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                    Add custom RSS feeds, website URLs, or upload files (CSV, PDF, TXT) as additional data sources.
                </p>

                {/* Add source input */}
                <div className="flex gap-2 mb-3">
                    <select
                        value={newSourceType}
                        onChange={e => setNewSourceType(e.target.value as 'url' | 'rss' | 'text')}
                        className="rounded-mars-sm border px-2 py-1.5 text-xs outline-none"
                        style={{ backgroundColor: 'var(--mars-color-surface)', borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text)' }}
                    >
                        <option value="url">URL</option>
                        <option value="rss">RSS Feed</option>
                        <option value="text">Text / Notes</option>
                    </select>
                    <input
                        type="text"
                        value={newSourceValue}
                        onChange={e => setNewSourceValue(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addCustomSource() } }}
                        placeholder={
                            newSourceType === 'url' ? 'https://example.com/article'
                                : newSourceType === 'rss' ? 'https://example.com/feed.xml'
                                    : 'Paste notes or references...'
                        }
                        className="flex-1 rounded-mars-sm border px-3 py-1.5 text-xs outline-none transition-colors focus:border-[var(--mars-color-primary)]"
                        style={{ backgroundColor: 'var(--mars-color-surface)', borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text)' }}
                    />
                    <button
                        onClick={addCustomSource}
                        disabled={!newSourceValue.trim()}
                        className="px-2.5 py-1.5 rounded-mars-sm border text-xs font-medium transition-colors disabled:opacity-40"
                        style={{ borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text-secondary)' }}
                        title="Add source"
                    >
                        <Plus className="w-3.5 h-3.5" />
                    </button>
                </div>

                {/* File upload */}
                <div className="mb-3">
                    <input
                        ref={fileInputRef}
                        type="file"
                        multiple
                        accept=".csv,.pdf,.txt,.md,.json,.xml,.html"
                        onChange={handleFileUpload}
                        className="hidden"
                    />
                    <button
                        onClick={() => fileInputRef.current?.click()}
                        className="flex items-center gap-2 px-3 py-2 rounded-mars-sm border border-dashed text-xs transition-colors hover:border-[var(--mars-color-primary)]"
                        style={{ borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text-secondary)', width: '100%', justifyContent: 'center' }}
                    >
                        <Upload className="w-3.5 h-3.5" />
                        Upload files (CSV, PDF, TXT, MD, JSON, XML)
                    </button>
                </div>

                {/* Listed custom sources */}
                {(customSources.length > 0 || uploadedFiles.length > 0) && (
                    <div className="space-y-1.5">
                        {customSources.map((src, i) => (
                            <div key={i} className="flex items-center gap-2 px-3 py-2 rounded-mars-sm border text-xs"
                                style={{ borderColor: 'var(--mars-color-border)', backgroundColor: 'var(--mars-color-surface)' }}>
                                {src.type === 'url' && <Link className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--mars-color-primary)' }} />}
                                {src.type === 'rss' && <Rss className="w-3.5 h-3.5 flex-shrink-0" style={{ color: '#f59e0b' }} />}
                                {src.type === 'text' && <FileText className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--mars-color-text-secondary)' }} />}
                                <span className="flex-1 truncate" style={{ color: 'var(--mars-color-text)' }}>{src.value}</span>
                                <span className="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] uppercase"
                                    style={{ backgroundColor: 'var(--mars-color-bg-tertiary)', color: 'var(--mars-color-text-tertiary)' }}>
                                    {src.type}
                                </span>
                                <button onClick={() => removeCustomSource(i)} className="flex-shrink-0 p-0.5 rounded hover:bg-[var(--mars-color-danger-subtle)]">
                                    <X className="w-3 h-3" style={{ color: 'var(--mars-color-text-tertiary)' }} />
                                </button>
                            </div>
                        ))}
                        {uploadedFiles.map((f, i) => (
                            <div key={`file-${i}`} className="flex items-center gap-2 px-3 py-2 rounded-mars-sm border text-xs"
                                style={{ borderColor: 'var(--mars-color-border)', backgroundColor: 'var(--mars-color-surface)' }}>
                                <Upload className="w-3.5 h-3.5 flex-shrink-0" style={{ color: '#22c55e' }} />
                                <span className="flex-1 truncate" style={{ color: 'var(--mars-color-text)' }}>{f.name}</span>
                                <span className="flex-shrink-0 text-[10px]" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                                    {f.size < 1024 ? `${f.size} B` : `${(f.size / 1024).toFixed(1)} KB`}
                                </span>
                                <span className="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] uppercase"
                                    style={{ backgroundColor: 'var(--mars-color-bg-tertiary)', color: 'var(--mars-color-text-tertiary)' }}>
                                    file
                                </span>
                                <button onClick={() => { removeUploadedFile(i); pendingFilesRef.current.splice(i, 1) }}
                                    className="flex-shrink-0 p-0.5 rounded hover:bg-[var(--mars-color-danger-subtle)]">
                                    <X className="w-3 h-3" style={{ color: 'var(--mars-color-text-tertiary)' }} />
                                </button>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Submit */}
            <div className="flex justify-end pt-2">
                <Button onClick={handleSubmit} disabled={!canSubmit} variant="primary" size="md">
                    <Sparkles className="w-4 h-4 mr-2" />
                    Generate Report
                </Button>
            </div>

            {/* Model Settings (collapsible) */}
            <div className="border rounded-mars-md overflow-hidden" style={{ borderColor: 'var(--mars-color-border)' }}>
                <button
                    onClick={() => setShowModelSettings(!showModelSettings)}
                    className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium"
                    style={{ color: 'var(--mars-color-text)', backgroundColor: 'var(--mars-color-surface)' }}
                >
                    <span className="flex items-center gap-2">
                        <Settings2 className="w-4 h-4" />
                        Model Settings
                    </span>
                    <span className="text-xs" style={{ color: 'var(--mars-color-text-secondary)' }}>
                        {stageConfig.model || 'gpt-4o (default)'}
                    </span>
                </button>
                {showModelSettings && (
                    <div className="px-4 py-3 space-y-3 border-t" style={{ borderColor: 'var(--mars-color-border)' }}>
                        <p className="text-xs" style={{ color: 'var(--mars-color-text-secondary)' }}>
                            Configure LLM models for Stages 2–4 (Data Collection uses no LLM).
                        </p>
                        {/* Primary Model */}
                        <div>
                            <label className="block text-xs font-medium mb-1" style={{ color: 'var(--mars-color-text)' }}>
                                Primary Model (Generation)
                            </label>
                            <select
                                value={stageConfig.model || ''}
                                onChange={e => setStageConfig({ ...stageConfig, model: e.target.value || undefined })}
                                className="w-full rounded-mars-sm border px-2 py-1.5 text-sm outline-none"
                                style={{ backgroundColor: 'var(--mars-color-surface)', borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text)' }}
                            >
                                <option value="">Default (gpt-4o)</option>
                                {availableModels.map(m => (
                                    <option key={m.value} value={m.value}>{m.label}</option>
                                ))}
                            </select>
                        </div>
                        {/* Review Model */}
                        <div>
                            <label className="block text-xs font-medium mb-1" style={{ color: 'var(--mars-color-text)' }}>
                                Review Model (Quality Check)
                            </label>
                            <select
                                value={stageConfig.review_model || ''}
                                onChange={e => setStageConfig({ ...stageConfig, review_model: e.target.value || undefined })}
                                className="w-full rounded-mars-sm border px-2 py-1.5 text-sm outline-none"
                                style={{ backgroundColor: 'var(--mars-color-surface)', borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text)' }}
                            >
                                <option value="">Same as Primary</option>
                                {availableModels.map(m => (
                                    <option key={m.value} value={m.value}>{m.label}</option>
                                ))}
                            </select>
                        </div>
                        {/* Specialist Model */}
                        <div>
                            <label className="block text-xs font-medium mb-1" style={{ color: 'var(--mars-color-text)' }}>
                                Specialist Model (Fact-Check)
                            </label>
                            <select
                                value={stageConfig.specialist_model || ''}
                                onChange={e => setStageConfig({ ...stageConfig, specialist_model: e.target.value || undefined })}
                                className="w-full rounded-mars-sm border px-2 py-1.5 text-sm outline-none"
                                style={{ backgroundColor: 'var(--mars-color-surface)', borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text)' }}
                            >
                                <option value="">Same as Primary</option>
                                {availableModels.map(m => (
                                    <option key={m.value} value={m.value}>{m.label}</option>
                                ))}
                            </select>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
