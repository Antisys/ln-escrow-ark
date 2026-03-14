<script>
	import { walletStore } from '$lib/stores/wallet.js';
	import WalletSetup from '$lib/components/WalletSetup.svelte';

	let ws = $derived($walletStore);
</script>

{#if !ws.initialized || ws.locked}
	<WalletSetup />
{:else}
	<div class="home">
		<h2>Arkana</h2>
		<p>Non-custodial Bitcoin escrow powered by Ark Protocol.</p>

		<div class="balance-card">
			<div class="balance-label">Balance</div>
			<div class="balance-amount">{ws.balance.total.toLocaleString()} sats</div>
			{#if ws.balance.boarding > 0}
				<div class="balance-detail">Boarding: {ws.balance.boarding.toLocaleString()} sats</div>
			{/if}
			{#if ws.boardingAddress}
				<div class="boarding">
					<div class="boarding-label">Fund your wallet:</div>
					<code class="boarding-addr">{ws.boardingAddress}</code>
				</div>
			{/if}
		</div>

		<div class="actions">
			<a href="/create" class="btn primary">Create Deal</a>
		</div>

		<p class="info">
			Your wallet key: <code>{ws.publicKey.slice(0, 16)}...</code>
		</p>
	</div>
{/if}

<style>
	.home { text-align: center; padding-top: 2rem; }
	h2 { color: #f7931a; margin-bottom: 0.25rem; }
	.balance-card { background: #151515; border: 1px solid #222; border-radius: 12px; padding: 1.5rem; margin: 2rem 0; }
	.balance-label { color: #888; font-size: 0.85rem; text-transform: uppercase; }
	.balance-amount { font-size: 2rem; font-weight: bold; color: #4ecdc4; margin: 0.25rem 0; }
	.balance-detail { color: #666; font-size: 0.85rem; }
	.boarding { margin-top: 1rem; padding-top: 1rem; border-top: 1px solid #222; }
	.boarding-label { color: #888; font-size: 0.8rem; margin-bottom: 0.5rem; }
	.boarding-addr { display: block; background: #0a0a0a; padding: 0.5rem; border-radius: 6px; word-break: break-all; font-size: 0.7rem; color: #f7931a; }
	.actions { margin: 2rem 0; }
	.btn { display: inline-block; padding: 0.75rem 2rem; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 1rem; }
	.primary { background: #f7931a; color: #000; }
	.info { color: #555; font-size: 0.8rem; }
	.info code { color: #666; }
</style>
