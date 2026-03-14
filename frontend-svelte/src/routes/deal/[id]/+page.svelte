<script>
	import { page } from '$app/stores';
	import { onMount, onDestroy } from 'svelte';
	import { dealKeys, dealAuths, getAuthForDeal, dealSecretCodes, getSecretCodeForDeal, clearSecretCodeForDeal, getRolesForDeal, switchActiveRole } from '$lib/stores/vault.js';
	import { navAuth, clearNavAuth } from '$lib/stores/nav.js';
	import { getDeal, getSigningStatus, connectDealWs, getSystemStatus, releaseDeal } from '$lib/api.js';
	import { getVisitorId, signAction, signForRelease } from '$lib/crypto.js';
	import { getStatusLabel, getStatusPillClass, friendlyError, copyToClipboard } from '$lib/utils/format.js';
	import LnurlSign from '$lib/components/LnurlSign.svelte';
	import FundingPanel from '$lib/components/deal/FundingPanel.svelte';
	import PayoutForm from '$lib/components/deal/PayoutForm.svelte';
	import DisputeModal from '$lib/components/deal/DisputeModal.svelte';
	import CompletedPanel from '$lib/components/deal/CompletedPanel.svelte';
	import ResolutionPanel from '$lib/components/deal/ResolutionPanel.svelte';
	import DisputedPanel from '$lib/components/deal/DisputedPanel.svelte';
	import DealDetails from '$lib/components/deal/DealDetails.svelte';
	import ReleaseConfirmModal from '$lib/components/deal/ReleaseConfirmModal.svelte';
	import PayoutTimer from '$lib/components/deal/PayoutTimer.svelte';

	let dealId = $derived($page.params.id);
	let deal = $state(null);
	let signingStatus = $state(null);
	let initialLoading = $state(true);
	let error = $state('');
	let actionMessage = $state('');
	let actionError = $state('');
	let actionErrorTimer = null;

	const MAX_POLL_ERRORS = 20;
	const POLL_INTERVAL_MS = 15000;
	const ERROR_DISPLAY_MS = 8000;

	function setActionError(msg) {
		actionError = msg;
		if (actionErrorTimer) clearTimeout(actionErrorTimer);
		// Network errors are transient — auto-clear so users can retry
		if (msg && (msg.toLowerCase().includes('network') || msg.toLowerCase().includes('connection'))) {
			actionErrorTimer = setTimeout(() => { actionError = ''; }, ERROR_DISPLAY_MS);
		}
	}
	let showSignModal = $state(false);
	let signRole = $state(null);
	let linkCopied = $state(false);
	let pollingInterval = null;
	let pollConsecutiveErrors = 0;
	let showKeyRecovery = $state(false);

	// QRCode library (loaded in onMount, used by FundingPanel)
	let QRCode = $state(null);
	let qrLoadFailed = $state(false);

	// WebSocket connection
	let wsConn = $state(null);

	// System status (LND + Esplora)
	let systemStatus = $state(null);
	let statusInterval = null;
	let fedimintMode = $derived(systemStatus?.fedimint_mode === true);
	let lndDown = $derived(systemStatus && !systemStatus.services?.gateway?.ok);

	let readyToFund = $derived(signingStatus?.ready_for_funding);

	// Countdown timer state
	let countdownText = $state('');
	let countdownUrgent = $state(false);
	let countdownInterval = null;

	// Stale deploy detection
	let appStale = $state(false);

	let storedAuthEntry = $derived($dealAuths[dealId]);

	// Compute user role reactively (supports same user as both buyer+seller)
	let userRole = $derived.by(() => {
		if (!storedAuthEntry) {
			if (deal) {
				const visitorId = getVisitorId();
				if (deal.seller_id === visitorId) return 'seller';
				if (deal.buyer_id === visitorId) return 'buyer';
			}
			return null;
		}
		// New format: has activeRole
		if (storedAuthEntry.activeRole) return storedAuthEntry.activeRole;
		// Legacy format: has role directly
		if (storedAuthEntry.role) return storedAuthEntry.role;
		return null;
	});

	// All roles this user holds on this deal (for role switcher)
	let availableRoles = $derived.by(() => {
		if (!storedAuthEntry) return [];
		// New format
		if (storedAuthEntry.activeRole) {
			return ['seller', 'buyer'].filter(r => storedAuthEntry[r]);
		}
		// Legacy
		if (storedAuthEntry.role) return [storedAuthEntry.role];
		return [];
	});

	// Derive key for the ACTIVE role (not just dealId)
	let storedKeyEntry = $derived($dealKeys[dealId]);
	let storedKey = $derived.by(() => {
		if (!storedKeyEntry) return null;
		// New format: keyed by role
		if (userRole && storedKeyEntry[userRole]?.privateKey) return storedKeyEntry[userRole];
		// Legacy format: direct {privateKey, publicKey}
		if (storedKeyEntry.privateKey) return storedKeyEntry;
		return null;
	});

	let storedAuth = $derived.by(() => {
		if (!storedAuthEntry) return null;
		// New format
		if (storedAuthEntry.activeRole) {
			const role = storedAuthEntry.activeRole;
			const roleData = storedAuthEntry[role];
			return roleData ? { role, linkingKey: roleData.linkingKey, userId: roleData.userId } : null;
		}
		// Legacy
		return storedAuthEntry;
	});

	// Component refs
	let fundingPanelRef = $state(null);

	// Dispute modal state
	let showDisputeModal = $state(false);

	// Release state
	let releaseInProgress = $state(false);
	let showReleaseConfirm = $state(false);

	onMount(async () => {
		try {
			const qrModule = await import('qrcode');
			QRCode = qrModule.default;
		} catch {
			// QR library failed to load — set a sentinel so FundingPanel doesn't block on it
			QRCode = null;
			qrLoadFailed = true;
		}

		const pollStatus = () => getSystemStatus().then(s => systemStatus = s).catch(() => {});
		pollStatus();
		statusInterval = setInterval(pollStatus, 30000);

		await loadDeal(true);

		wsConn = connectDealWs(dealId, (event, data) => {
			if (event === 'invoice:paid' || event === 'deal:funded') {
				fundingPanelRef?.handleInvoicePaid();
			}
			loadDeal(false);
		});

		pollingInterval = setInterval(() => loadDeal(false), POLL_INTERVAL_MS);
	});

	onDestroy(() => {
		if (wsConn) wsConn.close();
		if (pollingInterval) clearInterval(pollingInterval);
		if (countdownInterval) clearInterval(countdownInterval);
		if (statusInterval) clearInterval(statusInterval);
		clearNavAuth();
	});

	// Update nav auth when deal/auth state changes
	$effect(() => {
		if (!deal) {
			clearNavAuth();
			return;
		}
		navAuth.set({
			role: userRole,
			deal: deal,
		});
	});

	// Countdown timer for deal expiry
	function updateCountdown() {
		if (!deal?.expires_at) {
			countdownText = '';
			return;
		}
		const now = new Date();
		const expires = new Date(deal.expires_at + (deal.expires_at.endsWith('Z') ? '' : 'Z'));
		const diff = expires - now;
		if (diff <= 0) {
			countdownText = 'Expired';
			countdownUrgent = true;
			return;
		}
		const hours = Math.floor(diff / 3600000);
		const minutes = Math.floor((diff % 3600000) / 60000);
		if (hours >= 48) {
			const days = Math.floor(hours / 24);
			const remHours = hours % 24;
			countdownText = `${days}d ${remHours}h remaining`;
		} else {
			countdownText = `${hours}h ${minutes}m remaining`;
		}
		countdownUrgent = hours < 24;
	}

	$effect(() => {
		const isFundedOrShipped = deal && ['funded', 'shipped'].includes(deal.status) && deal.expires_at;
		if (isFundedOrShipped) {
			updateCountdown();
			if (!countdownInterval) {
				countdownInterval = setInterval(updateCountdown, 30000);
			}
		} else {
			if (countdownInterval) {
				clearInterval(countdownInterval);
				countdownInterval = null;
			}
			countdownText = '';
		}
	});

	let loadDealInFlight = false;
	async function loadDeal(isInitial = false) {
		if (loadDealInFlight && !isInitial) return;
		loadDealInFlight = true;

		if (isInitial) {
			initialLoading = true;
			error = '';
		}
		try {
			const [newDeal, newSigningStatus] = await Promise.all([
				getDeal(dealId),
				getSigningStatus(dealId),
			]);

			deal = newDeal;
			signingStatus = newSigningStatus;
			pollConsecutiveErrors = 0;

			if (['completed', 'refunded', 'cancelled'].includes(newDeal.status)) {
				actionMessage = '';
				// Stop polling — deal is in terminal state
				if (pollingInterval) { clearInterval(pollingInterval); pollingInterval = null; }
				if (statusInterval) { clearInterval(statusInterval); statusInterval = null; }
				if (countdownInterval) { clearInterval(countdownInterval); countdownInterval = null; }
				// Safe to clear secret code now that payout is confirmed
				if (newDeal.payout_status === 'paid' || newDeal.buyer_payout_status === 'paid') {
					clearSecretCodeForDeal(dealId);
				}
			}

		} catch (e) {
			if (isInitial) {
				error = e.message;
			} else {
				pollConsecutiveErrors++;
				if (pollConsecutiveErrors >= MAX_POLL_ERRORS) {
					if (pollingInterval) { clearInterval(pollingInterval); pollingInterval = null; }
					error = 'Lost connection to server. Please refresh the page.';
				}
				// Polling error — will retry on next interval
			}
		} finally {
			if (isInitial) {
				initialLoading = false;
			}
			loadDealInFlight = false;
		}
	}

	function needsKeyRegistration() {
		const role = userRole;
		if (!role || !signingStatus) return false;
		if (role === 'seller') return !signingStatus.seller_pubkey_registered;
		if (role === 'buyer') return !signingStatus.buyer_pubkey_registered;
		return false;
	}

	// Auto-open sign modal if key registration is needed
	let autoRegisterTriggered = $state(false);
	$effect(() => {
		if (storedKey && needsKeyRegistration() && !autoRegisterTriggered && !showSignModal) {
			autoRegisterTriggered = true;
			startSign(userRole);
		}
	});

	function startSign(role) {
		signRole = role;
		showSignModal = true;
	}

	function handleSignSuccess(result) {
		showSignModal = false;
		actionMessage = 'Signed and key registered!';
		loadDeal(false);
	}


	async function copyShareLink() {
		if (!deal?.deal_link) return;
		await copyToClipboard(deal.deal_link);
		linkCopied = true;
		setTimeout(() => linkCopied = false, 2000);
	}

	let lastSignError = $state('');

	function getSignedAction(action, forRole) {
		let key;
		if (forRole && storedKeyEntry?.[forRole]?.privateKey) {
			key = storedKeyEntry[forRole];
		} else {
			key = storedKey;
		}
		if (!key?.privateKey) {
			lastSignError = 'no private key in store';
			return null;
		}
		try {
			const result = signAction(key.privateKey, dealId, action);
			lastSignError = '';
			return result;
		} catch (e) {
			lastSignError = `signAction(${action}): ${e.message}`;
			// signAction failed — lastSignError captures details for UI
			return null;
		}
	}

	function getAuthenticatedUserId(forRole) {
		if (forRole && storedAuthEntry?.[forRole]?.userId) return storedAuthEntry[forRole].userId;
		if (storedAuth?.userId) return storedAuth.userId;
		return getVisitorId();
	}

	function requestRelease() {
		showReleaseConfirm = true;
	}

	async function handleRelease() {
		if (releaseInProgress) return;
		showReleaseConfirm = false;
		releaseInProgress = true;
		actionError = '';
		actionMessage = '';

		try {
			const userId = getAuthenticatedUserId('buyer');
			if (!userId) { actionError = 'Could not determine user identity.'; return; }
			const sig = getSignedAction('release', 'buyer');
			if (!sig) { actionError = 'Could not sign release action.'; return; }
			// Non-custodial: include recovery code + Schnorr signature from buyer's ephemeral key
			const secretCode = getSecretCodeForDeal(dealId);
			let buyerEscrowSig = null;
			const buyerKey = storedKeyEntry?.buyer;
			if (buyerKey?.privateKey && secretCode) {
				try { buyerEscrowSig = signForRelease(buyerKey.privateKey, secretCode); } catch (e) { /* Escrow sig failed — release will proceed without it */ }
			}
			deal = await releaseDeal(dealId, userId, sig.signature, sig.timestamp, secretCode, buyerEscrowSig);
			// Only clear secret code once payout is confirmed paid — if the LN payment
			// fails, the secret code may still be needed for an escrow claim retry.
			if (deal?.payout_status === 'paid') {
				clearSecretCodeForDeal(dealId);
			}
			actionMessage = 'Funds released! Payment is on its way to the seller.';
		} catch (e) {
			setActionError(friendlyError(e.message, () => { appStale = true; }));
		} finally {
			releaseInProgress = false;
		}
	}

