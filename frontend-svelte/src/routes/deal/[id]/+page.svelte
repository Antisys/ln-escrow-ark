<script>
	import { page } from '$app/state';
	import { walletStore } from '$lib/stores/wallet.js';
	import { getPublicKey, signMessage, sendToAddress, sha256Hash, isUnlocked } from '$lib/ark-wallet.js';
	import { getDeal, createEscrow, confirmFunding, releaseDeal, refundDeal, shipDeal, disputeDeal } from '$lib/api.js';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import WalletSetup from '$lib/components/WalletSetup.svelte';

	let ws = $derived($walletStore);
	let dealId = $derived(page.params.id);
	let deal = $state(null);
	let error = $state('');
	let success = $state('');
	let loading = $state(false);
	let secretCode = $state('');
	let escrowAddress = $state('');
	let escrowCreated = $state(false);

	// Role detection: match pubkey prefix (seller_id/buyer_id are pubkey prefixes)
	let myRole = $derived(() => {
		if (!deal || !isUnlocked()) return 'viewer';
		const myPub = getPublicKey();
		if (deal.seller_pubkey === myPub || deal.seller_id === myPub.slice(0, 16)) return 'seller';
		if (deal.buyer_pubkey === myPub || deal.buyer_id === myPub.slice(0, 16)) return 'buyer';
		return 'viewer';
	});

	let pollInterval = null;

	$effect(() => {
		if (dealId && ws.initialized && !ws.locked) {
			loadDeal();
			pollInterval = setInterval(loadDeal, 5000);
			return () => clearInterval(pollInterval);
		}
	});

	async function loadDeal() {
		try {
			deal = await getDeal(dealId);
			if (deal.ark_escrow_address) {
				escrowAddress = deal.ark_escrow_address;
				escrowCreated = true;
			}
		} catch (e) {
			if (!error) error = e.message;
		}
	}

	// ── Buyer: Create escrow and show funding address ──
	async function handleCreateEscrow() {
		loading = true; error = ''; success = '';
		try {
			const result = await createEscrow(dealId, getPublicKey());
			escrowAddress = result.escrow_address;
			escrowCreated = true;
			success = 'Escrow created! Send funds to the address below.';
			await loadDeal();
		} catch (e) { error = e.message; }
		loading = false;
	}

	// ── Buyer: Try to fund via Ark SDK wallet ──
	async function handleFundViaWallet() {
		loading = true; error = ''; success = '';
		try {
			const txid = await sendToAddress(escrowAddress, deal.price_sats);
			await confirmFunding(dealId, txid, 0);
			success = 'Deal funded!';
			await loadDeal();
		} catch (e) {
			error = `Wallet send failed: ${e.message}. You can fund manually via CLI.`;
		}
		loading = false;
	}

	// ── Buyer: Manually confirm funding (for CLI/regtest) ──
	let manualTxid = $state('');
	async function handleManualFund() {
		if (!manualTxid) { error = 'Enter VTXO txid'; return; }
		loading = true; error = ''; success = '';
		try {
			await confirmFunding(dealId, manualTxid, 0);
			success = 'Funding confirmed!';
			await loadDeal();
		} catch (e) { error = e.message; }
		loading = false;
	}

	// ── Seller: Mark as shipped ──
	async function handleShip() {
		loading = true; error = ''; success = '';
		try {
			const sig = await signMessage('ship');
			await shipDeal(dealId, { seller_id: getPublicKey().slice(0, 16), signature: sig });
			success = 'Marked as shipped!';
			await loadDeal();
		} catch (e) { error = e.message; }
		loading = false;
	}

	// ── Buyer: Release funds to seller ──
	async function handleRelease() {
		if (!secretCode) { error = 'Enter your secret code'; return; }
		loading = true; error = ''; success = '';
		try {
			const sig = await signMessage(secretCode);
			await releaseDeal(dealId, {
				buyer_id: getPublicKey().slice(0, 16),
				secret_code: secretCode,
				buyer_escrow_signature: sig,
			});
			success = 'Funds released to seller!';
			await loadDeal();
		} catch (e) { error = e.message; }
		loading = false;
	}

	// ── Buyer: Request refund ──
	async function handleRefund() {
		loading = true; error = ''; success = '';
		try {
			await refundDeal(dealId, { user_id: getPublicKey().slice(0, 16) });
			success = 'Refund requested';
			await loadDeal();
		} catch (e) { error = e.message; }
		loading = false;
	}

	// ── Either: Open dispute ──
	async function handleDispute() {
		loading = true; error = ''; success = '';
		try {
			const sig = await signMessage('dispute');
			await disputeDeal(dealId, { user_id: getPublicKey().slice(0, 16), reason: 'Dispute opened', escrow_signature: sig });
			success = 'Dispute opened';
			await loadDeal();
		} catch (e) { error = e.message; }
		loading = false;
	}

	function copyText(text) {
		navigator.clipboard.writeText(text).then(() => { success = 'Copied!'; setTimeout(() => success = '', 2000); });
	}
