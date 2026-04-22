'use client'

export default function FooterBar() {
          return (
                    <footer
                              className="flex flex-shrink-0 border-t"
                              style={{
                                        backgroundColor: 'var(--mars-color-surface-raised)',
                                        borderColor: 'var(--mars-color-border)',
                              }}
                              role="contentinfo"
                    >
                              <div
                                        className="flex items-center justify-between px-6 w-full"
                                        style={{ height: '64px' }}
                              >
                                        {/* Left: branding */}
                                        <div className="flex items-center gap-2">
                                                  <div className="w-5 h-5 rounded flex items-center justify-center"
                                                            style={{ background: 'linear-gradient(135deg, #6366f1, #3b82f6)' }}>
                                                            <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                                                      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                                                            </svg>
                                                  </div>
                                                  <span className="text-xs font-semibold" style={{ color: 'var(--mars-color-text-secondary)' }}>
                                                            MARS - AI Weekly
                                                  </span>
                                                  <span className="text-[11px]" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                                                            · AI-Powered Weekly Report Generator
                                                  </span>
                                        </div>

                                        {/* Right: version / info */}
                                        <div className="flex items-center gap-4">
                                                  <span className="text-[11px]" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                                                            4-stage automated pipeline
                                                  </span>
                                                  <span
                                                            className="text-[10px] px-2 py-0.5 rounded-full font-medium"
                                                            style={{
                                                                      backgroundColor: 'var(--mars-color-primary-subtle)',
                                                                      color: 'var(--mars-color-primary)',
                                                            }}
                                                  >
                                                            v1.0
                                                  </span>
                                        </div>
                              </div>
                    </footer>
          )
}
