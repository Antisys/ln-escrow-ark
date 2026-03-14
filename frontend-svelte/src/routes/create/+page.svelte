<script>
	import { onMount, onDestroy } from 'svelte';
	import { userName } from '$lib/stores/vault.js';
	import { createDeal, getLimits, getSystemStatus } from '$lib/api.js';
	import { getVisitorId, signAction } from '$lib/crypto.js';
	import { validateLightningAddress, submitPayoutInvoice } from '$lib/api/payout.js';
	import { submitRefundInvoice } from '$lib/api/refund.js';
	import { formatSatsCompact } from '$lib/utils/format.js';
	import LnurlSign from '$lib/components/LnurlSign.svelte';

	let role = $state('seller');
	let title = $state('');
	let description = $state('');
	let price = $state('');
	let recoveryContact = $state('');
	let lightningAddress = $state('');
	let addressError = $state('');
	let addressLoading = $state(false);
	let timeoutHours = $state(168); // 7 days default
	let timeoutAction = $state('release'); // 'release' = seller gets funds (default), 'refund' = buyer gets funds

	function formatTimeout(hours) {
		if (hours < 24) return `${hours}h`;
		const days = Math.round(hours / 24);
		return `${days} day${days !== 1 ? 's' : ''}`;
	}

	function handleRoleChange(newRole) {
		role = newRole;
		// Default timeout action based on role
		// Seller expects payment → release after timeout
		// Buyer wants protection → refund after timeout
		timeoutAction = newRole === 'seller' ? 'release' : 'refund';
	}

	let loading = $state(false);
	let error = $state('');
	let createdDeal = $state(null);
	let step = $state('form'); // form, address, sign, done

	// Amount limits
	let limits = $state({ min_sats: 1, max_sats: 10000000 });

	// System status (LND + Esplora)
	let systemStatus = $state(null);
	let statusInterval = null;

	onMount(async () => {
		const [limitsResult, statusResult] = await Promise.allSettled([
			getLimits(),
			getSystemStatus()
		]);
		if (limitsResult.status === 'fulfilled') limits = limitsResult.value;
		if (statusResult.status === 'fulfilled') systemStatus = statusResult.value;
		// Auto-retry system status every 30s so banner auto-dismisses on recovery
		statusInterval = setInterval(() => {
			getSystemStatus().then(s => systemStatus = s).catch(() => {});
		}, 30000);
	});

	onDestroy(() => {
		if (statusInterval) clearInterval(statusInterval);
	});

	async function handleCreate() {
		if (!title || !price) {
			error = 'Please fill in title and price';
			return;
		}

		const priceNum = parseInt(price, 10);
		if (priceNum < limits.min_sats) {
			error = `Minimum amount is ${formatSatsCompact(limits.min_sats)}`;
			return;
		}
		if (priceNum > limits.max_sats) {
			error = `Maximum amount is ${formatSatsCompact(limits.max_sats)}`;
			return;
		}

		loading = true;
		error = '';

		try {
			const visitorId = getVisitorId();
			const dealData = {
				title,
				description,
				price_sats: parseInt(price, 10),
				timeout_hours: Math.max(1, Math.round(timeoutHours)),
				timeout_action: timeoutAction,
				creator_role: role,
				seller_id: role === 'seller' ? visitorId : null,
				buyer_id: role === 'buyer' ? visitorId : null,
				seller_name: role === 'seller' ? ($userName || null) : null,
				buyer_name: role === 'buyer' ? ($userName || null) : null,
				recovery_contact: recoveryContact || null
			};

			createdDeal = await createDeal(dealData);
			step = 'address';
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	async function handleValidateAddress() {
		if (!lightningAddress.trim()) {
			addressError = 'Please enter your Lightning Address';
			return;
		}
		addressLoading = true;
		addressError = '';
		try {
			await validateLightningAddress(lightningAddress.trim(), parseInt(price, 10));
			step = 'sign';
		} catch (e) {
			addressError = e.message;
		} finally {
			addressLoading = false;
		}
	}

	async function handleSignSuccess(result) {
		// After auth, save the Lightning Address using the newly-stored key
		// Use result.role from backend (not the outer `role` state which user may have toggled)
		const confirmedRole = result.role || role;
		try {
			const { signature, timestamp } = signAction(result.ephemeralKey.privateKey, result.dealId,
				confirmedRole === 'seller' ? 'submit-payout-invoice' : 'submit-refund-invoice');
			const userId = getVisitorId();
			if (confirmedRole === 'seller') {
				await submitPayoutInvoice(result.dealId, userId, lightningAddress.trim(), signature, timestamp);
			} else {
				await submitRefundInvoice(result.dealId, userId, lightningAddress.trim(), signature, timestamp);
			}
		} catch (e) {
			// Non-fatal — user can still set it on the deal page
		}
		window.location.href = `/deal/${result.dealId}`;
	}

</script>

<svelte:head>
	<title>Create Deal - trustMeBro-ARK</title>
</svelte:head>

<div class="create-page">
	{#if step === 'address'}
		<div class="sign-card">
			<h2>Your Lightning Address</h2>
			<p class="address-hint">
				{role === 'seller'
					? `Where should we send your ${parseInt(price, 10)?.toLocaleString()} sats when the buyer releases?`
					: `Where should we refund your ${parseInt(price, 10)?.toLocaleString()} sats if needed?`}
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
				<button class="btn secondary" onclick={() => step = 'form'}>Back</button>
			</div>
		</div>
	{:else if step === 'sign'}
		<div class="sign-card">
			<h2>Sign to Create Deal</h2>
			<p class="wallet-hint">This doesn't have to be the same wallet as your Lightning Address.</p>

			<LnurlSign
				dealToken={createdDeal.deal_link_token}
				role={role}
				onSuccess={handleSignSuccess}
			/>
		</div>
	{:else}
		<form onsubmit={(e) => { e.preventDefault(); handleCreate(); }}>
			<div class="form-header">
				<h1>Create New Deal as <span class="role-tag" class:buyer={role === 'buyer'}>{role === 'seller' ? 'Seller' : 'Buyer'}</span>
				<button type="button" class="role-swap" onclick={() => handleRoleChange(role === 'seller' ? 'buyer' : 'seller')} title="Switch role">&#x21C4;</button></h1>
			</div>

			<div class="field">
				<label for="title">Title</label>
				<input id="title" type="text" bind:value={title} placeholder="What is this deal for?" />
			</div>

			<div class="field">
				<label for="description">Description (optional)</label>
				<textarea id="description" bind:value={description} placeholder="Additional details..." rows="3"></textarea>
			</div>

			<div class="field">
				<label for="price">Price (sats)</label>
				<input
					id="price"
					type="number"
					step="1"
					min={limits.min_sats}
					max={limits.max_sats}
					bind:value={price}
					placeholder={limits.min_sats.toString()}
				/>
				<p class="hint">Min: {formatSatsCompact(limits.min_sats)} / Max: {formatSatsCompact(limits.max_sats)}</p>

				{#if price && parseInt(price) > 0}
					{@const priceNum = parseInt(price)}
					{@const servicePct = limits.service_fee_percent ?? 1.0}
					{@const serviceFeeSats = Math.floor(priceNum * (servicePct / 100))}
					{@const totalSats = priceNum + serviceFeeSats}
					<div class="fee-breakdown">
						<div class="fee-row"><span>{priceNum.toLocaleString()} sats</span><span class="fee-label">deal amount</span></div>
						<div class="fee-row"><span>+ {serviceFeeSats.toLocaleString()} sats</span><span class="fee-label">service fee ({servicePct}%)</span></div>
						<div class="fee-row fee-total"><span>= {totalSats.toLocaleString()} sats</span><span class="fee-label">total</span></div>
					</div>
				{/if}
			</div>

			<div class="field">
				<label for="timelock-slider">Timelock Recovery: <strong>{formatTimeout(timeoutHours)}</strong></label>
				<input
					id="timelock-slider"
					type="range"
					class="timeout-slider"
					min="1"
					max="720"
					step="1"
					bind:value={timeoutHours}
				/>
				<div class="slider-labels">
					<span>1h</span>
					<span style="position:absolute;left:23%">7d</span>
					<span>30d</span>
				</div>
			</div>

			<div class="field">
				<p class="timeout-text">After timeout, funds go to
					<span class="timeout-tag" class:refund={timeoutAction === 'refund'} class:release={timeoutAction === 'release'}>{timeoutAction === 'release' ? 'Seller' : 'Buyer'}</span>
					<button type="button" class="role-swap" onclick={() => timeoutAction = timeoutAction === 'release' ? 'refund' : 'release'} title="Switch timeout action">&#x21C4;</button>
				</p>
				<p class="hint">
					{timeoutAction === 'release'
						? 'Seller can claim funds automatically. Buyer can dispute before timeout.'
						: 'Buyer can recover funds automatically. Seller can dispute before timeout.'}
				</p>
			</div>

		{#if systemStatus && !systemStatus.operational}
				<div class="system-warning">
					<strong>Service unavailable</strong>
					<p>Lightning node is unreachable. Deal creation is temporarily disabled.</p>
				</div>
			{/if}

			{#if error}
				<p class="error">{error}</p>
			{/if}

			<button type="submit" class="btn primary" disabled={loading || (systemStatus && !systemStatus.operational)}>
				{loading ? 'Creating...' : 'Create Deal'}
			</button>
		</form>
	{/if}
</div>

<style>
	.create-page {
		max-width: 600px;
		width: 100%;
		margin: 0 auto;
	}

	h1 {
		color: var(--text);
		margin: 0;
		font-size: 1.3rem;
		font-weight: 400;
	}

	.form-header {
		margin-bottom: 1.5rem;
	}

	h2 {
		color: var(--success);
		margin-bottom: 1rem;
	}

	form {
		background: var(--surface);
		padding: 2rem;
		border-radius: 8px;
		border: 1px solid var(--border);
	}

	.field {
		margin-bottom: 1.5rem;
	}

	.field label {
		display: block;
		margin-bottom: 0.5rem;
		color: var(--text-muted);
	}

	.field input:not([type="range"]), .field textarea {
		width: 100%;
		padding: 0.75rem;
		background: var(--bg);
		border: 1px solid var(--border-hover);
		border-radius: 4px;
		color: var(--text);
		font-size: 1rem;
	}

	.field textarea {
		resize: vertical;
	}

	.hint {
		margin-top: 0.25rem;
		font-size: 0.875rem;
		color: var(--text-dim);
	}

	.fee-breakdown {
		margin-top: 0.75rem;
		padding: 0.75rem;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 0.85rem;
		font-family: monospace;
	}

	.fee-row {
		display: flex;
		justify-content: space-between;
		padding: 0.2rem 0;
		color: var(--text-muted);
	}

	.fee-label {
		color: var(--text-dim);
	}

	.fee-row.fee-total {
		border-top: 1px solid var(--border);
		margin-top: 0.25rem;
		padding-top: 0.4rem;
		color: var(--accent);
		font-weight: 600;
	}

	.role-tag {
		background: var(--accent);
		color: var(--bg);
		padding: 0.15rem 0.5rem;
		border-radius: 4px;
		font-weight: 600;
		font-size: 1.3rem;
	}

	.role-tag.buyer {
		background: var(--orange);
	}

	.role-swap {
		background: none;
		border: 1px solid var(--border-hover);
		border-radius: 4px;
		color: var(--text-muted);
		cursor: pointer;
		padding: 0.1rem 0.4rem;
		font-size: 0.9rem;
		line-height: 1;
		vertical-align: middle;
		margin-left: 0.25rem;
	}

	.role-swap:hover {
		color: var(--text);
		border-color: var(--text-muted);
	}

	.timeout-slider {
		-webkit-appearance: none;
		appearance: none;
		width: 100%;
		height: 2px;
		background: #555;
		border: none;
		border-radius: 0;
		outline: none;
		margin: 1rem 0 0.5rem;
		padding: 0;
		cursor: pointer;
	}

	.timeout-slider::-webkit-slider-thumb {
		-webkit-appearance: none;
		width: 18px;
		height: 18px;
		background: var(--accent);
		border-radius: 50%;
		cursor: pointer;
	}

	.timeout-slider::-moz-range-thumb {
		width: 18px;
		height: 18px;
		background: var(--accent);
		border-radius: 50%;
		cursor: pointer;
		border: none;
	}

	.slider-labels {
		display: flex;
		justify-content: space-between;
		position: relative;
		color: var(--text-muted);
		font-size: 0.75rem;
	}

	.timeout-text {
		color: var(--text-muted);
		margin: 0;
		font-size: 0.95rem;
	}

	.timeout-tag {
		padding: 0.1rem 0.5rem;
		border-radius: 4px;
		font-weight: 600;
	}

	.timeout-tag.release {
		background: var(--accent);
		color: var(--bg);
	}

	.timeout-tag.refund {
		background: var(--orange);
		color: var(--bg);
	}

	.btn {
		display: block;
		width: 100%;
		padding: 0.75rem 1.5rem;
		border-radius: 4px;
		border: none;
		font-size: 1rem;
		cursor: pointer;
		text-align: center;
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

	.system-warning {
		background: var(--orange-bg);
		border: 1px solid var(--orange);
		border-radius: 4px;
		padding: 0.75rem 1rem;
		margin-bottom: 1rem;
		color: var(--orange);
	}

	.system-warning strong {
		display: block;
		margin-bottom: 0.25rem;
	}

	.system-warning p {
		margin: 0;
		font-size: 0.875rem;
		color: var(--warning);
	}

	.error {
		color: var(--error);
		margin-bottom: 1rem;
	}

	.sign-card {
		background: var(--surface);
		padding: 2rem;
		border-radius: 8px;
		border: 1px solid var(--border);
		text-align: center;
	}

	.sign-card h2 {
		color: var(--accent);
	}

	.btn.secondary {
		background: var(--border);
		color: var(--text);
		margin-top: 1rem;
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