</script>

<svelte:head>
	<title>{deal?.title || 'Deal'} - trustMeBro-ARK</title>
</svelte:head>

<div class="deal-page">
{#if initialLoading}
		<div class="loading-state">
			<div class="spinner-small"></div>
		</div>
	{:else if error}
		<div class="card error-card">
			<h2>Error</h2>
			<p>{error}</p>
			<a href="/" class="btn">Back</a>
		</div>
	{:else if deal}
		<!-- Deal Header: Title + Status Pill -->
		<div class="deal-header">
			<h1>{deal.title}</h1>
			<span class="status-pill {getStatusPillClass(deal.status)}">{getStatusLabel(deal.status)}</span>
		</div>

		<!-- Big Amount Hero -->
		<div class="deal-amount-hero">{deal.price_sats?.toLocaleString()} <span class="sats-label">sats</span></div>
		{#if deal.description}
			<p class="deal-description">{deal.description}</p>
		{/if}

		<!-- System status warning -->
		{#if lndDown}
			<div class="system-warning">
				<strong>Service degraded</strong>
				<p>Lightning node is unreachable. Funding and payouts are temporarily unavailable.</p>
			</div>
		{/if}

		<!-- Main Action Card -->
		<div class="action-card">
			{#if !userRole && ['completed', 'released', 'refunded', 'expired', 'cancelled'].includes(deal?.status)}
				<!-- Finished deal, viewer is not a participant -->
				<div class="action-content completed-state">
					<div class="celebration">{deal.status === 'refunded' ? '↩️' : '✅'}</div>
					<h2>Deal {deal.status === 'refunded' ? 'Refunded' : 'Completed'}</h2>
					<p>This deal has been {deal.status === 'refunded' ? 'refunded' : 'completed'}.</p>
					<div class="completed-actions">
						<a href="/" class="btn">Home</a>
						<a href="/create" class="btn primary">Create New Deal</a>
					</div>
				</div>
			{:else if !userRole}
				<!-- Not signed in yet -->
				<div class="action-content">
					{#if deal.seller_linking_pubkey && deal.buyer_linking_pubkey}
						<!-- Both roles taken — recovery scenario -->
						{#if showKeyRecovery}
							<h2>Recover Access</h2>
							<p>Select your role, then sign in with your wallet.</p>
							<div class="recovery-role-buttons">
								<button class="btn primary" onclick={() => { startSign('seller'); showKeyRecovery = false; }}>I'm the Seller</button>
								<button class="btn primary" onclick={() => { startSign('buyer'); showKeyRecovery = false; }}>I'm the Buyer</button>
							</div>
						{:else}
							<h2>Sign In to Continue</h2>
							<p>Sign in with your Lightning wallet to access this deal.</p>
							<button class="btn primary" onclick={() => showKeyRecovery = true}>Sign In</button>
						{/if}
					{:else}
						<!-- Deal still needs a counterparty -->
						<h2>Join This Deal</h2>
						<p>Sign in with your Lightning wallet to join.</p>
						<div class="join-role-buttons">
							{#if deal.seller_linking_pubkey && !deal.buyer_linking_pubkey}
								<button class="btn primary" onclick={() => startSign('buyer')}>Join as Buyer</button>
							{:else if deal.buyer_linking_pubkey && !deal.seller_linking_pubkey}
								<button class="btn primary" onclick={() => startSign('seller')}>Join as Seller</button>
							{:else}
								<button class="btn primary" onclick={() => startSign('buyer')}>Join as Buyer</button>
								<button class="btn" onclick={() => startSign('seller')}>Join as Seller</button>
							{/if}
						</div>
						<p class="hint">You'll scan a QR code with your Lightning wallet (Phoenix, Zeus, Alby, etc.)</p>
					{/if}
				</div>
			{:else}
				<!-- Signed in - show current action -->
				<div class="role-header">
					<div class="role-badge" class:seller={userRole === 'seller'} class:buyer={userRole === 'buyer'}>
						{userRole === 'seller' ? '🏷️ Seller' : '🛒 Buyer'}
					</div>
					{#if availableRoles.length > 1}
						<button class="role-switch-btn" onclick={() => { const other = userRole === 'seller' ? 'buyer' : 'seller'; switchActiveRole(dealId, other); }}>
							Switch to {userRole === 'seller' ? 'Buyer' : 'Seller'} view
						</button>
					{/if}
				</div>

				{#if !storedKey}
					<!-- Key lost from browser -->
					<div class="action-content">
						<h2>Sign In Again</h2>
						<p>Your session is no longer in this browser. This happens when you clear browser data or switch devices.</p>
						<button class="btn primary" onclick={() => startSign(userRole)}>Sign in with wallet</button>
						<p class="hint" style="margin-top: 0.5rem;">Use the same Lightning wallet you signed in with originally.</p>
						<p class="hint" style="margin-top: 0.75rem;">Your funds are safe regardless. Signing in again restores your access to this deal.</p>
					</div>
				{:else if needsKeyRegistration()}
					<div class="action-content">
						<h2>Complete Sign-In</h2>
						<p>One more step to finish setting up your account for this deal.</p>
						<button class="btn primary" onclick={() => startSign(userRole)}>Continue</button>
					</div>
				{:else if ['expired', 'cancelled'].includes(deal.status) && !deal.funded_at}
					<div class="action-content">
						{#if deal.status === 'expired'}
							<h2>Deal Expired</h2>
							<p>This deal timed out before funding was completed. No funds were locked.</p>
						{:else}
							<h2>Deal Cancelled</h2>
							<p>This deal was cancelled.</p>
						{/if}
					</div>
				{:else if !readyToFund}
					<div class="action-content">
						{#if userRole === 'seller' && deal.buyer_started_at && !deal.buyer_linking_pubkey}
							<h2>Buyer is joining...</h2>
							<p>The buyer opened the link and is signing in.</p>
							<div class="joining-indicator"><span class="pulse"></span></div>
						{:else}
							<h2>Waiting for {userRole === 'seller' ? 'Buyer' : 'Seller'}</h2>
							<p>The other participant needs to sign in.</p>
						{/if}
					</div>
				{:else if !signingStatus?.funding_txid}
					<div class="action-content">
						{#if !deal.has_seller_payout_invoice || !deal.has_buyer_payout_invoice}
							<!-- Waiting for Lightning Addresses (collected during create/join) -->
							{#if (userRole === 'seller' && deal.has_seller_payout_invoice) || (userRole === 'buyer' && deal.has_buyer_payout_invoice)}
								<div class="payout-saved-badge">Your Lightning Address saved</div>
								<p class="hint">Waiting for the other party to provide their Lightning Address before funding.</p>
							{:else}
								<h2>Lightning Address Required</h2>
								<p>Your Lightning Address was not saved during signup. Please set it now.</p>
								<PayoutForm
									type={userRole === 'seller' ? 'release' : 'refund'}
									{deal}
									{dealId}
									{storedKey}
									{lndDown}
									getSignedAction={(action) => getSignedAction(action, userRole)}
									getAuthenticatedUserId={() => getAuthenticatedUserId(userRole)}
									onDealUpdate={() => loadDeal(false)}
								/>
							{/if}
						{:else}
							<FundingPanel
								bind:this={fundingPanelRef}
								{deal}
								{dealId}
								userRole={userRole}
								{lndDown}
								{QRCode}
								{qrLoadFailed}
								{signingStatus}
								onDealUpdate={() => loadDeal(false)}
							/>
						{/if}
					</div>
				{:else if ['completed', 'released', 'refunded'].includes(deal.status)}
					<CompletedPanel
						{deal}
						{dealId}
						{userRole}
						{storedKey}
						{lndDown}
						{getSignedAction}
						{getAuthenticatedUserId}
						onDealUpdate={() => loadDeal(false)}
					/>
				{:else if deal.status === 'releasing'}
					<div class="action-content payout-processing">
						<h2>Releasing Funds...</h2>
						<PayoutTimer />
					</div>
				{:else if deal.status === 'refunding'}
					<div class="action-content payout-processing">
						<h2>Refunding Funds...</h2>
						<PayoutTimer />
					</div>
				{:else if deal.status === 'disputed'}
					<DisputedPanel
						{deal}
						{dealId}
						{userRole}
						{getSignedAction}
						{getAuthenticatedUserId}
						onDealUpdate={() => loadDeal(false)}
						onError={(msg) => setActionError(friendlyError(msg, () => { appStale = true; }))}
					/>
				{:else if deal.status === 'expired' && signingStatus?.funding_txid}
					<div class="action-content">
						<h2>Deal Expired</h2>
						{#if (deal.timeout_action === 'refund' ? deal.buyer_payout_status : deal.payout_status) === 'paid' || deal.refund_txid || deal.release_txid}
							<p>The deal timed out. Funds have been returned to the {deal.timeout_action === 'refund' ? 'buyer' : 'seller'}.</p>
						{:else if (deal.timeout_action === 'refund' ? deal.buyer_payout_status : deal.payout_status) === 'failed'}
							<p>The deal timed out. The automatic payout could not be completed. The system will retry, or a referee will process it manually.</p>
						{:else}
							<p>The deal timed out. Funds will be returned to the {deal.timeout_action === 'refund' ? 'buyer' : 'seller'} automatically.</p>
						{/if}
					</div>
				{:else if signingStatus?.funding_txid}
					<ResolutionPanel
						{deal}
						{dealId}
						{userRole}
						{availableRoles}
						{storedKey}
						storedKeyEntry={storedKeyEntry}
						{lndDown}
						{signingStatus}
						{getSignedAction}
						{getAuthenticatedUserId}
						onDealUpdate={() => loadDeal(false)}
						onRequestRelease={requestRelease}
						{releaseInProgress}
					/>
				{:else}
					<div class="action-content">
						<h2>Deal in Progress</h2>
						<p>Status: {deal.status}</p>
					</div>
				{/if}

				{#if actionMessage}
					<p class="success" role="status" aria-live="polite">{actionMessage}</p>
				{/if}
				{#if actionError}
					<p class="error" role="alert" aria-live="assertive">{actionError}</p>
					{#if appStale}
						<button class="btn primary" onclick={() => location.reload()}>Reload Page</button>
					{/if}
				{/if}
			{/if}
		</div>

		<!-- Invite link -->
		{#if userRole && deal?.deal_link_token && (!signingStatus?.buyer_pubkey_registered || !signingStatus?.seller_pubkey_registered) && !['completed', 'released', 'refunded', 'expired', 'cancelled'].includes(deal?.status)}
			<div class="invite-card">
				<h3>Invite {!signingStatus?.buyer_pubkey_registered ? 'Buyer' : 'Seller'}</h3>
				<p class="invite-hint">Share this link to join the deal:</p>
				<div class="invite-link-row">
					<input type="text" readonly value={deal.deal_link} class="invite-input" aria-label="Deal invite link" />
					<button class="invite-copy" onclick={copyShareLink}>{linkCopied ? 'Copied!' : 'Copy'}</button>
				</div>
			</div>
		{/if}

		<!-- Collapsible Details -->
		{#if userRole}
			<DealDetails
				{deal}
				{signingStatus}
				{storedKey}
				{userRole}
				{countdownText}
				{countdownUrgent}
				onOpenDispute={() => showDisputeModal = true}
			/>
		{/if}

		<!-- Dispute Modal -->
		<DisputeModal
			bind:show={showDisputeModal}
			{dealId}
			{storedKeyEntry}
			{userRole}
			{getSignedAction}
			{getAuthenticatedUserId}
			onDealUpdate={() => loadDeal(false)}
		/>

		<!-- Release Confirmation Modal -->
		<ReleaseConfirmModal
			bind:show={showReleaseConfirm}
			{deal}
			releasing={releaseInProgress}
			onConfirm={handleRelease}
		/>

		<!-- Sign Modal -->
		{#if showSignModal}
			<div class="modal-overlay" onclick={() => showSignModal = false} role="presentation" onkeydown={(e) => e.key === 'Escape' && (showSignModal = false)}>
				<div class="modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Sign in" onkeydown={(e) => e.stopPropagation()}>
					<button class="modal-close" onclick={() => showSignModal = false} aria-label="Close">&times;</button>
					<h2>Sign in as {signRole === 'seller' ? 'Seller' : 'Buyer'}</h2>
					<LnurlSign
						dealToken={deal.deal_link_token}
						role={signRole}
						onSuccess={handleSignSuccess}
					/>
				</div>
			</div>
		{/if}
	{/if}
</div>

<style>
	@import '$lib/styles/deal-shared.css';

	/* --- Page layout --- */
	.deal-page { max-width: 600px; width: 100%; margin: 0 auto; }
	.loading-state { text-align: center; padding: 2rem; color: var(--text-dim); }

	/* --- Deal header --- */
	.deal-header {
		display: flex; align-items: center; gap: 0.75rem;
		margin-bottom: 0.5rem; flex-wrap: wrap;
	}
	h1 { color: var(--text); font-size: 1.25rem; margin: 0; }

	.status-pill {
		padding: 0.25rem 0.75rem; border-radius: 20px;
		font-size: 0.8rem; font-weight: 600;
	}
	.pill-pending { background: color-mix(in srgb, var(--text-muted) 13%, transparent); color: var(--text-muted); }
	.pill-funded { background: var(--accent-bg); color: var(--accent); }
	.pill-shipped { background: var(--info-bg); color: var(--info); }
	.pill-completed { background: var(--success-bg); color: var(--success); }
	.pill-refunded { background: color-mix(in srgb, var(--text-muted) 13%, transparent); color: var(--text-muted); }
	.pill-disputed { background: var(--error-bg); color: var(--error); }

	.deal-amount-hero {
		font-size: 2.5rem; font-weight: 700; color: var(--accent); margin-bottom: 0.25rem;
	}
	.sats-label { font-size: 1rem; color: var(--text-muted); font-weight: 400; }
	.deal-description { color: var(--text-muted); font-size: 0.95rem; margin: 0 0 1rem 0; }

	/* --- Action card (wraps child panels) --- */
	.action-card {
		background: var(--surface); border-radius: 12px;
		padding: 1.5rem; margin-bottom: 1.5rem;
		border: 1px solid var(--border);
	}
	.role-header {
		display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem;
	}
	.role-badge {
		display: inline-block; padding: 0.25rem 0.75rem;
		border-radius: 12px; font-size: 0.8rem;
		background: var(--orange-bg); color: var(--orange);
	}
	.role-badge.seller { background: var(--accent-bg); color: var(--accent); }
	.role-badge.buyer { background: var(--orange-bg); color: var(--orange); }
	.role-switch-btn {
		background: none; border: 1px solid var(--border-hover); border-radius: 6px;
		color: var(--text-muted); font-size: 0.75rem; padding: 0.2rem 0.5rem;
		cursor: pointer;
	}
	.role-switch-btn:hover { color: var(--accent); border-color: var(--accent); }

	/* --- Recovery / sign-in --- */
	.recovery-role-buttons, .join-role-buttons { display: flex; gap: 1rem; justify-content: center; margin: 1rem 0; }

	/* --- Invite card --- */
	.invite-card {
		background: var(--surface); border: 1px solid var(--border);
		border-radius: 8px; padding: 1.25rem; margin-bottom: 1rem;
	}
	.invite-card h3 { color: var(--accent); font-size: 1rem; margin: 0 0 0.25rem; }
	.invite-hint { color: var(--text-muted); font-size: 0.8rem; margin: 0 0 0.75rem; }
	.invite-link-row { display: flex; gap: 0.5rem; }
	.invite-input {
		flex: 1; background: var(--bg); border: 1px solid var(--border-hover);
		border-radius: 4px; color: var(--accent); font-family: monospace;
		font-size: 0.8rem; padding: 0.5rem; min-width: 0;
	}
	.invite-copy {
		padding: 0.5rem 0.75rem; background: var(--border);
		border: 1px solid var(--border-hover); border-radius: 4px;
		color: var(--text); cursor: pointer; font-size: 0.8rem; white-space: nowrap;
	}
	.invite-copy:hover { background: var(--border-hover); }

	/* --- System warning --- */
	.system-warning {
		background: var(--orange-bg); border: 1px solid var(--orange);
		border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 1rem; color: var(--orange);
	}
	.system-warning strong { display: block; margin-bottom: 0.25rem; }
	.system-warning p { margin: 0; font-size: 0.8rem; color: var(--orange); }

	/* --- Error card --- */
	.card {
		background: var(--surface); padding: 1.5rem;
		border-radius: 12px; border: 1px solid var(--border);
	}
	.card.error-card { border-color: var(--error); text-align: center; }
	.card.error-card h2 { color: var(--error); margin: 0 0 0.5rem 0; }
	.card.error-card p { color: var(--text-muted); margin-bottom: 1rem; }

	/* --- Joining indicator --- */
	.joining-indicator { display: flex; justify-content: center; margin-top: 1rem; }
	.pulse {
		width: 12px; height: 12px; background: var(--accent);
		border-radius: 50%; animation: pulse 1.5s ease-in-out infinite;
	}
	@keyframes pulse {
		0%, 100% { opacity: 0.3; transform: scale(1); }
		50% { opacity: 1; transform: scale(1.2); }
	}

	@media (max-width: 640px) {
		.deal-page { max-width: 100%; }
		.deal-header { flex-direction: column; align-items: flex-start; gap: 0.25rem; }
		h1 { font-size: 1.1rem; }
	}
</style>
