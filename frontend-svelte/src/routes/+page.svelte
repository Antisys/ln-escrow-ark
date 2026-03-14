<script>
	import { walletStore } from '$lib/stores/wallet.js';
	import { getBalance, getBoardingAddress, getAddress } from '$lib/ark-wallet.js';
	import { getApiUrl } from '$lib/config.js';
	import WalletSetup from '$lib/components/WalletSetup.svelte';

	let ws = $derived($walletStore);
	let fundingTab = $state('boarding'); // boarding, ark, faucet
	let faucetLoading = $state(false);
	let faucetMsg = $state('');
	let copied = $state('');

	async function refreshBalance() {
		const balance = await getBalance();
		const boardingAddr = await getBoardingAddress();
		const arkAddr = await getAddress();
		walletStore.update(s => ({ ...s, balance, boardingAddress: boardingAddr, address: arkAddr }));
	}

	async function requestFaucet() {
		faucetLoading = true; faucetMsg = '';
		try {
			// Use boarding address if available, otherwise ask backend to generate one
			let addr = ws.boardingAddress;
			if (!addr) {
				// No SDK wallet — use pubkey to get a regtest address from backend
				faucetMsg = 'No boarding address available. Getting one from server...';
				const res = await fetch(`${getApiUrl()}/faucet/address?pubkey=${ws.publicKey}`, {
					headers: { 'Origin': window.location.origin },
				});
				if (res.ok) {
					const data = await res.json();
					addr = data.address;
				}
			}
			if (!addr) {
				faucetMsg = 'Could not get a funding address. Try refreshing.';
				faucetLoading = false;
				return;
			}

			const res = await fetch(`${getApiUrl()}/faucet`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ address: addr, amount_sats: 100000 }),
			});
			if (res.ok) {
				const data = await res.json();
				faucetMsg = `Sent 100,000 sats! TX: ${data.txid.slice(0, 12)}...`;
				setTimeout(refreshBalance, 12000);
			} else {
				const err = await res.json().catch(() => ({}));
				faucetMsg = err.detail || 'Faucet unavailable';
			}
		} catch (e) { faucetMsg = `Faucet error: ${e.message}`; }
		faucetLoading = false;
	}

	function copy(text) {
		navigator.clipboard.writeText(text);
		copied = text.slice(0, 8);
		setTimeout(() => copied = '', 2000);
	}
</script>