</script>

{#if !ws.initialized || ws.locked}
	<WalletSetup />
{:else if !deal}
	<p class="center">{error || 'Loading deal...'}</p>
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
				<span class="value price">{deal.price_sats?.toLocaleString()} sats</span>
			</div>
			<div class="info-item">
				<span class="label">Your role</span>
				<span class="value role-{myRole()}">{myRole()}</span>
			</div>
			<div class="info-item">
				<span class="label">Timeout</span>
				<span class="value">{deal.timeout_hours}h</span>
			</div>
		</div>

		<!-- Share link (seller, before buyer joins) -->
		{#if myRole() === 'seller' && !deal.buyer_id}
			<div class="action-card">
				<h3>Waiting for buyer</h3>
				<p>Share this link:</p>
				<code class="copy-text" onclick={() => copyText(`${window.location.origin}/join/${deal.deal_link_token}`)}>
					{window.location.origin}/join/{deal.deal_link_token}
				</code>
				<p class="hint">Click to copy</p>
			</div>
		{/if}

		<!-- Step 1: Create Escrow (buyer, deal has both parties but no escrow yet) -->
		{#if myRole() === 'buyer' && deal.buyer_id && ['pending', 'active'].includes(deal.status) && !escrowCreated}
			<div class="action-card">
				<h3>Step 1: Create Escrow</h3>
				<p>Lock {deal.price_sats?.toLocaleString()} sats in a non-custodial escrow.</p>
				<button onclick={handleCreateEscrow} disabled={loading}>
					{loading ? 'Creating...' : 'Create Escrow'}
				</button>
			</div>
		{/if}

		<!-- Step 2: Fund the Escrow (buyer, escrow created but not funded) -->
		{#if myRole() === 'buyer' && escrowCreated && ['pending', 'active'].includes(deal.status)}
			<div class="action-card">
				<h3>Step 2: Fund Escrow</h3>
				<p>Send <strong>{deal.price_sats?.toLocaleString()} sats</strong> to this escrow address:</p>
				<code class="escrow-addr" onclick={() => copyText(escrowAddress)}>{escrowAddress}</code>
				<p class="hint">Click to copy. This is a P2TR tapscript address.</p>

				<div class="fund-options">
					<button onclick={handleFundViaWallet} disabled={loading} class="primary">
						{loading ? 'Sending...' : 'Fund from Ark Wallet'}
					</button>
					<details>
						<summary>Manual funding (CLI/regtest)</summary>
						<input type="text" bind:value={manualTxid} placeholder="VTXO txid after sending" />
						<button onclick={handleManualFund} disabled={loading} class="secondary">Confirm Manual Funding</button>
					</details>
				</div>
			</div>
		{/if}

		<!-- Seller: waiting for funding -->
		{#if myRole() === 'seller' && deal.buyer_id && ['pending', 'active'].includes(deal.status)}
			<div class="action-card">
				<h3>Waiting for buyer to fund</h3>
				<p>The buyer needs to deposit {deal.price_sats?.toLocaleString()} sats into the escrow.</p>
			</div>
		{/if}

		<!-- Ship (seller, deal funded) -->
		{#if myRole() === 'seller' && deal.status === 'funded'}
			<div class="action-card">
				<h3>Deal Funded! Ship your item.</h3>
				<button onclick={handleShip} disabled={loading}>
					{loading ? 'Updating...' : 'Mark as Shipped'}
				</button>
			</div>
		{/if}

		<!-- Release (buyer, deal funded or shipped) -->
		{#if myRole() === 'buyer' && ['funded', 'shipped'].includes(deal.status)}
			<div class="action-card">
				<h3>Confirm Delivery</h3>
				<p>Enter your secret code to release funds to the seller.</p>
				<input type="text" bind:value={secretCode} placeholder="Your secret code" />
				<button onclick={handleRelease} disabled={loading} class="primary">
					{loading ? 'Releasing...' : 'Release Funds'}
				</button>
			</div>
		{/if}

		<!-- Dispute / Refund (funded or shipped) -->
		{#if (myRole() === 'buyer' || myRole() === 'seller') && ['funded', 'shipped'].includes(deal.status)}
			<div class="action-card subtle">
				{#if myRole() === 'buyer'}
					<button onclick={handleRefund} disabled={loading} class="secondary">Request Refund</button>
				{/if}
				<button onclick={handleDispute} disabled={loading} class="danger">Open Dispute</button>
			</div>
		{/if}

		<!-- Completed -->
		{#if ['released', 'completed', 'refunded'].includes(deal.status)}
			<div class="action-card done">
				<h3>{deal.status === 'refunded' ? 'Refunded' : 'Completed'}</h3>
				<p>This deal has been {deal.status}.</p>
				{#if deal.ark_vtxo_txid}
					<p class="txid">VTXO: {deal.ark_vtxo_txid}</p>
				{/if}
			</div>
		{/if}

		<!-- Disputed -->
		{#if deal.status === 'disputed'}
			<div class="action-card disputed">
				<h3>Disputed</h3>
				<p>This deal is under dispute. Oracle arbitration pending.</p>
				{#if deal.dispute_reason}<p class="reason">{deal.dispute_reason}</p>{/if}
			</div>
		{/if}

		{#if error}<p class="error">{error}</p>{/if}
		{#if success}<p class="success">{success}</p>{/if}
	</div>
{/if}

<style>
	.deal { max-width: 500px; margin: 1rem auto; }
	.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
	h2 { color: #f7931a; margin: 0; }
	.desc { color: #888; }
	.center { text-align: center; color: #888; }
	.info-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.75rem; background: #151515; border-radius: 12px; padding: 1rem; margin: 1rem 0; }
	.info-item { text-align: center; }
	.label { display: block; color: #666; font-size: 0.75rem; text-transform: uppercase; }
	.value { font-weight: bold; font-size: 1.1rem; }
	.price { color: #4ecdc4; }
	.role-seller { color: #9b59b6; }
	.role-buyer { color: #3498db; }
	.role-viewer { color: #888; }
	.action-card { background: #151515; border: 1px solid #222; border-radius: 12px; padding: 1.25rem; margin: 1rem 0; text-align: center; }
	.action-card.subtle { background: transparent; border: 1px solid #1a1a1a; }
	.action-card.done { border-color: #2ecc7133; }
	.action-card.disputed { border-color: #e67e2233; }
	.action-card h3 { margin: 0 0 0.5rem; color: #eee; }
	.action-card p { color: #888; font-size: 0.9rem; margin: 0.5rem 0; }
	input[type="text"] { width: 100%; padding: 0.75rem; border: 1px solid #333; border-radius: 8px; background: #1a1a1a; color: #fff; margin: 0.5rem 0; box-sizing: border-box; font-family: monospace; }
	button { width: 100%; padding: 0.75rem; border: none; border-radius: 8px; font-weight: bold; font-size: 1rem; cursor: pointer; margin-top: 0.5rem; }
	button.primary, button:not(.secondary):not(.danger) { background: #f7931a; color: #000; }
	button.secondary { background: #333; color: #ccc; }
	button.danger { background: #c0392b; color: #fff; }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	.escrow-addr { display: block; background: #0a0a0a; padding: 0.75rem; border-radius: 8px; word-break: break-all; font-size: 0.75rem; color: #f7931a; cursor: pointer; margin: 0.5rem 0; }
	.copy-text { display: block; background: #0a0a0a; padding: 0.75rem; border-radius: 8px; word-break: break-all; font-size: 0.8rem; color: #4ecdc4; cursor: pointer; }
	.hint { font-size: 0.75rem; color: #555; }
	.fund-options { margin-top: 1rem; }
	details { margin-top: 1rem; text-align: left; }
	summary { cursor: pointer; color: #888; font-size: 0.85rem; }
	.error { color: #ff4444; text-align: center; margin-top: 1rem; }
	.success { color: #2ecc71; text-align: center; margin-top: 1rem; }
	.txid { font-family: monospace; font-size: 0.75rem; color: #666; word-break: break-all; }
	.reason { font-style: italic; color: #e67e22; }
</style>
