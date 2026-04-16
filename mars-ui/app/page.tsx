'use client'

import { Suspense, useState, useEffect, useCallback, useRef } from 'react'
import { useSearchParams } from 'next/navigation'
import { Newspaper, Plus, History, ArrowRight, X, ChevronLeft, ChevronRight } from 'lucide-react'
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

function ResumeParam({ onResume }: { onResume: (id: string) => void }) {
          const searchParams = useSearchParams()
          const resumeFromUrl = searchParams.get('resume')
          useEffect(() => {
                    if (resumeFromUrl) onResume(resumeFromUrl)
          }, [resumeFromUrl, onResume])
          return null
}

function HomeContent() {
          const [view, setView] = useState<'task' | 'resumed'>('task')
          const [resumeTaskId, setResumeTaskId] = useState<string | null>(null)
          const [recentTasks, setRecentTasks] = useState<RecentTask[]>([])
          const [panelOpen, setPanelOpen] = useState(true)
          const [recentDropdownOpen, setRecentDropdownOpen] = useState(false)
          const dropdownRef = useRef<HTMLDivElement>(null)

          const handleUrlResume = useCallback((id: string) => {
                    setResumeTaskId(id)
                    setView('resumed')
          }, [])

          const fetchRecent = useCallback(() => {
                    fetch(getApiUrl('/api/aiweekly/recent'))
                              .then(r => r.ok ? r.json() : [])
                              .then((data: RecentTask[]) => setRecentTasks(data))
                              .catch(() => { })
          }, [])

          const handleStartNew = useCallback(() => {
                    setResumeTaskId(null)
                    setView('task')
          }, [])

          const handleResume = useCallback((id: string) => {
                    setResumeTaskId(id)
                    setView('resumed')
                    setRecentDropdownOpen(false)
          }, [])

          const handleDelete = useCallback(async (id: string, e: React.MouseEvent) => {
                    e.stopPropagation()
                    if (!confirm('Delete this task? This will remove all data and files.')) return
                    try {
                              await fetch(getApiUrl(`/api/aiweekly/${id}`), { method: 'DELETE' })
                              setRecentTasks(prev => prev.filter(t => t.task_id !== id))
                    } catch { /* ignore */ }
          }, [])

          const handleRecentToggle = useCallback(() => {
                    if (!recentDropdownOpen) fetchRecent()
                    setRecentDropdownOpen(prev => !prev)
          }, [recentDropdownOpen, fetchRecent])

          // Close dropdown on outside click
          useEffect(() => {
                    if (!recentDropdownOpen) return
                    const handleClick = (e: MouseEvent) => {
                              if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
                                        setRecentDropdownOpen(false)
                              }
                    }
                    document.addEventListener('mousedown', handleClick)
                    return () => document.removeEventListener('mousedown', handleClick)
          }, [recentDropdownOpen])

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

                              {/* Right collapsible panel */}
                              <div
                                        className="flex-shrink-0 border-l h-full flex flex-col transition-all duration-300"
                                        style={{
                                                  width: panelOpen ? '480px' : '40px',
                                                  backgroundColor: 'var(--mars-color-surface-raised)',
                                                  borderColor: 'var(--mars-color-border)',
                                        }}
                              >
                                        {/* Toggle button */}
                                        <button
                                                  onClick={() => setPanelOpen(prev => !prev)}
                                                  className="p-2 flex items-center justify-center transition-colors hover:bg-[var(--mars-color-bg-hover)]"
                                                  style={{ color: 'var(--mars-color-text-secondary)' }}
                                                  aria-label={panelOpen ? 'Collapse panel' : 'Expand panel'}
                                        >
                                                  {panelOpen ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
                                        </button>

                                        {panelOpen && (
                                                  <div className="flex flex-col gap-2 px-3 py-2">
                                                            {/* Start New Task button */}
                                                            <button
                                                                      onClick={handleStartNew}
                                                                      className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-mars-md transition-colors hover:bg-[var(--mars-color-bg-hover)]"
                                                                      style={{ color: 'var(--mars-color-text)' }}
                                                            >
                                                                      <Plus className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--mars-color-primary)' }} />
                                                                      Start New Task
                                                            </button>

                                                            {/* Recent Tasks dropdown */}
                                                            <div className="relative" ref={dropdownRef}>
                                                                      <button
                                                                                onClick={handleRecentToggle}
                                                                                className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-mars-md transition-colors hover:bg-[var(--mars-color-bg-hover)]"
                                                                                style={{ color: 'var(--mars-color-text)' }}
                                                                      >
                                                                                <History className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--mars-color-primary)' }} />
                                                                                Recent Tasks
                                                                      </button>

                                                                      {recentDropdownOpen && (
                                                                                <div
                                                                                          className="mt-1 rounded-mars-md border shadow-lg overflow-hidden max-h-[60vh] overflow-y-auto"
                                                                                          style={{
                                                                                                    backgroundColor: 'var(--mars-color-surface)',
                                                                                                    borderColor: 'var(--mars-color-border)',
                                                                                          }}
                                                                                >
                                                                                          {recentTasks.length === 0 ? (
                                                                                                    <p className="p-3 text-xs" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                                                                                                              No recent tasks found.
                                                                                                    </p>
                                                                                          ) : (
                                                                                                    recentTasks.map((task) => (
                                                                                                              <button
                                                                                                                        key={task.task_id}
                                                                                                                        onClick={() => handleResume(task.task_id)}
                                                                                                                        className="w-full flex items-center gap-2 p-2 text-left transition-colors hover:bg-[var(--mars-color-bg-hover)] border-b last:border-b-0"
                                                                                                                        style={{ borderColor: 'var(--mars-color-border)' }}
                                                                                                              >
                                                                                                                        <div className="flex-shrink-0 w-6 h-6 rounded flex items-center justify-center"
                                                                                                                                  style={{ background: 'linear-gradient(135deg, #3b82f6, #2563eb)' }}>
                                                                                                                                  <Newspaper className="w-3 h-3 text-white" />
                                                                                                                        </div>
                                                                                                                        <div className="flex-1 min-w-0">
                                                                                                                                  <p className="text-xs font-medium truncate" style={{ color: 'var(--mars-color-text)' }}>
                                                                                                                                            {task.task ? task.task : 'AI Weekly Report'}
                                                                                                                                  </p>
                                                                                                                                  <p className="text-[10px]" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                                                                                                                                            {task.current_stage
                                                                                                                                                      ? `Stage ${task.current_stage}: ${STAGE_NAMES[task.current_stage] || ''}`
                                                                                                                                                      : 'Starting...'}
                                                                                                                                            {' · '}{Math.round(task.progress_percent)}%
                                                                                                                                  </p>
                                                                                                                        </div>
                                                                                                                        <div
                                                                                                                                  role="button"
                                                                                                                                  tabIndex={0}
                                                                                                                                  onClick={(e) => handleDelete(task.task_id, e)}
                                                                                                                                  onKeyDown={(e) => { if (e.key === 'Enter') handleDelete(task.task_id, e as unknown as React.MouseEvent) }}
                                                                                                                                  className="flex-shrink-0 p-1 rounded transition-colors hover:bg-[var(--mars-color-danger-subtle,rgba(239,68,68,0.1))]"
                                                                                                                                  title="Delete task"
                                                                                                                        >
                                                                                                                                  <X className="w-3 h-3" style={{ color: 'var(--mars-color-text-tertiary)' }} />
                                                                                                                        </div>
                                                                                                              </button>
                                                                                                    ))
                                                                                          )}
                                                                                </div>
                                                                      )}
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
