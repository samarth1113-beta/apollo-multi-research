import React, { useState, useEffect } from 'react'

export const KEY_FIELDS = [
  { name: 'OPENROUTER_API_KEY', label: 'OpenRouter API Key', required: true },
  { name: 'OPENAI_API_KEY', label: 'OpenAI API Key', required: false },
  { name: 'ANTHROPIC_API_KEY', label: 'Anthropic API Key', required: false },
  { name: 'TAVILY_API_KEY', label: 'Tavily API Key', required: true },
  { name: 'PERPLEXITY_API_KEY', label: 'Perplexity API Key', required: false },
  { name: 'REDDIT_CLIENT_ID', label: 'Reddit Client ID', required: false },
  { name: 'REDDIT_SECRET', label: 'Reddit Secret', required: false },
  { name: 'YOUTUBE_API_KEY', label: 'YouTube API Key', required: false },
  { name: 'GITHUB_TOKEN', label: 'GitHub Token', required: false },
]

export const EMPTY_KEYS = KEY_FIELDS.reduce((acc, f) => {
  acc[f.name] = ''
  return acc
}, {})

export default function ConfigPanel({
  apiBase,
  keys,
  setKeys,
  isOpen,
  setIsOpen,
  statusMessage,
  setStatusMessage,
  onKeysSaved,
}) {
  const [visibleFields, setVisibleFields] = useState({})
  const [isSaving, setIsSaving] = useState(false)

  // On app load, call GET /api/keys and prefill the inputs with the saved values
  useEffect(() => {
    let cancelled = false
    fetch(`${apiBase}/api/keys`)
      .then(async (resp) => {
        if (!resp.ok) {
          const errData = await resp.json().catch(() => ({}))
          throw new Error(errData.detail || `HTTP ${resp.status}`)
        }
        return resp.json()
      })
      .then((data) => {
        if (cancelled) return
        if (data.expired) {
          setKeys({ ...EMPTY_KEYS })
          setIsOpen(true)
          setStatusMessage({
            type: 'warning',
            text: 'Your API keys are older than 30 days and were cleared. Please enter them again.',
          })
        } else if (data.keys && typeof data.keys === 'object') {
          const nextKeys = { ...EMPTY_KEYS }
          for (const field of KEY_FIELDS) {
            nextKeys[field.name] = data.keys[field.name] || ''
          }
          setKeys(nextKeys)
        }
      })
      .catch(() => {
        // Backend may not be reachable yet on initial load; handled on save/start
      })

    return () => {
      cancelled = true
    }
  }, [apiBase, setKeys, setIsOpen, setStatusMessage])

  const toggleFieldVisibility = (fieldName) => {
    setVisibleFields((prev) => ({
      ...prev,
      [fieldName]: !prev[fieldName],
    }))
  }

  const handleInputChange = (fieldName, value) => {
    setKeys((prev) => ({
      ...prev,
      [fieldName]: value,
    }))
  }

  const handleSaveKeys = async (e) => {
    if (e) e.preventDefault()
    setIsSaving(true)
    setStatusMessage(null)

    try {
      const resp = await fetch(`${apiBase}/api/keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(keys),
      })
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}))
        throw new Error(errData.detail || `Failed to save keys (HTTP ${resp.status})`)
      }
      setStatusMessage({
        type: 'success',
        text: 'Keys saved to .env (GitIgnored).',
      })
      if (onKeysSaved) onKeysSaved()
    } catch (err) {
      setStatusMessage({
        type: 'error',
        text: err.message || 'Failed to save API keys.',
      })
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div>
      <h2 className="text-[17px] font-bold text-[#31333F] mb-3 flex items-center gap-1.5">
        <span>⚙️ Configuration</span>
      </h2>

      <div className="bg-white border border-[#E5E7EB] rounded-[8px] overflow-hidden">
        {/* Collapsible Section Header with '>' arrow */}
        <button
          type="button"
          onClick={() => setIsOpen((prev) => !prev)}
          aria-expanded={isOpen}
          className="w-full px-3.5 py-2.5 flex items-center gap-2.5 text-left hover:bg-[#F9FAFB] transition cursor-pointer"
        >
          <span
            className={`text-xs text-[#6B7280] font-bold inline-block transition-transform duration-150 ${
              isOpen ? 'rotate-90' : ''
            }`}
          >
            &gt;
          </span>
          <span className="text-sm font-medium text-[#31333F]">
            🔑 API Keys
          </span>
        </button>

        {/* Collapsible Content */}
        {isOpen && (
          <form
            onSubmit={handleSaveKeys}
            className="px-3.5 pb-4 pt-2 border-t border-[#E5E7EB] space-y-3"
          >
            <div className="space-y-3">
              {KEY_FIELDS.map((field) => {
                const isVisible = Boolean(visibleFields[field.name])
                return (
                  <div key={field.name} className="flex flex-col">
                    <label
                      htmlFor={`key-input-${field.name}`}
                      className="text-xs font-medium text-[#31333F] mb-1.5"
                    >
                      {field.label}
                    </label>
                    <div className="relative flex items-center">
                      <input
                        id={`key-input-${field.name}`}
                        type={isVisible ? 'text' : 'password'}
                        value={keys[field.name] || ''}
                        onChange={(e) => handleInputChange(field.name, e.target.value)}
                        autoComplete="off"
                        spellCheck={false}
                        className="w-full rounded-[8px] bg-[#F0F2F6] border border-transparent focus:border-[#FF4B4B] focus:bg-white pl-3 pr-9 py-2 text-xs text-[#31333F] placeholder-[#6B7280] focus:outline-none transition"
                      />
                      <button
                        type="button"
                        onClick={() => toggleFieldVisibility(field.name)}
                        title={isVisible ? `Hide ${field.label}` : `Show ${field.label}`}
                        aria-label={isVisible ? `Hide ${field.label}` : `Show ${field.label}`}
                        className="absolute right-2.5 text-[#31333F] hover:text-black p-1 cursor-pointer select-none"
                      >
                        {isVisible ? (
                          <svg
                            xmlns="http://www.w3.org/2000/svg"
                            viewBox="0 0 24 24"
                            fill="currentColor"
                            className="w-4 h-4 text-[#6B7280]"
                          >
                            <path d="M3.53 2.47a.75.75 0 00-1.06 1.06l18 18a.75.75 0 101.06-1.06l-18-18zM22.676 12.553a11.249 11.249 0 01-2.631 4.31l-3.099-3.099a5.25 5.25 0 00-6.71-6.71L7.759 4.577a11.217 11.217 0 014.242-.827c4.97 0 9.185 3.223 10.675 7.69.12.362.12.752 0 1.113z" />
                            <path d="M15.75 12c0 .18-.013.357-.037.53l-4.244-4.243A3.75 3.75 0 0115.75 12zM12.53 15.713l-4.243-4.244a3.75 3.75 0 004.243 4.243z" />
                            <path d="M6.75 12c0-.619.107-1.213.304-1.764l-3.1-3.1a11.25 11.25 0 00-2.63 4.31c-.12.362-.12.752 0 1.114 1.489 4.467 5.704 7.69 10.675 7.69 1.5 0 2.933-.294 4.242-.827l-2.477-2.477A5.25 5.25 0 016.75 12z" />
                          </svg>
                        ) : (
                          <svg
                            xmlns="http://www.w3.org/2000/svg"
                            viewBox="0 0 24 24"
                            fill="currentColor"
                            className="w-4 h-4 text-[#31333F]"
                          >
                            <path d="M12 15a3 3 0 100-6 3 3 0 000 6z" />
                            <path
                              fillRule="evenodd"
                              d="M1.323 11.447C2.811 6.976 7.028 3.75 12.001 3.75c4.97 0 9.185 3.223 10.675 7.69.12.362.12.752 0 1.113-1.487 4.471-5.705 7.697-10.677 7.697-4.97 0-9.186-3.223-10.675-7.69a1.762 1.762 0 010-1.113zM17.25 12a5.25 5.25 0 11-10.5 0 5.25 5.25 0 0110.5 0z"
                              clipRule="evenodd"
                            />
                          </svg>
                        )}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>

            <div className="pt-1 space-y-2.5">
              <button
                type="submit"
                disabled={isSaving}
                className="px-3.5 py-1.5 rounded-[8px] bg-white hover:bg-[#F0F2F6] active:bg-[#E5E7EB] border border-[#D1D5DB] text-[#31333F] text-sm font-medium transition cursor-pointer disabled:opacity-50"
              >
                {isSaving ? 'Saving...' : 'Save Keys'}
              </button>

              {statusMessage && (
                <div
                  role="status"
                  className={`text-xs font-medium px-3 py-2 rounded-[8px] border ${
                    statusMessage.type === 'success'
                      ? 'bg-[#E8F5E9] border-[#C8E6C9] text-[#2E7D32]'
                      : statusMessage.type === 'warning'
                      ? 'bg-[#FFF8E1] border-[#FFE082] text-[#B45309]'
                      : 'bg-[#FFEBEE] border-[#FFCDD2] text-[#C62828]'
                  }`}
                >
                  {statusMessage.text}
                </div>
              )}
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
