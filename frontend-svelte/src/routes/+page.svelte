<script>
	import { onMount, onDestroy } from 'svelte';
	import { dealAuths, dealKeys, storeAuthForDeal, removeAuthForDeal, hiddenDeals, hideDeal, unhideDeal } from '$lib/stores/vault.js';
	import { navAuth, clearNavAuth } from '$lib/stores/nav.js';
	import { getLoginChallenge, checkAuthStatus, getMyDeals, getDeal } from '$lib/api.js';
	import { API_URL } from '$lib/api/base-url.js';
	import { getStatusColor } from '$lib/utils/format.js';

	const FINISHED_STATUSES = ['completed', 'refunded', 'expired', 'cancelled', 'released'];

	let joinLink = $state('');
	let showArchived = $state(false);
	let validatingDeals = $state(true);
	let validatedDealIds = $state([]);
	let fetchedDeals = $state({});

	// Get list of deal IDs user has signed (from localStorage)
	let signedDealIds = $derived(Object.keys($dealAuths));

	// Validate local deals against backend on mount
	onMount(async () => {
		const localDealIds = Object.keys($dealAuths);
		if (localDealIds.length === 0) {
			validatingDeals = false;
			return;
		}

		const validIds = [];
		const deals = {};
		for (const dealId of localDealIds) {
			try {
				const deal = await getDeal(dealId);
				validIds.push(dealId);
				deals[dealId] = deal;
			} catch (err) {
				// Deal doesn't exist anymore - remove from localStorage
				removeAuthForDeal(dealId);
			}
		}
		validatedDealIds = validIds;
		fetchedDeals = deals;
		validatingDeals = false;
	});

	// Login state
	let showLogin = $state(false);
	let loginLoading = $state(false);
	let loginError = $state('');
	let loginK1 = $state(null);
	let loginQrUrl = $state(null);
	let pollFailures = $state(0);
	let loginLnurl = $state(null);
	let loginCopied = $state(false);
	let pollInterval = $state(null);
	let recoveredDeals = $state([]);
	let linkingPubkey = $state(null);
	let showSteps = $state(false);

	onDestroy(() => {
		clearNavAuth();
		stopPolling();
	});

	// Set nav auth: show nothing when user has deals, sign-in when they don't
	let hasDeals = $derived(allDealIds.length > 0);
	$effect(() => {
		if (linkingPubkey || hasDeals) {
			navAuth.set({ role: 'signed-in', deal: null, onSignOut: requestClearLocalData });
		} else {
			navAuth.set({ role: null, deal: null, onGlobalSignIn: startLogin });
		}
	});

	function handleJoin() {
		if (!joinLink) return;
		let input = joinLink.trim();
		// Full deal page URL → go directly to deal
		if (input.includes('/deal/')) {
			const dealId = input.split('/deal/').pop().split('?')[0].split('#')[0];
			window.location.href = `/deal/${dealId}`;
			return;
		}
		// Full join URL → extract token
		let token = input;
		if (input.includes('/join/')) {
			token = input.split('/join/').pop().split('?')[0].split('#')[0];
		}
		window.location.href = `/join/${token}`;
	}

	let showSignOutModal = $state(false);
	let signOutConfirmText = $state('');

	function requestClearLocalData() {
		showSignOutModal = true;
		signOutConfirmText = '';
	}

	function clearLocalData() {
		showSignOutModal = false;
		dealAuths.set({});
		dealKeys.set({});
		hiddenDeals.set([]);
		recoveredDeals = [];
		validatedDealIds = [];
		linkingPubkey = null;
		signOutConfirmText = '';
	}

	async function startLogin() {
		showLogin = true;
		loginLoading = true;
		loginError = '';

		try {
			const response = await getLoginChallenge();
			loginK1 = response.k1;
			loginLnurl = response.lnurl || response.qr_content;
			loginQrUrl = `${API_URL}/qr/${response.qr_content}`;

			loginLoading = false;
			startPolling();
		} catch (err) {
			loginError = err.message;
			loginLoading = false;
		}
	}

	function startPolling() {
		pollFailures = 0;
		pollInterval = setInterval(async () => {
			try {
				const status = await checkAuthStatus(loginK1);
				pollFailures = 0;
				if (status.verified) {
					stopPolling();
					await handleLoginSuccess(status);
				}
			} catch (err) {
				pollFailures++;
				if (pollFailures >= 5) {
					stopPolling();
					loginError = 'Connection lost. Please try again.';
				}
}
		}, 4000);  // Poll every 4s to stay under rate limit (20/60s)
	}

	function stopPolling() {
		if (pollInterval) {
			clearInterval(pollInterval);
			pollInterval = null;
		}
	}

	async function handleLoginSuccess(authStatus) {
		try {
			linkingPubkey = authStatus.pubkey;

			// Fetch user's deals
			const result = await getMyDeals(loginK1);
			recoveredDeals = result.deals || [];

			// Store auth for each recovered deal in localStorage
			for (const deal of recoveredDeals) {
				const userId = deal.user_role === 'buyer' ? deal.buyer_id : deal.seller_id;
				storeAuthForDeal(deal.deal_id, authStatus.pubkey, deal.user_role, userId);
			}

			showLogin = false;
		} catch (err) {
			loginError = err.message;
		}
	}

	function closeLogin() {
		stopPolling();
		showLogin = false;
		loginK1 = null;
		loginQrUrl = null;
	}

	// Combine validated local deals and recovered deals (deduplicated), newest first
	let allDealIdsUnfiltered = $derived.by(() => {
		const localIds = validatingDeals ? signedDealIds : validatedDealIds;
		const ids = new Set(localIds);
		for (const deal of recoveredDeals) {
			ids.add(deal.deal_id);
		}
		const arr = Array.from(ids);
		// Sort by created_at descending (newest first) when data is available
		arr.sort((a, b) => {
			const aInfo = fetchedDeals[a] || recoveredDeals.find(d => d.deal_id === a);
			const bInfo = fetchedDeals[b] || recoveredDeals.find(d => d.deal_id === b);
			const aTime = aInfo?.created_at || '';
			const bTime = bInfo?.created_at || '';
			return bTime.localeCompare(aTime);
		});
		return arr;
	});

	let hiddenCount = $derived(allDealIdsUnfiltered.filter(id => $hiddenDeals.includes(id)).length);

	let allDealIds = $derived.by(() => {
		if (showArchived) return allDealIdsUnfiltered;
		return allDealIdsUnfiltered.filter(id => !$hiddenDeals.includes(id));
	});

	function getDealInfo(dealId) {
		// Check recovered deals first (from LNURL sign-in)
		const recovered = recoveredDeals.find(d => d.deal_id === dealId);
		if (recovered) {
			return {
				title: recovered.title,
				role: recovered.user_role,
				status: recovered.status,
				price: recovered.price_sats
			};
		}
		// Check fetched deals (from validation)
		const fetched = fetchedDeals[dealId];
		const authEntry = $dealAuths[dealId];
		const roleFromAuth = authEntry?.activeRole || authEntry?.role || 'participant';
		if (fetched) {
			return {
				title: fetched.title || `Deal ${dealId.slice(0, 8)}...`,
				role: roleFromAuth,
				status: fetched.status,
				price: fetched.price_sats
			};
		}
		// Fallback
		return {
			title: `Deal ${dealId.slice(0, 8)}...`,
			role: roleFromAuth,
			status: null,
			price: null
		};
	}

