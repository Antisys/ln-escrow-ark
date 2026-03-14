<script>
	import PayoutForm from './PayoutForm.svelte';
	import PayoutTimer from './PayoutTimer.svelte';

	let {
		deal,
		dealId,
		userRole,
		storedKey,
		lndDown = false,
		getSignedAction,
		getAuthenticatedUserId,
		onDealUpdate,
	} = $props();
</script>

{#if deal.status === 'completed' || deal.status === 'released'}
	<div class="action-content completed-state">
		{#if userRole === 'seller'}
			{#if deal.payout_status === 'paid'}
				<div class="celebration">🎉</div>
				<h2>Payment Received!</h2>
				<p>{deal.price_sats?.toLocaleString()} sats sent to your wallet.</p>
				<p class="thank-you">Deal complete.</p>
				<div class="completed-actions">
					<a href="/" class="btn">View My Deals</a>
					<a href="/create" class="btn primary">Create New Deal</a>
				</div>
			{:else if deal.payout_status === 'awaiting_address'}
				<h2>Submit Payment Address</h2>
				<p>The dispute has been resolved in your favor. Submit your Lightning Address to receive {deal.price_sats?.toLocaleString()} sats.</p>
				<PayoutForm
					type="release"
					{deal}
					{dealId}
					{storedKey}
					{lndDown}
					getSignedAction={(action) => getSignedAction(action, 'seller')}
					getAuthenticatedUserId={() => getAuthenticatedUserId('seller')}
					{onDealUpdate}
				/>
			{:else if deal.payout_status === 'pending'}
				<h2>Payment Processing...</h2>
				<p>Sending {deal.price_sats?.toLocaleString()} sats to your wallet.</p>
				<PayoutTimer />
			{:else if deal.payout_status === 'failed'}
				<h2>Payment Failed</h2>
				<p>We couldn't send the payment. Try a different Lightning Address.</p>
				<PayoutForm
					type="release"
					{deal}
					{dealId}
					{storedKey}
					{lndDown}
					getSignedAction={(action) => getSignedAction(action, 'seller')}
					getAuthenticatedUserId={() => getAuthenticatedUserId('seller')}
					{onDealUpdate}
				/>
			{:else if deal.payout_status === 'payout_stuck'}
				<div class="warning-box">
					<strong>Payment requires manual review</strong>
					We were unable to send payment to your Lightning Address after multiple attempts. Your funds are safe — please contact support to receive them.
				</div>
			{:else}
				<div class="celebration">🎉</div>
				<h2>Deal Completed!</h2>
				<p>Funds have been released. Payment is on its way.</p>
				<p class="thank-you">Deal complete.</p>
				<div class="completed-actions">
					<a href="/" class="btn">View My Deals</a>
					<a href="/create" class="btn primary">Create New Deal</a>
				</div>
			{/if}
		{:else}
			{#if deal.status === 'released'}
				<h2>Funds Released</h2>
				<p>You've released the funds. The seller will be notified to collect payment.</p>
				<p class="invoice-status">You can safely close this page.</p>
			{:else}
				<div class="celebration">🎉</div>
				<h2>Deal Completed!</h2>
				<p>Funds have been released to the seller.</p>
				<p class="thank-you">Deal complete.</p>
			{/if}
			<div class="completed-actions">
				<a href="/" class="btn">View My Deals</a>
				<a href="/create" class="btn primary">Create New Deal</a>
			</div>
		{/if}
	</div>
{:else if deal.status === 'refunded'}

	<div class="action-content refunded-state">
		{#if userRole === 'buyer'}
			{#if deal.buyer_payout_status === 'paid'}
				<div class="celebration">🎉</div>
				<h2>Refund Received!</h2>
				<p>{deal.price_sats?.toLocaleString()} sats returned to your wallet.</p>
				<p class="thank-you">Refund complete.</p>
				<div class="completed-actions">
					<a href="/" class="btn">View My Deals</a>
					<a href="/create" class="btn primary">Create New Deal</a>
				</div>
			{:else if deal.buyer_payout_status === 'awaiting_address'}
				<h2>Submit Refund Address</h2>
				<p>The dispute has been resolved in your favor. Submit your Lightning Address to receive your {deal.price_sats?.toLocaleString()} sats refund.</p>
				<PayoutForm
					type="refund"
					{deal}
					{dealId}
					{storedKey}
					{lndDown}
					getSignedAction={(action) => getSignedAction(action, 'buyer')}
					getAuthenticatedUserId={() => getAuthenticatedUserId('buyer')}
					{onDealUpdate}
				/>
			{:else if deal.buyer_payout_status === 'pending'}
				<h2>Refund Processing...</h2>
				<p>Sending {deal.price_sats?.toLocaleString()} sats back to your wallet.</p>
				<PayoutTimer />
			{:else if deal.buyer_payout_status === 'failed'}
				<h2>Refund Payment Failed</h2>
				<p>We couldn't send the refund. Try a different Lightning Address.</p>
				<PayoutForm
					type="refund"
					{deal}
					{dealId}
					{storedKey}
					{lndDown}
					getSignedAction={(action) => getSignedAction(action, 'buyer')}
					getAuthenticatedUserId={() => getAuthenticatedUserId('buyer')}
					{onDealUpdate}
				/>
			{:else if deal.buyer_payout_status === 'payout_stuck'}
				<div class="warning-box">
					<strong>Refund requires manual review</strong>
					We were unable to send your refund after multiple attempts. Your funds are safe — please contact support to receive them.
				</div>
			{:else}
				<span class="big-icon">↩</span>
				<h2>Refund on Its Way!</h2>
				<p>Your refund is being processed.</p>
				<div class="completed-actions">
					<a href="/" class="btn">View My Deals</a>
					<a href="/create" class="btn primary">Create New Deal</a>
				</div>
			{/if}
		{:else}
			<span class="big-icon">↩</span>
			<h2>Deal Refunded</h2>
			<p>Funds have been returned to the buyer.</p>
			<div class="completed-actions">
				<a href="/" class="btn">View My Deals</a>
				<a href="/create" class="btn primary">Create New Deal</a>
			</div>
		{/if}
	</div>
{/if}

<style>
	@import '$lib/styles/deal-shared.css';
</style>
