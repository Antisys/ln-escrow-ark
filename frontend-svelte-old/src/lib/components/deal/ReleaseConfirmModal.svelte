<script>
	let {
		show = $bindable(false),
		deal,
		releasing = false,
		onConfirm,
	} = $props();
</script>

{#if show}
	<div class="modal-overlay" onclick={() => !releasing && (show = false)} role="presentation" onkeydown={(e) => e.key === 'Escape' && !releasing && (show = false)}>
		<div class="modal confirm-modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Confirm release" onkeydown={(e) => e.stopPropagation()}>
			<button class="modal-close" onclick={() => !releasing && (show = false)} aria-label="Close" disabled={releasing}>&times;</button>
			<h2 class="release-title">Confirm Release</h2>
			<p class="confirm-amount">{deal.price_sats?.toLocaleString()} sats</p>
			{#if deal.seller_name}<p class="release-recipient">to <strong class="release-recipient-name">{deal.seller_name}</strong></p>{/if}
			<p class="release-warning-box">This will send funds to the seller via Lightning. This action is <strong>irreversible</strong>.</p>
			<div class="modal-actions">
				<button class="btn" onclick={() => show = false} disabled={releasing}>Cancel</button>
				<button class="btn danger" onclick={onConfirm} disabled={releasing}>
					{releasing ? 'Releasing...' : 'Confirm Release'}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	@import '$lib/styles/deal-shared.css';

	.release-title { color: var(--error); }
	.release-recipient { color: var(--text-muted); margin: 0 0 0.5rem; text-align: center; }
	.release-recipient-name { color: var(--text); }
	.release-warning-box {
		color: var(--error); background: var(--error-bg);
		padding: 0.75rem; border-radius: 6px;
		border: 1px solid var(--error-bg);
		text-align: center; margin-bottom: 1rem;
	}
</style>
