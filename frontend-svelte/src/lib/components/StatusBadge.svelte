<script>
	let { status } = $props();
	const colors = {
		pending: '#888', active: '#4ecdc4', funded: '#f7931a',
		shipped: '#9b59b6', released: '#2ecc71', completed: '#2ecc71',
		refunded: '#e74c3c', disputed: '#e67e22', expired: '#555',
	};
</script>

<span class="badge" style="background: {colors[status] || '#444'}">{status}</span>

<style>
	.badge { padding: 0.2rem 0.6rem; border-radius: 12px; font-size: 0.75rem; font-weight: bold; text-transform: uppercase; color: #000; }
</style>
