# Cognis: Project Collaboration

## Status

IMPLEMENTED (branch `feat/project-collaboration`). Extends
`30-projects-and-revisions.md` (projects, grants) and amends
`28-agent-sharing.md` (agent sharing, non-goal "cross-user conversations").

## Goals

### Project home workspace

Project conversation and task listings reuse the dashboard sections, with
project-specific conversation classification (including authorized channel and
direct contexts). Additive `/conversations/page` and `/tasks/page` project
endpoints return `CursorPage` responses. Keyset boundaries use activity time
and ID, and bind the cursor to user, project, resource and agent filter.
Authorization is rechecked on every page. Legacy array endpoints remain for
existing tool and API consumers.

The client aborts superseded requests, deduplicates appended items and refreshes
the loaded range after mutations. Mobile resource grids have explicit bounded
columns; long asset titles and owner metadata cannot expand page width.
Conversation header metadata is one shared rendering snippet, also available
in every conversation inspector tab, including mobile/PWA.

The project page is the working home for project activity. Conversation, task,
and schedule cards open the existing dashboard entity UI in-place; project
assets open the existing deliverable renderer or attachment preview. Opening
an item does not navigate away from `/projects/{project_id}`. The optional
explicit “Open full page” control remains available.

The dashboard window preference also applies here. Window layouts are stored
under a user-and-project-specific key, separate from the global dashboard.
Phones use the full-screen modal. URL `view` and `item` parameters restore
entity modals, and browser history closes/reopens URL-selected entities.
Project tabs, filters and scroll remain in place while working in a modal.

New chats and “Continue in my chat” always supply the current project ID;
agent defaults cannot override it. Agent cards start project topic chats,
not global agent-direct chats. Continuations keep the existing source backlink
semantics; they do not silently copy another author's entire transcript.

Shared chats are read-only and refresh durable history periodically. Shared
tasks expose project-readable content, not the author's control chat or live
work projection. Nested deliverable renderers inherit the modal's sharing
capability. Schedules retain owner-only API access; a schedule-list failure
does not prevent other project activity from loading.

Asset links outside the recent activity window show an explicit unavailable
message instead of silently ignoring the link.

1. Full project CRUD from chat tools and the API, including safe edits of
   project instructions.
2. Agents can be assigned to projects (many-to-many) so agent work is
   classified as project work, for example a catalog agent in a sample museum
   project.
3. Topic conversations can be explicitly assigned to, moved between, or
   removed from projects; conversation lists filter by project.
4. Projects can be shared with roles. Members see each other's project work,
   use the project's agents, and read recent deliverables and artifacts.

## Non-goals

- Usage and cost reporting per project.
- Shared project memory in Mnemory (members keep `(user, owner)` keying).
- Multi-author conversations. One conversation still has one author; other
  members read it and continue in their own conversation.
- Group grantees (the schema stays polymorphic as in spec 28).

## Roles

| Role | Grant value | Read project work | Create work, use agents | Edit config, assign own agents | Share, archive |
|---|---|---|---|---|---|
| viewer | `viewer` | yes | no | no | no |
| member | `member` (legacy `use`) | yes | yes | no | no |
| manager | `manager` | yes | yes | yes | no |
| owner | project owner | yes | yes | yes | yes |

Requirements map to roles: `view` → viewer+, `use` → member+, `manage` →
manager+, `share` → owner. There is no admin bypass. Migration 155 rewrites
existing `use` grants to `member`; `normalize_project_role` also accepts
`use` from older rows.

`cognis/core/project_access.py` is the single owner of this policy. REST
routes (`check_project_access`), builtin tools, the `/project` command, and
the agent loop all call it.

## Agent assignment

Table `project_agents(project_id, agent_id, is_default, executor_scope,
added_by, created_at, updated_at)`. A partial unique index allows at most
one default project per agent.

- **Who assigns:** a manager of the project who owns the agent (a primary
  agent only). Assignment shares the agent with every project member, so
  only its owner may decide that. The agent owner or project owner can
  remove an assignment.
- **Executor scope:** the same choice as agent grants (spec 28):
  `owner_executor` runs members' turns on the owner's executor and
  credentials; `grantee_executor` makes each member bring their own.
- **Project-scoped access:** `resolve_agent_use_grant(agent, user,
  project_id)` returns a direct agent grant first, otherwise a
  `ProjectAgentGrant` when the agent is assigned to that active project and
  the user is a member+. The derived grant has the attributes of
  `AgentGrantRow`, so executor routing, memory keying, KB access, and
  delegation behave exactly like a direct share. It is valid only for work
  whose stored project is that project: conversation creation, task and
  schedule creation, executor resolution, delegation, workflow
  `agent_override`, and KB tools all pass the project ID.
- **Default project:** `is_default` classifies the agent's work.
  - New topic conversations with no explicit project get the agent's default
    project when the caller may use it.
  - Long-lived chats (channel, main, agent-direct) never store a project.
    Their effective project is derived on each turn from the agent default
    (`resolve_effective_project_id`); project metadata is injected and tasks
    created from them inherit it.

