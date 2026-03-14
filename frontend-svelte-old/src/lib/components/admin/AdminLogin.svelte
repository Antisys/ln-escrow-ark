<script>
	import { onMount, onDestroy } from 'svelte';
	import { getAdminChallenge, checkAdminAuthStatus } from '$lib/api.js';
	import { copyToClipboard } from '$lib/utils/format.js';

	let {
		QRCode,
		onAuthenticated,
	} = $props();

	let lnurlChallenge = $state(null);
	let lnurlQrDataUrl = $state('');
	let lnurlPolling = $state(null);
	let rejectedPubkey = $state(null);
	let pollFailures = $state(0);
	let pollError = $state(null);

	let startError = $state('');

	async function startLnurlAuth() {
		startError = '';
		try {
			lnurlChallenge = await getAdminChallenge();
			lnurlQrDataUrl = await QRCode.toDataURL(lnurlChallenge.qr_content, {
				width: 256,
				margin: 2,
				color: { dark: '#000000', light: '#ffffff' }
			});

			lnurlPolling = setInterval(async () => {
				try {
					const status = await checkAdminAuthStatus(lnurlChallenge.k1);
					pollFailures = 0;
					if (status.verified) {
						clearInterval(lnurlPolling);
						lnurlPolling = null;

						if (status.is_admin) {
							onAuthenticated(status.linking_pubkey);
						} else {
							lnurlChallenge = null;
							lnurlQrDataUrl = '';
							rejectedPubkey = status.linking_pubkey;
						}
					}
				} catch {
					pollFailures++;
					if (pollFailures >= 5) {
						clearInterval(lnurlPolling);
						lnurlPolling = null;
						lnurlChallenge = null;
						lnurlQrDataUrl = '';
						pollError = 'Connection lost. Please try again.';
					}
				}
			}, 4000);
		} catch (e) {
			startError = e.message || 'Failed to load';
		}
	}

	onMount(() => startLnurlAuth());
	onDestroy(() => {
		if (lnurlPolling) clearInterval(lnurlPolling);
	});
</script>

<div class="login-card">
	<div class="lnurl-auth">
		{#if lnurlQrDataUrl}
			<div class="qr-section">
				<p class="qr-hint">Scan with your Lightning wallet</p>
				<div class="qr-box">
					<img src={lnurlQrDataUrl} alt="Admin sign-in QR code" />
				</div>
				<div class="qr-actions">
					<button class="btn copy-btn" onclick={() => copyToClipboard(lnurlChallenge?.qr_content || '')}>Copy Link</button>
				</div>
				<p class="status-text">Waiting for wallet...</p>
			</div>
		{:else if pollError}
			<p class="error-text">{pollError}</p>
			<button class="btn primary" onclick={() => { pollError = null; pollFailures = 0; startLnurlAuth(); }}>Try Again</button>
		{:else if startError}
			<p class="error-text">{startError}</p>
			<button class="btn primary" onclick={() => startLnurlAuth()}>Try Again</button>
		{:else}
			<div class="loading"><div class="spinner"></div></div>
		{/if}
	</div>

	{#if rejectedPubkey}
		<div class="rejected-pubkey">
			<p>Not a referee. Add your pubkey to ADMIN_PUBKEYS:</p>
			<button class="code-copy" onclick={() => copyToClipboard(rejectedPubkey)}>{rejectedPubkey}</button>
			<p class="hint small">Click to copy</p>
		</div>
	{/if}
</div>

<style>
	.login-card {
		background: var(--surface);
		padding: 2rem;
		border-radius: 8px;
		border: 1px solid var(--border);
		max-width: 400px;
		margin: 0 auto;
	}
	.loading { text-align: center; padding: 2rem; }
	.spinner {
		width: 32px; height: 32px;
		border: 3px solid var(--border); border-top-color: var(--accent);
		border-radius: 50%; animation: spin 1s linear infinite;
		margin: 0 auto;
	}
	@keyframes spin { to { transform: rotate(360deg); } }
	.lnurl-auth { text-align: center; }
	.qr-section { text-align: center; }
	.qr-hint { color: var(--text-muted); font-size: 0.9rem; margin-bottom: 0.75rem; }
	.qr-box {
		background: white; padding: 1rem; border-radius: 12px;
		display: block; width: fit-content; margin: 0 auto;
	}
	.qr-box img { display: block; width: 220px; height: 220px; border-radius: 4px; }
	.qr-actions { margin-top: 0.75rem; }
	.btn {
		padding: 0.75rem 1.25rem; background: var(--border);
		border: 1px solid var(--border-hover); border-radius: 4px;
		color: var(--text); cursor: pointer;
	}
	.btn:hover:not(:disabled) { background: var(--border-hover); }
	.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--bg); font-weight: 600; }
	.copy-btn {
		background: var(--surface); border: 1px solid var(--border); color: var(--text);
		padding: 0.4rem 1.2rem; border-radius: 6px; cursor: pointer; font-size: 0.85rem;
	}
	.copy-btn:hover { border-color: var(--accent); color: var(--accent); }
	.status-text { margin-top: 0.75rem; color: var(--orange); font-size: 0.85rem; font-style: italic; }
	.rejected-pubkey {
		margin-top: 1.5rem; padding: 1rem; background: var(--bg);
		border: 1px solid #ff6b6b; border-radius: 6px; text-align: center;
	}
	.rejected-pubkey p { margin: 0 0 0.5rem; color: #ff6b6b; }
	.code-copy {
		font-family: monospace; background: var(--bg); border: 1px solid var(--border);
		color: var(--orange); padding: 0.5rem; border-radius: 4px; cursor: pointer;
		word-break: break-all; font-size: 0.8rem; display: block; width: 100%; text-align: left;
	}
	.hint { color: var(--text-dim); font-size: 0.875rem; }
	.hint.small { font-size: 0.75rem; }
	.error-text { color: var(--error); margin-bottom: 1rem; }
</style>
