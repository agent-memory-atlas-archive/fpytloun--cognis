# Rich Deliverables

Rich deliverables are durable, structured Cognis outputs. They let an agent
author a deliberate presentation instead of flattening everything into a
Markdown response, while retaining an accessible Markdown fallback.

Use them for decision briefs, dashboards, research reports, comparisons,
incident summaries, timelines, and other outputs where hierarchy, evidence, or
visual structure improves understanding.

## How they differ from artifacts and documents

| Capability | Best for | Primary representation |
|---|---|---|
| Artifact | A file, upload, generated image, PDF, or self-contained HTML page | Stored blob |
| Document tools | A portable PDF produced from Markdown/HTML | Generated PDF artifact |
| Rich deliverable | A structured, Cognis-native experience | Durable block payload plus Markdown fallback |

A rich deliverable is artifact-compatible as a `dlv_*` content reference, but
the downloadable virtual artifact is its fallback content. It is not the rich
payload JSON.

## Rendering targets

- **Web chat** renders the interactive rich layout directly in the
  conversation.
- **Open** uses the authenticated Cognis experience.
- **Share** mints a standalone temporary bearer URL when the user requests it.
  It is not a permanent public URL.
- **Channels** receive the accessible Markdown fallback rather than an
  interactive block tree.
- **PDF export** uses Cognis server-side rendering and caching. It is distinct
  from executor-side `document_generate`.
- **Single HTML export** is a self-contained offline publication. It uses the
  same content renderer as the hosted page, including Mermaid diagrams,
  responsive tables, charts, and typography. JavaScript must be enabled.
  Viewer download, copy, share, and close controls are omitted; table-of-contents
  navigation and content interactions remain available. It embeds authorized
  deliverable images as base64 data URLs and includes its styles and scripts in
  one file; unlike the live standalone page, it does not need Cognis assets or
  media routes to render. Missing referenced images cause an explicit failure
  rather than an incomplete download. The export is limited to 32 MiB.
- **Markdown export** downloads the stored Markdown fallback for rich and
  Markdown deliverables. It is not available for plain-text or HTML deliverables.

The download menu offers the available formats in embedded, full, and
standalone views. Share links can download the same formats while valid; the
downloaded files do not extend the life of a share token.

In chat, deliverables read as part of the assistant response: they use chat
typography and colors without a surrounding document card or toolbar. Tables,
charts, and figures can use the chat column while prose keeps its reading
measure. Revision history sits below the content on the left; icon-only
fullscreen, download, and sharing controls align on the right like assistant
message actions. The three-dot control contains copy, library, favorites, and
collapse actions. A side arrow opens Contents at the right of the deliverable:
a sticky sidebar in wide document areas, or a right-side drawer on narrow
screens. It collapses automatically when the document area narrows. Library
and standalone readers retain their document layout.

Virtual deliverable preview URLs open the original deliverable viewer, not a
reconstructed Markdown file preview. Converting a signed preview link preserves
its exact expiry; Markdown downloads are unchanged. Installed-app previews have
a Close control that returns to app history when available, or to the app home
page for direct launches.

Authenticated owners can open an expired share through their private access.
The viewer labels this as an expired shared link; anonymous readers and other
users do not gain access. Owner sharing offers 1, 7 (default), 30, or 90 days,
or a custom date/time within the next 90 days. Creating a link does not revoke
earlier links. Forever is not supported. The signing secret is deployment-wide,
so selective revocation is not available through key rotation.

Long documents automatically expose a table of contents based on section
headings, including multiple headings within one Markdown block. An explicit
`metadata.toc: false` still disables it. Figure images can be activated with a
click or keyboard to open a borderless gallery preview. On desktop, click the
image to zoom around the pointer, move the pointer to pan, and click again to
reset. On touch screens, double-tap to zoom/reset, pinch to change zoom, and
drag to pan. The magnifying-glass control also toggles zoom for touch and
keyboard users. Escape, Close, or clicking/tapping the backdrop returns focus
to the figure. The preview uses the same
authorized image URL; it does not mint another share or download link.
Deliverables inside Cognis, including task outputs and fullscreen views, follow
your account appearance and have no separate theme control. External standalone
readers have a theme icon that cycles through light, dark, and system settings;
that browser-local preference never overrides in-app appearance.
A collapsed desktop contents sidebar reopens
from a small arrow beside the title; narrow screens retain the right-side
contents control and overlay drawer.