## Conversation project assignment

Only topic conversations store `project_id`. Channel, main, agent-direct,
task-control, task-step, and managed conversations refuse explicit
assignment (`project_assignment_refusal`).

Assignment paths: REST `PATCH /conversations/{id}` (`project_id: null`
clears), `/project [name|id|none]`, and the `set_conversation_project` tool.
All call `change_conversation_project`, which requires the author, member+
on the target project, and that the conversation's agent stays usable in the
new project.

When the project changes, the next turn re-resolves project metadata.
Project metadata entries that no longer match the stored project are not
injected (`_project_metadata_applies`); when project instructions change, a
new `developer_message` event is recorded and replaces the cached entry
(latest event wins on replay).

## Visibility and shared reading

`conversations.visibility` and `tasks.visibility` take `project` or
`private`.

- New conversations default to `project`; it only matters inside a shared
  project. Rows that existed before migration 155 are `private`.
- Tasks in a project default to `project` unless spawned from a private
  conversation. Lineage forks keep the source visibility.
- Project readers (viewer+) can read project-visible conversations and
  tasks of other members: conversation detail, Chat v2 snapshot/sync/
  timeline/tool output, task detail/steps/comments/workflow run, and the
  deliverables and artifacts those produce. History is read with the
  author's authority after the caller's access is checked. Readers get only
  durable history: the author's queue, pending state, and live runtime
  overlays are stripped. Work graph and activity overview stay author-only
  because they traverse managed descendants.
- Readers never get write access. Sending messages, queue actions,
  archive/delete, title/project/visibility changes, minting public share
  links, and owner-only metadata (runtime state, notifications, attention
  actions) stay author-only.

### Read-only vs. continue

A shared conversation is read-only for other members. When its agent is also
available to the member in the project (assigned to the project, or shared
directly), the UI offers **Continue in my chat**. This creates the member's
own conversation in the same project with the same agent and a reference
back to the source. Without such an agent the conversation is read-only with
no continuation.

## Leaving and removal

- `POST /projects/{id}/leave` revokes the caller's grants. With
  `make_private: true` the caller's project conversations and tasks become
  private first.
- Owner revocation (`DELETE /grants/{id}`) takes effect immediately. The
  removed member's project-visible content stays visible to the project
  (authorship is preserved); their private content stays theirs.

## REST API additions

| Method | Path | Role |
|---|---|---|
| PATCH | `/api/v1/projects/{id}` (`instructions_mode: replace\|append`) | manager (status: owner) |
| DELETE | `/api/v1/projects/{id}` (archive) | owner |
| GET | `/api/v1/projects/{id}/grants` | viewer (active members); owner sees history |
| POST/DELETE | `/api/v1/projects/{id}/grants[/{grant_id}]` | owner |
| PATCH | `/api/v1/projects/{id}/grants/{grant_id}` (role) | owner |
| POST | `/api/v1/projects/{id}/leave` | grantee |
| GET | `/api/v1/projects/{id}/agents` | viewer |
| PUT/DELETE | `/api/v1/projects/{id}/agents/{agent_id}` | manager + agent owner |
| GET | `/api/v1/projects/{id}/conversations?agent_id=` | viewer |
| GET | `/api/v1/projects/{id}/tasks` | viewer |
| GET | `/api/v1/projects/{id}/activity` (deliverables, artifacts) | viewer |
| GET | `/api/v1/agents/{id}/projects` | agent view |

`ConversationResponse` adds `visibility`, `is_readonly_for_caller`, and
`project_assignable`. `ProjectResponse` adds `agents` and `caller_role`.
`AgentResponse` adds `shared_via_project_ids`.

## Builtin tools

Tool groups `projects_read` (`list_projects`, `get_project`) and
`projects_manage` (all project tools). New tools: `assign_agent_to_project`,
`unassign_agent_from_project`, and `set_conversation_project`.
`update_project` gains `instructions_mode=append`, and its description warns
that instructions affect every member's sessions. All tools enforce roles
through `project_access`.

## Security invariants

- Without a stored project, no project-derived agent grant exists.
  Long-lived chats derive a project only from the agent's own default, and
  only for users who are members of it.
- A project-derived grant never lets a member use an agent outside its
  project. Agent listings mark such agents with `shared_via_project_ids`;
  runtime target discovery does not include them.
- Readers authorize per request; revocation takes effect immediately.
- Execution fails closed: executor resolution and each workflow step
  re-authorize a non-owned primary agent (direct or project grant), so
  schedules and queued tasks of a removed member stop running.
- Artifact preview and signed URLs have no admin bypass.
- Long-lived chats inject only the current agent-default project's metadata;
  metadata of a previous default stops applying.
- The `update_project` tool accepts only configuration fields; status
  (archive) stays owner-only.
- Managed (`agent_work`) conversations are never readable by other members.
