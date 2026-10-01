# Adding a model provider

If the provider speaks the OpenAI API, it already works through `openai_compatible` — consider documenting it instead.

1. Create `apps/api/isocline/providers/<name>.py` with a subclass of `LLMProvider` (`providers/base.py`):
   - class attributes: `id`, `name`, `default_base_url`, `requires_key`, `base_supported_params`,
     `env_api_key` / `env_base_url` (environment variables for self-hosted BYOK);
   - `async generate(messages, model, config, tools=None, response_schema=None, timeout=120) -> GenerateResult`
     (text, tool calls, structured output, token usage, model);
   - optional `async list_models() -> list[ModelInfo]`.
   Use `providers/http.py::post_json` so HTTP errors map to `ProviderError` kinds (`rate_limit`, `timeout`,
   `unavailable`, `auth`, ...) that recovery rules understand. Never log keys.
2. Register it in `providers/registry.py` (`_PROVIDERS`). Nothing else branches on provider ids.
3. Add catalog rows (model, prices, capabilities) to `apps/api/isocline/data/model_catalog.json`.
4. Test with `respx` (no network, no key): request shape, tool-call parsing, error mapping, usage. See
   `apps/api/tests/unit/test_core_units.py` for patterns.
5. Document it in `docs/providers.md` and `.env.example`.
