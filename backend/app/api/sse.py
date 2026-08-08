"""Headers required for unbuffered, non-cacheable SSE responses."""

SSE_RESPONSE_HEADERS = {
    # Do not let browsers, reverse proxies, or CDN edges retain or transform
    # a partial agent response before it reaches the EventSource client.
    "Cache-Control": "no-store, no-cache, max-age=0, must-revalidate, no-transform",
    "Pragma": "no-cache",
    "Expires": "0",
    "Surrogate-Control": "no-store",
    "X-Accel-Buffering": "no",
}
