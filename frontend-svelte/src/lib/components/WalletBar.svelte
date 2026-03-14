<script>
	import { walletStore } from '$lib/stores/wallet.js';
	import { lockWallet } from '$lib/ark-wallet.js';
	import { APP_NAME } from '$lib/config.js';

	let ws = $derived($walletStore);

	function handleLock() {
		lockWallet();
		walletStore.set({ initialized: false, locked: true, publicKey: '', address: '', boardingAddress: '', balance: { total: 0, offchain: 0, boarding: 0 } });
	}

	function formatSats(n) {
		return n.toLocaleString();
	}
</script>

<nav class="wallet-bar">
	<a href="/" class="brand"><img src="/logo.svg" alt="" class="logo" />{APP_NAME}</a>
	{#if ws.initialized && !ws.locked}
		<div class="wallet-info">
			<span class="balance">{formatSats(ws.balance.total)} sats</span>
			<span class="pubkey" title={ws.publicKey}>{ws.publicKey.slice(0, 8)}...</span>
			<button class="lock-btn" onclick={handleLock}>Lock</button>
		</div>
	{/if}
</nav>

<style>
	.wallet-bar { display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 1.5rem; background: #111; border-bottom: 1px solid #222; }
	.brand { color: #0099ff; font-weight: bold; font-size: 1.1rem; text-decoration: none; display: flex; align-items: center; gap: 0.5rem; }
	.logo { width: 42px; height: 42px; }
	.wallet-info { display: flex; align-items: center; gap: 1rem; font-size: 0.85rem; }
	.balance { color: #4ecdc4; font-weight: bold; }
	.pubkey { color: #666; font-family: monospace; }
	.lock-btn { background: none; border: 1px solid #444; color: #999; padding: 0.25rem 0.75rem; border-radius: 4px; cursor: pointer; font-size: 0.8rem; }
	.lock-btn:hover { color: #fff; border-color: #666; }
</style>
