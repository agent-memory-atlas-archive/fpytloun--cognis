/** Settle a prompt only when the server confirms a durable terminal rejection. */
export function isResolvedApprovalRejection(details: Record<string, unknown> | null): boolean {
  return details?.resolved === true
    && (details?.decision === 'deny' || details?.decision === 'cancel');
}
