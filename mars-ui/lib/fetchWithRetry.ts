export async function apiFetchWithRetry(
          url: string,
          options?: RequestInit,
          retries = 3,
          delay = 1000,
): Promise<Response> {
          for (let attempt = 0; attempt <= retries; attempt++) {
                    try {
                              const controller = new AbortController()
                              const timeoutId = setTimeout(() => controller.abort(), 30000)
                              const response = await fetch(url, {
                                        ...options,
                                        signal: controller.signal,
                              })
                              clearTimeout(timeoutId)
                              if (response.ok || attempt === retries) return response
                    } catch (err) {
                              if (attempt === retries) throw err
                    }
                    await new Promise((r) => setTimeout(r, delay * (attempt + 1)))
          }
          // Unreachable, but satisfies TS
          throw new Error('apiFetchWithRetry: exhausted retries')
}
