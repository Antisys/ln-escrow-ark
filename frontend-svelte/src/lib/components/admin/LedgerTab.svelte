<script>
	import { onMount } from 'svelte';
	import { getAdminLedger } from '$lib/api.js';
	import { getStatusColor, copyToClipboard } from '$lib/utils/format.js';

	let { adminPubkey } = $props();

	onMount(() => loadLedger());

	let ledgerEntries = $state([]);
	let ledgerTotals = $state(null);
	let ledgerLoading = $state(false);
	let ledgerError = $state('');
	let ledgerCopied = $state(null);

	export async function loadLedger() {
		if (!adminPubkey) return;
		ledgerLoading = true;
		ledgerError = '';
		try {
			const result = await getAdminLedger(adminPubkey);
			ledgerEntries = result.entries;
			ledgerTotals = result.totals;
		} catch (e) {
			ledgerError = e.message;
		} finally {
			ledgerLoading = false;
		}
	}

	async function copyDealId(text, id) {
		if (!text) return;
		await copyToClipboard(text);
		ledgerCopied = id;
		setTimeout(() => { if (ledgerCopied === id) ledgerCopied = null; }, 1500);
	}
</script>

<div class="tab-content">
	<div class="panel-header">
		<h2>Financial Ledger</h2>
		<button onclick={loadLedger} disabled={ledgerLoading}>
			{ledgerLoading ? 'Loading...' : 'Refresh'}
		</button>
	</div>

	{#if ledgerError}
		<p class="error">{ledgerError}</p>
	{/if}

	{#if ledgerEntries.length === 0 && !ledgerLoading}
		<p class="empty">No funded deals yet</p>
	{:else}
		<div class="ledger-table-wrapper">
			<table class="ledger-table">
				<thead>
					<tr>
						<th>Deal</th>
						<th class="num income">LN In</th>
						<th class="num outflow">LN Out</th>
						<th class="num">Net</th>
					</tr>
				</thead>
				<tbody>
					{#each ledgerEntries as e}
						<tr>
							<td class="deal-cell">
								<span class="ledger-title">{e.title}</span>
								<span class="ledger-status" style="color: {getStatusColor(e.status)}">{e.status}</span>
							</td>
							<td class="num income">
								{#if e.ln_in_sats != null}
									{e.ln_in_sats.toLocaleString()}
								{:else}
									<span class="ledger-dash">&mdash;</span>
								{/if}
							</td>
							<td class="num outflow">
								{#if e.ln_out_sats != null}
									{e.ln_out_sats.toLocaleString()}
									<span class="ln-out-type">{e.ln_out_type}</span>
								{:else}
									<span class="ledger-dash">&mdash;</span>
								{/if}
							</td>
							<td class="num net-total {e.net_sats > 0 ? 'net-positive' : e.net_sats < 0 ? 'net-negative' : ''}">
								<strong>{e.net_sats > 0 ? '+' : ''}{e.net_sats.toLocaleString()}</strong>
							</td>
						</tr>
					{/each}
				</tbody>
				{#if ledgerTotals}
					<tfoot>
						<tr class="totals-row">
							<td><strong>Totals</strong></td>
							<td class="num income"><strong>{(ledgerTotals.ln_in ?? 0).toLocaleString()}</strong></td>
							<td class="num outflow"><strong>{(ledgerTotals.ln_out ?? 0).toLocaleString()}</strong></td>
							<td class="num net-total {ledgerTotals.net > 0 ? 'net-positive' : ledgerTotals.net < 0 ? 'net-negative' : ''}"><strong>{ledgerTotals.net > 0 ? '+' : ''}{(ledgerTotals.net ?? 0).toLocaleString()}</strong></td>
						</tr>
					</tfoot>
				{/if}
			</table>
		</div>
	{/if}
</div>

<style>
	h2 { color: var(--text); font-size: 1.125rem; margin: 0; }
	.tab-content { background: var(--surface); padding: 1.5rem; border-radius: 8px; border: 1px solid var(--border); }
	.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
	button { padding: 0.75rem 1.25rem; background: var(--border); border: 1px solid var(--border-hover); border-radius: 4px; color: var(--text); cursor: pointer; }
	button:hover:not(:disabled) { background: var(--border-hover); }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	.error { color: var(--error); font-size: 0.875rem; }
	.empty { color: var(--text-dim); text-align: center; padding: 2rem; }
	.ledger-table-wrapper { overflow-x: auto; }
	.ledger-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
	.ledger-table th, .ledger-table td { padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }
	.ledger-table th { color: var(--text-muted); font-weight: 500; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
	.ledger-table th.num, .ledger-table td.num { text-align: right; }
	.ledger-table th.income, .ledger-table td.income { color: var(--success); }
	.ledger-table th.outflow, .ledger-table td.outflow { color: var(--error); }
	.deal-cell { display: flex; flex-direction: column; gap: 0.15rem; }
	.ledger-title { color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 180px; }
	.ledger-status { font-size: 0.65rem; text-transform: uppercase; font-weight: 600; }
	.net-positive { color: var(--accent) !important; }
	.net-negative { color: #ff6b6b !important; }
	.net-total { border-left: 1px solid var(--border-hover); }
	.ledger-dash { color: var(--border-hover); }
	.ln-out-type { display: block; font-size: 0.65rem; color: var(--text-muted); text-transform: uppercase; }
	.totals-row { border-top: 2px solid var(--border-hover); }
	.totals-row td { padding-top: 0.75rem; color: var(--text); }
</style>
