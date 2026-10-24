<script lang="ts">
  let { class: className = '', strokeWidth: _strokeWidth = 1.8 } = $props<{ class?: string; strokeWidth?: number }>();
</script>

<!-- Use the canonical brand artwork as an alpha mask, not a duplicated path. -->
<span class={`inline-block ${className}`} aria-hidden="true"
  style="background:currentColor;mask:url('/brand/cognis-mark.svg') center/contain no-repeat;-webkit-mask:url('/brand/cognis-mark.svg') center/contain no-repeat"></span>
