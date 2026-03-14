<script>
	import { onMount } from 'svelte';
	import { getDeal, getAdminDeals } from '$lib/api.js';
	import { getStatusColor } from '$lib/utils/format.js';

	let { adminPubkey } = $props();

	onMount(() => loadAllDeals());

	let allDeals = $state([]);
	let dealsLoading = $state(false);
	let dealsError = $state('');
	let showFinished = $state(false);

	let selectedDeal = $state(null);
	let dealLoading = $state(false);
	let dealError = $state('');

	export async function loadAllDeals() {
		if (!adminPubkey) return;
		dealsLoading = true;
		dealsError = '';
		try {
			const result = await getAdminDeals(adminPubkey, showFinished, 100);
			allDeals = result.deals;
		} catch (e) {
			dealsError = e.message;
		} finally {
			dealsLoading = false;
		}
	}

	async function selectDeal(dealId) {
		dealLoading = true;
		dealError = '';
		try {
			selectedDeal = await getDeal(dealId);
		} catch (e) {
			dealError = e.message;
		} finally {
			dealLoading = false;
		}
	}
</script>

<div class="tab-content">
	<div class="panel-header">
		<h2>All Deals</h2>
		<div class="header-controls">
			<label class="toggle">
				<input type="checkbox" bind:checked={showFinished} onchange={loadAllDeals} />
				<span>Show finished</span>
			</label>
			<button onclick={loadAllDeals} disabled={dealsLoading}>
				{dealsLoading ? 'Loading...' : 'Refresh'}
			</button>
		</div>
	</div>

	{#if dealsError}
		<p class="error">{dealsError}</p>
	{/if}

	<div class="two-column">
		<div class="deals-list">
			{#if allDeals.length === 0 && !dealsLoading}
				<p class="empty">No deals found</p>
			{/if}
			{#each allDeals as d}
				<button
					class="deal-row"
					class:selected={selectedDeal?.deal_id === d.deal_id}
					onclick={() => selectDeal(d.deal_id)}
				>
					<div class="deal-row-main">
						<span class="deal-row-title">{d.title}</span>
						<span class="deal-row-status" style="color: {getStatusColor(d.status)}">{d.status}</span>
					</div>
					<div class="deal-row-details">
						<span class="deal-row-amount">{d.price_sats?.toLocaleString() ?? 0} sats</span>
						<span class="deal-row-meta">
							{#if d.seller_name}<span class="creator-tag">by {d.seller_name}</span>{/if}
							{#if d.timeout_action}
								<span class="beneficiary-tag {d.timeout_action === 'refund' ? 'ben-buyer' : 'ben-seller'}" title="Timeout: {d.timeout_action === 'refund' ? 'Buyer' : 'Seller'}">
									{d.timeout_action === 'refund' ? 'B' : 'S'}
								</span>
							{/if}
							<span>{new Date(d.created_at).toLocaleDateString()}</span>
						</span>
					</div>
				</button>
			{/each}
		</div>

		<div class="deal-detail">
			{#if selectedDeal}
				<div class="detail-card">
					<h3>{selectedDeal.title}</h3>
					<div class="detail-status" style="color: {getStatusColor(selectedDeal.status)}">
						{selectedDeal.status.toUpperCase()}
					</div>
					<div class="detail-info">
						<div class="info-row">
							<span class="label">Deal ID:</span>
							<span class="value mono">{selectedDeal.deal_id}</span>
						</div>
						<div class="info-row">
							<span class="label">Amount:</span>
							<span class="value">{selectedDeal.price_sats?.toLocaleString() ?? 0} sats</span>
						</div>
						<div class="info-row">
							<span class="label">Seller:</span>
							<span class="value">{selectedDeal.seller_name || selectedDeal.seller_id?.slice(0, 12) || '-'}</span>
						</div>
						<div class="info-row">
							<span class="label">Buyer:</span>
							<span class="value">{selectedDeal.buyer_name || selectedDeal.buyer_id?.slice(0, 12) || '-'}</span>
						</div>
						<div class="info-row">
							<span class="label">Timeout beneficiary:</span>
							<span class="value" style="color: {selectedDeal.timeout_action === 'refund' ? 'var(--info)' : 'var(--orange)'}">
								{selectedDeal.timeout_action === 'refund' ? 'Buyer (refund)' : 'Seller (release)'}
							</span>
						</div>
						<div class="info-row">
							<span class="label">Created:</span>
							<span class="value">{new Date(selectedDeal.created_at).toLocaleString()}</span>
						</div>
					</div>
					<a href="/deal/{selectedDeal.deal_id}" target="_blank" class="btn secondary">
						View Deal Page
					</a>
				</div>
			{:else}
				<p class="hint">Select a deal to view details</p>
			{/if}
		</div>
	</div>
</div>

<style>
	h2 { color: var(--text); font-size: 1.125rem; margin: 0; }
	h3 { color: var(--text); font-size: 1rem; margin: 0 0 1rem 0; }
	.tab-content { background: var(--surface); padding: 1.5rem; border-radius: 8px; border: 1px solid var(--border); }
	.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
	.header-controls { display: flex; align-items: center; gap: 1rem; }
	.two-column { display: grid; grid-template-columns: 1fr 1.5fr; gap: 1rem; }
	.deals-list { display: flex; flex-direction: column; gap: 0.5rem; max-height: 500px; overflow-y: auto; }
	.deal-row {
		display: flex; flex-direction: column; gap: 0.25rem; padding: 0.75rem;
		background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
		cursor: pointer; text-align: left; width: 100%;
	}
	.deal-row:hover { border-color: var(--border-hover); }
	.deal-row.selected { border-color: var(--accent); background: #1a2a2a; }
	.deal-row-main { display: flex; justify-content: space-between; align-items: center; }
	.deal-row-title { color: var(--text); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px; }
	.deal-row-status { font-size: 0.7rem; text-transform: uppercase; font-weight: 600; }
	.deal-row-amount { color: var(--orange); font-size: 0.85rem; }
	.deal-row-details { display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--text-dim); }
	.deal-row-meta { display: flex; align-items: center; gap: 0.4rem; }
	.creator-tag { color: var(--text-muted); }
	.beneficiary-tag { display: inline-flex; align-items: center; justify-content: center; width: 16px; height: 16px; border-radius: 50%; font-size: 0.6rem; font-weight: 700; }
	.ben-buyer { background: #1e3a5f; color: var(--info); }
	.ben-seller { background: #3a2a00; color: var(--orange); }
	.deal-detail { min-height: 300px; }
	.detail-card { background: var(--bg); padding: 1.25rem; border-radius: 8px; }
	.detail-card h3 { margin-bottom: 0.5rem; }
	.detail-status { font-size: 0.8rem; font-weight: 600; text-transform: uppercase; margin-bottom: 1rem; }
	.detail-info { display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 1rem; }
	.info-row { display: flex; justify-content: space-between; font-size: 0.875rem; }
	.info-row .label { color: var(--text-dim); }
	.info-row .value { color: var(--text); }
	.info-row .value.mono { font-family: monospace; font-size: 0.8rem; }
	.toggle { display: flex; align-items: center; gap: 0.5rem; color: var(--text-muted); font-size: 0.875rem; cursor: pointer; }
	.toggle input { width: auto; }
	.btn.secondary { background: var(--border); display: inline-block; text-decoration: none; text-align: center; padding: 0.75rem 1.25rem; border: 1px solid var(--border-hover); border-radius: 4px; color: var(--text); }
	button { padding: 0.75rem 1.25rem; background: var(--border); border: 1px solid var(--border-hover); border-radius: 4px; color: var(--text); cursor: pointer; }
	button:hover:not(:disabled) { background: var(--border-hover); }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	.error { color: var(--error); font-size: 0.875rem; }
	.hint { color: var(--text-dim); font-size: 0.875rem; }
	.empty { color: var(--text-dim); text-align: center; padding: 2rem; }
	@media (max-width: 768px) { .two-column { grid-template-columns: 1fr; } }
</style>
