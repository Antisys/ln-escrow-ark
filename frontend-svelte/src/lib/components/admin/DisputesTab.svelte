<script>
	import { onMount } from 'svelte';
	import { getDeal, getAdminDisputes, getAdminFailedPayouts, adminResolveRelease, adminResolveRefund, adminOracleSign } from '$lib/api.js';
	import { signOracleAttestation } from '$lib/crypto.js';
	import { getStatusColor } from '$lib/utils/format.js';

	let {
		adminPubkey,
		lndDown = false,
	} = $props();

	let disputes = $state([]);
	let disputesLoading = $state(false);
	let disputesError = $state('');

	let failedPayouts = $state([]);

	let selectedDeal = $state(null);
	let dealLoading = $state(false);
	let dealError = $state('');

	let resolutionNote = $state('');
	let resolving = $state(false);
	let resolveError = $state('');
	let resolveMessage = $state('');

	let confirmAction = $state(null);
	let showConfirmDialog = $state(false);

	// Oracle signing
	let oraclePrivkey = $state('');
	let oracleOutcome = $state('seller');
	let oracleReason = $state('');
	let oracleSigning = $state(false);
	let oracleError = $state('');
	let oracleResult = $state(null);

	async function executeOracleSign() {
		if (!selectedDeal || !oraclePrivkey) return;
		if (!selectedDeal.fedimint_escrow_id) { oracleError = 'No escrow ID on this deal'; return; }
		oracleSigning = true;
		oracleError = '';
		oracleResult = null;
		try {
			// Sign locally in the browser — private key NEVER sent to server
			const signedEvent = signOracleAttestation(
				oraclePrivkey,
				selectedDeal.fedimint_escrow_id,
				oracleOutcome,
				oracleReason || null
			);
			oracleResult = await adminOracleSign(
				selectedDeal.deal_id,
				adminPubkey,
				signedEvent
			);
		} catch (e) {
			oracleError = e.message;
		} finally {
			oracleSigning = false;
		}
	}

	onMount(() => loadDisputes());

	export async function loadDisputes() {
		if (!adminPubkey) return;
		disputesLoading = true;
		disputesError = '';
		try {
			const [disputeResult, failedResult] = await Promise.all([
				getAdminDisputes(adminPubkey),
				getAdminFailedPayouts(adminPubkey).catch(() => ({ deals: [] }))
			]);
			disputes = disputeResult.deals;
			failedPayouts = failedResult.deals;
		} catch (e) {
			disputesError = e.message;
		} finally {
			disputesLoading = false;
		}
	}

	async function selectDeal(dealId) {
		dealLoading = true;
		dealError = '';
		resolveError = '';
		resolveMessage = '';
		resolutionNote = '';
		try {
			selectedDeal = await getDeal(dealId);
		} catch (e) {
			dealError = e.message;
		} finally {
			dealLoading = false;
		}
	}

	function requestRelease() { confirmAction = 'release'; showConfirmDialog = true; }
	function requestRefund() { confirmAction = 'refund'; showConfirmDialog = true; }
	function cancelConfirm() { showConfirmDialog = false; confirmAction = null; }

	async function confirmResolve() {
		showConfirmDialog = false;
		if (confirmAction === 'release') await executeRelease();
		else if (confirmAction === 'refund') await executeRefund();
		confirmAction = null;
	}

	async function executeRelease() {
		if (!selectedDeal) return;
		if (lndDown) { resolveError = 'Cannot resolve: Lightning node is unreachable.'; return; }
		resolving = true; resolveError = ''; resolveMessage = '';
		try {
			const result = await adminResolveRelease(selectedDeal.deal_id, adminPubkey, resolutionNote);
			resolveMessage = 'Released to seller!' + (result.txid ? ` (ref: ${result.txid.slice(0, 12)}…)` : '');
			loadDisputes();
			selectDeal(selectedDeal.deal_id);
		} catch (e) {
			resolveError = e.message;
		} finally {
			resolving = false;
		}
	}

	async function executeRefund() {
		if (!selectedDeal) return;
		if (lndDown) { resolveError = 'Cannot resolve: Lightning node is unreachable.'; return; }
		resolving = true; resolveError = ''; resolveMessage = '';
		try {
			const result = await adminResolveRefund(selectedDeal.deal_id, adminPubkey, resolutionNote);
			resolveMessage = 'Refunded to buyer!' + (result.txid ? ` (ref: ${result.txid.slice(0, 12)}…)` : '');
			loadDisputes();
			selectDeal(selectedDeal.deal_id);
		} catch (e) {
			resolveError = e.message;
		} finally {
			resolving = false;
		}
	}
