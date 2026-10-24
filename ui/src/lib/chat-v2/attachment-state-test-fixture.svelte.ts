import type { AttachmentRef } from '$lib/types/api';

/** Same reactive array/spread boundary used by the compact composer. */
export function reactiveAttachments(refs: AttachmentRef[]): AttachmentRef[] {
  const attachments = $state(refs);
  return [...attachments];
}
