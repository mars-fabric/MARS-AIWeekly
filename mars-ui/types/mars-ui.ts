export type ToastType = 'info' | 'success' | 'warning' | 'error'

export type ToastData = {
          id: string
          type: ToastType
          title: string
          message?: string
          duration?: number
          action?: {
                    label: string
                    onClick: () => void
          }
}
