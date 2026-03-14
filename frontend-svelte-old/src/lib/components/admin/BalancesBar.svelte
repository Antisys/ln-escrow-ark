<script>
	import { onMount } from 'svelte';

	let { config } = $props();

	let refLnSats = $state(0);
	let refLnDate = $state('');
	let editingRefLn = $state(false);
	let refLnInput = $state('');

	onMount(() => {
		try {
			const saved = JSON.parse(localStorage.getItem('admin_ref_balances') || '{}');
			refLnSats = saved.ln_sats ?? 0;
			refLnDate = saved.ln_date ?? '';
		} catch {}
	});

	function saveRefBalance() {
		const val = parseInt(refLnInput);
		if (isNaN(val) || val < 0) return;
		const now = new Date();
		const dateStr = now.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
		refLnSats = val; refLnDate = dateStr; editingRefLn = false;
		persistRef();
	}

	function snapshotRefBalance() {
		const now = new Date();
		const dateStr = now.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
		if (config?.lightning?.local_balance_sats != null) {
			refLnSats = config.lightning.local_balance_sats; refLnDate = dateStr;
		}
		persistRef();
	}

	function persistRef() {
		localStorage.setItem('admin_ref_balances', JSON.stringify({
			ln_sats: refLnSats, ln_date: refLnDate
		}));
	}
</script>

<div class="balances-row">
	{#if config?.lightning?.local_balance_sats != null}
		<div class="balance-card">
			<span class="balance-label">Lightning (outbound)</span>
			{#if refLnSats > 0}
				{#if editingRefLn}
					<span class="balance-ref-edit">
						<input type="number" bind:value={refLnInput} onkeydown={(e) => { if (e.key === 'Enter') saveRefBalance(); if (e.key === 'Escape') editingRefLn = false; }} class="ref-input" />
						<button class="ref-btn" onclick={() => saveRefBalance()}>OK</button>
						<button class="ref-btn ref-btn-cancel" onclick={() => editingRefLn = false}>X</button>
					</span>
				{:else}
					<button class="balance-ref" onclick={() => { editingRefLn = true; refLnInput = refLnSats.toString(); }} title="Click to edit">{refLnSats.toLocaleString()} sats <span class="balance-date">{refLnDate}</span></button>
				{/if}
			{:else}
				<button class="balance-ref ref-empty" onclick={() => snapshotRefBalance()} title="Click to snapshot current balance">no ref — click to set</button>
			{/if}
			<span class="balance-live">{config.lightning.local_balance_sats.toLocaleString()} sats
				<button class="snapshot-btn" onclick={(e) => { e.stopPropagation(); snapshotRefBalance(); }} title="Snapshot current balance as reference">pin</button>
			</span>
		</div>
	{/if}
</div>

<style>
	.balances-row { display: flex; gap: 0.75rem; margin-bottom: 1rem; }
	.balance-card {
		flex: 1; display: flex; flex-direction: column; gap: 0.2rem;
		padding: 0.6rem 1rem; background: var(--surface); border: 1px solid var(--border);
		border-radius: 6px; font-size: 0.85rem;
	}
	.balance-card:hover { border-color: var(--accent); }
	.balance-label { color: var(--text-muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; }
	.balance-ref { color: var(--text-dim); font-family: monospace; font-size: 0.8rem; cursor: pointer; background: none; border: none; padding: 0; text-align: left; }
	.balance-ref:hover { color: var(--text-muted); }
	.ref-empty { font-style: italic; font-family: inherit; }
	.balance-ref-edit { display: flex; align-items: center; gap: 0.3rem; }
	.ref-input {
		width: 90px; padding: 0.15rem 0.3rem; background: #111;
		border: 1px solid var(--accent); border-radius: 3px; color: var(--text);
		font-family: monospace; font-size: 0.8rem;
	}
	.ref-btn {
		padding: 0.1rem 0.4rem; background: var(--border); border: 1px solid var(--text-dim);
		border-radius: 3px; color: var(--text); font-size: 0.7rem; cursor: pointer;
	}
	.ref-btn:hover { background: var(--border-hover); }
	.ref-btn-cancel { color: var(--text-muted); }
	.snapshot-btn {
		margin-left: 0.3rem; padding: 0.05rem 0.3rem; background: transparent;
		border: 1px solid var(--border-hover); border-radius: 3px; color: var(--text-dim); font-size: 0.65rem; cursor: pointer;
	}
	.snapshot-btn:hover { border-color: var(--accent); color: var(--accent); }
	.balance-date { font-size: 0.7rem; color: var(--border-hover); }
	.balance-live { color: var(--accent); font-weight: bold; font-family: monospace; font-size: 1rem; }
</style>
