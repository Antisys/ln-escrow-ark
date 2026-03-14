<script>
	import { shipDeal } from '$lib/api.js';
	import { getSecretCodeForDeal } from '$lib/stores/vault.js';
	import PayoutForm from './PayoutForm.svelte';

	let {
		deal,
		dealId,
		userRole,
		availableRoles = [],
		storedKey,
		storedKeyEntry = null,
		lndDown = false,
		signingStatus,
		getSignedAction,
		getAuthenticatedUserId,
		onDealUpdate,
		onRequestRelease,
		releaseInProgress = false,
	} = $props();

	let showShippingForm = $state(false);
	let trackingCarrier = $state('');
	let trackingNumber = $state('');
	let shippingNotes = $state('');
	let shippingSubmitting = $state(false);
	let shippingError = $state('');

	// Does this user hold both roles?
	let isDualRole = $derived(availableRoles.includes('buyer') && availableRoles.includes('seller'));

	// Role-specific key helpers
	function keyForRole(role) {
		if (storedKeyEntry?.[role]?.privateKey) return storedKeyEntry[role];
		return storedKey;
	}

	async function handleShipDeal() {
		if (shippingSubmitting) return;
		const sig = getSignedAction('ship', 'seller');
		if (!sig) { shippingError = 'Key not found. Please re-authenticate with your wallet.'; return; }
		shippingSubmitting = true;
		shippingError = '';
		try {
			const userId = getAuthenticatedUserId('seller');
			await shipDeal(dealId, userId, trackingCarrier, trackingNumber, shippingNotes, sig.signature, sig.timestamp);
			showShippingForm = false;
			onDealUpdate();
		} catch (e) {
			shippingError = e.message;
		} finally {
			shippingSubmitting = false;
		}
	}

</script>

