export async function apiFetchWithRetry(
          url: string,
          options?: RequestInit,
          retries = 2,
          delay = 500,
): Promise<Response> {
          for (let attempt = 0; attempt <= retries; attempt++) {
                    try {
                              const response = await fetch(url, options)
                              if (response.ok || attempt === retries) return response
                    } catch (err) {
                              if (attempt === retries) throw err
                    }
                    await new Promise((r) => setTimeout(r, delay * (attempt + 1)))
          }
          // Unreachable, but satisfies TS
          throw new Error('apiFetchWithRetry: exhausted retries')
}