</script>

<div class="tab-content">
	{#if failedPayouts.length > 0}
		<div class="failed-payouts-alert">
			<strong>Failed Payouts ({failedPayouts.length})</strong>
			<p>Payout failed for these deals. Retry or process manually.</p>
			<div class="failed-list">
				{#each failedPayouts as fp}
					<button class="failed-row" onclick={() => selectDeal(fp.deal_id)}>
						<span class="failed-title">{fp.title}</span>
						<span class="failed-amount">{fp.price_sats?.toLocaleString()} sats</span>
						<span class="failed-status">{fp.status}</span>
					</button>
				{/each}
			</div>
		</div>
	{/if}

	<div class="panel-header">
		<h2>Disputed Deals</h2>
		<button onclick={loadDisputes} disabled={disputesLoading}>
			{disputesLoading ? 'Loading...' : 'Refresh'}
		</button>
	</div>

	{#if disputesError}
		<p class="error">{disputesError}</p>
	{/if}

	<div class="two-column">
		<div class="deals-list">
			{#if disputes.length === 0 && !disputesLoading}
				<p class="empty">No disputes to resolve</p>
			{/if}
			{#each disputes as d}
				<button
					class="deal-row"
					class:selected={selectedDeal?.deal_id === d.deal_id}
					onclick={() => selectDeal(d.deal_id)}
				>
					<div class="deal-row-main">
						<span class="deal-row-title">{d.title}</span>
						<span class="deal-row-amount">{d.price_sats?.toLocaleString() ?? 0} sats</span>
					</div>
					<div class="deal-row-details">
						<span>Disputed: {new Date(d.disputed_at).toLocaleDateString()}</span>
						<span class="deal-row-meta">
							{#if d.seller_name}<span class="creator-tag">by {d.seller_name}</span>{/if}
							{#if d.timeout_action}
								<span class="beneficiary-tag {d.timeout_action === 'refund' ? 'ben-buyer' : 'ben-seller'}">
									{d.timeout_action === 'refund' ? 'B' : 'S'}
								</span>
							{/if}
						</span>
					</div>
				</button>
			{/each}
		</div>

		<div class="deal-detail">
			{#if dealLoading}
				<p class="loading">Loading deal...</p>
			{:else if dealError}
				<p class="error">{dealError}</p>
			{:else if selectedDeal}
				<div class="detail-card">
					<h3>{selectedDeal.title}</h3>
					<div class="detail-status" style="color: {getStatusColor(selectedDeal.status)}">
						{selectedDeal.status.toUpperCase()}
					</div>

					<div class="detail-info">
						<div class="info-row">
							<span class="label">Amount:</span>
							<span class="value">{selectedDeal.price_sats?.toLocaleString() ?? 0} sats</span>
						</div>
						<div class="info-row">
							<span class="label">Seller:</span>
							<span class="value">{selectedDeal.seller_name || selectedDeal.seller_id?.slice(0, 8) || '-'}</span>
						</div>
						<div class="info-row">
							<span class="label">Buyer:</span>
							<span class="value">{selectedDeal.buyer_name || selectedDeal.buyer_id?.slice(0, 8) || '-'}</span>
						</div>
						<div class="info-row">
							<span class="label">Timeout beneficiary:</span>
							<span class="value" style="color: {selectedDeal.timeout_action === 'refund' ? 'var(--info)' : 'var(--orange)'}">
								{selectedDeal.timeout_action === 'refund' ? 'Buyer (refund)' : 'Seller (release)'}
							</span>
						</div>
						{#if selectedDeal.description}
							<div class="info-row vertical">
								<span class="label">Description:</span>
								<span class="value reason">{selectedDeal.description}</span>
							</div>
						{/if}
						{#if selectedDeal.dispute_reason}
							<div class="info-row vertical">
								<span class="label">Dispute Reason:</span>
								<span class="value reason dispute-highlight">{selectedDeal.dispute_reason}</span>
							</div>
						{/if}
						{#if selectedDeal.disputed_by}
							<div class="info-row">
								<span class="label">Disputed by:</span>
								<span class="value">{selectedDeal.disputed_by === selectedDeal.buyer_id ? 'Buyer' : 'Seller'}</span>
							</div>
						{/if}
					</div>

					<!-- Timeline -->
					<div class="detail-timeline">
						<h4>Timeline</h4>
						<div class="tl-row">
							<span class="tl-label">Created</span>
							<span class="tl-date">{new Date(selectedDeal.created_at).toLocaleString()}</span>
						</div>
						{#if selectedDeal.funded_at}
							<div class="tl-row">
								<span class="tl-label">Funded</span>
								<span class="tl-date">{new Date(selectedDeal.funded_at).toLocaleString()}</span>
							</div>
						{/if}
						{#if selectedDeal.shipped_at}
							<div class="tl-row">
								<span class="tl-label">Shipped</span>
								<span class="tl-date">{new Date(selectedDeal.shipped_at).toLocaleString()}</span>
							</div>
						{/if}
						{#if selectedDeal.disputed_at}
							<div class="tl-row">
								<span class="tl-label">Disputed</span>
								<span class="tl-date">{new Date(selectedDeal.disputed_at).toLocaleString()}</span>
							</div>
						{/if}
					</div>

					<!-- Shipping info -->
					{#if selectedDeal.tracking_carrier || selectedDeal.tracking_number || selectedDeal.shipping_notes}
						<div class="detail-shipping">
							<h4>Shipping</h4>
							{#if selectedDeal.tracking_carrier}
								<div class="info-row">
									<span class="label">Carrier:</span>
									<span class="value">{selectedDeal.tracking_carrier}</span>
								</div>
							{/if}
							{#if selectedDeal.tracking_number}
								<div class="info-row">
									<span class="label">Tracking:</span>
									<span class="value mono">{selectedDeal.tracking_number}</span>
								</div>
							{/if}
							{#if selectedDeal.shipping_notes}
								<div class="info-row vertical">
									<span class="label">Notes:</span>
									<span class="value">{selectedDeal.shipping_notes}</span>
								</div>
							{/if}
						</div>
					{/if}

					<!-- Payout status -->
					<div class="detail-payouts">
						<div class="info-row">
							<span class="label">Seller payout:</span>
							<span class="value {selectedDeal.has_seller_payout_invoice ? 'payout-set' : 'payout-unset'}">
								{selectedDeal.has_seller_payout_invoice ? 'Set' : 'Not set'}
							</span>
						</div>
						<div class="info-row">
							<span class="label">Buyer refund addr:</span>
							<span class="value {selectedDeal.has_buyer_payout_invoice ? 'payout-set' : 'payout-unset'}">
								{selectedDeal.has_buyer_payout_invoice ? 'Set' : 'Not set'}
							</span>
						</div>
					</div>

					{#if selectedDeal.status === 'disputed'}
						<div class="oracle-section">
							<h4>Oracle Sign & Publish</h4>
							<div class="field">
								<label>Outcome</label>
								<div class="outcome-toggle">
									<button class="toggle-btn" class:active={oracleOutcome === 'seller'} onclick={() => oracleOutcome = 'seller'}>
										Seller
									</button>
									<button class="toggle-btn" class:active={oracleOutcome === 'buyer'} onclick={() => oracleOutcome = 'buyer'}>
										Buyer
									</button>
								</div>
							</div>
							<div class="field">
								<label for="oracle-reason">Reason (optional)</label>
								<textarea id="oracle-reason" bind:value={oracleReason} placeholder="Why this outcome..." rows="2"></textarea>
							</div>
							<div class="field">
								<label for="oracle-privkey">Oracle Private Key</label>
								<input type="password" id="oracle-privkey" bind:value={oraclePrivkey} placeholder="32-byte hex (signs locally, never sent to server)" />
							</div>
							<button class="btn oracle" onclick={executeOracleSign} disabled={!oraclePrivkey || oracleSigning || oraclePrivkey.length !== 64}>
								{oracleSigning ? 'Signing...' : 'Sign & Publish'}
							</button>
							{#if oracleError}
								<p class="error" style="margin-top: 0.5rem">{oracleError}</p>
							{/if}
							{#if oracleResult}
								<div class="oracle-result">
									<div class="oracle-result-header">Published to {oracleResult.published}/{oracleResult.total} relays</div>
									<div class="oracle-result-id">Event: {oracleResult.event_id?.slice(0, 16)}...</div>
									<div class="oracle-result-id">Pubkey: {oracleResult.pubkey?.slice(0, 16)}...</div>
									{#if oracleResult.relays}
										{#each oracleResult.relays as r}
											<div class="relay-row">
												<span class={r.ok ? 'relay-ok' : 'relay-fail'}>{r.ok ? '✓' : '✗'}</span>
												<span class="relay-url">{r.url}</span>
												{#if r.message}<span class="relay-msg">{r.message}</span>{/if}
											</div>
										{/each}
									{/if}
								</div>
							{/if}

							<!-- Admin resolve (after oracle consensus reached) -->
							<div class="resolution-buttons" style="margin-top: 1rem">
								<button class="btn success" onclick={requestRelease} disabled={resolving}>
									Release to Seller
								</button>
								<button class="btn danger" onclick={requestRefund} disabled={resolving}>
									Refund to Buyer
								</button>
							</div>
							{#if resolveError}<p class="error" style="margin-top: 0.5rem">{resolveError}</p>{/if}
							{#if resolveMessage}<p class="success-msg">{resolveMessage}</p>{/if}
						</div>
					{/if}
				</div>
			{:else}
				<p class="hint">Select a dispute to view details</p>
			{/if}
		</div>
	</div>
</div>

<!-- Confirmation Dialog -->
{#if showConfirmDialog}
	<div class="confirm-overlay" onclick={cancelConfirm} role="presentation" tabindex="-1" onkeydown={(e) => e.key === 'Escape' && cancelConfirm()}>
		<div class="confirm-dialog" onclick={(e) => e.stopPropagation()} role="dialog" tabindex="-1" onkeydown={(e) => e.stopPropagation()}>
			<h3>Confirm {confirmAction === 'release' ? 'Release' : 'Refund'}</h3>
			<p class="confirm-warning">
				{#if confirmAction === 'release'}
					You are about to <strong>release funds to the seller</strong>.
					This action cannot be undone.
				{:else}
					You are about to <strong>refund funds to the buyer</strong>.
					This action cannot be undone.
				{/if}
			</p>
			<div class="confirm-deal-info">
				<div>Deal: <strong>{selectedDeal?.title}</strong></div>
				<div>Amount: <strong>{(selectedDeal?.price_sats || 0).toLocaleString()} sats</strong></div>
			</div>
			<div class="confirm-buttons">
				<button class="btn secondary" onclick={cancelConfirm}>Cancel</button>
				<button
					class="btn {confirmAction === 'release' ? 'success' : 'danger'}"
					onclick={confirmResolve}
				>
					Confirm {confirmAction === 'release' ? 'Release' : 'Refund'}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.failed-payouts-alert {
		background: var(--error-bg); border: 1px solid var(--error); border-radius: 8px;
		padding: 1rem; margin-bottom: 1rem;
	}
	.failed-payouts-alert strong { color: var(--error); font-size: 1rem; }
	.failed-payouts-alert p { color: var(--text); font-size: 0.85rem; margin: 0.25rem 0 0.75rem; }
	.failed-list { display: flex; flex-direction: column; gap: 0.35rem; }
	.failed-row {
		display: flex; justify-content: space-between; align-items: center;
		padding: 0.5rem 0.75rem; background: #2a1a1a; border: 1px solid #5a2a2a;
		border-radius: 4px; cursor: pointer; color: var(--text); text-align: left;
	}
	.failed-row:hover { border-color: var(--error); }
	.failed-title { flex: 1; font-size: 0.85rem; }
	.failed-amount { color: var(--orange); font-size: 0.85rem; margin: 0 0.75rem; }
	.failed-status { color: var(--error); font-size: 0.75rem; text-transform: uppercase; }

	h2 { color: var(--text); font-size: 1.125rem; margin: 0; }
	h3 { color: var(--text); font-size: 1rem; margin: 0 0 1rem 0; }
	h4 { color: var(--text-muted); font-size: 0.9rem; margin: 0 0 0.75rem 0; }
	.tab-content { background: var(--surface); padding: 1.5rem; border-radius: 8px; border: 1px solid var(--border); }
	.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
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
	.info-row.vertical { flex-direction: column; gap: 0.25rem; }
	.info-row .label { color: var(--text-dim); }
	.info-row .value { color: var(--text); }
	.info-row .value.mono { font-family: monospace; font-size: 0.8rem; }
	.info-row .value.reason { background: var(--surface); padding: 0.5rem; border-radius: 4px; font-size: 0.85rem; }
	.dispute-highlight { border-left: 3px solid var(--error); padding-left: 0.5rem; }
	.detail-timeline, .detail-shipping, .detail-payouts { border-top: 1px solid var(--border); padding-top: 0.75rem; margin-top: 0.75rem; }
	.detail-timeline h4, .detail-shipping h4 { color: var(--text-muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }
	.tl-row { display: flex; justify-content: space-between; font-size: 0.8rem; padding: 0.2rem 0; }
	.tl-label { color: var(--text-muted); }
	.tl-date { color: #bbb; }
	.payout-set { color: var(--success); }
	.payout-unset { color: var(--text-dim); }
	.resolution-section { border-top: 1px solid var(--border); padding-top: 1rem; margin-top: 1rem; }
	.resolution-section h4 { color: var(--accent); }
	.resolution-buttons { display: flex; gap: 0.75rem; margin-top: 1rem; }
	.field { margin-bottom: 1rem; }
	.field label { display: block; margin-bottom: 0.5rem; color: var(--text-muted); font-size: 0.875rem; }
	.field textarea { width: 100%; padding: 0.75rem; background: var(--bg); border: 1px solid var(--border-hover); border-radius: 4px; color: var(--text); min-height: 60px; resize: vertical; box-sizing: border-box; }
	button { padding: 0.75rem 1.25rem; background: var(--border); border: 1px solid var(--border-hover); border-radius: 4px; color: var(--text); cursor: pointer; }
	button:hover:not(:disabled) { background: var(--border-hover); }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	.btn.success { background: var(--success); border-color: var(--success); color: var(--bg); }
	.btn.danger { background: var(--error); border-color: var(--error); color: white; }
	.btn.secondary { background: var(--border); }
	.error { color: var(--error); font-size: 0.875rem; }
	.success-msg { color: var(--success); font-size: 0.875rem; margin-top: 0.5rem; }
	.hint { color: var(--text-dim); font-size: 0.875rem; }
	.empty { color: var(--text-dim); text-align: center; padding: 2rem; }
	.loading { color: var(--text-muted); text-align: center; padding: 2rem; }
	.confirm-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0, 0, 0, 0.8); display: flex; align-items: center; justify-content: center; z-index: 1000; }
	.confirm-dialog { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1.5rem; max-width: 400px; width: 90%; }
	.confirm-dialog h3 { color: var(--text); margin-bottom: 1rem; }
	.confirm-warning { color: var(--text-muted); margin-bottom: 1rem; line-height: 1.5; }
	.confirm-warning strong { color: var(--orange); }
	.confirm-deal-info { background: var(--bg); padding: 0.75rem; border-radius: 4px; margin-bottom: 1rem; font-size: 0.9rem; color: var(--text-muted); }
	.confirm-deal-info strong { color: var(--text); }
	.confirm-buttons { display: flex; gap: 0.75rem; justify-content: flex-end; }
	.oracle-section { border-top: 1px solid var(--border); padding-top: 1rem; margin-top: 1rem; }
	.oracle-section h4 { color: #a78bfa; }
	.field input[type="password"] { width: 100%; padding: 0.75rem; background: var(--bg); border: 1px solid var(--border-hover); border-radius: 4px; color: var(--text); font-family: monospace; font-size: 0.85rem; box-sizing: border-box; }
	.outcome-toggle { display: flex; gap: 0.5rem; }
	.toggle-btn { padding: 0.5rem 1.25rem; background: var(--bg); border: 1px solid var(--border-hover); border-radius: 4px; color: var(--text-muted); cursor: pointer; font-size: 0.85rem; }
	.toggle-btn.active { border-color: #a78bfa; color: #a78bfa; background: #1a1a2a; }
	.btn.oracle { background: #7c3aed; border-color: #7c3aed; color: white; margin-top: 0.75rem; }
	.btn.oracle:hover:not(:disabled) { background: #6d28d9; }
	.oracle-result { margin-top: 0.75rem; background: var(--bg); border-radius: 4px; padding: 0.75rem; font-size: 0.8rem; }
	.oracle-result-header { color: #a78bfa; font-weight: 600; margin-bottom: 0.25rem; }
	.oracle-result-id { color: var(--text-dim); font-family: monospace; font-size: 0.75rem; margin-bottom: 0.5rem; }
	.relay-row { display: flex; gap: 0.5rem; align-items: center; padding: 0.15rem 0; font-family: monospace; font-size: 0.75rem; }
	.relay-ok { color: var(--success); }
	.relay-fail { color: var(--error); }
	.relay-url { color: var(--text-muted); }
	.relay-msg { color: var(--text-dim); font-size: 0.7rem; }
	@media (max-width: 768px) { .two-column { grid-template-columns: 1fr; } }
</style>
