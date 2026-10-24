# Planning and execution intent

`/plan` asks the agent to analyze, explore, design and produce a plan rather than
implement it. Supporting documents, scratch files and proportionate diagnostics
can have incidental effects; planning is not a strict read-only sandbox.

The controller supplies planning instructions to the agent. It does not turn the
chat-mode label into `read_only_required`. The command classifier reports effects
and uncertainty, while normal policy and independent Judge review decide whether
the proposed action is appropriate. A plan/build label is neither approval nor
denial of a tool call.

Explicit read-only restrictions remain binding. Clients that explicitly send
`read_only_required=true` still request that strict ceiling, independently of
their chat mode. Older captured approvals keep their original restrictions.
Deploy the corresponding Intaris change as well: older Intaris versions infer
the strict ceiling from `chat_mode=plan`.
