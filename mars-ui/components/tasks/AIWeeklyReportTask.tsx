'use client'

import React, { useEffect, useCallback } from 'react'
import { Trash2, RotateCcw } from 'lucide-react'
import { Button } from '@/components/core'
import Stepper from '@/components/core/Stepper'
import type { StepperStep } from '@/components/core/Stepper'
import { useAIWeeklyTask } from '@/hooks/useAIWeeklyTask'
import {
    AIWEEKLY_STEP_LABELS,
    AIWEEKLY_WIZARD_STEP_TO_STAGE,
    AIWEEKLY_STAGE_SHARED_KEYS,
} from '@/types/aiweekly'
import type { AIWeeklyWizardStep } from '@/types/aiweekly'
import AIWeeklySetupPanel from '@/components/aiweekly/AIWeeklySetupPanel'
import AIWeeklyReviewPanel from '@/components/aiweekly/AIWeeklyReviewPanel'
import AIWeeklyReportPanel from '@/components/aiweekly/AIWeeklyReportPanel'

interface AIAIWeeklyReportTaskProps {
    onBack: () => void
    resumeTaskId?: string | null
}

export default function AIWeeklyReportTask({ onBack, resumeTaskId }: AIAIWeeklyReportTaskProps) {
    const hook = useAIWeeklyTask()
    const {
        taskId, taskState, currentStep, error, isExecuting,
        setCurrentStep, resumeTask, deleteTask, resetFromStage, clearError,
    } = hook

    useEffect(() => {
        if (resumeTaskId) resumeTask(resumeTaskId)
    }, [resumeTaskId, resumeTask])

    // Stepper
    const stepperSteps: StepperStep[] = AIWEEKLY_STEP_LABELS.map((label, idx) => {
        const stageNum = AIWEEKLY_WIZARD_STEP_TO_STAGE[idx]
        let status: StepperStep['status'] = 'pending'

        if (taskState && stageNum) {
            const stage = taskState.stages.find(s => s.stage_number === stageNum)
            if (stage) {
                if (stage.status === 'completed') status = 'completed'
                else if (stage.status === 'failed') status = 'failed'
                else if (stage.status === 'running') status = 'active'
            }
        } else if (idx < currentStep) {
            status = 'completed'
        }

        if (idx === 0 && taskId) status = 'completed'
        if (idx === currentStep && status !== 'failed') status = 'active'

        return { id: `step-${idx}`, label, status }
    })

    const goNext = useCallback(() => {
        if (currentStep < 4) setCurrentStep((currentStep + 1) as AIWeeklyWizardStep)
    }, [currentStep, setCurrentStep])

    const goBack = useCallback(() => {
        if (currentStep > 0 && !isExecuting) setCurrentStep((currentStep - 1) as AIWeeklyWizardStep)
    }, [currentStep, isExecuting, setCurrentStep])

    const handleDelete = useCallback(async () => {
        if (!confirm('Delete this task? This will remove all data and files.')) return
        await deleteTask()
        onBack()
    }, [deleteTask, onBack])

    const handleStepClick = useCallback((index: number) => {
        if (isExecuting) return
        setCurrentStep(index as AIWeeklyWizardStep)
    }, [isExecuting, setCurrentStep])

    const hasLaterCompletedStages = useCallback(() => {
        if (!taskState) return false
        const currentStageNum = AIWEEKLY_WIZARD_STEP_TO_STAGE[currentStep]
        if (!currentStageNum) return false
        return taskState.stages.some(s => s.stage_number > currentStageNum && s.status === 'completed')
    }, [taskState, currentStep])

    const handleResetFromHere = useCallback(async () => {
        const stageNum = AIWEEKLY_WIZARD_STEP_TO_STAGE[currentStep]
        if (!stageNum) return
        const nextStage = stageNum + 1
        if (nextStage > 4) return
        if (!confirm(`Reset all stages from Stage ${nextStage} onwards?`)) return
        await resetFromStage(nextStage)
    }, [currentStep, resetFromStage])

    return (
        <div className="p-6 max-w-7xl mx-auto">
            {/* Header */}
            <div className="flex items-center gap-3 mb-6">
                <div>
                    <h2 className="text-2xl font-semibold" style={{ color: 'var(--mars-color-text)' }}>
                        AI Weekly Report
                    </h2>
                    <p className="text-sm mt-0.5" style={{ color: 'var(--mars-color-text-secondary)' }}>
                        Generate a publication-ready weekly AI report through 4 interactive stages
                    </p>
                </div>
                {taskState?.total_cost_usd != null && taskState.total_cost_usd > 0 && (
                    <div
                        className="ml-auto text-xs px-3 py-1.5 rounded-mars-md"
                        style={{
                            backgroundColor: 'var(--mars-color-surface-overlay)',
                            color: 'var(--mars-color-text-secondary)',
                        }}
                    >
                        Cost: ${taskState.total_cost_usd.toFixed(4)}
                    </div>
                )}
                {taskId && (
                    <div className={`flex items-center gap-2 ${taskState?.total_cost_usd ? '' : 'ml-auto'}`}>
                        <Button onClick={handleDelete} variant="secondary" size="sm" disabled={isExecuting}>
                            <Trash2 className="w-3.5 h-3.5 mr-1" />Delete
                        </Button>
                    </div>
                )}
            </div>

            {/* Error banner */}
            {error && (
                <div className="mb-4 p-3 rounded-mars-md flex items-center justify-between text-sm"
                    style={{ backgroundColor: 'var(--mars-color-danger-subtle)', color: 'var(--mars-color-danger)', border: '1px solid var(--mars-color-danger)' }}>
                    <span>{error}</span>
                    <button onClick={clearError} className="ml-2 font-medium underline">Dismiss</button>
                </div>
            )}

            {/* Stepper */}
            <div className="mb-8">
                <Stepper steps={stepperSteps} orientation="horizontal" size="sm" onStepClick={taskId ? handleStepClick : undefined} />
            </div>

            {/* Reset banner */}
            {hasLaterCompletedStages() && !isExecuting && (
                <div className="mb-4 p-3 rounded-mars-md flex items-center justify-between text-sm"
                    style={{ backgroundColor: 'var(--mars-color-warning-subtle, rgba(245,158,11,0.1))', border: '1px solid var(--mars-color-warning, #f59e0b)', color: 'var(--mars-color-text)' }}>
                    <span style={{ color: 'var(--mars-color-text-secondary)' }}>
                        Stages after this one have been completed. You can reset them to re-run.
                    </span>
                    <button onClick={handleResetFromHere}
                        className="ml-3 flex items-center gap-1.5 px-3 py-1.5 rounded-mars-sm text-xs font-medium transition-colors"
                        style={{ backgroundColor: 'var(--mars-color-warning, #f59e0b)', color: '#fff' }}>
                        <RotateCcw className="w-3.5 h-3.5" />Reset Later Stages
                    </button>
                </div>
            )}

            {/* Panel content */}
            <div>
                {currentStep === 0 && (
                    <AIWeeklySetupPanel hook={hook} onNext={goNext} />
                )}
                {currentStep === 1 && (
                    <AIWeeklyReviewPanel hook={hook} stageNum={1} stageName="Data Collection"
                        sharedKey="raw_collection" onNext={goNext} onBack={goBack} />
                )}
                {currentStep === 2 && (
                    <AIWeeklyReviewPanel hook={hook} stageNum={2} stageName="Content Curation"
                        sharedKey="curated_items" onNext={goNext} onBack={goBack} />
                )}
                {currentStep === 3 && (
                    <AIWeeklyReviewPanel hook={hook} stageNum={3} stageName="Report Generation"
                        sharedKey="draft_report" onNext={goNext} onBack={goBack} />
                )}
                {currentStep === 4 && (
                    <AIWeeklyReportPanel hook={hook} stageNum={4} onBack={goBack} />
                )}
            </div>
        </div>
    )
}
