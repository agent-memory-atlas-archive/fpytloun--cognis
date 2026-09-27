# Using Chat

The chat workspace is where you talk to an agent, watch responses stream in real time, and follow tool usage or delegated work without leaving the conversation.

![Cognis chat workspace with web research tools](../assets/screenshots/chat-desktop.webp)

## Starting a conversation

Open `Chat`, create a new conversation, and select an agent.
Web conversations can exist before they have an active session; Cognis creates the root session when you send the first real message.

That first message is also used to bootstrap Intaris intention generation right away, so the session purpose is available from the first turn instead of waiting for a follow-up turn.

## What the chat UI shows

Depending on what the agent is doing, the conversation can display:

- streaming assistant responses
- reasoning or progress blocks
- tool call indicators and results
- delegation status cards for background work
- queued messages when you send another message during an active turn
- reconnection status for the WebSocket session

“Sending” means the client has not yet received admission confirmation. A
server-admitted message stops showing that label even while the agent is still
working. Its local, live-runtime, and saved-history representations share one
message identity, so acknowledgement does not create a second bubble.

“Preparing input” means the model is still generating a tool call; the tool has
not executed. Streamed tool preparation is bounded per generation to 600 seconds
from its first progress event and 262,144 total input characters. A limit breach
uses the normal bounded model-error recovery policy. Large changes should be
split into smaller calls.

When a generation fails or is cancelled, its abandoned preparation indicators
are removed from the active overlay. This does not create tool results or change
previously completed calls.

## Runtime selection

`/model`, `/thinking`, and `/fast` select session overrides for the next message.
`/profile` selects an agent profile and clears those overrides.
Session details and `/info` show the selected values separately from the last model call.

Thinking selections have distinct meanings:

| Command | Meaning |
|---|---|
| `/thinking clear` | Remove the session override and inherit the profile or agent configuration |
| `/thinking reset` or `/thinking inherit` | Same as `clear` |
| `/thinking default` | Use the provider/model default, without an inherited effort hint |
| `/thinking none` or `/thinking off` | Disable thinking, if the model supports it |
| `/thinking high` | Use the selected supported effort |

`off` now means disabled thinking, not inheritance. Use `clear` for inheritance.
For adaptive Claude models, provider default sends adaptive thinking without an effort hint.
Models with mandatory thinking do not offer `none`.
`/thinking` shows the session selection separately from the effective effort and its source.
If model metadata is unavailable, explicit effort changes fail without changing the saved selection.
Clearing an override does not require model metadata.

Agent and profile forms use the same states: **Inherit**, **Provider default**,
**Disabled**, and the supported effort levels. Profile inheritance uses the agent configuration.
Provider default stops effort inheritance even if a lower layer specifies `low`.

Fast mode also distinguishes **Inherit**, **Enabled**, and **Disabled**.
`/fast clear` removes the session override. `default`, `reset`, and `inherit` are aliases for `clear`.
`/fast off` suppresses inherited acceleration parameters; it does not enable inheritance.
The command resolves the next request's provider and model, not the last completed request.
Disabled and Inherit remain available if capability discovery fails.

Fast mode support depends on the provider transport as well as the model.
Native Claude API fast mode currently supports Opus 5 and Opus 4.8.
It uses `speed: "fast"` and the fast-mode beta header.
Codex uses the accelerated service tier from its registry.
Model support does not confirm account eligibility. Premium pricing can apply.
Claude rate-limit or eligibility errors remain errors; Cognis does not silently downgrade Claude fast requests.
Existing Codex tier-rejection recovery can retry at normal priority.
The selected fast-mode setting describes a request, not proof of accelerated execution.
Anthropic's response `usage.speed` reports the actual speed (`fast` or `standard`) independently.

### Provider model registry drift

In Settings → Providers, select **Discover** to compare configured models with a fresh registry snapshot.
Discovery can use a bundled catalog or supply partial metadata. It does not change saved configuration.
If connection fields have changed, save or discard those changes before discovery.
Changing the connection invalidates the comparison.

Each model shows differing supplied fields, with configured and registry values.
Expand **Registry drift** to reset one field or all discovered fields for that model.
The model editor provides the same comparison.
These actions change only the draft. Save the provider to apply the changes, or discard the draft.
Fields absent from discovery remain unchanged.
A model absent from discovery is not automatically obsolete and is never automatically removed.
Differences can be intentional administrator overrides, including explicit disabled capabilities.

Cognis stores these selections in its database. They survive controller restarts
and compaction. A session reset or renewal clears the overrides.

Chat command retries return the original selection result without applying the
change again. Timeline feedback can arrive later if Intaris is unavailable.

## Queued messages

If you send a message while the agent is still processing the previous turn,
Cognis queues the new message instead of interrupting the active turn. The chat
workspace shows each pending queued message before it runs.

