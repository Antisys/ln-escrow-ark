<script>
	import { openDispute } from '$lib/api.js';
	import { signDispute } from '$lib/crypto.js';

	let {
		show = $bindable(false),
		dealId,
		storedKeyEntry = null,
		userRole = null,
		getSignedAction,
		getAuthenticatedUserId,
		onDealUpdate,
	} = $props();

	let disputeReason = $state('');
	let disputeSubmitting = $state(false);
	let disputeSuccess = $state(false);
	let actionError = $state('');

	async function submitDispute() {
		if (!disputeReason.trim()) {
			actionError = 'Please describe the issue';
			return;
		}
		const sig = getSignedAction('dispute');
		if (!sig) { actionError = 'Key not found. Please re-authenticate with your wallet.'; return; }
		disputeSubmitting = true;
		disputeSuccess = false;
		actionError = '';
		try {
			const userId = getAuthenticatedUserId();
			// Non-custodial: sign SHA256("dispute") with ephemeral key for delegated escrow dispute
			let escrowSig = null;
			const roleKey = userRole && storedKeyEntry?.[userRole];
			if (roleKey?.privateKey) {
				try { escrowSig = signDispute(roleKey.privateKey); } catch (e) { /* Escrow dispute sig failed — dispute will proceed without it */ }
			}
			await openDispute(dealId, userId, disputeReason, sig.signature, sig.timestamp, escrowSig);

			disputeSubmitting = false;
			disputeSuccess = true;

			await new Promise(resolve => setTimeout(resolve, 1500));

			show = false;
			disputeReason = '';
			disputeSuccess = false;
			await onDealUpdate();
		} catch (e) {
			actionError = `Failed to open dispute: ${e.message}`;
			disputeSubmitting = false;
		}
	}
</script>

{#if show}
	<div class="modal-overlay" onclick={() => show = false} role="presentation" onkeydown={(e) => e.key === 'Escape' && (show = false)}>
		<div class="modal dispute-modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Open dispute" onkeydown={(e) => e.stopPropagation()}>
			{#if disputeSuccess}
				<div class="dispute-success">
					<div class="success-icon">✓</div>
					<h2>Dispute Submitted</h2>
					<p>A referee will review and resolve this case.</p>
				</div>
			{:else}
				<button class="modal-close" onclick={() => show = false} aria-label="Close">&times;</button>
				<h2>Open Dispute</h2>
				<p class="modal-hint">Describe the problem with this deal. A referee will review and decide on the resolution.</p>

				<div class="dispute-form">
					<label for="dispute-reason">What went wrong?</label>
					<textarea
						id="dispute-reason"
						bind:value={disputeReason}
						placeholder="Describe the issue in detail..."
						rows="4"
					></textarea>
				</div>

				<div class="dispute-info">
					<p><strong>What happens next:</strong></p>
					<ul>
						<li>The deal will be marked as disputed</li>
						<li>A referee will review the case</li>
						<li>Funds remain locked until resolved</li>
						<li>Referee will release to seller or refund to buyer</li>
					</ul>
				</div>

				{#if actionError}
					<p class="error">{actionError}</p>
				{/if}

				<div class="modal-actions">
					<button class="btn" onclick={() => show = false}>Cancel</button>
					<button class="btn danger" onclick={submitDispute} disabled={disputeSubmitting}>
						{disputeSubmitting ? 'Submitting...' : 'Submit Dispute'}
					</button>
				</div>
			{/if}
		</div>
	</div>
{/if}

<style>
	.modal-overlay {
		position: fixed; top: 0; left: 0; right: 0; bottom: 0;
		background: rgba(0, 0, 0, 0.7);
		display: flex; align-items: center; justify-content: center;
		z-index: 1000;
	}
	.modal {
		background: var(--surface);
		padding: 2rem;
		border-radius: 12px;
		border: 1px solid var(--border);
		max-width: 400px;
		width: 90%;
		position: relative;
	}
	.dispute-modal { max-width: 450px; }
	.modal-close {
		position: absolute; top: 0.5rem; right: 1rem;
		background: none; border: none;
		font-size: 2rem; color: var(--text-dim); cursor: pointer;
	}
	.modal-close:hover { color: var(--text); }
	.modal h2 { color: var(--text); text-align: center; margin-bottom: 1rem; }
	.modal-hint { color: var(--text-muted); font-size: 0.95rem; margin-bottom: 1rem; }

	.dispute-form { margin-bottom: 1rem; }
	.dispute-form label {
		display: block; color: var(--text-muted);
		margin-bottom: 0.5rem; font-size: 0.95rem;
	}
	.dispute-form textarea {
		width: 100%;
		padding: 0.75rem;
		background: var(--bg);
		border: 1px solid var(--border-hover);
		border-radius: 4px;
		color: var(--text);
		font-size: 0.95rem;
		resize: vertical;
	}

	.dispute-info {
		background: var(--bg);
		padding: 1rem;
		border-radius: 4px;
		margin-bottom: 1rem;
		font-size: 0.8rem;
	}
	.dispute-info p { margin: 0 0 0.5rem 0; color: var(--text-muted); }
	.dispute-info ul { margin: 0; padding-left: 1.25rem; color: var(--text-muted); }
	.dispute-info li { margin: 0.25rem 0; }

	.error { color: var(--error); font-size: 0.8rem; margin-top: 0.75rem; }

	.modal-actions {
		display: flex; gap: 0.75rem; justify-content: flex-end;
	}
	.btn {
		padding: 0.6rem 1.25rem;
		border-radius: 6px;
		border: 1px solid var(--border-hover);
		font-size: 0.95rem;
		cursor: pointer;
		background: var(--border);
		color: var(--text);
	}
	.btn:hover { background: var(--border-hover); }
	.btn.danger {
		background: var(--error);
		color: white;
		font-weight: 600;
		border: none;
	}
	.btn.danger:hover { background: var(--error-hover); }

	.dispute-success { text-align: center; padding: 2rem 1rem; }
	.dispute-success .success-icon {
		width: 60px; height: 60px;
		background: var(--success);
		border-radius: 50%;
		display: flex; align-items: center; justify-content: center;
		font-size: 2rem; color: white;
		margin: 0 auto 1rem;
	}
	.dispute-success h2 { color: var(--success); margin-bottom: 0.5rem; }
	.dispute-success p { color: var(--text-muted); }
</style>