</script>

<svelte:head>
	<title>trustMeBro-ARK</title>
</svelte:head>

<div class="home">
	<!-- Hero Section -->
	<div class="hero">
		<h1>Bitcoin Deals.<br/>No trust required.</h1>
		<p class="tagline">Secure peer-to-peer trades with trustless protection. Pay and get paid via Lightning.</p>
		<div class="hero-actions">
			<a href="/create" class="btn primary large">Create a Deal</a>
		</div>
	</div>

	<!-- How it works -->
	<div class="how-section">
		<button class="how-it-works-toggle" onclick={() => showSteps = !showSteps}>
			How it works {showSteps ? '\u25BE' : '\u25B8'}
		</button>
		{#if showSteps}
			<div class="steps">
				<div class="step">
					<div class="step-num">1</div>
					<div class="step-text">
						<strong>Create</strong>
						<span>Set terms, share the link</span>
					</div>
				</div>
				<div class="step-arrow">&rarr;</div>
				<div class="step">
					<div class="step-num">2</div>
					<div class="step-text">
						<strong>Fund</strong>
						<span>Buyer pays a Lightning invoice</span>
					</div>
				</div>
				<div class="step-arrow">&rarr;</div>
				<div class="step">
					<div class="step-num">3</div>
					<div class="step-text">
						<strong>Trade</strong>
						<span>Deliver goods or services</span>
					</div>
				</div>
				<div class="step-arrow">&rarr;</div>
				<div class="step">
					<div class="step-num">4</div>
					<div class="step-text">
						<strong>Release</strong>
						<span>Seller gets paid via Lightning</span>
					</div>
				</div>
			</div>

			<div class="features">
				<div class="feature">
					<div class="feature-icon">🔒</div>
					<div class="feature-text">
						<strong>Trustless protection</strong>
						<span>Funds are locked until both parties agree. Neither party can run off with the sats.</span>
					</div>
				</div>
				<div class="feature">
					<div class="feature-icon">LN</div>
					<div class="feature-text">
						<strong>Lightning in, Lightning out</strong>
						<span>Pay and get paid via Lightning. Simple as that.</span>
					</div>
				</div>
				<div class="feature">
					<div class="feature-icon">T</div>
					<div class="feature-text">
						<strong>Auto timeout</strong>
						<span>Every deal has a time limit. If it expires, funds go back to the right party automatically.</span>
					</div>
				</div>
			</div>

			<div class="info-banner">
				Early access &mdash; start with small amounts until you're comfortable.
			</div>

			<a href="/how" class="how-link">Read the full guide &rarr;</a>
		{/if}
	</div>

	<!-- Join a Deal -->
	<div class="join-section">
		<h2>Join a Deal</h2>
		<div class="join-form">
			<input
				type="text"
				bind:value={joinLink}
				placeholder="Paste deal link or token"
			/>
			<button onclick={handleJoin} disabled={!joinLink}>Join</button>
		</div>
	</div>

	{#if validatingDeals}
		<div class="deals-section">
			<div class="section-header">
				<h2>Your Deals</h2>
			</div>
			<div class="validating">
				<div class="spinner small"></div>
				<span>Checking deals...</span>
			</div>
		</div>
	{:else if allDealIds.length > 0 || hiddenCount > 0}
		<div class="deals-section">
			<div class="section-header">
				<h2>Your Deals</h2>
				<div class="header-actions">
					{#if hiddenCount > 0}
						<button class="archive-toggle" onclick={() => showArchived = !showArchived}>
							{showArchived ? 'Hide archived' : `Show archived (${hiddenCount})`}
						</button>
					{/if}
					<button class="sign-out-btn" onclick={requestClearLocalData}>Sign Out</button>
				</div>
			</div>
			<div class="deals-list">
				{#each allDealIds as dealId}
					{@const info = getDealInfo(dealId)}
					{@const isHidden = $hiddenDeals.includes(dealId)}
					{@const isFinished = FINISHED_STATUSES.includes(info.status)}
					<a href="/deal/{dealId}" class="deal-card" class:archived={isHidden}>
						<div class="deal-header">
							<span class="deal-title">{info.title}</span>
							<div class="deal-header-right">
								<span class="deal-role" class:seller={info.role === 'seller'} class:buyer={info.role === 'buyer'}>{info.role}</span>
								{#if isHidden}
									<button class="archive-btn visible" title="Restore" onclick={(e) => { e.preventDefault(); e.stopPropagation(); unhideDeal(dealId); }}>&#x21A9;</button>
								{:else if isFinished}
									<button class="archive-btn" title="Archive" onclick={(e) => { e.preventDefault(); e.stopPropagation(); hideDeal(dealId); }}>
									<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
								</button>
								{/if}
							</div>
						</div>
						{#if info.status || info.price}
							<div class="deal-info">
								{#if info.price}
									<span class="deal-amount">{info.price.toLocaleString()} sats</span>
								{/if}
								{#if info.status}
									<span class="deal-status" style="color: {getStatusColor(info.status)}">{info.status}</span>
								{/if}
							</div>
						{/if}
					</a>
				{/each}
			</div>
		</div>
	{:else}
		<div class="signin-section">
			<p>Recover your deals by signing in with your Lightning wallet</p>
			<button class="btn signin" onclick={startLogin}>Sign In</button>
		</div>
	{/if}
</div>

<!-- Login Modal -->
{#if showLogin}
	<div class="modal-overlay" role="presentation" onclick={closeLogin} onkeydown={(e) => e.key === 'Escape' && closeLogin()}>
		<div class="modal" role="dialog" aria-modal="true" aria-label="Sign in" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
			<button class="modal-close" onclick={closeLogin} aria-label="Close">&times;</button>
			<h2>Sign in with Lightning</h2>

			{#if loginLoading}
				<div class="loading">
					<div class="spinner"></div>
					<p>Generating QR code...</p>
				</div>
			{:else if loginError}
				<div class="error" role="alert">
					<p>{loginError}</p>
					<button class="btn" onclick={startLogin}>Try Again</button>
				</div>
			{:else}
				<div class="qr-section">
					<p class="qr-hint">Scan with your Lightning wallet</p>
					<div class="qr-box">
						<img src={loginQrUrl} alt="QR" />
					</div>
					<div class="qr-actions">
						<button class="btn copy-btn" onclick={() => { navigator.clipboard.writeText(loginLnurl).catch(() => {}); loginCopied = true; setTimeout(() => loginCopied = false, 2000); }}>
							{loginCopied ? 'Copied!' : 'Copy Link'}
						</button>
					</div>
					<p class="status-text">Waiting for wallet...</p>
				</div>
			{/if}
		</div>
	</div>
{/if}

<!-- Sign Out Confirmation Modal -->
{#if showSignOutModal}
	<div class="modal-overlay" onclick={() => showSignOutModal = false} role="presentation" onkeydown={(e) => e.key === 'Escape' && (showSignOutModal = false)}>
		<div class="modal signout-modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Sign out confirmation" onkeydown={(e) => e.stopPropagation()}>
			<button class="modal-close" onclick={() => showSignOutModal = false} aria-label="Close">&times;</button>
			<h2>Sign Out</h2>
			<p class="signout-warning">This will delete <strong>{allDealIdsUnfiltered.length}</strong> deal key{allDealIdsUnfiltered.length !== 1 ? 's' : ''} from this browser. You will need to re-authenticate to access your deals.</p>
			<p class="signout-warning" style="color: var(--error);">If you have active deals with funds, make sure you can recover your keys (via wallet sign-in) before signing out.</p>
			<label class="signout-confirm-label" for="signout-confirm">Type <strong>DELETE</strong> to confirm:</label>
			<input id="signout-confirm" type="text" bind:value={signOutConfirmText} placeholder="DELETE" class="signout-confirm-input" />
			<div class="modal-actions">
				<button class="btn" onclick={() => showSignOutModal = false}>Cancel</button>
				<button class="btn danger" onclick={clearLocalData} disabled={signOutConfirmText !== 'DELETE'}>Sign Out</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.home {
		max-width: 800px;
		width: 100%;
		margin: 0 auto;
	}

	/* Hero */
	.hero {
		text-align: center;
		padding: 2rem 0 1.5rem;
	}

	h1 {
		color: var(--text);
		font-size: 2rem;
		line-height: 1.3;
		margin-bottom: 0.75rem;
	}

	.tagline {
		color: var(--text-muted);
		font-size: 1.05rem;
		max-width: 500px;
		margin: 0 auto 1.5rem;
		line-height: 1.5;
	}

	.hero-actions {
		display: flex;
		justify-content: center;
		gap: 1rem;
	}

	/* How it works section */
	.how-section {
		margin-bottom: 1.5rem;
	}

	.how-it-works-toggle {
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 0.95rem;
		cursor: pointer;
		padding: 0.5rem 0;
		margin-bottom: 0.5rem;
		display: block;
		width: 100%;
		text-align: center;
	}

	.how-it-works-toggle:hover {
		color: var(--accent);
	}

	.how-link {
		display: block;
		text-align: center;
		color: var(--accent);
		font-size: 0.85rem;
		margin-top: 0.75rem;
	}

	/* Steps */
	.steps {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
		margin-bottom: 2rem;
		padding: 1.25rem;
		background: var(--surface);
		border-radius: 8px;
		border: 1px solid var(--border);
	}

	.step {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}

	.step-num {
		width: 28px;
		height: 28px;
		border-radius: 50%;
		background: var(--accent-bg);
		color: var(--accent);
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 0.8rem;
		font-weight: 700;
		flex-shrink: 0;
	}

	.step-text {
		display: flex;
		flex-direction: column;
		line-height: 1.3;
	}

	.step-text strong {
		color: var(--text);
		font-size: 0.95rem;
	}

	.step-text span {
		color: var(--text-dim);
		font-size: 0.8rem;
	}

	.step-arrow {
		color: var(--text-dim);
		font-size: 1rem;
		flex-shrink: 0;
	}

	/* Features */
	.features {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		margin-top: 0.75rem;
	}

	.feature {
		display: flex;
		align-items: flex-start;
		gap: 0.75rem;
		padding: 0.75rem;
		background: var(--bg);
		border-radius: 6px;
	}

	.feature-icon {
		min-width: 36px;
		height: 36px;
		border-radius: 6px;
		background: var(--accent-bg);
		color: var(--accent);
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 0.75rem;
		font-weight: 700;
		flex-shrink: 0;
	}

	.feature-text {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}

	.feature-text strong {
		color: var(--text);
		font-size: 0.9rem;
	}

	.feature-text span {
		color: var(--text-muted);
		font-size: 0.8rem;
		line-height: 1.4;
	}

	.info-banner {
		margin-top: 0.75rem;
		padding: 0.6rem 1rem;
		background: var(--orange-bg);
		border: 1px solid var(--orange-border);
		border-radius: 6px;
		color: var(--orange);
		font-size: 0.85rem;
		text-align: center;
	}

	h2 {
		color: var(--text);
		margin-bottom: 1rem;
		font-size: 1.25rem;
	}

	.btn {
		display: inline-block;
		padding: 0.75rem 1.5rem;
		border-radius: 6px;
		text-decoration: none;
		font-weight: 600;
		border: none;
		cursor: pointer;
	}

	.btn.primary {
		background: linear-gradient(135deg, var(--accent), var(--accent-hover));
		color: var(--bg);
	}

	.btn.primary:hover {
		opacity: 0.9;
		text-decoration: none;
	}

	.btn.large {
		padding: 0.9rem 2.5rem;
		font-size: 1.05rem;
		border-radius: 8px;
	}

	.join-section {
		background: var(--surface);
		padding: 1.5rem;
		border-radius: 8px;
		margin-bottom: 1rem;
		border: 1px solid var(--border);
	}

	.join-form {
		display: flex;
		gap: 0.5rem;
	}

	.join-form input {
		flex: 1;
		padding: 0.75rem;
		background: var(--bg);
		border: 1px solid var(--border-hover);
		border-radius: 4px;
		color: var(--text);
	}

	.join-form button {
		padding: 0.75rem 1.5rem;
		background: var(--accent);
		border: none;
		border-radius: 4px;
		color: var(--bg);
		font-weight: 600;
		cursor: pointer;
	}

	.join-form button:hover:not(:disabled) {
		background: var(--accent-hover);
	}

	.join-form button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	/* Sign In Section */
	.signin-section {
		background: var(--surface);
		padding: 2rem;
		border-radius: 8px;
		border: 1px solid var(--border);
		text-align: center;
	}

	.signin-section p {
		color: var(--text-muted);
		margin-bottom: 1rem;
	}

	.btn.signin {
		background: linear-gradient(135deg, var(--orange), #ff6b00);
		color: white;
		padding: 0.75rem 2rem;
		font-size: 1rem;
	}

	.btn.signin:hover {
		opacity: 0.9;
	}

	.deals-section {
		background: var(--surface);
		padding: 1.5rem;
		border-radius: 8px;
		border: 1px solid var(--border);
	}

	.section-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 1rem;
	}

	.section-header h2 {
		margin-bottom: 0;
	}

	.sign-out-btn {
		padding: 0.4rem 0.8rem;
		background: transparent;
		border: 1px solid var(--text-dim);
		border-radius: 4px;
		color: var(--text-muted);
		font-size: 0.8rem;
		cursor: pointer;
		font-family: inherit;
	}

	.sign-out-btn:hover {
		border-color: var(--error);
		color: var(--error);
	}

	.deals-list {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.deal-card {
		display: block;
		background: var(--bg);
		padding: 1rem;
		border-radius: 6px;
		border: 1px solid var(--border);
		text-decoration: none;
		transition: border-color 0.2s;
	}

	.deal-card:hover {
		border-color: var(--accent);
		text-decoration: none;
	}

	.deal-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.deal-title {
		color: var(--text);
		font-weight: 500;
	}

	.deal-info {
		display: flex;
		justify-content: space-between;
		color: var(--text-muted);
		font-size: 0.8rem;
		margin-top: 0.5rem;
	}

	.deal-amount {
		color: var(--accent);
	}

	.deal-status {
		text-transform: uppercase;
		font-size: 0.8rem;
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.archive-toggle {
		padding: 0.4rem 0.8rem;
		background: transparent;
		border: 1px solid var(--text-dim);
		border-radius: 4px;
		color: var(--text-muted);
		font-size: 0.75rem;
		cursor: pointer;
		font-family: inherit;
	}

	.archive-toggle:hover {
		border-color: var(--accent);
		color: var(--accent);
	}

	.deal-header-right {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.archive-btn {
		background: none;
		border: none;
		color: var(--text-dim);
		cursor: pointer;
		padding: 0.3rem;
		border-radius: 4px;
		line-height: 1;
		display: flex;
		align-items: center;
	}

	.archive-btn:hover {
		color: var(--error);
		background: var(--error-bg);
	}

	.archive-btn.visible:hover {
		color: var(--accent);
		background: var(--accent-bg);
	}

	.deal-card.archived {
		opacity: 0.5;
	}

	.deal-role {
		font-size: 0.8rem;
		padding: 0.2rem 0.5rem;
		border-radius: 4px;
		background: var(--border);
		color: var(--text-muted);
	}

	.deal-role.seller {
		background: var(--accent-bg);
		color: var(--accent);
	}

	.deal-role.buyer {
		background: var(--orange-bg);
		color: var(--orange);
	}

	/* Modal */
	.modal-overlay {
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		bottom: 0;
		background: rgba(0, 0, 0, 0.7);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
	}

	.modal {
		background: var(--surface);
		padding: 2rem;
		border-radius: 12px;
		border: 1px solid var(--border);
		max-width: 400px;
		width: 90%;
		position: relative;
	}

	.modal-close {
		position: absolute;
		top: 0.5rem;
		right: 1rem;
		background: none;
		border: none;
		font-size: 2rem;
		color: var(--text-dim);
		cursor: pointer;
	}

	.modal-close:hover {
		color: var(--text);
	}

	.modal h2 {
		color: var(--text);
		text-align: center;
		margin-bottom: 1rem;
	}

	.loading, .error {
		text-align: center;
		padding: 2rem;
	}

	.spinner {
		width: 40px;
		height: 40px;
		border: 3px solid var(--border);
		border-top: 3px solid var(--accent);
		border-radius: 50%;
		animation: spin 1s linear infinite;
		margin: 0 auto 1rem;
	}

	.spinner.small {
		width: 20px;
		height: 20px;
		border-width: 2px;
		margin: 0;
	}

	.validating {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		color: var(--text-muted);
		padding: 1rem 0;
	}

	@keyframes spin {
		0% { transform: rotate(0deg); }
		100% { transform: rotate(360deg); }
	}

	.error {
		color: var(--error);
	}

	.qr-section {
		text-align: center;
	}

	.qr-hint {
		color: var(--text-muted);
		font-size: 0.95rem;
		margin-bottom: 0.75rem;
	}

	.qr-box {
		background: white;
		padding: 1rem;
		border-radius: 12px;
		display: block;
		width: fit-content;
		margin: 0 auto;
	}

	.qr-box img {
		display: block;
		width: 220px;
		height: 220px;
		border-radius: 4px;
	}

	.qr-actions {
		margin-top: 0.75rem;
	}

	.copy-btn {
		background: var(--surface);
		border: 1px solid var(--border);
		color: var(--text);
		padding: 0.4rem 1.2rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.8rem;
	}

	.copy-btn:hover {
		border-color: var(--accent);
		color: var(--accent);
	}

	.status-text {
		margin-top: 0.75rem;
		color: var(--accent);
		font-size: 0.8rem;
		font-style: italic;
	}

	.signout-warning {
		color: var(--orange);
		font-size: 0.9rem;
		margin-bottom: 0.75rem;
	}

	.signout-confirm-label {
		display: block;
		color: var(--text-muted);
		font-size: 0.85rem;
		margin-bottom: 0.5rem;
	}

	.signout-confirm-input {
		width: 100%;
		padding: 0.6rem;
		background: var(--bg);
		border: 1px solid var(--border-hover);
		border-radius: 6px;
		color: var(--text);
		font-size: 0.95rem;
		margin-bottom: 1rem;
		box-sizing: border-box;
	}

	.btn.danger {
		background: var(--error);
		color: white;
		font-weight: 600;
		border: none;
	}

	.btn.danger:hover {
		background: var(--error-hover);
	}

	.btn.danger:disabled {
		background: var(--border-hover);
		color: var(--text-muted);
		cursor: not-allowed;
	}

	.modal-actions {
		display: flex;
		gap: 0.75rem;
		justify-content: flex-end;
	}

	@media (max-width: 640px) {
		h1 {
			font-size: 1.5rem;
		}

		.steps {
			flex-direction: column;
			gap: 0.75rem;
		}

		.step {
			width: 100%;
		}

		.step-arrow {
			transform: rotate(90deg);
		}
	}
</style>
