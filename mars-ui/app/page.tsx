'use client'

import { Suspense, useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'next/navigation'
import { Newspaper, Play, CheckCircle2, AlertCircle, Search, X, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react'
import AIWeeklyReportTask from '@/components/tasks/AIWeeklyReportTask'
import { getApiUrl } from '@/lib/config'

interface RecentTask {
          task_id: string
          task: string
          status: string
          created_at: string | null
          current_stage: number | null
          progress_percent: number
}

const STAGE_NAMES: Record<number, string> = {
          1: 'Data Collection',
          2: 'Content Curation',
          3: 'Report Generation',
          4: 'Quality Review',
}

type FilterTab = 'all' | 'running' | 'completed' | 'failed'

function timeAgo(dateStr: string | null): string {
          if (!dateStr) return ''
          const now = Date.now()
          const then = new Date(dateStr).getTime()
          const diffMs = now - then
          const mins = Math.floor(diffMs / 60000)
          if (mins < 1) return 'just now'
          if (mins < 60) return `${mins}m ago`
          const hours = Math.floor(mins / 60)
          if (hours < 24) return `about ${hours} hour${hours > 1 ? 's' : ''} ago`
          const days = Math.floor(hours / 24)
          return `${days} day${days > 1 ? 's' : ''} ago`
}

function getStatusColor(status: string): string {
          switch (status) {
                    case 'completed': return '#22c55e'
                    case 'failed': return '#ef4444'
                    case 'running': return '#f59e0b'
                    default: return '#3b82f6'
          }
}

function StatusIcon({ status }: { status: string }) {
          switch (status) {
                    case 'completed':
                              return <CheckCircle2 className="w-4 h-4" style={{ color: '#22c55e' }} />
                    case 'failed':
                              return <AlertCircle className="w-4 h-4" style={{ color: '#ef4444' }} />
                    case 'running':
                              return <Loader2 className="w-4 h-4 animate-spin" style={{ color: '#f59e0b' }} />
                    default:
                              return <Play className="w-4 h-4" style={{ color: '#3b82f6' }} />
          }
}

function ResumeParam({ onResume }: { onResume: (id: string) => void }) {
          const searchParams = useSearchParams()
          const resumeFromUrl = searchParams.get('resume')
          useEffect(() => {
                    if (resumeFromUrl) onResume(resumeFromUrl)
          }, [resumeFromUrl, onResume])
          return null
}

function HomeContent() {
          const [resumeTaskId, setResumeTaskId] = useState<string | null>(null)
          const [recentTasks, setRecentTasks] = useState<RecentTask[]>([])
          const [panelOpen, setPanelOpen] = useState(true)
          const [searchQuery, setSearchQuery] = useState('')
          const [activeFilter, setActiveFilter] = useState<FilterTab>('all')

          const handleUrlResume = useCallback((id: string) => {
                    setResumeTaskId(id)
          }, [])

          const fetchRecent = useCallback(() => {
                    fetch(getApiUrl('/api/aiweekly/recent'))
                              .then(r => r.ok ? r.json() : [])
                              .then((data: RecentTask[]) => setRecentTasks(data))
                              .catch(() => { })
          }, [])

          // Fetch sessions on mount and periodically
          useEffect(() => {
                    fetchRecent()
                    const interval = setInterval(fetchRecent, 30000)
                    return () => clearInterval(interval)
          }, [fetchRecent])

          const handleStartNew = useCallback(() => {
                    setResumeTaskId(null)
          }, [])

          const handleResume = useCallback((id: string) => {
                    setResumeTaskId(id)
          }, [])

          const handleDelete = useCallback(async (id: string, e: React.MouseEvent) => {
                    e.stopPropagation()
                    if (!confirm('Delete this task? This will remove all data and files.')) return
                    try {
                              await fetch(getApiUrl(`/api/aiweekly/${id}`), { method: 'DELETE' })
                              setRecentTasks(prev => prev.filter(t => t.task_id !== id))
                    } catch { /* ignore */ }
          }, [])

          // Filtered tasks
          const filteredTasks = useMemo(() => {
                    let tasks = recentTasks
                    if (activeFilter !== 'all') {
                              tasks = tasks.filter(t => {
                                        if (activeFilter === 'running') return t.status === 'running' || t.status === 'pending'
                                        return t.status === activeFilter
                              })
                    }
                    if (searchQuery.trim()) {
                              const q = searchQuery.toLowerCase()
                              tasks = tasks.filter(t =>
                                        (t.task || '').toLowerCase().includes(q) ||
                                        t.task_id.toLowerCase().includes(q)
                              )
                    }
                    return tasks
          }, [recentTasks, activeFilter, searchQuery])

          // Counts per filter
          const counts = useMemo(() => {
                    const all = recentTasks.length
                    const running = recentTasks.filter(t => t.status === 'running' || t.status === 'pending').length
                    const completed = recentTasks.filter(t => t.status === 'completed').length
                    const failed = recentTasks.filter(t => t.status === 'failed').length
                    return { all, running, completed, failed }
          }, [recentTasks])

          const filters: { key: FilterTab; label: string; count: number }[] = [
                    { key: 'all', label: 'All', count: counts.all },
                    { key: 'running', label: 'Running', count: counts.running },
                    { key: 'completed', label: 'Completed', count: counts.completed },
                    { key: 'failed', label: 'Failed', count: counts.failed },
          ]

          return (
                    <div className="flex h-full">
                              <Suspense><ResumeParam onResume={handleUrlResume} /></Suspense>

                              {/* Main content area */}
                              <div className="flex-1 min-h-0 overflow-auto">
                                        <AIWeeklyReportTask
                                                  onBack={handleStartNew}
                                                  resumeTaskId={resumeTaskId}
                                                  key={resumeTaskId || 'new'}
                                        />
                              </div>

                              {/* Right Sessions panel */}
                              <div
                                        className="flex-shrink-0 border-l h-full flex flex-col transition-all duration-300 overflow-hidden"
                                        style={{
                                                  width: panelOpen ? '320px' : '40px',
                                                  backgroundColor: 'var(--mars-color-surface-raised)',
                                                  borderColor: 'var(--mars-color-border)',
                                        }}
                              >
                                        {/* Toggle button */}
                                        <button
                                                  onClick={() => setPanelOpen(prev => !prev)}
                                                  className="p-2 flex items-center justify-center transition-colors hover:bg-[var(--mars-color-bg-hover)] flex-shrink-0"
                                                  style={{ color: 'var(--mars-color-text-secondary)' }}
                                                  aria-label={panelOpen ? 'Collapse panel' : 'Expand panel'}
                                        >
                                                  {panelOpen ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
                                        </button>

                                        {panelOpen && (
                                                  <div className="flex flex-col flex-1 min-h-0">
                                                            {/* SESSIONS header */}
                                                            <div className="px-4 pb-3">
                                                                      <h3 className="text-xs font-semibold tracking-widest uppercase mb-3"
                                                                                style={{ color: 'var(--mars-color-text-secondary)' }}>
                                                                                Sessions
                                                                      </h3>

                                                                      {/* Search */}
                                                                      <div className="relative mb-3">
                                                                                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5"
                                                                                          style={{ color: 'var(--mars-color-text-tertiary)' }} />
                                                                                <input
                                                                                          type="text"
                                                                                          placeholder="Search sessions..."
                                                                                          value={searchQuery}
                                                                                          onChange={e => setSearchQuery(e.target.value)}
                                                                                          className="w-full pl-8 pr-3 py-1.5 text-xs rounded-md border outline-none transition-colors
                                                                                                    focus:border-[var(--mars-color-primary)]"
                                                                                          style={{
                                                                                                    backgroundColor: 'var(--mars-color-bg)',
                                                                                                    borderColor: 'var(--mars-color-border)',
                                                                                                    color: 'var(--mars-color-text)',
                                                                                          }}
                                                                                />
                                                                      </div>

                                                                      {/* Filter tabs */}
                                                                      <div className="flex gap-1">
                                                                                {filters.map(f => (
                                                                                          <button
                                                                                                    key={f.key}
                                                                                                    onClick={() => setActiveFilter(f.key)}
                                                                                                    className="px-2 py-1 text-[10px] font-medium rounded-md transition-colors"
                                                                                                    style={{
                                                                                                              backgroundColor: activeFilter === f.key
                                                                                                                        ? 'var(--mars-color-primary)'
                                                                                                                        : 'transparent',
                                                                                                              color: activeFilter === f.key
                                                                                                                        ? '#fff'
                                                                                                                        : 'var(--mars-color-text-secondary)',
                                                                                                    }}
                                                                                          >
                                                                                                    {f.label} ({f.count})
                                                                                          </button>
                                                                                ))}
                                                                      </div>
                                                            </div>

                                                            {/* Session list */}
                                                            <div className="flex-1 overflow-y-auto px-2 pb-2">
                                                                      {filteredTasks.length === 0 ? (
                                                                                <p className="px-3 py-6 text-xs text-center"
                                                                                          style={{ color: 'var(--mars-color-text-tertiary)' }}>
                                                                                          No sessions found.
                                                                                </p>
                                                                      ) : (
                                                                                filteredTasks.map(task => (
                                                                                          <button
                                                                                                    key={task.task_id}
                                                                                                    onClick={() => handleResume(task.task_id)}
                                                                                                    className="w-full text-left p-3 mb-1 rounded-lg transition-colors hover:bg-[var(--mars-color-bg-hover)] group"
                                                                                          >
                                                                                                    <div className="flex items-start gap-2.5">
                                                                                                              <div className="flex-shrink-0 mt-0.5">
                                                                                                                        <StatusIcon status={task.status} />
                                                                                                              </div>
                                                                                                              <div className="flex-1 min-w-0">
                                                                                                                        <p className="text-sm font-medium truncate"
                                                                                                                                  style={{ color: 'var(--mars-color-text)' }}>
                                                                                                                                  {task.task || 'AI Weekly Report'}
                                                                                                                        </p>
                                                                                                                        <p className="text-[11px] mt-0.5"
                                                                                                                                  style={{ color: 'var(--mars-color-text-tertiary)' }}>
                                                                                                                                  {task.current_stage
                                                                                                                                            ? `Stage ${task.current_stage}: ${STAGE_NAMES[task.current_stage] || ''}`
                                                                                                                                            : 'Setup'}
                                                                                                                        </p>
                                                                                                                        {/* Progress bar */}
                                                                                                                        <div className="flex items-center gap-2 mt-2">
                                                                                                                                  <div className="flex-1 h-1.5 rounded-full overflow-hidden"
                                                                                                                                            style={{ backgroundColor: 'var(--mars-color-bg)' }}>
                                                                                                                                            <div
                                                                                                                                                      className="h-full rounded-full transition-all duration-500"
                                                                                                                                                      style={{
                                                                                                                                                                width: `${Math.round(task.progress_percent)}%`,
                                                                                                                                                                backgroundColor: getStatusColor(task.status),
                                                                                                                                                      }}
                                                                                                                                            />
                                                                                                                                  </div>
                                                                                                                                  <span className="text-[10px] font-medium w-8 text-right"
                                                                                                                                            style={{ color: getStatusColor(task.status) }}>
                                                                                                                                            {Math.round(task.progress_percent)}%
                                                                                                                                  </span>
                                                                                                                        </div>
                                                                                                                        {/* Time ago */}
                                                                                                                        <p className="text-[10px] mt-1.5"
                                                                                                                                  style={{ color: 'var(--mars-color-text-tertiary)' }}>
                                                                                                                                  {timeAgo(task.created_at)}
                                                                                                                        </p>
                                                                                                              </div>
                                                                                                              {/* Delete button */}
                                                                                                              <div
                                                                                                                        role="button"
                                                                                                                        tabIndex={0}
                                                                                                                        onClick={(e) => handleDelete(task.task_id, e)}
                                                                                                                        onKeyDown={(e) => { if (e.key === 'Enter') handleDelete(task.task_id, e as unknown as React.MouseEvent) }}
                                                                                                                        className="flex-shrink-0 p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity
                                                                                                                                  hover:bg-[var(--mars-color-danger-subtle,rgba(239,68,68,0.1))]"
                                                                                                                        title="Delete task"
                                                                                                              >
                                                                                                                        <X className="w-3 h-3" style={{ color: 'var(--mars-color-text-tertiary)' }} />
                                                                                                              </div>
                                                                                                    </div>
                                                                                          </button>
                                                                                ))
                                                                      )}
                                                            </div>

                                                            {/* Footer total */}
                                                            <div className="flex-shrink-0 px-4 py-2 border-t text-[10px]"
                                                                      style={{
                                                                                borderColor: 'var(--mars-color-border)',
                                                                                color: 'var(--mars-color-text-tertiary)',
                                                                      }}>
                                                                      {recentTasks.length} session{recentTasks.length !== 1 ? 's' : ''} total
                                                            </div>
                                                  </div>
                                        )}
                              </div>
                    </div>
          )
}

export default function Home() {
          return <HomeContent />
}