PDFs adapt the publication design to A4 portrait: bundled Archivo and
JetBrains Mono fonts, semantic status badges, a compact contents list with
page links, and three-column summary metrics. Short structured tables (up to
four rows) stay with their headings when they fit on a page; longer tables
repeat column headers across pages. Fonts are packaged locally, not fetched
from external services. PDF bookmarks and page numbers remain available.
PDF diagrams use the packaged, offline Chromium/Mermaid CLI runtime to
render up to three authored Mermaid diagrams to images per export. The source
remains legible when a diagram is invalid, exceeds the bounded render budget,
or a non-Docker installation has no CLI configured.
Native installations must provide `COGNIS_MERMAID_CLI` and
`PUPPETEER_EXECUTABLE_PATH` for PDF diagram support; web rendering uses
the bundled browser Mermaid module instead.

The standalone renderer scopes media access to the shared deliverable and
applies its own security policy. It is not a static HTML artifact and should
not be described as hosting.

## Writing a rich deliverable

Agents use the `write_deliverable` `rich` action. The action accepts one
canonical payload source. Cognis normalizes that payload and derives the
channel-safe Markdown fallback.

```text
write_deliverable(
  action="rich",
  payload={
    title: "Weekly delivery review",
    blocks: [...],
    sources: [...],
    metadata: {...}
  }
)
```

For a substantial payload that would be difficult to inspect or retry inline,
create an editable local JSON file with the available file-editing tool and
publish it as `application/json` with `artifact_publish`. Then pass its
immutable `art_*` ID:

```text
write_deliverable(
  action="rich",
  payload_artifact={ artifact_id: "art_<32 lowercase hex characters>" }
)
```

Do not combine `payload` and `payload_artifact`. Rich calls do not accept
`content`, `format`, `rich`, top-level `title`, `target`, or top-level
`outputs`. Put the title and optional outputs in the payload.

Before writing a Rich deliverable, call `validate_tool_call` with the complete
proposed `write_deliverable` arguments. Then call `write_deliverable` with
those exact unchanged arguments. Validation receipts are bound to the argument
shape, including the selected payload source.

The **Cognis Rich Deliverable** system skill guides agents toward appropriate
composition, hierarchy, evidence, and block selection. It is a writing and
presentation guide; it does not replace schema validation.

### Dashboard presentation

Use `action: "rich:dashboard"` for dense, technical operational views. The
action owns the presentation metadata and applies a wide canvas with compact
spacing. Do not set `metadata.presentation` in an authored payload.

Embedded chat hosts keep control of their width. Full and standalone views use
the wider bounded dashboard canvas.

The payload can include a top-level `title`. The stored deliverable title from
the host takes precedence when both values exist.

## Viewer shell

Standalone and full-view rendering provide copy, download, and table-of-contents
controls. Only external standalone readers provide separate theme controls.
A payload can optionally identify that shell
with `metadata.viewer_identity` when an authored label or semantic icon adds
meaning. Omitting it adds no identity chrome.

## Revisions

To edit or replace an existing deliverable, call `write_deliverable` with
`supersedes` set to the `dlv_` ID of its latest revision. The result is a new
deliverable and the next revision of the same document. It works for any
format and in both direct chat and task steps. A task can also revise a
deliverable written in chat, and chat can revise a task output.

- Only the latest revision can be superseded. When the target already has a
  newer revision, the tool rejects the call and returns
  `latest_deliverable_id`.
- Older revisions stay readable by their exact ID and through the revision
  history. Artifact search and listing return only the latest revision.
- Rewriting a deliverable inside the same task step still replaces the step
  draft. It does not create a new revision.

In the web app, the chat, the activity inspector, the Work view, and the task
output show a revision picker when a deliverable has more than one revision.
An older chat card stays in the history, collapsed and marked as superseded,
with a link to the latest revision.

## Choose the smallest useful format

- Use ordinary Markdown for prose that does not benefit from visual hierarchy.
- Use an artifact for a file the reader should download or retain.
- Use `document_generate` for a print-ready PDF.
- Use a rich deliverable when the reader benefits from structured navigation,
  comparison, evidence, metrics, or an interactive standalone view.

## Continue

- [Content, Artifacts, and Temporary Sharing](content-and-sharing.md)
- [Rich Deliverable Composition](rich-deliverable-composition.md)
- [Layout and narrative blocks](rich-deliverable-blocks-layout.md)
- [Data, evidence, and utility blocks](rich-deliverable-blocks-data.md)
