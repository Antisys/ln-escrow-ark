<script>
	import { onMount } from 'svelte';
	import { getAdminConfig, getLimits, updateLimits, updateFees } from '$lib/api.js';
	import { formatSats } from '$lib/utils/format.js';

	let { adminPubkey } = $props();

	let settingsSection = $state(null);

	// Config state
	let config = $state(null);
	let configError = $state('');
	let configLoading = $state(false);

	// Limits state
	let limits = $state(null);
	let limitsLoading = $state(false);
	let limitsError = $state('');
	let limitsMessage = $state('');
	let editMinSats = $state('');
	let editMaxSats = $state('');

	// Fees state
	let feesLoading = $state(false);
	let feesError = $state('');
	let feesMessage = $state('');
	let editServiceFee = $state('');

	onMount(async () => {
		try {
			limits = await getLimits();
			editMinSats = limits.min_sats.toString();
			editMaxSats = limits.max_sats.toString();
			editServiceFee = (limits.service_fee_percent ?? 1.0).toString();
		} catch {
			// Limits load failed — fields will remain empty
		}
	});

	async function loadConfig() {
		if (!adminPubkey) return;
		configLoading = true;
		configError = '';
		try {
			config = await getAdminConfig(adminPubkey);
		} catch (e) {
			configError = e.message;
		} finally {
			configLoading = false;
		}
	}

	async function handleUpdateLimits() {
		if (!adminPubkey) return;
		limitsLoading = true; limitsError = ''; limitsMessage = '';
		try {
			const result = await updateLimits(adminPubkey, parseInt(editMinSats), parseInt(editMaxSats));
			limits = result.limits;
			limitsMessage = 'Limits updated!';
		} catch (e) {
			limitsError = e.message;
		} finally {
			limitsLoading = false;
		}
	}

	async function handleUpdateFees() {
		if (!adminPubkey) return;
		feesLoading = true; feesError = ''; feesMessage = '';
		try {
			await updateFees(adminPubkey, parseFloat(editServiceFee));
			feesMessage = 'Fees updated!';
			limits = await getLimits();
		} catch (e) {
			feesError = e.message;
		} finally {
			feesLoading = false;
		}
	}
</script>

<div class="tab-content">
	<div class="settings-menu">
		<button class:active={settingsSection === 'limits'} onclick={() => settingsSection = settingsSection === 'limits' ? null : 'limits'}>
			Deal Limits
		</button>
		<button class:active={settingsSection === 'fees'} onclick={() => settingsSection = settingsSection === 'fees' ? null : 'fees'}>
			Fees
		</button>
		<button class:active={settingsSection === 'config'} onclick={() => { settingsSection = settingsSection === 'config' ? null : 'config'; if (settingsSection === 'config') loadConfig(); }}>
			Backend Config
		</button>
	</div>

	{#if settingsSection === 'limits'}
		<div class="settings-panel">
			<h3>Deal Amount Limits</h3>
			<p class="hint">Configure minimum and maximum deal amounts.</p>
			{#if limits}
				<div class="limits-current">
					Current: <strong>{formatSats(limits.min_sats)}</strong> - <strong>{formatSats(limits.max_sats)}</strong>
				</div>
				<div class="field-row">
					<div class="field">
						<label for="edit-min-sats">Minimum (sats)</label>
						<input id="edit-min-sats" type="number" bind:value={editMinSats} />
					</div>
					<div class="field">
						<label for="edit-max-sats">Maximum (sats)</label>
						<input id="edit-max-sats" type="number" bind:value={editMaxSats} />
					</div>
				</div>
				<button onclick={handleUpdateLimits} disabled={limitsLoading}>
					{limitsLoading ? 'Updating...' : 'Update Limits'}
				</button>
				{#if limitsMessage}<p class="success-msg">{limitsMessage}</p>{/if}
				{#if limitsError}<p class="error">{limitsError}</p>{/if}
			{/if}
		</div>
	{/if}

	{#if settingsSection === 'fees'}
		<div class="settings-panel">
			<h3>Fee Settings</h3>
			<p class="hint">Configure service fee percentage.</p>
			<div class="limits-current">
				Current: <strong>{limits?.service_fee_percent ?? 1.0}%</strong> service fee
			</div>
			<div class="field-row">
				<div class="field">
					<label for="edit-service-fee">Service Fee (%)</label>
					<input id="edit-service-fee" type="number" step="0.1" min="0" max="10" bind:value={editServiceFee} />
				</div>
			</div>
			<button onclick={handleUpdateFees} disabled={feesLoading}>
				{feesLoading ? 'Updating...' : 'Update Fees'}
			</button>
			{#if feesMessage}<p class="success-msg">{feesMessage}</p>{/if}
			{#if feesError}<p class="error">{feesError}</p>{/if}
		</div>
	{/if}

	{#if settingsSection === 'config'}
		<div class="settings-panel">
			<h3>Backend Configuration</h3>
			{#if configLoading}
				<p>Loading...</p>
			{:else if configError}
				<p class="error">{configError}</p>
			{:else if config}
				<pre>{JSON.stringify(config, null, 2)}</pre>
			{:else}
				<button onclick={loadConfig}>Load Config</button>
			{/if}
		</div>
	{/if}
</div>

<style>
	h3 { color: var(--text); font-size: 1rem; margin: 0 0 1rem 0; }
	.tab-content { background: var(--surface); padding: 1.5rem; border-radius: 8px; border: 1px solid var(--border); }
	.settings-menu { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
	.settings-menu button { padding: 0.5rem 1rem; background: var(--bg); border: 1px solid var(--border); border-radius: 4px; color: var(--text-muted); cursor: pointer; }
	.settings-menu button.active { border-color: var(--accent); color: var(--accent); }
	.settings-panel { background: var(--bg); padding: 1.25rem; border-radius: 8px; }
	.settings-panel pre { background: var(--surface); padding: 1rem; border-radius: 4px; font-size: 0.75rem; overflow-x: auto; color: var(--text-muted); }
	.limits-current { background: var(--surface); padding: 0.75rem; border-radius: 4px; margin-bottom: 1rem; color: var(--text-muted); }
	.limits-current strong { color: var(--accent); }
	.field { margin-bottom: 1rem; }
	.field label { display: block; margin-bottom: 0.5rem; color: var(--text-muted); font-size: 0.875rem; }
	.field input { width: 100%; padding: 0.75rem; background: var(--bg); border: 1px solid var(--border-hover); border-radius: 4px; color: var(--text); box-sizing: border-box; }
	.field-row { display: flex; gap: 1rem; }
	.field-row .field { flex: 1; }
	button { padding: 0.75rem 1.25rem; background: var(--border); border: 1px solid var(--border-hover); border-radius: 4px; color: var(--text); cursor: pointer; }
	button:hover:not(:disabled) { background: var(--border-hover); }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	.hint { color: var(--text-dim); font-size: 0.875rem; }
	.error { color: var(--error); font-size: 0.875rem; }
	.success-msg { color: var(--success); font-size: 0.875rem; margin-top: 0.5rem; }
</style>
