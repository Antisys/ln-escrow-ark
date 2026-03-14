<script>
	import { page } from '$app/state';
	import { walletStore } from '$lib/stores/wallet.js';
	import { getPublicKey } from '$lib/ark-wallet.js';
	import { getDealByToken, joinDeal } from '$lib/api.js';
	import { goto } from '$app/navigation';
	import WalletSetup from '$lib/components/WalletSetup.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';

	let ws = $derived($walletStore);
	let token = $derived(page.params.token);
	let deal = $state(null);
	let error = $state('');
	let loading = $state(false);

	$effect(() => {
		if (token) loadDeal();
	});

	async function loadDeal() {
		try {
			deal = await getDealByToken(token);
		} catch (e) {
			error = 'Deal not found';
		}
	}

	async function handleJoin() {
		if (!deal) return;
		loading = true; error = '';
		try {
			await joinDeal(deal.deal_id, getPublicKey());
			goto(`/deal/${deal.deal_id}`);
		} catch (e) {
			error = e.message;
		}
		loading = false;
	}
</script>

{#if !ws.initialized || ws.locked}
	<WalletSetup />
{:else if error}
	<p class="error">{error}</p>
{:else if !deal}
	<p>Loading deal...</p>
{:else}
	<div class="join">
		<h2>Join Deal</h2>
		<div class="deal-info">
			<h3>{deal.title}</h3>
			{#if deal.description}<p class="desc">{deal.description}</p>{/if}
			<div class="price">{deal.price_sats?.toLocaleString()} sats</div>
			<StatusBadge status={deal.status} />
		</div>
		<button onclick={handleJoin} disabled={loading}>
			{loading ? 'Joining...' : 'Join as Buyer'}
		</button>
	</div>
{/if}

<style>
	.join { max-width: 400px; margin: 2rem auto; text-align: center; }
	h2 { color: #f7931a; }
	.deal-info { background: #151515; border: 1px solid #222; border-radius: 12px; padding: 1.5rem; margin: 1.5rem 0; }
	h3 { margin: 0 0 0.5rem; }
	.desc { color: #888; font-size: 0.9rem; }
	.price { font-size: 1.5rem; font-weight: bold; color: #4ecdc4; margin: 0.75rem 0; }
	button { width: 100%; padding: 0.75rem; border: none; border-radius: 8px; background: #f7931a; color: #000; font-weight: bold; font-size: 1rem; cursor: pointer; }
	button:disabled { opacity: 0.5; }
	.error { color: #ff4444; text-align: center; }
</style>
