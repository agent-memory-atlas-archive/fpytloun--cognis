<script lang="ts">
  import CognisLogo from '$lib/components/CognisLogo.svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import QRCode from 'qrcode';

  import Button from '$lib/components/ui/Button.svelte';
  import Card from '$lib/components/ui/Card.svelte';
  import Input from '$lib/components/ui/Input.svelte';
  import LoadingState from '$lib/components/LoadingState.svelte';
  import { auth } from '$lib/stores/auth';

  let bootstrapping = true;
  let email = '';
  let password = '';
  let error = '';
  let submitting = false;
  let challengeToken = '';
  let setupRequired = false;
  let setupSecret = '';
  let qrDataUrl = '';
  let code = '';
  let recoveryCodes: string[] = [];

  function returnTarget(): string {
    const target = $page.url.searchParams.get('returnTo');
    return target && target.startsWith('/') ? target : '/';
  }

  onMount(() => {
    void (async () => {
      try {
        await auth.bootstrap();
        if (auth.getSnapshot().status === 'authenticated') {
          await goto(returnTarget(), { replaceState: true });
        }
      } catch (caughtError) {
        error = caughtError instanceof Error ? caughtError.message : 'Unable to verify your session.';
      } finally {
        bootstrapping = false;
      }
    })();
  });

  async function handleSubmit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    error = '';
    submitting = true;

    try {
      const challenge = await auth.login(email, password);
      if (!challenge) {
        await goto(returnTarget(), { replaceState: true });
        return;
      }
      challengeToken = challenge.challenge_token;
      setupRequired = challenge.status === 'mfa_setup_required';
      if (setupRequired) {
        const setup = await auth.startMfaSetup(challengeToken);
        setupSecret = setup.secret;
        qrDataUrl = await QRCode.toDataURL(setup.provisioning_uri, {
          width: 220,
          margin: 1,
          color: { dark: '#0f172a', light: '#ffffff' }
        });
      }
    } catch (caughtError) {
      error = caughtError instanceof Error ? caughtError.message : 'Unable to log in.';
    } finally {
      submitting = false;
    }
  }

  async function handleMfaSubmit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    error = '';
    submitting = true;
    try {
      const completed = await auth.completeMfa(challengeToken, code, setupRequired);
      recoveryCodes = completed.recovery_codes ?? [];
      if (recoveryCodes.length === 0) {
        await goto(returnTarget(), { replaceState: true });
      }
    } catch (caughtError) {
      error = caughtError instanceof Error ? caughtError.message : 'Unable to verify the code.';
    } finally {
      submitting = false;
    }
  }

  async function finishRecoveryAcknowledgement(): Promise<void> {
    recoveryCodes = [];
    await goto(returnTarget(), { replaceState: true });
  }
</script>

<svelte:head>
  <title>Sign In · Cognis</title>
</svelte:head>

<div class="app-fullscreen-safe app-fullscreen-safe--compact flex items-center justify-center overflow-y-auto">
  {#if bootstrapping}
    <LoadingState label="Loading workspace" description="Restoring your Cognis session and preparing the UI shell." />
  {:else}
  <Card class="w-full max-w-sm p-8 sm:p-10">
    <div class="space-y-6">
      <div class="space-y-3 text-center">
        <CognisLogo class="mx-auto h-16 w-16" />
        <h1 class="text-2xl font-semibold text-strong">Cognis</h1>
        <p class="text-sm text-muted">User sign-in</p>
      </div>

      {#if recoveryCodes.length > 0}
        <div class="space-y-4">
          <div>
            <h2 class="font-semibold text-strong">Save your recovery codes</h2>
            <p class="mt-1 text-sm text-muted">Each code works once. Store them securely.</p>
          </div>
          <pre class="rounded-2xl border border-control-border bg-canvas p-4 text-sm text-foreground">{recoveryCodes.join('\n')}</pre>
          <Button class="w-full justify-center" onclick={finishRecoveryAcknowledgement}>I saved these codes</Button>
        </div>
      {:else if challengeToken}
        <form class="space-y-5" onsubmit={handleMfaSubmit} novalidate>
          {#if setupRequired}
            <div class="space-y-3 text-center">
              <p class="text-sm text-secondary">Scan this code with your authenticator app.</p>
              {#if qrDataUrl}<img class="mx-auto rounded-xl bg-white p-2" src={qrDataUrl} alt="TOTP setup QR code" />{/if}
              <p class="break-all font-mono text-xs text-muted">{setupSecret}</p>
            </div>
          {:else}
            <p class="text-sm text-secondary">Enter your authenticator code or a recovery code.</p>
          {/if}
          <label class="block space-y-2 text-sm font-medium text-foreground">
            <span>Authentication code</span>
            <Input bind:value={code} name="code" autocomplete="one-time-code" inputmode="numeric" placeholder="123456" />
          </label>
          {#if error}
            <p class="rounded-2xl border border-danger-border bg-danger-subtle px-4 py-3 text-sm text-danger">{error}</p>
          {/if}
          <Button class="w-full justify-center" type="submit" disabled={submitting}>
            {submitting ? 'Verifying…' : setupRequired ? 'Enable and sign in' : 'Verify'}
          </Button>
        </form>
      {:else}
      <form class="space-y-5" onsubmit={handleSubmit} novalidate>
        <label class="block space-y-2 text-sm font-medium text-foreground">
          <span>Email</span>
          <Input bind:value={email} name="email" type="email" autocomplete="username" placeholder="admin@example.com" />
        </label>

        <label class="block space-y-2 text-sm font-medium text-foreground">
          <span>Password</span>
          <Input bind:value={password} name="password" type="password" autocomplete="current-password" placeholder="••••••••" />
        </label>

        {#if error}
          <p class="rounded-2xl border border-danger-border bg-danger-subtle px-4 py-3 text-sm text-danger">
            {error}
          </p>
        {/if}

        <Button class="w-full justify-center" type="submit" disabled={submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
      {/if}
    </div>
  </Card>
  {/if}
</div>
