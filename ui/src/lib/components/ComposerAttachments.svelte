<script lang="ts">
  import Mic from 'lucide-svelte/icons/mic';
  import Pause from 'lucide-svelte/icons/pause';
  import Play from 'lucide-svelte/icons/play';
  import X from 'lucide-svelte/icons/x';

  import { haptic } from '$lib/haptics';
  import type { AttachmentRef } from '$lib/types/api';
  import { formatVoiceDuration } from '$lib/utils/voice-recorder';

  /**
   * Composer attachment preview strip.
   *
   * Renders image attachments as small thumbnails (familiar messaging-app
   * affordance), audio recordings as inline mini-players, and everything
   * else as a filename chip. Every item has an overlay remove button so
   * the user can drop an attachment before sending. Reused by the inline
   * and expanded composer to keep previews consistent.
   */

  interface Props {
    attachments: AttachmentRef[];
    onremove: (artifactId: string) => void;
    /** Retry a failed background upload (local attachments only). */
    onretry?: (attachment: AttachmentRef) => void;
    disabled?: boolean;
    class?: string;
  }

  let { attachments, onremove, onretry, disabled = false, class: className = '' }: Props = $props();

  function uploadPercent(attachment: AttachmentRef): number {
    return Math.round(Math.max(0, Math.min(1, attachment.upload_progress ?? 0)) * 100);
  }

  function uploadLabel(attachment: AttachmentRef): string {
    if (attachment.upload_state === 'failed') return 'Upload failed';
    return `Uploading ${uploadPercent(attachment)}%`;
  }

  let playingId = $state<string | null>(null);
  const audioElements = new Map<string, HTMLAudioElement>();

  function isImage(attachment: AttachmentRef): boolean {
    return typeof attachment.mime_type === 'string' && attachment.mime_type.startsWith('image/');
  }

  function isAudio(attachment: AttachmentRef): boolean {
    if (attachment.voice_recording) return true;
    return typeof attachment.mime_type === 'string' && attachment.mime_type.startsWith('audio/');
  }

  function audioUrl(attachment: AttachmentRef): string | null {
    return attachment.blob_url ?? attachment.url ?? null;
  }

  function togglePlay(attachment: AttachmentRef): void {
    const id = attachment.artifact_id;
    let audio = audioElements.get(id);
    if (!audio) {
      const url = audioUrl(attachment);
      if (!url) return;
      audio = new Audio(url);
      audio.onended = () => {
        if (playingId === id) playingId = null;
      };
      audioElements.set(id, audio);
    }
    if (playingId === id) {
      audio.pause();
      playingId = null;
      return;
    }
    audioElements.forEach((other, key) => {
      if (key !== id) other.pause();
    });
    void audio.play().then(() => {
      playingId = id;
      haptic.light();
    }).catch(() => {
      playingId = null;
    });
  }
</script>

{#if attachments.length > 0}
  <div class={`flex flex-wrap gap-2 ${className}`}>
    {#each attachments as attachment (attachment.artifact_id)}
      {#if isImage(attachment) && attachment.url}
        <div class="group relative h-20 w-20 overflow-hidden rounded-xl border border-control-border bg-surface">
          <img
            alt={attachment.filename}
            class="h-full w-full object-cover"
            loading="lazy"
            src={attachment.url}
          />
          {#if attachment.upload_state === 'uploading'}
            <div
              class="pointer-events-none absolute inset-x-0 bottom-0 bg-scrim/70 px-1 py-0.5 text-center text-[10px] font-medium tabular-nums text-white"
              role="status"
              aria-label={uploadLabel(attachment)}
            >
              {uploadPercent(attachment)}%
              <div class="mt-0.5 h-0.5 w-full overflow-hidden rounded bg-white/25">
                <div class="h-full bg-white transition-[width]" style={`width: ${uploadPercent(attachment)}%`}></div>
              </div>
            </div>
          {:else if attachment.upload_state === 'failed'}
            <button
              type="button"
              class="absolute inset-x-0 bottom-0 bg-danger-subtle py-0.5 text-[10px] font-medium text-danger"
              title={attachment.upload_error ?? 'Upload failed'}
              onclick={() => onretry?.(attachment)}
            >
              Retry
            </button>
          {/if}
          <button
            aria-label={`Remove ${attachment.filename}`}
            class="absolute right-1 top-1 inline-flex h-6 w-6 items-center justify-center rounded-full bg-scrim/85 text-white shadow-md transition hover:bg-danger-subtle hover:text-danger disabled:cursor-not-allowed disabled:opacity-50"
            {disabled}
            onclick={() => onremove(attachment.artifact_id)}
            type="button"
          >
            <X class="h-3.5 w-3.5" />
          </button>
        </div>
      {:else if isAudio(attachment)}
        <div class="flex items-center gap-2 rounded-full border border-control-border bg-inset/70 px-3 py-1.5 text-xs text-foreground">
          <button
            aria-label={playingId === attachment.artifact_id ? 'Pause recording' : 'Play recording'}
            class="inline-flex h-7 w-7 items-center justify-center rounded-full bg-surface text-foreground transition hover:bg-surface-hover disabled:opacity-50"
            type="button"
            onclick={() => togglePlay(attachment)}
            disabled={!audioUrl(attachment)}
          >
            {#if playingId === attachment.artifact_id}
              <Pause class="h-3.5 w-3.5" />
            {:else}
              <Play class="h-3.5 w-3.5" />
            {/if}
          </button>
          <Mic class="h-3.5 w-3.5 text-pink-tone" />
          <span class="font-medium tabular-nums">{formatVoiceDuration(attachment.duration_seconds ?? 0)}</span>
          {#if attachment.voice_recording}
            <span class="text-[10px] uppercase tracking-wider text-muted">ready</span>
          {/if}
          <button
            aria-label={`Remove ${attachment.filename}`}
            class="text-muted transition hover:text-strong disabled:cursor-not-allowed disabled:opacity-50"
            {disabled}
            onclick={() => { haptic.warning(); onremove(attachment.artifact_id); }}
            type="button"
          >
            <X class="h-3.5 w-3.5" />
          </button>
        </div>
      {:else}
        <div class="flex items-center gap-2 rounded-full border border-control-border bg-inset/70 px-3 py-2 text-xs text-foreground">
          <span class="max-w-[220px] truncate">{attachment.filename}</span>
          {#if attachment.upload_state === 'uploading'}
            <span class="tabular-nums text-info" role="status" aria-label={uploadLabel(attachment)}>{uploadPercent(attachment)}%</span>
          {:else if attachment.upload_state === 'failed'}
            <button
              type="button"
              class="font-medium text-danger hover:underline"
              title={attachment.upload_error ?? 'Upload failed'}
              onclick={() => onretry?.(attachment)}
            >
              Retry
            </button>
          {/if}
          <button
            aria-label={`Remove ${attachment.filename}`}
            class="text-muted transition hover:text-strong disabled:cursor-not-allowed disabled:opacity-50"
            {disabled}
            onclick={() => onremove(attachment.artifact_id)}
            type="button"
          >
            <X class="h-3.5 w-3.5" />
          </button>
        </div>
      {/if}
    {/each}
  </div>
{/if}
