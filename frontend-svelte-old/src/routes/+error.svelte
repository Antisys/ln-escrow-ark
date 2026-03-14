<script>
	import { page } from '$app/stores';
</script>

<div class="error-page">
	<h1>{$page.status}</h1>
	<p>{$page.error?.message || 'Something went wrong'}</p>
	<a href="/" class="btn">Back to Home</a>
</div>

<style>
	.error-page {
		max-width: 500px;
		margin: 4rem auto;
		text-align: center;
		padding: 2rem;
		background: var(--surface);
		border-radius: 8px;
		border: 1px solid var(--border);
	}

	h1 {
		color: var(--error);
		font-size: 3rem;
		margin-bottom: 0.5rem;
	}

	p {
		color: var(--text-muted);
		margin-bottom: 1.5rem;
	}

	.btn {
		display: inline-block;
		padding: 0.75rem 1.5rem;
		background: var(--accent);
		color: var(--bg);
		border-radius: 6px;
		text-decoration: none;
		font-weight: 600;
	}

	.btn:hover {
		opacity: 0.9;
		text-decoration: none;
	}
</style>
