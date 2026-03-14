<script>
	import { onMount } from 'svelte';
	import { getAdminConfig, getSystemStatus } from '$lib/api.js';
	import AdminLogin from '$lib/components/admin/AdminLogin.svelte';
	import BalancesBar from '$lib/components/admin/BalancesBar.svelte';
	import DisputesTab from '$lib/components/admin/DisputesTab.svelte';
	import DealsTab from '$lib/components/admin/DealsTab.svelte';
	import LedgerTab from '$lib/components/admin/LedgerTab.svelte';
	import SettingsTab from '$lib/components/admin/SettingsTab.svelte';

	let QRCode = $state(null);

	// Auth state
	let adminPubkey = $state(null);
	let isAuthenticated = $derived(!!adminPubkey);

	// UI state
	let activeTab = $state('disputes');

	// Config state (needed for BalancesBar)
	let config = $state(null);

	// System status
	let systemStatus = $state(null);
	let lndDown = $derived(systemStatus && !systemStatus.services?.gateway?.ok);

	let qrLoadFailed = $state(false);

	onMount(async () => {
		try {
			const qrModule = await import('qrcode');
			QRCode = qrModule.default;
		} catch {
			qrLoadFailed = true;
		}
		getSystemStatus().then(s => systemStatus = s).catch(() => {});
	});

	function handleAuthenticated(pubkey) {
		adminPubkey = pubkey;
		loadConfig();
	}

	async function loadConfig() {
		if (!adminPubkey) return;
		try {
			config = await getAdminConfig(adminPubkey);
		} catch {
			// Config load failed — BalancesBar will show empty state
		}
	}

	function logout() {
		adminPubkey = null;
		config = null;
	}
</script>

<svelte:head>
	<title>Referee Panel - trustMeBro-ARK</title>
</svelte:head>

<div class="admin-page">
	<div class="admin-header">
		<h1>Referee Panel</h1>
		{#if isAuthenticated}
			<button class="btn-logout" onclick={logout}>Logout</button>
		{/if}
	</div>

	{#if !isAuthenticated}
		{#if QRCode || qrLoadFailed}
			<AdminLogin QRCode={QRCode} onAuthenticated={handleAuthenticated} />
		{:else}
			<div class="loading-qr"><div class="spinner"></div></div>
		{/if}
	{:else}
		<!-- Tab Navigation -->
		<div class="admin-tabs">
			<button class:active={activeTab === 'disputes'} onclick={() => activeTab = 'disputes'}>
				Disputes
			</button>
			<button class:active={activeTab === 'deals'} onclick={() => activeTab = 'deals'}>
				All Deals
			</button>
			<button class:active={activeTab === 'ledger'} onclick={() => activeTab = 'ledger'}>
				Ledger
			</button>
			<button class:active={activeTab === 'settings'} onclick={() => activeTab = 'settings'}>
				Settings
			</button>
		</div>

		<BalancesBar {config} />

		{#if lndDown}
			<div class="system-warning">
				<strong>Service degraded</strong>
				<p>Lightning node is unreachable. Payouts after resolution will fail.</p>
			</div>
		{/if}

		{#if activeTab === 'disputes'}
			<DisputesTab {adminPubkey} {lndDown} />
		{:else if activeTab === 'deals'}
			<DealsTab {adminPubkey} />
		{:else if activeTab === 'ledger'}
			<LedgerTab {adminPubkey} />
		{:else if activeTab === 'settings'}
			<SettingsTab {adminPubkey} />
		{/if}
	{/if}
</div>

<style>
	.admin-page { max-width: 1000px; width: 100%; margin: 0 auto; }
	.admin-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }
	h1 { color: var(--accent); margin: 0; }
	.btn-logout {
		padding: 0.5rem 1rem; background: transparent; border: 1px solid var(--text-dim);
		border-radius: 4px; color: var(--text-muted); cursor: pointer;
	}
	.btn-logout:hover { border-color: var(--error); color: var(--error); }
	.admin-tabs { display: flex; gap: 0.5rem; margin-bottom: 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }
	.admin-tabs button {
		padding: 0.75rem 1.5rem; background: transparent; border: none;
		border-radius: 4px 4px 0 0; color: var(--text-muted); cursor: pointer;
	}
	.admin-tabs button.active { background: var(--surface); color: var(--accent); }
	.system-warning {
		background: #3a2a00; border: 1px solid var(--orange); border-radius: 8px;
		padding: 0.75rem 1rem; margin-bottom: 1rem; color: var(--orange);
	}
	.system-warning strong { display: block; margin-bottom: 0.25rem; }
	.system-warning p { margin: 0; font-size: 0.875rem; color: #cca050; }

	.loading-qr { text-align: center; padding: 3rem; }
	.spinner {
		width: 32px; height: 32px;
		border: 3px solid var(--border); border-top-color: var(--accent);
		border-radius: 50%; animation: spin 1s linear infinite;
		margin: 0 auto;
	}
	@keyframes spin { to { transform: rotate(360deg); } }

	@media (max-width: 768px) {
		.admin-tabs { flex-wrap: wrap; }
	}
</style>
