<script>
	import { createLnInvoice, checkLnInvoice } from '$lib/api.js';
	import { copyToClipboard } from '$lib/utils/format.js';
	import { onMount, onDestroy } from 'svelte';

	let {
		deal,
		dealId,
		userRole,
		lndDown = false,
		QRCode = null,
		qrLoadFailed = false,
		signingStatus = null,
		onDealUpdate,
	} = $props();

	// Lightning invoice state
	let lnInvoice = $state(null);
	let lnInvoiceLoading = $state(false);
	let lnInvoiceError = $state('');
	let lnQrDataUrl = $state('');
	let invoicePolling = $state(null);
	let countdownTimer = $state(null);
	let invoiceCreatedAt = $state(null);
	let invoiceExpired = $state(false);
	let invoiceCountdown = $state('');
	let invoicePaid = $state(false);
	let pollFailures = $state(0);

	// Auto-create invoice
	let invoiceAutoCreated = $state(false);
	let createCountdown = $state(30);
	let createCountdownTimer = $state(null);

	onDestroy(() => {
		if (invoicePolling) clearInterval(invoicePolling);
		if (countdownTimer) clearInterval(countdownTimer);
		if (createCountdownTimer) clearInterval(createCountdownTimer);
	});

	// Auto-create invoice when buyer reaches deposit stage
	$effect(() => {
		if (
			deal &&
			userRole === 'buyer' &&
			!signingStatus?.funding_txid &&
			!lnInvoice &&
			!lnInvoiceLoading &&
			!invoiceAutoCreated &&
			!lndDown &&
			(QRCode || qrLoadFailed)
		) {
			invoiceAutoCreated = true;
			handleCreateLnInvoice();
		}
	});

	const INVOICE_TIMEOUT_MS = 30 * 60 * 1000;

	async function handleCreateLnInvoice() {
		if (lndDown) { lnInvoiceError = 'Lightning node is unreachable. Please try again later.'; return; }
		lnInvoiceLoading = true;
		lnInvoiceError = '';
		invoiceExpired = false;
		invoiceCountdown = '';
		createCountdown = 30;
		if (createCountdownTimer) clearInterval(createCountdownTimer);
		createCountdownTimer = setInterval(() => {
			if (createCountdown > 0) createCountdown--;
		}, 1000);
		try {
			const result = await createLnInvoice(dealId);
			lnInvoice = result;
			invoiceCreatedAt = Date.now();

			if (QRCode && result.bolt11) {
				lnQrDataUrl = await QRCode.toDataURL(result.bolt11.toUpperCase(), {
					width: 280,
					margin: 2,
					color: { dark: '#000000', light: '#ffffff' }
				});
			}

			startInvoicePolling();
		} catch (e) {
			lnInvoiceError = e.message;
		} finally {
			lnInvoiceLoading = false;
			if (createCountdownTimer) { clearInterval(createCountdownTimer); createCountdownTimer = null; }
		}
	}

	function startInvoicePolling() {
		if (invoicePolling) clearInterval(invoicePolling);
		invoicePolling = setInterval(async () => {
			if (invoiceCreatedAt && Date.now() - invoiceCreatedAt > INVOICE_TIMEOUT_MS) {
				clearInterval(invoicePolling);
				invoicePolling = null;
				invoiceExpired = true;
				lnQrDataUrl = '';
				return;
			}
			if (invoiceCreatedAt) {
				const remaining = INVOICE_TIMEOUT_MS - (Date.now() - invoiceCreatedAt);
				const mins = Math.floor(remaining / 60000);
				const secs = Math.floor((remaining % 60000) / 1000);
				invoiceCountdown = `${mins}:${secs.toString().padStart(2, '0')}`;
			}
			try {
				const status = await checkLnInvoice(dealId);
				pollFailures = 0;
				if (status.paid) {
					clearInterval(invoicePolling);
					invoicePolling = null;
					invoicePaid = true;
					lnInvoice = null;
					lnQrDataUrl = '';
					invoiceCountdown = '';
					// Non-custodial: secret_code was stored in localStorage at invoice-creation
					// time (generated in browser, never sent to server). Nothing to do here.
					await onDealUpdate();
				} else if (status.invoice_expired) {
					// Backend detected the LN receive operation failed/expired
					clearInterval(invoicePolling);
					invoicePolling = null;
					invoiceExpired = true;
					lnQrDataUrl = '';
				}
			} catch (e) {
				pollFailures++;
				if (pollFailures >= 10) {
					clearInterval(invoicePolling);
					invoicePolling = null;
					lnInvoiceError = 'Connection lost while waiting for payment. Please refresh.';
					return;
				}
				// Invoice check failed — will retry on next poll interval
			}
		}, 5000);
		// 1s countdown timer
		if (invoiceCreatedAt) {
			if (countdownTimer) clearInterval(countdownTimer);
			const updateCountdown = () => {
				if (!invoiceCreatedAt || invoiceExpired || !invoicePolling) return;
				const remaining = INVOICE_TIMEOUT_MS - (Date.now() - invoiceCreatedAt);
				if (remaining <= 0) return;
				const mins = Math.floor(remaining / 60000);
				const secs = Math.floor((remaining % 60000) / 1000);
				invoiceCountdown = `${mins}:${secs.toString().padStart(2, '0')}`;
			};
			updateCountdown();
			countdownTimer = setInterval(() => {
				if (!invoicePolling) { clearInterval(countdownTimer); countdownTimer = null; return; }
				updateCountdown();
			}, 1000);
		}
	}

	function retryInvoice() {
		invoiceExpired = false;
		invoiceAutoCreated = false;
		lnInvoice = null;
		lnQrDataUrl = '';
		handleCreateLnInvoice();
	}

	async function copyInvoice() {
		if (lnInvoice?.bolt11) {
			await copyToClipboard(lnInvoice.bolt11);
		}
	}

	/** Called from parent when WS event fires (invoice paid / deal funded) */
	export function handleInvoicePaid() {
		if (invoicePolling) { clearInterval(invoicePolling); invoicePolling = null; }
		invoicePaid = true;
		lnInvoice = null;
		lnQrDataUrl = '';
		invoiceCountdown = '';
	}
