<script lang="ts">
  import MessageSquare from 'lucide-svelte/icons/message-square';
  import CheckCheck from 'lucide-svelte/icons/check-check';
  import CalendarClock from 'lucide-svelte/icons/calendar-clock';
  import FileText from 'lucide-svelte/icons/file-text';
  import FileSpreadsheet from 'lucide-svelte/icons/file-spreadsheet';
  import FileCode from 'lucide-svelte/icons/file-code';
  import FileArchive from 'lucide-svelte/icons/file-archive';
  import FileImage from 'lucide-svelte/icons/file-image';
  import File from 'lucide-svelte/icons/file';
  import Settings from 'lucide-svelte/icons/settings';
  import Plus from 'lucide-svelte/icons/plus';
  import AgentAvatar from '$lib/components/AgentAvatar.svelte';
  import ProjectAvatar from '$lib/components/projects/ProjectAvatar.svelte';
  import { navigationItems } from '$lib/navigation';
  import type { PaletteThumbnails } from '$lib/palette/thumbnails';
  import type { PaletteItem } from '$lib/palette/model';
  let { item, thumbnails }: { item: PaletteItem; thumbnails: PaletteThumbnails } = $props();
  let src = $state('');
  let failed = $state(false);
  const extension = $derived(item.title.split('.').at(-1)?.toLowerCase() ?? '');
  const image = $derived(item.kind === 'artifact' && /^image\/(png|jpeg|webp|gif|avif)$/.test(item.format ?? ''));
  const Icon = $derived(
    item.kind === 'page' ? navigationItems.find(page => page.href === item.href)?.icon ?? File :
    item.kind === 'conversation' || item.kind === 'agent' ? MessageSquare : item.kind === 'task' ? CheckCheck :
    item.kind === 'schedule' ? CalendarClock : item.kind === 'setting' ? Settings :
    item.kind === 'action' ? Plus : image ? FileImage :
    ['xlsx', 'xls', 'csv', 'ods'].includes(extension) ? FileSpreadsheet :
    ['zip', 'tar', 'gz', '7z'].includes(extension) ? FileArchive :
    ['json', 'py', 'ts', 'js', 'yaml', 'html', 'css'].includes(extension) ? FileCode :
    item.kind === 'deliverable' || ['pdf', 'md', 'docx', 'txt'].includes(extension) ? FileText : File
  );
  function thumbnail(node: HTMLElement) {
    let alive = true;
    const controller = new AbortController();
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      void thumbnails.get(item, controller.signal).then((url) => {
        if (alive) src = url;
      }).catch(() => {});
    });
    observer.observe(node);
    return { destroy() { alive = false; controller.abort(); observer.disconnect(); } };
  }
</script>

<span class="result-icon" class:conversation={item.kind === 'conversation' || item.kind === 'agent'} class:task={item.kind === 'task'}
  class:schedule={item.kind === 'schedule'} class:document={item.kind === 'deliverable' || extension === 'pdf'}
  class:spreadsheet={['xlsx', 'xls', 'csv'].includes(extension)} use:thumbnail>
  {#if item.kind === 'project'}
    <ProjectAvatar name={item.title} avatarUrl={item.project_avatar_url}
      icon={item.project_icon} color={item.project_color} class="h-10 w-10" />
  {:else if (item.kind === 'conversation' || item.kind === 'agent') && item.agent_name}
    <AgentAvatar name={item.agent_name} avatarUrl={item.agent_avatar_url} draggable={false} class="h-10 w-10 rounded-full text-sm" />
  {:else if src && !failed}
    <img {src} alt="" loading="lazy" decoding="async" width="40" height="40" onerror={() => failed = true} />
  {:else}
    <Icon size={22} strokeWidth={1.6} />
    {#if item.kind === 'artifact' && !image && extension.length <= 5}<span class="extension">{extension}</span>{/if}
  {/if}
</span>

<style>
  .result-icon { position:relative; display:flex; align-items:center; justify-content:center; flex:none; width:40px; height:40px; border-radius:11px; color:var(--muted); background:color-mix(in srgb, var(--foreground) 6%, transparent); border:1px solid color-mix(in srgb, var(--foreground) 7%, transparent); overflow:hidden; }
  .result-icon.conversation { border-radius:50%; color:#75aaf8; background:#75aaf81a; }
  .result-icon.task { color:#a793f6; background:#a793f61a; }
  .result-icon.schedule { color:#e6ad68; background:#e6ad681a; }
  .result-icon.document { color:#ef9299; background:#ef92991a; }
  .result-icon.spreadsheet { color:#71c4a0; background:#71c4a01a; }
  img { width:100%;height:100%;object-fit:cover; }
  .extension { position:absolute;bottom:1px;font-size:7px;line-height:10px;font-weight:700;text-transform:uppercase;letter-spacing:.03em; }
</style>