{#if !ws.initialized || ws.locked}
	<WalletSetup />
{:else}
	<div class="home">
		<img src="/logo.svg" alt="Arkana" class="home-logo" />
		<h2>Arkana</h2>
		<p>Non-custodial Bitcoin escrow powered by Ark Protocol.</p>

		<div class="balance-card">
			<div class="balance-label">Balance</div>
			<div class="balance-amount">{ws.balance.total.toLocaleString()} sats</div>
			{#if ws.balance.boarding > 0}
				<div class="balance-detail">Boarding: {ws.balance.boarding.toLocaleString()}</div>
			{/if}
			{#if ws.balance.offchain > 0}
				<div class="balance-detail">Offchain: {ws.balance.offchain.toLocaleString()}</div>
			{/if}
			<button class="refresh-btn" onclick={refreshBalance}>Refresh</button>
		</div>

		<div class="fund-section">
			<h3>Fund Wallet</h3>
			<div class="fund-tabs">
				<button class:active={fundingTab === 'boarding'} onclick={() => fundingTab = 'boarding'}>On-chain</button>
				<button class:active={fundingTab === 'ark'} onclick={() => fundingTab = 'ark'}>Ark Transfer</button>
				<button class:active={fundingTab === 'faucet'} onclick={() => fundingTab = 'faucet'}>Faucet (Regtest)</button>
			</div>

			{#if fundingTab === 'boarding'}
				<div class="fund-content">
					<p>Send Bitcoin to this boarding address:</p>
					{#if ws.boardingAddress}
						<code class="addr" onclick={() => copy(ws.boardingAddress)}>{ws.boardingAddress}</code>
						<p class="hint">{copied ? 'Copied!' : 'Click to copy'}</p>
					{:else}
						<p class="hint">Boarding address not available (Ark SDK not connected)</p>
					{/if}
					<p class="note">After sending, wait for 1 confirmation, then funds appear as "Boarding" balance. Use "Settle" in your Ark wallet to convert to offchain sats.</p>
				</div>
			{:else if fundingTab === 'ark'}
				<div class="fund-content">
					<p>Receive from another Ark wallet:</p>
					{#if ws.address}
						<code class="addr" onclick={() => copy(ws.address)}>{ws.address}</code>
						<p class="hint">{copied ? 'Copied!' : 'Click to copy'}</p>
					{:else if ws.boardingAddress}
						<code class="addr" onclick={() => copy(ws.boardingAddress)}>{ws.boardingAddress}</code>
						<p class="hint">{copied ? 'Copied!' : 'Click to copy (boarding address)'}</p>
					{:else}
						<p class="hint">Ark address not available</p>
					{/if}
					<p class="note">Share this address with the sender. Transfer is instant and free.</p>
				</div>
			{:else if fundingTab === 'faucet'}
				<div class="fund-content">
					<p>Get free regtest coins for testing:</p>
					<button class="fund-btn" onclick={requestFaucet} disabled={faucetLoading}>
						{faucetLoading ? 'Requesting...' : 'Get 100,000 sats'}
					</button>
					{#if faucetMsg}<p class="faucet-msg">{faucetMsg}</p>{/if}
					<p class="note">Only works on regtest. Coins have no real value.</p>
				</div>
			{/if}
		</div>

		<div class="actions">
			<a href="/create" class="btn primary">Create Deal</a>
		</div>

		<p class="info">
			Pubkey: <code onclick={() => copy(ws.publicKey)}>{ws.publicKey.slice(0, 20)}...</code>
		</p>
	</div>
{/if}

<style>
	.home { text-align: center; padding-top: 2rem; }
	.home-logo { width: 120px; height: 120px; margin-bottom: 0.5rem; }
	h2 { color: #f7931a; margin-bottom: 0.25rem; }
	.balance-card { background: #151515; border: 1px solid #222; border-radius: 12px; padding: 1.5rem; margin: 2rem 0; }
	.balance-label { color: #888; font-size: 0.85rem; text-transform: uppercase; }
	.balance-amount { font-size: 2rem; font-weight: bold; color: #4ecdc4; margin: 0.25rem 0; }
	.balance-detail { color: #666; font-size: 0.85rem; }
	.refresh-btn { background: #222; border: 1px solid #333; color: #888; padding: 0.3rem 0.8rem; border-radius: 6px; cursor: pointer; font-size: 0.75rem; margin-top: 0.75rem; }
	.refresh-btn:hover { color: #fff; border-color: #555; }
	.fund-section { background: #151515; border: 1px solid #222; border-radius: 12px; padding: 1.25rem; margin: 1rem 0; }
	.fund-section h3 { margin: 0 0 0.75rem; color: #ccc; font-size: 1rem; text-align: center; }
	.fund-tabs { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
	.fund-tabs button { flex: 1; padding: 0.5rem; border: 1px solid #333; border-radius: 8px; background: #111; color: #888; cursor: pointer; font-size: 0.8rem; }
	.fund-tabs button.active { background: #1a2a3c; border-color: #0066cc; color: #0099ff; }
	.fund-content { text-align: center; }
	.fund-content p { color: #888; font-size: 0.85rem; margin: 0.5rem 0; }
	.addr { display: block; background: #0a0a0a; padding: 0.75rem; border-radius: 8px; word-break: break-all; font-size: 0.7rem; color: #0099ff; cursor: pointer; margin: 0.5rem 0; }
	.note { font-size: 0.75rem; color: #555; font-style: italic; }
	.fund-btn { padding: 0.6rem 1.5rem; border: none; border-radius: 8px; background: #0066cc; color: #fff; font-weight: bold; cursor: pointer; }
	.fund-btn:disabled { opacity: 0.5; }
	.faucet-msg { color: #4ecdc4; font-size: 0.85rem; }
	.boarding { margin-top: 1rem; padding-top: 1rem; border-top: 1px solid #222; }
	.boarding-label { color: #888; font-size: 0.8rem; margin-bottom: 0.5rem; }
	.boarding-addr { display: block; background: #0a0a0a; padding: 0.5rem; border-radius: 6px; word-break: break-all; font-size: 0.7rem; color: #f7931a; }
	.actions { margin: 2rem 0; }
	.btn { display: inline-block; padding: 0.75rem 2rem; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 1rem; }
	.primary { background: #f7931a; color: #000; }
	.info { color: #555; font-size: 0.8rem; }
	.info code { color: #666; }
</style>
