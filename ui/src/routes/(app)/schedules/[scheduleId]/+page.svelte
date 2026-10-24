<script lang="ts">
  import { page } from '$app/stores';
  import ScheduleDetailWorkspace from '$lib/components/schedules/ScheduleDetailWorkspace.svelte';
</script>

{#key $page.params.scheduleId}
  <ScheduleDetailWorkspace id={$page.params.scheduleId ?? ''} />
{/key}
