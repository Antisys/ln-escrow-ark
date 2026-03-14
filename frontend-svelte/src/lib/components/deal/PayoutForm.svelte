<script>
	import { submitPayoutInvoice } from '$lib/api.js';
	import { submitRefundInvoice } from '$lib/api/refund.js';
	import { friendlyError } from '$lib/utils/format.js';

	let {
		type = 'release',
		deal,
		dealId,
		storedKey,
		lndDown = false,
		getSignedAction,
		getAuthenticatedUserId,
		onDealUpdate,
	} = $props();

	let payoutInvoice = $state('');
	let payoutSubmitting = $state(false);
	let payoutSaved = $state(false);
	let payoutError = $state('');

	// Confirm modal
	let showConfirm = $state(false);

	function requestSubmitPayout() {
		const val = payoutInvoice.trim();
		if (!val) { payoutError = 'Please enter a Lightning Address'; return; }
		if (!/^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$/.test(val)) {
			payoutError = 'Invalid format. Use a Lightning Address (you@wallet.com)';
			return;
		}
		payoutError = '';
		showConfirm = true;
	}

	async function handleSubmitPayout() {
		showConfirm = false;
		const action = type === 'release' ? 'submit-payout-invoice' : 'submit-refund-invoice';
		const sig = getSignedAction(action);
		if (!sig) { payoutError = 'Key not found. Please re-authenticate with your wallet.'; return; }
		payoutSubmitting = true;
		payoutError = '';
		payoutSaved = false;
		try {
			const userId = getAuthenticatedUserId();
			const submitFn = type === 'release' ? submitPayoutInvoice : submitRefundInvoice;
			await submitFn(dealId, userId, payoutInvoice.trim(), sig.signature, sig.timestamp);
			payoutSaved = true;
			await onDealUpdate();
		} catch (e) {
			payoutError = friendlyError(e.message);
		} finally {
			payoutSubmitting = false;
		}
	}
</script>

<div class="payout-form">
	<input
		type="text"
		bind:value={payoutInvoice}
		placeholder="you@wallet.com"
		class="payout-input"
		disabled={payoutSubmitting}
		aria-label="Lightning Address"
	/>
	<button class="btn primary" onclick={requestSubmitPayout} disabled={payoutSubmitting || lndDown}>
		{payoutSubmitting ? 'Verifying...' : 'Save Lightning Address'}
	</button>
	{#if payoutError}
		<p class="error" role="alert">{payoutError}</p>
	{/if}
	{#if payoutSaved}
		<div class="payout-saved-badge">Lightning Address saved</div>
	{/if}
</div>

<!-- Confirmation Modal -->
{#if showConfirm}
	<div class="modal-overlay" onclick={() => showConfirm = false} role="presentation" onkeydown={(e) => e.key === 'Escape' && (showConfirm = false)}>
		<div class="modal confirm-modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Confirm payout address" onkeydown={(e) => e.stopPropagation()}>
			<button class="modal-close" onclick={() => showConfirm = false} aria-label="Close">&times;</button>
			<h2>Confirm {type === 'release' ? 'Payment' : 'Refund'} Address</h2>
			<p>{type === 'release' ? 'Funds' : 'Refund'} will be sent to:</p>
			<p class="confirm-destination"><strong>{payoutInvoice.trim()}</strong></p>
			<p class="confirm-warning">Double-check the address. Once paid, this cannot be undone.</p>
			<div class="modal-actions">
				<button class="btn" onclick={() => showConfirm = false}>Cancel</button>
				<button class="btn primary" onclick={handleSubmitPayout} disabled={payoutSubmitting}>
					{payoutSubmitting ? 'Verifying...' : 'Confirm'}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.btn {
		padding: 0.6rem 1.25rem; border-radius: 6px;
		border: 1px solid var(--border-hover); font-size: 0.95rem;
		cursor: pointer; background: var(--border); color: var(--text);
	}
	.btn:hover { background: var(--border-hover); }
	.btn.primary { background: var(--accent); color: var(--bg); font-weight: 600; border: none; }
	.btn.primary:hover { background: var(--accent-hover); }

	.error { color: var(--error); font-size: 0.8rem; margin-top: 0.75rem; }

	.payout-form { margin: 1rem 0; }
	.payout-input {
		width: 100%; padding: 0.6rem;
		background: var(--bg); border: 1px solid var(--border-hover);
		border-radius: 6px; color: var(--text);
		font-size: 0.95rem; margin-bottom: 0.5rem; box-sizing: border-box;
	}
	.payout-saved-badge {
		display: inline-block; padding: 0.35rem 0.75rem;
		border-radius: 12px; font-size: 0.8rem;
		background: var(--success-bg); color: var(--success); margin-top: 0.5rem;
	}

	.modal-overlay {
		position: fixed; top: 0; left: 0; right: 0; bottom: 0;
		background: rgba(0, 0, 0, 0.7);
		display: flex; align-items: center; justify-content: center; z-index: 1000;
	}
	.modal {
		background: var(--surface); padding: 2rem; border-radius: 12px;
		border: 1px solid var(--border); max-width: 400px; width: 90%; position: relative;
	}
	.modal-close {
		position: absolute; top: 0.5rem; right: 1rem;
		background: none; border: none; font-size: 2rem; color: var(--text-dim); cursor: pointer;
	}
	.modal-close:hover { color: var(--text); }
	.modal h2 { color: var(--text); text-align: center; margin-bottom: 1rem; }
	.confirm-destination {
		color: var(--accent); word-break: break-all;
		text-align: center; font-size: 0.95rem; margin: 0.5rem 0 1rem;
	}
	.confirm-warning {
		color: var(--orange); font-size: 0.9rem;
		text-align: center; margin-bottom: 1rem;
	}
	.modal-actions { display: flex; gap: 0.75rem; justify-content: flex-end; }
</style>
