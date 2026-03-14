<script>
	import WalletBar from '$lib/components/WalletBar.svelte';
	let { children } = $props();
</script>

<svelte:head>
	<title>Arkana</title>
</svelte:head>

<WalletBar />
<main>{@render children()}</main>

<style>
	:global(body) { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #eee; }
	:global(a) { color: #f7931a; }
	main { max-width: 600px; margin: 0 auto; padding: 1rem; }
</style>
