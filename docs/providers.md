# Providers

| id | Class | Key env var(s) | Base URL env var | Notes |
|---|---|---|---|---|
| `openai` | `OpenAIProvider` | `OPENAI_API_KEY` | `OPENAI_BASE_URL` | Chat Completions, tools, JSON schema |
| `anthropic` | `AnthropicProvider` | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL` | Messages API, tools |
| `google` | `GeminiProvider` | `GEMINI_API_KEY`, `GOOGLE_API_KEY` | `GEMINI_BASE_URL` | Gemini API |
| `openrouter` | `OpenRouterProvider` | `OPENROUTER_API_KEY` | — | OpenAI-compatible |
| `ollama` | `OllamaProvider` | — | `OLLAMA_BASE_URL` | local models; no key |
| `openai_compatible` | `OpenAICompatibleProvider` | `OPENAI_COMPATIBLE_API_KEY` | `OPENAI_COMPATIBLE_BASE_URL` | vLLM, LM Studio, llama.cpp server, LiteLLM, TGI, or any HTTP endpoint speaking the OpenAI API — this is the "generic HTTP" provider |
| `local_test` | `LocalTestProvider` | — | — | deterministic test fixture |

**Credential resolution** for a model call: the node's `credential_id` if set (only that credential), else the first
workspace credential for the provider whose scope admits the call, else the provider's environment variables.
Environment credentials are shared by all accounts on the installation. Keys never enter workflow JSON.

Adding one: [contributing/adding-a-provider.md](contributing/adding-a-provider.md). Design:
[design/model-provider-abstraction.md](design/model-provider-abstraction.md).
