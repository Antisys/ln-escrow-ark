<script>
	import { page } from '$app/state';
	import { walletStore } from '$lib/stores/wallet.js';
	import { getPublicKey, signMessage, sendToAddress } from '$lib/ark-wallet.js';
	import { getDeal, createEscrow, confirmFunding, releaseDeal, refundDeal, shipDeal, disputeDeal } from '$lib/api.js';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import WalletSetup from '$lib/components/WalletSetup.svelte';

	let ws = $derived($walletStore);
	let dealId = $derived(page.params.id);
	let deal = $state(null);
	let error = $state('');
	let loading = $state(false);
	let secretCode = $state('');
	let myRole = $derived(deal ? (deal.seller_pubkey === getPublicKey() ? 'seller' : deal.buyer_pubkey === getPublicKey() ? 'buyer' : 'viewer') : 'viewer');

	let pollInterval = null;

	$effect(() => {
		if (dealId && ws.initialized && !ws.locked) {
			loadDeal();
			pollInterval = setInterval(loadDeal, 5000);
			return () => clearInterval(pollInterval);
		}
	});

	async function loadDeal() {
		try { deal = await getDeal(dealId); } catch (e) { error = e.message; }
	}

	// ── Buyer: Fund the deal ──
	async function handleFund() {
		loading = true; error = '';
		try {
			const escrow = await createEscrow(dealId);
			const txid = await sendToAddress(escrow.address, deal.price_sats);
			await confirmFunding(dealId, txid, 0);
			await loadDeal();
		} catch (e) { error = e.message; }
		loading = false;
	}

	// ── Seller: Mark as shipped ──
	async function handleShip() {
		loading = true; error = '';
		try {
			await shipDeal(dealId, { carrier: '', tracking_number: '', notes: '' });
			await loadDeal();
		} catch (e) { error = e.message; }
		loading = false;
	}

	// ── Buyer: Release funds to seller ──
	async function handleRelease() {
		if (!secretCode) { error = 'Enter secret code'; return; }
		loading = true; error = '';
		try {
			const sig = await signMessage(secretCode);
			await releaseDeal(dealId, { secret_code: secretCode, buyer_signature: sig });
			await loadDeal();
		} catch (e) { error = e.message; }
		loading = false;
	}

	// ── Buyer: Request refund ──
	async function handleRefund() {
		loading = true; error = '';
		try {
			const sig = await signMessage('refund');
			await refundDeal(dealId, { buyer_signature: sig });
			await loadDeal();
		} catch (e) { error = e.message; }
		loading = false;
	}

	// ── Either: Open dispute ──
	async function handleDispute() {
		loading = true; error = '';
		try {
			const sig = await signMessage('dispute');
			await disputeDeal(dealId, { disputed_by: getPublicKey(), reason: 'Dispute opened', signature: sig });
			await loadDeal();
		} catch (e) { error = e.message; }
		loading = false;
	}

	function copyLink() {
		const url = `${window.location.origin}/join/${deal.deal_link_token}`;
		navigator.clipboard.writeText(url);
	}
</script>

