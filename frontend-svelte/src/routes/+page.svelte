<script>
	import { walletStore } from '$lib/stores/wallet.js';
	import WalletSetup from '$lib/components/WalletSetup.svelte';

	let ws = $derived($walletStore);
	let copied = $state('');

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

		<div class="wallet-card">
			<div class="wallet-label">Wallet</div>
			<div class="wallet-pubkey" onclick={() => copy(ws.publicKey)}>
				{ws.publicKey.slice(0, 20)}...
			</div>
			<p class="hint">{copied ? 'Copied!' : 'Click to copy pubkey'}</p>
			<p class="wallet-note">Your identity key. Deals are funded directly — no wallet balance needed.</p>
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
	.wallet-card { background: #151515; border: 1px solid #222; border-radius: 12px; padding: 1.5rem; margin: 2rem 0; text-align: center; }
	.wallet-label { color: #888; font-size: 0.85rem; text-transform: uppercase; }
	.wallet-pubkey { font-family: monospace; font-size: 0.85rem; color: #0099ff; cursor: pointer; margin: 0.5rem 0; padding: 0.5rem; background: #0a0a0a; border-radius: 8px; }
	.wallet-note { font-size: 0.75rem; color: #555; margin-top: 0.5rem; }
	.hint { font-size: 0.75rem; color: #555; }
	.boarding { margin-top: 1rem; padding-top: 1rem; border-top: 1px solid #222; }
	.boarding-label { color: #888; font-size: 0.8rem; margin-bottom: 0.5rem; }
	.boarding-addr { display: block; background: #0a0a0a; padding: 0.5rem; border-radius: 6px; word-break: break-all; font-size: 0.7rem; color: #f7931a; }
	.actions { margin: 2rem 0; }
	.btn { display: inline-block; padding: 0.75rem 2rem; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 1rem; }
	.primary { background: #f7931a; color: #000; }
	.info { color: #555; font-size: 0.8rem; }
	.info code { color: #666; }
</style>
