<script>
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { onMount, onDestroy } from 'svelte';
	import { dealAuths, getAuthForDeal } from '$lib/stores/vault.js';
	import { navAuth, clearNavAuth } from '$lib/stores/nav.js';
	import { getDealByToken } from '$lib/api.js';
	import { getVisitorId, signAction } from '$lib/crypto.js';
	import { validateLightningAddress, submitPayoutInvoice } from '$lib/api/payout.js';
	import { submitRefundInvoice } from '$lib/api/refund.js';
	import LnurlSign from '$lib/components/LnurlSign.svelte';

	let token = $derived($page.params.token);
	let deal = $state(null);
	let loading = $state(true);
	let error = $state('');
	let step = $state('view'); // view, address, sign, done
	let lightningAddress = $state('');
	let addressError = $state('');
	let addressLoading = $state(false);

	onMount(async () => {
		await loadDeal();
	});

	onDestroy(() => {
		clearNavAuth();
	});

	// Determine the join role based on who created the deal
	let joinRole = $derived(deal?.creator_role === 'buyer' ? 'seller' : 'buyer');

	// Update nav auth when deal loads — only show the correct join button
	$effect(() => {
		if (!deal) {
			clearNavAuth();
			return;
		}
		// Force the nav to only show the determined join role
		navAuth.set({
			role: null,
			deal: {
				...deal,
				// Pretend the other role is already filled so nav only shows one button
				seller_linking_pubkey: joinRole === 'seller' ? null : 'filled',
				buyer_linking_pubkey: joinRole === 'buyer' ? null : 'filled',
			},
			onJoinSeller: joinRole === 'seller' ? () => { step = 'address'; } : () => {},
			onJoinBuyer: joinRole === 'buyer' ? () => { step = 'address'; } : () => {}
		});
	});

	async function loadDeal() {
		loading = true;
		error = '';
		try {
			deal = await getDealByToken(token);

			// Check if user already signed this deal AS THE JOIN ROLE
			// (don't redirect if they signed as the other role — dual-role scenario)
			const auth = getAuthForDeal(deal.deal_id);
			const thisJoinRole = deal.creator_role === 'buyer' ? 'seller' : 'buyer';
			if (auth && auth.role === thisJoinRole) {
				goto(`/deal/${deal.deal_id}`);
				return;
			}

		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	function handleJoin() {
		step = 'address';
	}

	async function handleValidateAddress() {
		if (!lightningAddress.trim()) {
			addressError = 'Please enter your Lightning Address';
			return;
		}
		addressLoading = true;
		addressError = '';
		try {
			await validateLightningAddress(lightningAddress.trim(), deal.price_sats);
			step = 'sign';
		} catch (e) {
			addressError = e.message;
		} finally {
			addressLoading = false;
		}
	}

	async function handleSignSuccess(result) {
		// Save the Lightning Address using the newly-stored key
		try {
			const { signature, timestamp } = signAction(result.ephemeralKey.privateKey, result.dealId,
				joinRole === 'seller' ? 'submit-payout-invoice' : 'submit-refund-invoice');
			const userId = getVisitorId();
			if (joinRole === 'seller') {
				await submitPayoutInvoice(result.dealId, userId, lightningAddress.trim(), signature, timestamp);
			} else {
				await submitRefundInvoice(result.dealId, userId, lightningAddress.trim(), signature, timestamp);
			}
		} catch (e) {
			// Silently ignore — address save is best-effort during join
		}
		step = 'done';
		setTimeout(() => {
			goto(`/deal/${result.dealId}`);
		}, 1500);
	}
</script>

<svelte:head>
	<title>Join Deal - trustMeBro-ARK</title>
</svelte:head>

<div class="join-page">
	{#if loading}
		<div class="loading-card">
			<p>Loading deal...</p>
		</div>
	{:else if error && !deal}
		<div class="error-card">
			<h2>Error</h2>
			<p>{error}</p>
			<a href="/">Back to Home</a>
		</div>
	{:else if deal}
		<div class="deal-card">
			<div class="deal-header">
				<h1>{deal.title}</h1>
				<span class="status" class:pending={deal.status === 'pending'}>{deal.status}</span>
			</div>

			{#if deal.description}
				<p class="description">{deal.description}</p>
			{/if}

			<div class="deal-details">
				<div class="detail">
					<span class="label">Price</span>
					<span class="value price">{deal.price_sats?.toLocaleString() || deal.price} sats</span>
				</div>
				<div class="detail">
					<span class="label">Created by</span>
					<span class="value">{deal.creator_role === 'seller' ? 'Seller' : 'Buyer'}</span>
				</div>
			</div>

			<div class="terms-section">
				<h3>Deal Terms</h3>
				<div class="terms-details">
					<div class="term">
						<span class="term-label">Timelock</span>
						<span class="term-value">
							{#if deal.timeout_hours >= 24}
								{Math.round(deal.timeout_hours / 24)} days
							{:else}
								{deal.timeout_hours} hours
							{/if}
						</span>
					</div>
					<div class="term">
						<span class="term-label">After timeout</span>
						<span class="term-value" class:warning-text={deal.timeout_action === 'release'}>
							{deal.timeout_action === 'release' ? 'Funds go to Seller' : 'Funds refunded to Buyer'}
						</span>
					</div>
				</div>
				<p class="terms-note">
					{#if joinRole === 'buyer'}
						{#if deal.timeout_action === 'release'}
							As buyer, you can file a dispute before the timeout to prevent automatic release to seller.
						{:else}
							As buyer, if no action is taken, you will automatically receive a refund after timeout.
						{/if}
					{:else}
						{#if deal.timeout_action === 'release'}
							As seller, if no dispute is filed, you will receive funds automatically after timeout.
						{:else}
							As seller, funds will be refunded to the buyer after timeout unless you file a dispute.
						{/if}
					{/if}
				</p>
			</div>

			{#if step === 'done'}
				<div class="success-section">
					<span class="checkmark">✓</span>
					<p>Successfully joined!</p>
					<p class="hint">Redirecting to deal page...</p>
				</div>
			{:else if step === 'address'}
				<div class="address-section">
					<h2>{joinRole === 'seller' ? 'Join by entering your Lightning Address' : 'Your Lightning Address'}</h2>
					<p class="address-hint">
						{joinRole === 'seller'
							? `Where should we send your ${deal.price_sats?.toLocaleString()} sats when the buyer releases?`
							: `Where should we refund your ${deal.price_sats?.toLocaleString()} sats if needed?`}
					</p>
					<div class="address-form">
						<input
							type="text"
							bind:value={lightningAddress}
							placeholder="you@walletofsatoshi.com"
							class="address-input"
							onkeydown={(e) => e.key === 'Enter' && handleValidateAddress()}
						/>
						<p class="wallet-hint">Wallets with Lightning Address: Wallet of Satoshi, Phoenix, Alby, Blink, Coinos</p>
						{#if addressError}
							<p class="error">{addressError}</p>
						{/if}
						<button class="btn primary" onclick={handleValidateAddress} disabled={addressLoading}>
							{addressLoading ? 'Validating...' : 'Continue'}
						</button>
						<button class="btn secondary" onclick={() => step = 'view'}>Back</button>
					</div>
				</div>
			{:else if step === 'sign'}
				<div class="sign-section">
					<h2>Join as {joinRole === 'seller' ? 'Seller' : 'Buyer'}</h2>
					{#if joinRole === 'buyer'}
						<p class="wallet-hint">This doesn't have to be the same wallet as your Lightning Address.</p>
					{/if}

					<LnurlSign
						dealToken={token}
						role={joinRole}
						onSuccess={handleSignSuccess}
					/>

					<button class="btn secondary" onclick={() => step = 'view'}>Back</button>
				</div>
			{:else if (joinRole === 'buyer' && deal.buyer_id) || (joinRole === 'seller' && deal.seller_id)}
				<div class="already-joined">
					<p>This deal already has a {joinRole}.</p>
					<a href="/deal/{deal.deal_id}" class="btn primary">View Deal</a>
				</div>
			{:else}
				{#if joinRole === 'seller'}
					<!-- Seller goes straight to address input -->
					<div class="address-section">
						<h2>Join by entering your Lightning Address</h2>
						<p class="address-hint">Where should we send your {deal.price_sats?.toLocaleString()} sats when the buyer releases?</p>
						<div class="address-form">
							<input
								type="text"
								bind:value={lightningAddress}
								placeholder="you@walletofsatoshi.com"
								class="address-input"
								onkeydown={(e) => e.key === 'Enter' && handleValidateAddress()}
							/>
							<p class="wallet-hint">Wallets with Lightning Address: Wallet of Satoshi, Phoenix, Alby, Blink, Coinos</p>
							{#if addressError}
								<p class="error">{addressError}</p>
							{/if}
							<button class="btn primary" onclick={handleValidateAddress} disabled={addressLoading}>
								{addressLoading ? 'Validating...' : 'Continue'}
							</button>
						</div>
					</div>
				{:else}
					<div class="join-section">
						<h2>Join as Buyer</h2>

						<div class="steps-preview">
							<div class="step-item">
								<span class="step-num">1</span>
								<span>Enter your Lightning Address</span>
							</div>
							<div class="step-item">
								<span class="step-num">2</span>
								<span>Scan QR code with your Lightning wallet</span>
							</div>
							<div class="step-item">
								<span class="step-num">3</span>
								<span>Pay the Lightning invoice ({deal.price_sats?.toLocaleString()} sats)</span>
							</div>
						</div>

						{#if error}
							<p class="error">{error}</p>
						{/if}

						<button class="btn primary" onclick={handleJoin}>
							Join Deal
						</button>
					</div>
				{/if}
			{/if}
		</div>
	{/if}
</div>

<style>
	.join-page {
		max-width: 600px;
		width: 100%;
		margin: 0 auto;
	}

	.loading-card, .error-card {
		background: var(--surface);
		padding: 2rem;
		border-radius: 8px;
		border: 1px solid var(--border);
		text-align: center;
	}

	.error-card {
		border-color: var(--error);
	}

	.error-card h2 {
		color: var(--error);
		margin-bottom: 1rem;
	}

	.error-card a {
		display: inline-block;
		margin-top: 1rem;
	}

	.deal-card {
		background: var(--surface);
		padding: 2rem;
		border-radius: 8px;
		border: 1px solid var(--border);
	}

	.deal-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		margin-bottom: 1rem;
	}

	h1 {
		color: var(--text);
		font-size: 1.5rem;
	}

	h2 {
		color: var(--accent);
		margin-bottom: 0.5rem;
	}

	.status {
		padding: 0.25rem 0.75rem;
		border-radius: 4px;
		font-size: 0.875rem;
		text-transform: uppercase;
		background: var(--border);
		color: var(--text-muted);
	}

	.status.pending {
		background: var(--orange-bg);
		color: var(--orange);
	}

	.description {
		color: var(--text-muted);
		margin-bottom: 1.5rem;
	}

	.deal-details {
		display: grid;
		gap: 1rem;
		margin-bottom: 1.5rem;
		padding: 1rem;
		background: var(--bg);
		border-radius: 4px;
	}

	.detail {
		display: flex;
		justify-content: space-between;
	}

	.label {
		color: var(--text-dim);
	}

	.value {
		color: var(--text);
	}

	.value.price {
		color: var(--orange);
		font-weight: 600;
	}

	.terms-section {
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 1rem;
		margin-bottom: 1.5rem;
	}

	.terms-section h3 {
		color: var(--text);
		font-size: 0.9rem;
		margin: 0 0 0.75rem 0;
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.terms-details {
		display: grid;
		gap: 0.5rem;
		margin-bottom: 0.75rem;
	}

	.term {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.term-label {
		color: var(--text-dim);
		font-size: 0.875rem;
	}

	.term-value {
		color: var(--accent);
		font-weight: 500;
	}

	.term-value.warning-text {
		color: var(--orange);
	}

	.terms-note {
		font-size: 0.8rem;
		color: var(--text-muted);
		margin: 0;
		padding-top: 0.75rem;
		border-top: 1px solid var(--surface);
	}

	.join-section {
		border-top: 1px solid var(--border);
		padding-top: 1.5rem;
		margin-top: 1.5rem;
	}

	.hint {
		color: var(--text-muted);
		margin-bottom: 1rem;
		font-size: 0.875rem;
	}

	.error {
		color: var(--error);
		margin-bottom: 1rem;
	}

	.btn {
		display: inline-block;
		padding: 0.75rem 1.5rem;
		border-radius: 4px;
		border: none;
		font-size: 1rem;
		cursor: pointer;
		text-decoration: none;
	}

	.btn.primary {
		background: var(--accent);
		color: var(--bg);
		font-weight: 600;
	}

	.btn.primary:hover:not(:disabled) {
		background: var(--accent-hover);
	}

	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.already-joined {
		border-top: 1px solid var(--border);
		padding-top: 1.5rem;
		margin-top: 1.5rem;
		text-align: center;
	}

	.already-joined p {
		color: var(--text-muted);
		margin-bottom: 1rem;
	}

	.sign-section {
		border-top: 1px solid var(--border);
		padding-top: 1.5rem;
		margin-top: 1.5rem;
		text-align: center;
	}

	.btn.secondary {
		background: var(--border);
		color: var(--text);
		margin-top: 1rem;
	}

	.success-section {
		border-top: 1px solid var(--success);
		padding-top: 1.5rem;
		margin-top: 1.5rem;
		text-align: center;
		color: var(--success);
	}

	.checkmark {
		font-size: 3rem;
		display: block;
		margin-bottom: 0.5rem;
	}

	.steps-preview {
		background: var(--bg);
		border-radius: 8px;
		padding: 1rem;
		margin-bottom: 1.5rem;
	}

	.step-item {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.5rem 0;
		color: var(--text-muted);
		font-size: 0.9rem;
	}

	.step-item:not(:last-child) {
		border-bottom: 1px solid var(--surface);
	}

	.step-num {
		width: 24px;
		height: 24px;
		border-radius: 50%;
		background: var(--border);
		color: var(--accent);
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 0.75rem;
		font-weight: 600;
		flex-shrink: 0;
	}

	.address-section {
		border-top: 1px solid var(--border);
		padding-top: 1.5rem;
		margin-top: 1.5rem;
	}

	.address-hint {
		color: var(--text-muted);
		font-size: 0.95rem;
		margin-bottom: 1.25rem;
	}

	.address-form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.address-input {
		width: 100%;
		padding: 0.75rem;
		background: var(--bg);
		border: 1px solid var(--border-hover);
		border-radius: 4px;
		color: var(--text);
		font-size: 1rem;
		box-sizing: border-box;
	}

	.wallet-hint {
		color: var(--text-dim);
		font-size: 0.8rem;
		margin: 0;
	}
</style>