{#if !ws.initialized || ws.locked}
	<WalletSetup />
{:else if !deal}
	<p>{error || 'Loading deal...'}</p>
{:else}
	<div class="deal">
		<div class="header">
			<h2>{deal.title}</h2>
			<StatusBadge status={deal.status} />
		</div>

		{#if deal.description}<p class="desc">{deal.description}</p>{/if}

		<div class="info-grid">
			<div class="info-item">
				<span class="label">Price</span>
				<span class="value">{deal.price_sats?.toLocaleString()} sats</span>
			</div>
			<div class="info-item">
				<span class="label">Your role</span>
				<span class="value role-{myRole}">{myRole}</span>
			</div>
			<div class="info-item">
				<span class="label">Timeout</span>
				<span class="value">{deal.timeout_hours}h</span>
			</div>
		</div>

		<!-- Share link (seller, before buyer joins) -->
		{#if myRole === 'seller' && !deal.buyer_pubkey}
			<div class="action-card">
				<p>Share this link with the buyer:</p>
				<button onclick={copyLink} class="secondary">Copy Deal Link</button>
			</div>
		{/if}

		<!-- Fund (buyer, deal active but not funded) -->
		{#if myRole === 'buyer' && ['active', 'pending'].includes(deal.status) && deal.buyer_pubkey}
			<div class="action-card">
				<h3>Fund Escrow</h3>
				<p>Send {deal.price_sats?.toLocaleString()} sats to the escrow VTXO.</p>
				<button onclick={handleFund} disabled={loading}>{loading ? 'Funding...' : 'Fund Deal'}</button>
			</div>
		{/if}

		<!-- Ship (seller, deal funded) -->
		{#if myRole === 'seller' && deal.status === 'funded'}
			<div class="action-card">
				<h3>Mark as Shipped</h3>
				<button onclick={handleShip} disabled={loading}>{loading ? 'Updating...' : 'Mark Shipped'}</button>
			</div>
		{/if}

		<!-- Release (buyer, deal funded or shipped) -->
		{#if myRole === 'buyer' && ['funded', 'shipped'].includes(deal.status)}
			<div class="action-card">
				<h3>Confirm Delivery</h3>
				<p>Release funds to the seller.</p>
				<input type="text" bind:value={secretCode} placeholder="Enter secret code" />
				<button onclick={handleRelease} disabled={loading}>{loading ? 'Releasing...' : 'Release Funds'}</button>
			</div>
		{/if}

		<!-- Dispute (either party, deal funded or shipped) -->
		{#if (myRole === 'buyer' || myRole === 'seller') && ['funded', 'shipped'].includes(deal.status)}
			<div class="action-card dispute">
				<button onclick={handleDispute} disabled={loading} class="danger">{loading ? 'Opening...' : 'Open Dispute'}</button>
			</div>
		{/if}

		<!-- Refund (buyer, deal funded, no shipping) -->
		{#if myRole === 'buyer' && deal.status === 'funded'}
			<div class="action-card">
				<button onclick={handleRefund} disabled={loading} class="secondary">{loading ? 'Refunding...' : 'Request Refund'}</button>
			</div>
		{/if}

		<!-- Completed -->
		{#if ['released', 'completed', 'refunded'].includes(deal.status)}
			<div class="action-card done">
				<h3>{deal.status === 'refunded' ? 'Refunded' : 'Completed'}</h3>
				<p>This deal has been {deal.status}.</p>
			</div>
		{/if}

		{#if error}<p class="error">{error}</p>{/if}
	</div>
{/if}

<style>
	.deal { max-width: 500px; margin: 1rem auto; }
	.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
	h2 { color: #f7931a; margin: 0; }
	.desc { color: #888; }
	.info-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.75rem; background: #151515; border-radius: 12px; padding: 1rem; margin: 1rem 0; }
	.info-item { text-align: center; }
	.label { display: block; color: #666; font-size: 0.75rem; text-transform: uppercase; }
	.value { font-weight: bold; font-size: 1.1rem; }
	.role-seller { color: #9b59b6; }
	.role-buyer { color: #3498db; }
	.role-viewer { color: #888; }
	.action-card { background: #151515; border: 1px solid #222; border-radius: 12px; padding: 1.25rem; margin: 1rem 0; text-align: center; }
	.action-card h3 { margin: 0 0 0.5rem; color: #eee; }
	.action-card p { color: #888; font-size: 0.9rem; margin: 0.5rem 0; }
	.action-card input { width: 100%; padding: 0.75rem; border: 1px solid #333; border-radius: 8px; background: #1a1a1a; color: #fff; margin: 0.5rem 0; box-sizing: border-box; }
	button { width: 100%; padding: 0.75rem; border: none; border-radius: 8px; font-weight: bold; font-size: 1rem; cursor: pointer; }
	button:not(.secondary):not(.danger) { background: #f7931a; color: #000; }
	button.secondary { background: #333; color: #ccc; }
	button.danger { background: #c0392b; color: #fff; }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	.dispute { border-color: #c0392b33; }
	.done { border-color: #2ecc7133; }
	.error { color: #ff4444; text-align: center; }
</style>
