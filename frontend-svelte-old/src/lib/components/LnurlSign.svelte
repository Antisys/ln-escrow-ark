<script>
	import { onMount, onDestroy } from 'svelte';
	import { getLnurlChallenge, checkAuthStatus, registerDerivedKey } from '$lib/api.js';
	import { API_URL } from '$lib/api/base-url.js';
	import { deriveEphemeralKey, getVisitorId, signTimeoutAuth, decryptFromBackup } from '$lib/crypto.js';
	import { dealKeys, dealAuths, storeKeyForDeal, storeAuthForDeal, storeSecretCodeForDeal } from '$lib/stores/vault.js';
	let { dealToken, role = 'seller', onSuccess = () => {} } = $props();

	let loading = $state(true);
	let error = $state(null);
	let k1 = $state(null);
	let lnurl = $state(null);
	let qrUrl = $state(null);
	let dealId = $state(null);
	let pollInterval = $state(null);
	let status = $state('loading'); // loading, ready, polling, success, error
	let copied = $state(false);
	let pollFailures = $state(0);

	async function fetchChallenge() {
		try {
			loading = true;
			error = null;
			const response = await getLnurlChallenge(dealToken, role);
			k1 = response.k1;
			lnurl = response.lnurl || response.qr_content;
			qrUrl = `${API_URL}/qr/${response.qr_content}`;
			dealId = response.deal_id;
			status = 'ready';
			loading = false;

			startPolling();
		} catch (err) {
			error = err.message;
			status = 'error';
			loading = false;
		}
	}

	function startPolling() {
		status = 'polling';
		pollInterval = setInterval(async () => {
			try {
				const authStatus = await checkAuthStatus(k1);
				pollFailures = 0;

				if (authStatus.verified) {
					stopPolling();
					await handleAuthSuccess(authStatus);
				}
			} catch (err) {
				pollFailures++;
				if (pollFailures >= 3) {
					stopPolling();
					error = 'Connection lost. Please try again.';
					status = 'error';
				}
			}
		}, 4000);  // Poll every 4s to stay under rate limit (20/60s)
	}

	function stopPolling() {
		if (pollInterval) {
			clearInterval(pollInterval);
			pollInterval = null;
		}
	}

	async function handleAuthSuccess(authStatus) {
		try {
			status = 'success';

			// Derive ephemeral key from signature
			const { privateKey, publicKey } = deriveEphemeralKey(
				authStatus.signature,
				dealId
			);

			// Get visitor ID
			const visitorId = getVisitorId();

			// Non-custodial: pre-sign SHA256("timeout") for delegated timeout claims.
			// Both buyer and seller pre-sign at auth time so the service can process
			// timeouts without requiring either party to be online.
			const timeoutSig = signTimeoutAuth(privateKey);

			// Register the derived key with backend
			const result = await registerDerivedKey(k1, visitorId, publicKey, timeoutSig);

			// Deterministic k1 → same wallet always derives the same key.
			// No need for stored auth_signature recovery — the key IS the same.
			const finalRole = result.role || role;
			storeKeyForDeal(result.deal_id, privateKey, publicKey, finalRole);
			storeAuthForDeal(result.deal_id, authStatus.pubkey, finalRole, visitorId);

			// Recovery: decrypt server-stored vault to restore secret_code
			if (result.recovery && result.encrypted_vault) {
				try {
					const vault = JSON.parse(result.encrypted_vault);
					const secretCode = await decryptFromBackup(privateKey, vault.iv, vault.ciphertext);
					storeSecretCodeForDeal(result.deal_id, secretCode);
					} catch (e) {
					console.warn('Failed to decrypt vault backup:', e);
				}
			}

			// Dual-role: if same wallet holds both roles, store key for other role too
			if (result.other_role_recovery) {
				const otherRole = typeof result.other_role_recovery === 'string'
					? result.other_role_recovery : result.other_role_recovery;
				storeKeyForDeal(result.deal_id, privateKey, publicKey, otherRole);
				storeAuthForDeal(result.deal_id, authStatus.pubkey, otherRole, visitorId);
			}

			// Call success callback
			onSuccess({
				linkingKey: authStatus.pubkey,
				ephemeralKey: { privateKey, publicKey },
				dealId: result.deal_id,
				role: result.role
			});
		} catch (err) {
			error = err.message;
			status = 'error';
		}
	}

	onMount(() => {
		fetchChallenge();
	});

	onDestroy(() => {
		stopPolling();
	});
</script>

<div class="lnurl-sign">
	{#if loading}
		<div class="loading">
			<div class="spinner"></div>
			<p>Preparing sign-in...</p>
		</div>
	{:else if error}
		<div class="error">
			<p>{error}</p>
			<button class="btn" onclick={fetchChallenge}>Try Again</button>
		</div>
	{:else if status === 'success'}
		<div class="success">
			<span class="checkmark">✓</span>
			<p>Signed successfully!</p>
		</div>
	{:else}
		<div class="qr-section">
			<p class="hint">Scan with your Lightning wallet</p>
			<div class="qr-box">
				<img src={qrUrl} alt="Sign-in QR code" />
			</div>
			<div class="qr-actions">
				<button class="btn copy-btn" onclick={() => { navigator.clipboard.writeText(lnurl).catch(() => {}); copied = true; setTimeout(() => copied = false, 2000); }}>
					{copied ? 'Copied!' : 'Copy Link'}
				</button>
			</div>
			<p class="status-text">Waiting for wallet confirmation...</p>
		</div>
	{/if}
</div>

<style>
	.lnurl-sign {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 1rem;
	}

	.loading, .error, .success {
		text-align: center;
		padding: 2rem;
	}

	.spinner {
		width: 40px;
		height: 40px;
		border: 3px solid var(--border);
		border-top: 3px solid var(--accent);
		border-radius: 50%;
		animation: spin 1s linear infinite;
		margin: 0 auto 1rem;
	}

	@keyframes spin {
		0% { transform: rotate(0deg); }
		100% { transform: rotate(360deg); }
	}

	.error {
		color: var(--error);
	}

	.error .btn {
		margin-top: 1rem;
		padding: 0.5rem 1rem;
		background: var(--accent);
		color: var(--bg);
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-weight: 600;
	}

	.success {
		color: var(--success);
	}

	.checkmark {
		font-size: 3rem;
		display: block;
		margin-bottom: 0.5rem;
	}

	.qr-section {
		text-align: center;
	}

	.hint {
		color: var(--text-muted);
		font-size: 0.9rem;
		margin-bottom: 0.75rem;
	}

	.qr-box {
		background: white;
		padding: 1rem;
		border-radius: 12px;
		display: block;
		width: fit-content;
		margin: 0 auto;
	}

	.qr-box img {
		display: block;
		width: 220px;
		height: 220px;
		border-radius: 4px;
	}

	.qr-actions {
		margin-top: 0.75rem;
	}

	.copy-btn {
		background: var(--surface);
		border: 1px solid var(--border);
		color: var(--text);
		padding: 0.4rem 1.2rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.85rem;
	}

	.copy-btn:hover {
		border-color: var(--accent);
		color: var(--accent);
	}

	.status-text {
		margin-top: 0.75rem;
		color: var(--orange);
		font-size: 0.85rem;
		font-style: italic;
	}
</style>
