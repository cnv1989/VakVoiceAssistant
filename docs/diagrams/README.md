# Diagram sources

These `.mmd` files are the [Mermaid](https://mermaid.js.org/) source for
the PNGs in [`../images/`](../images/) that the docs embed. Docs embed the rendered images instead of live Mermaid code fences so
diagrams show up correctly everywhere — not just on GitHub, which renders
Mermaid natively, but also plain Markdown viewers, PDF exports, etc.

If you change one of these files, re-render it with
[`@mermaid-js/mermaid-cli`](https://github.com/mermaid-js/mermaid-cli):

```bash
npx @mermaid-js/mermaid-cli \
  -i docs/diagrams/<name>.mmd \
  -o docs/images/<name>.png \
  -b white -s 3 \
  -c '{"theme":"neutral"}'
```

`-s 3` renders at 3x scale for crisp text on high-DPI displays; `-b white`
keeps the background readable regardless of the viewer's light/dark theme.

| File | Used in |
|---|---|
| `system-overview.mmd` | [`README.md`](../../README.md) |
| `client-audio-pipeline.mmd` | [`ARCHITECTURE.md`](../ARCHITECTURE.md#audio-pipeline) |
| `backend-request-flow.mmd` | [`ARCHITECTURE.md`](../ARCHITECTURE.md#request-flow) |
| `session-lifecycle.mmd` | [`ARCHITECTURE.md`](../ARCHITECTURE.md#session-lifecycle) |
| `infra-stack-hierarchy.mmd` | [`ARCHITECTURE.md`](../ARCHITECTURE.md#stack-hierarchy) |
| `deployment-pipeline.mmd` | [`ARCHITECTURE.md`](../ARCHITECTURE.md#deployment-pipeline) |
| `design-system-overview.mmd` | [`DESIGN.md`](../DESIGN.md#system-overview) |
| `deploy-flow.mmd` | [`DEPLOYMENT.md`](../DEPLOYMENT.md) |
| `vakdeepgram-architecture.mmd` | [`VakDeepGram/README.md`](../../VakDeepGram/README.md#architecture) |
