# Step-scoped Daily Brief lifecycle correction

## Owned state and compatibility

The workflow defines output producers. Effective Daily Brief scope is derived
from its pinned step definitions and current index for every attempt and cold
reload. Unknown or conditional graphs retain strict validation. The selection
uses the same required run-producer list as task final-deliverable resolution.
No agent or step name has special meaning.

Native preflight and execution use the same scope. Validation fingerprints bind
scope, owning step-run ID, actor and executing agent as well as existing task,
skill and evidence inputs. Daily Brief receipts are written only on accepted
domain validation. Internal Markdown packets receive no Pulse receipt.

The existing SQLite/PostgreSQL deliverable transaction, execution fence,
revision write semantics and cancellation ownership are unchanged. No schema,
grant, credential or production-state migration is required. Non-task chat and
ordinary workflows retain their existing presentation behavior.

## Proposed acceptance canary (not scheduled)

Use a new synthetic two-run workflow with required deliverables and `last`
input on the second run. Use two independently authorized primary-agent runtime
contexts. No Office365/Slack source access, credential sharing or external
mutations are needed.

1. Collector publishes a nonempty synthetic Markdown packet with explicit
   partial coverage. Verify one canonical step artifact and no Pulse receipt.
2. Collector completes explicitly. Verify the consuming agent receives the
   packet, not collector tool history or permissions.
3. Consumer reports the coverage gap; vault/invoice changes remain blocked.
4. Separately exercise final text rejection and accepted Pulse v13 publication
   with synthetic, authorized source images and actual validation receipts.
5. Verify a previously invalid final artifact permits validation and repair
   with terminal todos. Verify reload produces the same decision.

## Integration boundary

The owning coordinator decides integration and runtime loading. Before
integration, fetch and compare the approved commit with current main; do not
discard concurrent changes or rewrite history. Re-run affected checks on any
integration changes. Deploy the controller together with its matching common
package, verify the loaded revision and descriptor, then execute the synthetic
canary. Do not resume the failed real briefing before canary acceptance.

This change does not perform deployment, restart, task recovery or retry.
