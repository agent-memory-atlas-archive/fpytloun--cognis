<script lang="ts">
  import CognisLogo from '$lib/components/CognisLogo.svelte';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  import Button from '$lib/components/ui/Button.svelte';
  import Card from '$lib/components/ui/Card.svelte';
  import Input from '$lib/components/ui/Input.svelte';
  import { apiUrl } from '$lib/config';
  import { auth } from '$lib/stores/auth';

  let loading = true;
  let submitting = false;
  let token = '';
  let setupAvailable = true;
  let setupComplete = false;
  let error = '';
  let form = {
    email: '',
    name: '',
    password: '',
    confirmPassword: ''
  };

  function validate(): string | null {
    if (!token) {
      return 'The setup token is missing from the URL.';
    }
    if (!form.email.includes('@')) {
      return 'Enter a valid email address.';
    }
    if (form.password.length < 8) {
      return 'Password must be at least 8 characters long.';
    }
    if (form.password !== form.confirmPassword) {
      return 'Password confirmation must match.';
    }
    return null;
  }

  async function loadStatus(): Promise<void> {
    const url = new URL(window.location.href);
    token = url.searchParams.get('token') ?? '';
    const status = await fetch(apiUrl('/api/bootstrap-status'));
    const payload = await status.json();
    setupAvailable = Boolean(payload.setup_available);
    setupComplete = Boolean(payload.setup_complete);
  }

  async function handleSubmit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    error = '';
    const validationError = validate();
    if (validationError) {
      error = validationError;
      return;
    }

    submitting = true;
    try {
      const response = await fetch(apiUrl('/api/setup'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          token,
          email: form.email,
          name: form.name || null,
          password: form.password
        })
      });

      if (!response.ok) {
        if (response.status === 401) {
          throw new Error('The setup token is invalid or expired. Restart Cognis or use the local CLI to create the first admin user.');
        }
        if (response.status === 404) {
          throw new Error('Setup has already been completed. Open the login page to continue.');
        }
        throw new Error('Unable to complete setup.');
      }

      await auth.login(form.email, form.password);
      await goto('/getting-started', { replaceState: true });
    } catch (caughtError) {
      error = caughtError instanceof Error ? caughtError.message : 'Unable to complete setup.';
    } finally {
      submitting = false;
    }
  }

  onMount(() => {
    void loadStatus()
      .catch((caughtError) => {
        error = caughtError instanceof Error ? caughtError.message : 'Unable to load setup status.';
      })
      .finally(() => {
        loading = false;
      });
  });
</script>

<svelte:head>
  <title>Setup · Cognis</title>
</svelte:head>

<div class="app-fullscreen-safe mx-auto flex max-w-5xl items-center justify-center overflow-y-auto">
  <Card class="w-full max-w-2xl p-8">
    {#if loading}
      <p class="text-sm text-secondary">Loading setup status…</p>
    {:else if setupComplete && !setupAvailable}
      <div class="space-y-4">
        <CognisLogo class="h-16 w-16" />
        <p class="text-sm uppercase tracking-[0.3em] text-accent">Setup complete</p>
        <h1 class="text-3xl font-semibold text-strong">Cognis is already configured</h1>
        <p class="text-sm leading-6 text-muted">Open the login page to sign in with an existing account.</p>
        <Button onclick={() => goto('/login')}>Go to login</Button>
      </div>
    {:else}
      <div class="space-y-6">
        <div>
          <CognisLogo class="mb-5 h-16 w-16" />
          <p class="text-sm uppercase tracking-[0.3em] text-accent">First run</p>
          <h1 class="mt-3 text-3xl font-semibold text-strong">Create the first admin account</h1>
          <p class="mt-3 text-sm leading-6 text-muted">
            This creates the initial administrator for your Cognis instance. If the setup token expired, restart Cognis or run <code>cognis admin create-user</code> locally.
          </p>
        </div>

        <form class="space-y-4" onsubmit={handleSubmit} novalidate>
          <label class="block space-y-2 text-sm font-medium text-foreground">
            <span>Email <span class="text-danger">*</span></span>
            <Input bind:value={form.email} type="email" placeholder="admin@example.com" />
          </label>
          <label class="block space-y-2 text-sm font-medium text-foreground">
            <span>Name</span>
            <Input bind:value={form.name} placeholder="Admin" />
          </label>
          <label class="block space-y-2 text-sm font-medium text-foreground">
            <span>Password <span class="text-danger">*</span></span>
            <Input bind:value={form.password} type="password" placeholder="••••••••" />
          </label>
          <label class="block space-y-2 text-sm font-medium text-foreground">
            <span>Confirm password <span class="text-danger">*</span></span>
            <Input bind:value={form.confirmPassword} type="password" placeholder="••••••••" />
          </label>

          {#if error}
            <p class="rounded-2xl border border-danger-border bg-danger-subtle px-4 py-3 text-sm text-danger">{error}</p>
          {/if}

          <Button class="w-full justify-center" type="submit" disabled={submitting}>
            {submitting ? 'Creating account…' : 'Complete setup'}
          </Button>
        </form>
      </div>
    {/if}
  </Card>
</div>