</script>

<h2>Awaiting Deposit</h2>

{#if userRole === 'buyer'}
	{#if invoicePaid}
		<div class="payment-received">
			<div class="checkmark">&#10003;</div>
			<p class="received-text">Payment received!</p>
			<div class="loading-spinner"><div class="spinner-small"></div></div>
			<p class="hint">Locking funds in Fedimint escrow... this can take 10-30 seconds.</p>
		</div>
	{:else if invoiceExpired}
		<p class="error">Invoice expired. Please create a new one.</p>
		<button class="btn primary" onclick={retryInvoice}>Create New Invoice</button>
	{:else if lnInvoice}
		<p class="invoice-hint">Scan with your Lightning wallet to pay</p>
		{#if lnQrDataUrl}
			<div class="qr-wrapper">
				<div class="qr-container">
					<img src={lnQrDataUrl} alt="Lightning Invoice QR" />
				</div>
			</div>
		{/if}
		<div class="invoice-amount">{lnInvoice.amount_sats?.toLocaleString()} sats</div>
		{#if lnInvoice.service_fee_sats != null}
			<div class="fee-breakdown">
				<span>{lnInvoice.price_sats?.toLocaleString()} deal</span>
				{#if lnInvoice.service_fee_sats}<span>+ {lnInvoice.service_fee_sats?.toLocaleString()} service</span>{/if}
			</div>
		{/if}
		<div class="invoice-actions">
			<button class="btn" onclick={copyInvoice}>Copy Invoice</button>
		</div>
		<p class="invoice-status">Waiting for payment...{#if invoiceCountdown} <span class="invoice-timer">({invoiceCountdown})</span>{/if}</p>
	{:else if lnInvoiceError}
		<p class="error">{lnInvoiceError}</p>
		<p class="hint">Unable to generate invoice. Please refresh and try again.</p>
	{:else}
		<div class="create-progress">
			<div class="spinner-ring">
				<svg viewBox="0 0 60 60">
					<circle cx="30" cy="30" r="26" class="ring-bg" />
					<circle cx="30" cy="30" r="26" class="ring-fg" style="stroke-dashoffset: {163.4 * (createCountdown / 30)}" />
				</svg>
				<span class="countdown-number">{createCountdown > 0 ? createCountdown : '...'}</span>
			</div>
			{#if createCountdown > 0}
				<p>Creating Lightning invoice...</p>
			{:else}
				<p class="overtime">Taking longer than usual...</p>
			{/if}
		</div>
	{/if}
{:else}
	<div class="invoice-amount">{deal.price_sats?.toLocaleString()} sats</div>
	<p class="invoice-status">Waiting for buyer to pay...</p>
{/if}

<style>
	.btn {
		padding: 0.6rem 1.25rem;
		border-radius: 6px;
		border: 1px solid var(--border-hover);
		font-size: 0.95rem;
		cursor: pointer;
		background: var(--border);
		color: var(--text);
	}
	.btn:hover { background: var(--border-hover); }
	.btn.primary {
		background: var(--accent);
		color: var(--bg);
		font-weight: 600;
		border: none;
	}
	.btn.primary:hover { background: var(--accent-hover); }

	.hint { color: var(--text-muted); font-size: 0.8rem; }
	.error { color: var(--error); font-size: 0.8rem; margin-top: 0.75rem; }

	.qr-wrapper {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: center;
		margin: 1rem auto;
		width: fit-content;
	}
	.qr-container {
		background: white;
		padding: 1rem;
		border-radius: 12px;
		display: block;
		width: fit-content;
	}
	.qr-container img {
		display: block;
		width: 220px;
		height: 220px;
		border-radius: 4px;
	}
	.invoice-hint, .invoice-amount, .invoice-actions, .invoice-status {
		text-align: center;
	}
	.invoice-hint { color: var(--text-muted); font-size: 0.95rem; margin-bottom: 0.5rem; }
	.invoice-amount {
		font-size: 1.5rem;
		font-weight: 600;
		color: var(--accent);
		margin: 0.5rem 0;
	}
	.fee-breakdown {
		text-align: center;
		font-size: 0.75rem;
		color: var(--text-muted);
		margin-bottom: 0.5rem;
		display: flex;
		justify-content: center;
		gap: 0.5rem;
	}
	.invoice-actions { margin: 1rem 0; }
	.invoice-status {
		color: var(--accent);
		font-size: 0.8rem;
		animation: pulse-text 2s ease-in-out infinite;
	}
	@keyframes pulse-text {
		0%, 100% { opacity: 0.6; }
		50% { opacity: 1; }
	}
	.invoice-timer { color: var(--text-muted); font-size: 0.8rem; }

	.spinner-small {
		width: 28px; height: 28px;
		border: 3px solid var(--border);
		border-top: 3px solid var(--accent);
		border-radius: 50%;
		animation: spin 1s linear infinite;
	}
	.loading-spinner {
		display: flex;
		justify-content: center;
		padding: 1.5rem 0;
	}
	@keyframes spin {
		0% { transform: rotate(0deg); }
		100% { transform: rotate(360deg); }
	}

	.payment-received { text-align: center; padding: 1rem 0; }
	.checkmark {
		font-size: 3rem;
		color: var(--success);
		margin-bottom: 0.5rem;
	}
	.payment-received .received-text {
		color: var(--success);
		font-size: 1.2rem;
		font-weight: 600;
		margin-bottom: 1rem;
	}

	.create-progress {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1rem;
		padding: 1.5rem 0;
	}
	.spinner-ring {
		position: relative;
		width: 72px;
		height: 72px;
	}
	.spinner-ring svg {
		width: 100%;
		height: 100%;
		transform: rotate(-90deg);
	}
	.ring-bg {
		fill: none;
		stroke: var(--border);
		stroke-width: 4;
	}
	.ring-fg {
		fill: none;
		stroke: var(--accent);
		stroke-width: 4;
		stroke-dasharray: 163.4;
		stroke-linecap: round;
		transition: stroke-dashoffset 1s linear;
	}
	.countdown-number {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 1.3rem;
		font-weight: 600;
		color: var(--text);
	}

	h2 { color: var(--text); font-size: 1.1rem; margin: 0 0 0.5rem 0; }
	p { color: var(--text-muted); font-size: 0.95rem; margin: 0 0 1rem 0; }
	.overtime {
		color: var(--text-muted);
		font-size: 0.85rem;
		animation: pulse-text 2s ease-in-out infinite;
	}
</style>
