# Third-Party Notices

## gzh-design-skill

This product includes a vendored source snapshot at
`_third_party/gzh-design-skill` from
<https://github.com/isjiamu/gzh-design-skill>.

- Upstream commit: `ba1f4175519b481cb3566616c9e5178705067904`
- License: GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)
- Copyright and license notices: retained verbatim in the vendored directory.

The snapshot is used for internal theme components, preview examples, and
strict HTML/component validation. It is not modified by application runtime
operations; application-created themes are stored in the database.

For every internal deployment that provides network access to this product,
the corresponding source for the vendored snapshot and the integration code is
available to its users from the deployed source package. Before any external
distribution, complete a license review and provide the corresponding source
as required by AGPL-3.0.

## SearXNG

The optional image-search deployment pulls the unmodified official SearXNG
container from <https://github.com/searxng/searxng>.

- Container: `docker.io/searxng/searxng`
- Pinned image index: `sha256:f4c8e59de166ed71f6380c0847c312ca51f0d41996e31d0559163b6b09ecde52`
- License: GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)

SearXNG runs as a separate service and is not modified or vendored into this
repository. Its corresponding source and license notices remain available from
the official upstream project and container image.

## AICSS

The AI-output presentation layer incorporates the public React and plain-CSS
component examples published by AICSS at <https://www.aicss.dev/components>.
The integration is local to `frontend/src/components/AiOutput.tsx` and
`frontend/src/components/ai-output.css`; it does not add an AICSS package or
make AICSS a runtime dependency.

Adopted component patterns: Thinking State, Orbs, Thinking + Reasoning,
Streaming Text, Text Response, Web Search, File Diff, Code Block, Data Table,
To-do List, Inline Citations, Comparison Table, Image Generation, and AI Agent
Input. The application deliberately keeps its existing prompt composer and
uses the AI Agent Input pattern only in the shared component layer, because
this integration is scoped to AI output.

No license or terms page was published by the source site at the time this
notice was added. This notice records the source and the exact components used;
review any subsequently published upstream license terms before redistributing
the adapted implementation.
