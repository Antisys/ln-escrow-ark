<script>
	import { walletStore } from '$lib/stores/wallet.js';
	import { getPublicKey } from '$lib/ark-wallet.js';
	import { createDeal } from '$lib/api.js';
	import { goto } from '$app/navigation';

	let ws = $derived($walletStore);
	let title = $state('');
	let description = $state('');
	let price = $state('');
	let timeout = $state(24);
	let error = $state('');
	let loading = $state(false);

	async function handleCreate() {
		if (!title || !price) { error = 'Title and price required'; return; }
		const priceSats = parseInt(price);
		if (isNaN(priceSats) || priceSats < 1) { error = 'Invalid price'; return; }

		loading = true; error = '';
		try {
			const deal = await createDeal({
				title,
				description,
				price_sats: priceSats,
				timeout_hours: timeout,
				seller_pubkey: getPublicKey(),
			});
			goto(`/deal/${deal.deal_id}`);
		} catch (e) {
			error = e.message;
		}
		loading = false;
	}
</script>

{#if !ws.initialized || ws.locked}
	<p>Please <a href="/">unlock your wallet</a> first.</p>
{:else}
	<div class="create">
		<h2>Create Deal</h2>

		<label>Title
			<input bind:value={title} placeholder="What are you selling?" />
		</label>

		<label>Description
			<textarea bind:value={description} placeholder="Details..." rows="3"></textarea>
		</label>

		<label>Price (sats)
			<input bind:value={price} type="number" placeholder="50000" />
		</label>

		<label>Timeout (hours)
			<select bind:value={timeout}>
				<option value={6}>6 hours</option>
				<option value={24}>24 hours</option>
				<option value={72}>3 days</option>
				<option value={168}>7 days</option>
			</select>
		</label>

		<button onclick={handleCreate} disabled={loading}>
			{loading ? 'Creating...' : 'Create Deal'}
		</button>

		{#if error}<p class="error">{error}</p>{/if}
	</div>
{/if}

<style>
	.create { max-width: 400px; margin: 2rem auto; }
	h2 { color: #f7931a; text-align: center; }
	label { display: block; margin-bottom: 1rem; color: #888; font-size: 0.85rem; }
	input, textarea, select { width: 100%; padding: 0.75rem; border: 1px solid #333; border-radius: 8px; background: #1a1a1a; color: #fff; font-size: 1rem; margin-top: 0.25rem; box-sizing: border-box; }
	button { width: 100%; padding: 0.75rem; border: none; border-radius: 8px; background: #f7931a; color: #000; font-weight: bold; font-size: 1rem; cursor: pointer; margin-top: 1rem; }
	button:disabled { opacity: 0.5; }
	.error { color: #ff4444; text-align: center; }
</style>
