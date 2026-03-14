<script>
	import { getKeyForDeal, getSecretCodeForDeal } from '$lib/stores/vault.js';
	import { request } from '$lib/api/_shared.js';
	import { copyToClipboard } from '$lib/utils/format.js';

	let {
		deal,
		signingStatus,
		storedKey,
		userRole,
		countdownText,
		countdownUrgent = false,
		onOpenDispute,
	} = $props();

	let showDetails = $state(false);
	let linkCopied = $state(false);
	let exportError = $state('');

	async function copyDealLink() {
		if (!deal?.deal_link) return;
		await copyToClipboard(deal.deal_link);
		linkCopied = true;
		setTimeout(() => linkCopied = false, 2000);
	}

	async function exportRecoveryKit() {
		exportError = '';
		try {
			const serverData = await request(`/deals/${deal.deal_id}/recovery-info`);

			// Add client-side secrets (private key + secret code)
			const keyEntry = getKeyForDeal(deal.deal_id, userRole);
			const recoveryKit = {
				...serverData,
				exported_at: new Date().toISOString(),
				your_role: userRole,
				your_private_key: keyEntry?.privateKey || null,
				secret_code: getSecretCodeForDeal(deal.deal_id) || null,
				warning: "KEEP THIS FILE SECRET. Anyone with your private key can claim your funds.",
			};

			const blob = new Blob([JSON.stringify(recoveryKit, null, 2)], { type: 'application/json' });
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `recovery-kit-${deal.deal_id.slice(0, 8)}.json`;
			a.click();
			setTimeout(() => URL.revokeObjectURL(url), 1000);
		} catch (err) {
			exportError = 'Failed to export recovery kit: ' + err.message;
		}
	}
</script>

<button class="details-toggle" onclick={() => showDetails = !showDetails}>
	{showDetails ? 'Hide details' : 'Details'}
</button>
{#if showDetails}
	<div class="details-section">
		{#if ['funded', 'shipped'].includes(deal?.status)}
			<div class="dispute-section">
				<button class="btn danger-outline" onclick={onOpenDispute}>Report a Problem</button>
			</div>
		{/if}

		{#if signingStatus?.funding_txid && !['completed', 'released', 'refunded'].includes(deal?.status)}
			<div class="funding-info">
				<span class="funded-badge">Funded: {deal.price_sats?.toLocaleString()} sats</span>
				{#if countdownText}
					<div class="countdown-row">
						<span class="countdown" class:urgent={countdownUrgent}>{countdownText}</span>
						{#if deal?.timeout_action}
							<span class="timeout-hint">On timeout: {deal.timeout_action === 'refund' ? 'auto-refund' : 'auto-release'}</span>
						{/if}
					</div>
				{/if}
			</div>

			{#if storedKey && ['funded', 'shipped', 'disputed'].includes(deal?.status)}
				<div class="key-warning-box">
					<strong>Keys stored in this browser only.</strong>
					If you clear browser data or switch devices, sign in again with the same Lightning wallet to recover access.
				</div>
			{/if}

			{#if deal?.fedimint_escrow_id}
				<div class="escrow-id-box">
					<strong>Recovery Info</strong>
					<p>Save this if you need to recover funds in case of service outage:</p>
					<code class="escrow-id">{deal.fedimint_escrow_id}</code>
					{#if deal.fedimint_timeout_block}
						<p class="timeout-block">Timeout block: <code>{deal.fedimint_timeout_block}</code></p>
					{/if}
					<button class="btn recovery-export-btn" onclick={exportRecoveryKit}>
						Export Recovery Kit
					</button>
					<p class="recovery-hint">Downloads a JSON file with everything needed to recover funds independently.</p>
					{#if exportError}
						<p class="error">{exportError}</p>
					{/if}
				</div>
			{/if}
		{/if}

		{#if deal?.deal_link}
			<div class="deal-link-box">
				<strong>Deal Link</strong>
				<div class="deal-link-row">
					<input type="text" readonly value={deal.deal_link} class="deal-link-input" aria-label="Deal link" />
					<button class="deal-link-copy" onclick={copyDealLink}>{linkCopied ? 'Copied!' : 'Copy'}</button>
				</div>
			</div>
		{/if}
	</div>
{/if}

<style>
	@import '$lib/styles/deal-shared.css';

	.deal-link-box {
		margin-top: 0.75rem;
		padding-top: 0.75rem;
		border-top: 1px solid var(--border);
	}
	.deal-link-box strong {
		display: block;
		color: var(--text-muted);
		font-size: 0.8rem;
		margin-bottom: 0.4rem;
	}
	.deal-link-row { display: flex; gap: 0.5rem; }
	.deal-link-input {
		flex: 1;
		background: var(--bg);
		border: 1px solid var(--border-hover);
		border-radius: 4px;
		color: var(--text);
		padding: 0.4rem 0.6rem;
		font-size: 0.75rem;
	}
	.deal-link-copy {
		padding: 0.4rem 0.6rem;
		background: var(--border);
		border: 1px solid var(--border-hover);
		border-radius: 4px;
		color: var(--text);
		cursor: pointer;
		font-size: 0.75rem;
		white-space: nowrap;
	}
	.deal-link-copy:hover { background: var(--border-hover); }
	.recovery-export-btn {
		margin-top: 0.5rem;
		padding: 0.4rem 0.8rem;
		background: var(--border);
		border: 1px solid var(--border-hover);
		border-radius: 4px;
		color: var(--text);
		cursor: pointer;
		font-size: 0.8rem;
	}
	.recovery-export-btn:hover { background: var(--border-hover); }
	.recovery-hint {
		font-size: 0.7rem;
		color: var(--text-muted);
		margin-top: 0.3rem;
	}
</style>