Queued messages are compact by default so a long follow-up cannot take over the
chat viewport while the active turn is still running. Each queued row shows a
single-line preview, status, and the main controls; open the details view when
you need to review the full text.

From the queued-message panel you can:

- expand a queued row to review the exact message text waiting to run
- edit the queued text before Cognis starts processing it
- delete a queued message to cancel it

Queued attachment changes are handled by deleting the queued message and sending
a replacement, because attachments are already uploaded and referenced by the
time a message enters the queue. If you keep a queued message with attachments,
Cognis preserves the prepared attachment context and uses it when the queued
turn runs later.

## Approvals and escalations

If Intaris escalates a tool call, the chat UI shows an approval prompt. From there you can approve or deny the requested action.

This is how Cognis keeps risky or sensitive actions visible to the user instead of silently executing them.

## Markdown, links, and tool output

Assistant responses render Markdown as they stream. Plain `http://` and
`https://` URLs are clickable even when the agent did not format them as
Markdown links. URLs inside inline code or fenced code blocks stay as literal
text.

Tool results preserve raw output for copying. Filesystem `read` results use
syntax highlighting when Cognis can infer a language from the file path, while
JSON-shaped outputs keep the dedicated JSON rendering.

## Delegation and background work

Some work is better handled through delegated or structured execution instead of one immediate chat turn. When that happens, Cognis can show:

- a delegation card
- intermediate progress
- final completion or failure updates

The main conversation stays responsive while the sub-session or workflow continues.
Completed delegated work keeps its recoverable output with the sub-session. If a
sub-session produced several assistant messages, Cognis keeps them in order and
labels them as separate sections so the full report is not lost when a later
cleanup or final status message arrives.

Delegation cards in the parent conversation intentionally show compact metadata
only: the delegated title or task label, target/used agent, status, duration or
progress, and the child session link. The full delegated prompt is stored as the
initial user message inside the child session so the parent timeline stays
readable without losing auditability.

A child timeline shows that child's messages and runtime state. The parent's
latest admitted message remains in the parent timeline, including while it is
waiting for a session. In an open conversation, the chat runtime owns the turn
indicator; refreshing sidebar metadata cannot restart a settled indicator or
clear a newer active turn.

When background work finishes, Cognis classifies the follow-up before the agent
responds:

- results that still belong to the active work thread can be integrated back
  into that thread naturally
- scheduled briefs, pauses, and unrelated completions are shown as separate
  updates instead of pretending an older chat topic is still active

## Session management and compaction

Between turns, Cognis projects older recoverable tool results toward the steady
context target. The trigger and requested savings use the session's compatible
provider/model token calibration, including tool-schema overhead. Within-turn
burst and hard limits remain separate and unchanged. Protected instructions or
unrecoverable evidence can prevent reaching the steady target; projection does
not discard them merely to meet it.

Automatic compaction follows model-facing projection, not an independent 85%
threshold. A prompt above steady can continue if it fits the effective hard
boundary. A zero-turn compaction attempt is reported as skipped.
See [Context management](context-management.md) for the budgets, projection
modes, evidence rules, and worked examples.

Long conversations may be compacted so the active context stays usable. When that happens, the timeline can show a compaction card and Cognis continues from the new active session with the compacted summary included in context.

Cognis stops execution if required history is unavailable or incomplete. A
profile switch must retain the current turn and its recorded switch boundary.
Cache invalidation must not silently turn an existing conversation into an
empty prompt. Retry the turn after the event store is available again.

Retry reuses your original saved instruction without adding a duplicate user
message. Cognis verifies the saved retry link back to that instruction; if the
link or original instruction is missing, it still stops rather than guessing.

Forks read the complete source history and confirm all required writes before
returning success. Interrupted copies are not usable as complete conversation
history, including after a controller restart. If a fork fails, recreate it from
the original conversation; do not use a partially created fork as a recovery
shortcut. Intentional fork activity filtering and compaction summaries still
apply.

Use `/compact` to compact the current conversation manually. Manual compaction
runs immediately and rotates to the new active session before the next user
message is recorded.

Use `/recap` in a web or channel chat to add a brief recent-work recap. It uses
up to 30 conversation messages combined: user messages (including updates
sent mid-turn) and the last assistant reply per turn. An existing session
compaction summary is used as background when available. Tool outputs are not
included in the recap model's conversation input; they only provide
deterministic activity counts and links.
Deliverables, artifacts, and file changes cover the same recent window. Unlike
compaction, a recap is a timeline card only: it does not enter the agent's
context or rotate the session. Its work evidence opens existing detail views.
In web chat, you can enable
**Automatically recap web chats** in chat preferences. Automatic recaps run
quietly after five idle minutes only when new activity since the last published
recap contains completed, meaningful work. They are limited to one published
recap per 30 minutes and do not run in tasks or channels or send notifications.
Recently due recaps are recovered after controller restarts for up to two hours;
older conversations are not backfilled, and enabling the preference does not
recap conversations that were already idle.

