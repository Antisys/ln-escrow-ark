<script>
	import { cancelDispute, submitDisputeContact } from '$lib/api.js';
	import { friendlyError } from '$lib/utils/format.js';

	let {
		deal,
		dealId,
		userRole,
		getSignedAction,
		getAuthenticatedUserId,
		onDealUpdate,
		onError,
	} = $props();

	let disputeContact = $state('');
	let disputeMessage = $state('');
	let disputeContactSubmitting = $state(false);
	let disputeContactSaved = $state(false);
	let disputeContactError = $state('');
	let cancelDisputeSubmitting = $state(false);

	// Determine which role filed the dispute (needed for correct key selection)
	let disputerRole = $derived(
		deal.disputed_by === getAuthenticatedUserId('buyer') ? 'buyer'
		: deal.disputed_by === getAuthenticatedUserId('seller') ? 'seller'
		: userRole
	);

	async function handleDisputeContact() {
		if (!disputeContact.trim() && !disputeMessage.trim()) {
			disputeContactError = 'Please enter your contact info or a message';
			return;
		}
		const sig = getSignedAction('dispute-contact', userRole);
		if (!sig) { disputeContactError = 'Key not found.'; return; }
		disputeContactSubmitting = true;
		disputeContactError = '';
		try {
			const userId = getAuthenticatedUserId(userRole);
			await submitDisputeContact(dealId, userId, disputeContact.trim(), disputeMessage.trim(), sig.signature, sig.timestamp);
			disputeContactSaved = true;
			onDealUpdate();
		} catch (e) {
			disputeContactError = e.message;
		} finally {
			disputeContactSubmitting = false;
		}
	}

	async function handleCancelDispute() {
		const sig = getSignedAction('cancel-dispute', disputerRole);
		if (!sig) { onError('Key not found. Please re-authenticate with your wallet.'); return; }
		cancelDisputeSubmitting = true;
		try {
			const userId = getAuthenticatedUserId(disputerRole);
			await cancelDispute(dealId, userId, sig.signature, sig.timestamp);
			cancelDisputeSubmitting = false;
			disputeContactSaved = false;
			disputeContact = '';
			disputeMessage = '';
			disputeContactError = '';
			onDealUpdate();
		} catch (e) {
			onError(friendlyError(e.message));
			cancelDisputeSubmitting = false;
		}
	}
</script>

<div class="action-content disputed-state">
	<span class="big-icon">⚠</span>
	<h2>Dispute Open</h2>
	<p>This deal is under review by a referee.</p>
	<div class="dispute-details">
		{#if deal.disputed_by}
			<p class="dispute-meta">
				Raised by: <strong>{deal.disputed_by === deal.buyer_id ? 'Buyer' : 'Seller'}</strong>
				{#if deal.disputed_at}
					• {new Date(deal.disputed_at).toLocaleString()}
				{/if}
			</p>
		{/if}
		{#if deal.dispute_reason}
			<div class="dispute-reason">
				<strong>Reason:</strong> {deal.dispute_reason}
			</div>
		{/if}
	</div>
	<p class="hint">A referee will review the case and decide whether to release funds to the seller or refund to the buyer.</p>

	{#if disputeContactSaved}
		<div class="payout-saved-badge" style="margin-top: 1rem;">Message sent to referee</div>
	{:else}
		<div class="dispute-contact-form">
			<h3>Contact the Referee</h3>
			<input
				type="text"
				bind:value={disputeContact}
				placeholder="Your contact (email, telegram, nostr)"
				class="dispute-input"
			/>
			<textarea
				bind:value={disputeMessage}
				placeholder="Describe your side of the dispute..."
				rows="3"
				class="dispute-input"
			></textarea>
			{#if disputeContactError}
				<p class="error">{disputeContactError}</p>
			{/if}
			<button class="btn primary" onclick={handleDisputeContact} disabled={disputeContactSubmitting}>
				{disputeContactSubmitting ? 'Sending...' : 'Send to Referee'}
			</button>
		</div>
	{/if}

	{#if deal.disputed_by === getAuthenticatedUserId('buyer') || deal.disputed_by === getAuthenticatedUserId('seller')}
		<div class="cancel-dispute-section">
			<p class="hint">Resolved the issue? Cancel the dispute to continue the deal normally.</p>
			<button class="btn" onclick={handleCancelDispute} disabled={cancelDisputeSubmitting}>
				{cancelDisputeSubmitting ? 'Cancelling...' : 'Cancel Dispute'}
			</button>
		</div>
	{/if}
</div>

<style>
	@import '$lib/styles/deal-shared.css';
</style>