<div class="action-content">
	{#if signingStatus.ready_for_resolution}
		<!-- SELLER section: shipping + payout address -->
		{#if userRole === 'seller' || isDualRole}
			{#if deal.status === 'shipped'}
				<div class="shipping-info-box">
					<div class="shipping-badge">Shipped</div>
					{#if deal.tracking_carrier || deal.tracking_number}
						<div class="shipping-details">
							{#if deal.tracking_carrier}<span class="shipping-detail"><strong>Carrier:</strong> {deal.tracking_carrier}</span>{/if}
							{#if deal.tracking_number}<span class="shipping-detail"><strong>Tracking:</strong> {deal.tracking_number}</span>{/if}
						</div>
					{/if}
					{#if deal.shipping_notes}<p class="shipping-notes">{deal.shipping_notes}</p>{/if}
					<p class="shipping-date">Shipped {new Date(deal.shipped_at).toLocaleString()}</p>
				</div>
			{:else}
				{#if showShippingForm}
					<h2>Mark as Shipped</h2>
					<div class="shipping-form">
						<input type="text" bind:value={trackingCarrier} placeholder="Carrier (e.g. DHL, FedEx)" class="payout-input" aria-label="Shipping carrier" />
						<input type="text" bind:value={trackingNumber} placeholder="Tracking number" class="payout-input" aria-label="Tracking number" />
						<input type="text" bind:value={shippingNotes} placeholder="Notes (optional)" class="payout-input" aria-label="Shipping notes" />
						<div class="shipping-form-actions">
							<button class="btn primary" onclick={handleShipDeal} disabled={shippingSubmitting}>
								{shippingSubmitting ? 'Submitting...' : 'Confirm Shipped'}
							</button>
							<button class="btn" onclick={() => showShippingForm = false}>Cancel</button>
						</div>
						{#if shippingError}<p class="error" role="alert">{shippingError}</p>{/if}
					</div>
				{:else}
					<button class="btn ship-btn" onclick={() => showShippingForm = true}>Mark as Shipped</button>
				{/if}
			{/if}

			{#if deal.has_seller_payout_invoice}
				{#if !isDualRole}
					<p class="hint" style="margin-top: 1rem;">The buyer should release funds once they're satisfied.</p>
				{/if}
			{:else}
				<h2>Add Your Payment Address</h2>
				<p>Add a Lightning Address so you can receive funds when the buyer releases.</p>
				<PayoutForm
					type="release"
					{deal}
					{dealId}
					storedKey={keyForRole('seller')}
					{lndDown}
					getSignedAction={(action) => getSignedAction(action, 'seller')}
					getAuthenticatedUserId={() => getAuthenticatedUserId('seller')}
					{onDealUpdate}
				/>
			{/if}

			{#if isDualRole}
				<hr class="section-divider" />
			{/if}
		{/if}

		<!-- BUYER section: release button + refund address -->
		{#if userRole === 'buyer' || isDualRole}
			<h2>Release Funds</h2>
			<p>Satisfied with the deal? Release funds to the seller.</p>

			{#if deal.shipped_at && userRole === 'buyer' && !isDualRole}
				<div class="shipping-info-box">
					<div class="shipping-badge">Shipped</div>
					{#if deal.tracking_carrier || deal.tracking_number}
						<div class="shipping-details">
							{#if deal.tracking_carrier}<span class="shipping-detail"><strong>Carrier:</strong> {deal.tracking_carrier}</span>{/if}
							{#if deal.tracking_number}<span class="shipping-detail"><strong>Tracking:</strong> {deal.tracking_number}</span>{/if}
						</div>
					{/if}
					{#if deal.shipping_notes}<p class="shipping-notes">{deal.shipping_notes}</p>{/if}
					<p class="shipping-date">Shipped {new Date(deal.shipped_at).toLocaleString()}</p>
				</div>
			{/if}

			<div class="completion-buttons">
				{#if !deal.has_seller_payout_invoice}
					<div class="warning-box">
						<strong>Waiting for seller</strong>
						The seller hasn't added their payment address yet.{#if !isDualRole} Ask them to open this deal page.{/if}
					</div>
					<button class="btn primary" disabled>Release Funds</button>
				{:else if !deal.has_buyer_payout_invoice}
					<div class="warning-box">
						<strong>Your refund address is missing</strong>
						Add your Lightning Address so funds can be returned if there's a dispute.
					</div>
					<PayoutForm
						type="refund"
						{deal}
						{dealId}
						storedKey={keyForRole('buyer')}
						{lndDown}
						getSignedAction={(action) => getSignedAction(action, 'buyer')}
						getAuthenticatedUserId={() => getAuthenticatedUserId('buyer')}
						{onDealUpdate}
					/>
					<button class="btn primary" disabled>Release Funds</button>
				{:else}
					{@const recoveryCode = getSecretCodeForDeal(dealId)}
					{#if !recoveryCode}
						<div class="warning-box" style="margin-bottom: 0.75rem; font-size: 0.8rem;">
							<strong>Recovery code not found in this browser.</strong>
							If you need to release funds, use the browser that paid the invoice. Otherwise wait for timeout refund.
						</div>
					{:else}
						<!-- Recovery code stored in browser — no need to expose it in the UI -->
					{/if}
					{#if releaseInProgress}
						<div class="releasing-status">
							<div class="spinner-small"></div>
							<p class="releasing-text">Releasing funds to seller...</p>
						</div>
					{:else}
						<button class="btn primary" onclick={onRequestRelease} disabled={!recoveryCode}>
							Release Funds
						</button>
					{/if}
				{/if}
			</div>
		{/if}

		{#if userRole !== 'buyer' && userRole !== 'seller' && !isDualRole}
			<h2>Awaiting Resolution</h2>
			<p>The deal participants will resolve this transaction.</p>
		{/if}
	{:else}
		<h2>Awaiting Resolution</h2>
		<p>The deal participants will resolve this transaction.</p>
	{/if}
</div>

<style>
	@import '$lib/styles/deal-shared.css';

	.releasing-status { text-align: center; padding: 1rem 0; }
	.releasing-status .spinner-small { margin: 0 auto 0.75rem; }
	.releasing-text { color: var(--accent); font-size: 0.85rem; font-style: italic; }
	.section-divider { border: none; border-top: 1px solid #333; margin: 1.5rem 0; }
</style>
