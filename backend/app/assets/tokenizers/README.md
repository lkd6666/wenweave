# Bundled token estimator

The backend uses `o200k_base` from tiktoken 0.13.0 as a shared local text
estimator for all providers. It is an approximation; provider usage remains
the source of actual input, output and cache accounting.

- Source: https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken
- SHA-256: `446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d`
- Definition: `tiktoken_ext.openai_public.o200k_base`, tiktoken 0.13.0.
- License: MIT, retained in `LICENSE`.

Each worker verifies and loads the table once during startup. Counting is
offline and independent of `TIKTOKEN_CACHE_DIR`. Missing or corrupt tables
fall back to character estimation and emit a diagnostic; the next worker
startup retries loading. Runtime estimates keep the existing 1.6 safety
multiplier, image allowance and tool-schema budgeting.

Include this directory when packaging the backend. No extra configuration or
post-deployment download is required. `.gitattributes` disables line-ending
conversion for the checksum-verified table. It occupies about 3.4 MiB on disk;
its loaded encoding uses roughly 65 MiB per worker on the measured Windows
environment. Immutable history/message counts retain their existing caches.
