# Artifact access

Saved artifacts and deliverables belong to a user and a persistent agent.
Conversation and session IDs record provenance; they do not limit the owning
agent to a single chat. Human-owner HTTP access remains separate from agent tools.

Agent reads, discovery, native image inspection, outbound attachment authorization,
value references, and chat attachment hydration use the same content policy:

- The owning agent can read its content across conversations.
- `artifact_share(content_ref, agent_id, action)` grants or revokes explicit read
  access to another agent of the same user. Read access is not permission to
  reshare, revise, or delete content.
- An assigned knowledgebase gives access to its linked artifacts. This is checked
  dynamically; removing the assignment or membership removes that access.
- Task, managed conversation, and delegate ancestors can read descendant outputs,
  not the worker's unrelated storage. Output-specific grants survive source
  deletion. Closing managed work does not discard its results.
- Workers receive only explicitly passed, authorized content references.
  Specialist inputs are scoped to a logical session, not the reusable system
  agent. Compaction retains that scope; retry/follow-up copies retained inputs.
  Sibling specialist jobs do not share inputs.

Search filtering occurs before pagination. Inaccessible references are reported as
not found. An already-issued signed URL remains a bearer capability until expiry;
revocation prevents subsequent URL issuance and reads, not bytes already delivered.

## Agent avatar references

`image_generate` references, `image_edit` images/masks, `artifact_read`,
`artifact_get_metadata`, and `artifact_get_url` also accept current agent avatar
IDs. These images remain in the `avatars` store rather than the artifact registry.
The acting user must own or have use/manage access to the agent, and the storage
owner must match that agent. Primary and secondary agent avatars follow the same
rule. Project avatars do not qualify.

Unlinked/replaced avatars, missing bytes or metadata, and inaccessible avatars
are reported as not found. This exception does not enable artifact discovery,
sharing, revision, or outbound attachment tools for avatars. Signed URLs use the
normal bearer-capability lifetime; the content endpoint also checks that the
avatar is still linked to an agent with matching storage ownership.

## Migration and legacy content

Migration 157 and the idempotent bootstrap repair add agent ownership, read grants,
and specialist artifact scopes. Existing ownership is recovered from trusted
conversation/session/task provenance. Accepted turn attachments and validated
output ancestry are backfilled. Conversation/session/task deletion no longer
cascades into durable deliverables or deletes agent-owned artifact bytes.

Old publications without trustworthy provenance are retained for their human
owner, but are not made visible to every agent. The owner can explicitly share
them with `POST /api/v1/artifacts/{content_ref}/share` using
`{"agent_id": "<existing agent ID>", "action": "grant"}` (or `"revoke"`).
Inputs whose historical admission records have already been deleted must be
passed again. KB access never becomes a permanent explicit grant during migration.
