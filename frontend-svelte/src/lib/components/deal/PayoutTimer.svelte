<script>
	import { onMount, onDestroy } from 'svelte';

	const COUNTDOWN_SECS = 30;

	let remaining = $state(COUNTDOWN_SECS);
	let timer = null;

	onMount(() => {
		timer = setInterval(() => {
			if (remaining > 0) remaining--;
		}, 1000);
	});

	onDestroy(() => {
		if (timer) clearInterval(timer);
	});

	let display = $derived(remaining > 0 ? `${remaining}s` : '...');
	let progress = $derived(remaining / COUNTDOWN_SECS);
</script>

<div class="payout-timer">
	<div class="timer-ring">
		<svg viewBox="0 0 60 60">
			<circle cx="30" cy="30" r="26" class="ring-bg" />
			<circle cx="30" cy="30" r="26" class="ring-fg" style="stroke-dashoffset: {163.4 * (1 - progress)}" />
		</svg>
		<span class="timer-value">{display}</span>
	</div>
	{#if remaining <= 0}
		<p class="overtime">Taking longer than usual...</p>
	{/if}
</div>

<style>
	.payout-timer {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.75rem;
		padding: 1rem 0;
	}
	.timer-ring {
		position: relative;
		width: 72px;
		height: 72px;
	}
	.timer-ring svg {
		width: 100%;
		height: 100%;
		transform: rotate(-90deg);
	}
	.ring-bg {
		fill: none;
		stroke: #3a3a3a;
		stroke-width: 4;
	}
	.ring-fg {
		fill: none;
		stroke: #00d4aa;
		stroke-width: 4;
		stroke-dasharray: 163.4;
		stroke-linecap: round;
		transition: stroke-dashoffset 1s linear;
	}
	.timer-value {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 1.3rem;
		font-weight: 600;
		color: #e0e0e0;
		font-variant-numeric: tabular-nums;
	}
	.overtime {
		color: #888;
		font-size: 0.85rem;
		margin: 0;
		animation: pulse-text 2s ease-in-out infinite;
	}
	@keyframes pulse-text {
		0%, 100% { opacity: 0.6; }
		50% { opacity: 1; }
	}
</style>