Long-lived ambient chats, such as web direct chats with an agent and external
channel conversations, can also checkpoint after an idle gap. By default, if the
active session has been idle for 6 hours and has at least 20 uncompacted events,
Cognis compacts and rotates the active session before handling the next user
message. The conversation itself remains continuous; only the active session
context is refreshed. Normal web topic conversations are not idle-checkpointed.

Admins can tune or disable this behavior with
`session.long_lived_chat_idle_compaction_seconds` (`0` disables idle checkpoint
compaction) and `session.long_lived_chat_idle_compaction_min_events`.

Use `/undo` to remove the last normal user turn and everything the assistant produced after it from the visible timeline. Cognis keeps the underlying Intaris session history for auditability, rebases the same conversation onto a new active session, and reloads the current chat in place without changing the URL or creating a sidebar row. Use `/redo` before sending another normal message to restore the undone session. Sending a new normal message after `/undo` starts a divergent branch and clears redo.

## Long-running turns

Cognis keeps a safety watchdog on long-running turns. If a direct chat turn hits
that watchdog, Cognis records a visible system notice and may automatically
continue the same work once it is safe to do so. The continuation reminder tells
the agent to verify that the work still matches the original request, update
todos when appropriate, summarize the interrupted state briefly, and continue
only if more action is needed.

This is a recovery path, not an infinite retry loop. Continuations are bounded by
the controller's safety budget so repeated timeouts still stop instead of
running away.

## First-run readiness

Admins may see setup guidance until:

- Mnemory is reachable
- Intaris is reachable
- at least one LLM provider is configured
- at least one agent exists

## Recovery and diagnostics

If something looks wrong, check the system section for:

- provider health
- readiness diagnostics
- configuration summary
- database and key information

If the WebSocket connection drops, the UI will attempt to reconnect and recover missed events.

## Install as an app (PWA)

Cognis ships as a Progressive Web App. On desktop browsers (Chrome/Edge/Safari) and Android, you can install it for a dedicated window, app-icon launch, and an offline shell:

- **Chrome / Edge (any platform)**: a one-time install banner appears inside the app. You can also use the browser's address-bar install button, or menu -> "Install Cognis".
- **iOS Safari**: tap the Share icon, then "Add to Home Screen". Cognis detects this environment and shows a one-time hint with the instructions.
- **Android Chrome**: tap menu -> "Install app" or wait for the in-app install banner.

When installed:

- The app launches in a standalone window with no browser chrome, respecting the safe-area insets on iPhone notches.
- The app shell (HTML, JS, CSS) is cached so the UI loads even when the network is unavailable. Conversations still require a live WebSocket connection.
- Updates are applied automatically. When a new version is available, a small banner appears at the top of the screen with a "Reload" action.

## Mobile-specific behavior

![Cognis iOS PWA chat with tool activity](../assets/screenshots/pwa-chat.webp)

- Primary navigation on mobile is a bottom tab bar (Chat / Tasks / Agents / Settings). Inside a chat conversation the bar hides so the composer owns the bottom safe-area.
- Tapping the hamburger button in the header opens a right-side sheet drawer with the full navigation. The sheet supports swipe-down-to-dismiss.
- The composer uses 16 px text on mobile so iOS Safari does not zoom the viewport when you focus it.
- The bottom tab bar, composer, and floating action bars respect the `safe-area-inset-bottom` so they sit above the Home Indicator on iPhones.

### Tasks on mobile

- The Task board uses a column picker (Draft / Queued / Running / Paused / Done) so one column fills the viewport at a time, instead of horizontal-scrolling a 1200px kanban. Tap the column chip to switch.
- Multi-select still works: tap once to select, tap again to deselect. The bulk action bar wraps and floats above the bottom tab bar.
- Drag-and-drop between columns is desktop only. On mobile, open the task detail and use the state buttons (Submit, Pause, Cancel) to move work through the queue.

### Workflows on mobile

- The workflow list stacks above the editor; tap a workflow to open it.
- Each step has up / down arrow buttons for reorder. HTML5 drag-and-drop is still available on desktop but is a no-op on iOS Safari, so the arrows are the canonical touch-friendly control.
- A sticky action bar at the bottom of the screen keeps Save one tap away, even at the end of a long step editor. More actions (New, Duplicate, Export YAML, Delete) are behind the "Actions" button on the same bar.
- Tooltips (the `?` help icons) reveal on tap — hover-only tooltips are gone.

### Settings on mobile

- The 9-tab section strip becomes a horizontally scrollable pill row instead of wrapping to three lines.
- On the Executors tab, the per-executor "Individual tools" picker is now a searchable Sheet (tap "Configure" on the executor card) so you can find and toggle a tool without scanning a grid of 30+ chips.
