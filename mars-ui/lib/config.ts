const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8022'

function toWsUrl(httpUrl: string): string {
          return httpUrl.replace(/^http/, 'ws')
}

export const config = {
          apiUrl: API_URL,
          wsUrl: toWsUrl(API_URL),
}

export function getApiUrl(path: string): string {
          return `${config.apiUrl}${path}`
}

export function getWsUrl(path: string): string {
          return `${config.wsUrl}${path}`
}
