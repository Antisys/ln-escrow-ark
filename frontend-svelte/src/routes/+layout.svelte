<script>
	import { navAuth } from '$lib/stores/nav.js';

	let { children } = $props();
</script>

<div class="app">
	<nav>
		<div class="nav-inner">
		<div class="nav-left">
			<a href="/" class="logo">
				<img src="/logo.svg" alt="Logo" class="logo-icon" />
				<span class="brand">trust<span class="brand-me">Me</span><span class="brand-bro">Bro</span></span>
			</a>
			</div>
		<div class="nav-right">
			{#if $navAuth?.role === 'signed-in' && $navAuth?.onSignOut}
				<button class="nav-auth-btn sign-out" onclick={$navAuth.onSignOut}>Sign Out</button>
			{:else if $navAuth?.role === 'signed-in'}
				<span class="nav-signed-in">&#10003; Signed in</span>
			{:else if $navAuth?.role}
				<span class="nav-role-badge {$navAuth.role}">
					{$navAuth.role === 'seller' ? '🏷️ Seller' : '🛒 Buyer'}
				</span>
			{:else if $navAuth?.onGlobalSignIn}
				<button class="nav-auth-btn primary" onclick={$navAuth.onGlobalSignIn}>⚡ Sign In</button>
			{/if}
		</div>
		</div>
	</nav>

	<main>
		{@render children()}
	</main>
</div>

<style>
	:global(*) {
		box-sizing: border-box;
		margin: 0;
		padding: 0;
	}

	:global(:root) {
		/* Surface colors (dark theme) */
		--bg: #1a1a1a;
		--surface: #2a2a2a;
		--border: #3a3a3a;
		--border-hover: #4a4a4a;

		/* Text */
		--text: #e0e0e0;
		--text-muted: #888;
		--text-dim: #666;

		/* Accent */
		--accent: #00d4aa;
		--accent-hover: #00b894;
		--accent-bg: #00d4aa22;
		--accent-border: #00d4aa44;

		/* Bitcoin orange */
		--orange: #f7931a;
		--orange-bg: #f7931a22;
		--orange-border: #f7931a44;

		/* Status colors */
		--success: #22c55e;
		--success-bg: #22c55e22;
		--error: #ef4444;
		--error-hover: #dc2626;
		--error-bg: #ef444422;
		--info: #3b82f6;
		--info-bg: #3b82f622;
		--info-bg-hover: #3b82f633;
		--info-border: #3b82f644;

		/* Warning (yellow/amber) */
		--warning: #f59e0b;
		--warning-bg: #f59e0b22;
	}

	:global(body) {
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
		background: var(--bg);
		color: var(--text);
		line-height: 1.6;
	}

	:global(a) {
		color: var(--accent);
		text-decoration: none;
		transition: text-shadow 0.2s, color 0.2s;
	}

	:global(a:hover) {
		color: #ffffff;
		text-shadow: 0 0 12px rgba(0, 212, 170, 0.8), 0 0 24px rgba(0, 212, 170, 0.4);
	}

	.app {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
	}

	nav {
		background: var(--surface);
		padding: 0 1.5rem;
		border-bottom: 1px solid var(--border);
		position: sticky;
		top: 0;
		z-index: 100;
	}

	.nav-inner {
		display: flex;
		justify-content: space-between;
		align-items: center;
		max-width: 600px;
		margin: 0 auto;
		padding: 0.75rem 0;
		gap: 0.5rem;
	}

	.nav-left {
		display: flex;
		gap: 2rem;
		align-items: center;
	}

	.logo {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		font-size: 1.6rem;
		font-weight: bold;
		color: var(--accent);
	}

	.logo-icon {
		width: 52px;
		height: 52px;
	}

	.brand-me {
		color: var(--orange);
	}

	.brand-bro {
		color: var(--text);
	}

	.nav-right {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.nav-right :global(.nav-auth-btn) {
		padding: 0.5rem 0.75rem;
		border-radius: 6px;
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
		border: 1px solid var(--border-hover);
		background: transparent;
		color: var(--text);
		white-space: nowrap;
	}

	.nav-right :global(.nav-auth-btn:hover) {
		background: var(--border-hover);
	}

	.nav-right :global(.nav-auth-btn.primary) {
		background: linear-gradient(135deg, var(--orange), #ff6b00);
		border: none;
		color: white;
	}

	.nav-right :global(.nav-auth-btn.primary:hover) {
		opacity: 0.9;
	}

	.nav-right :global(.nav-role-badge) {
		padding: 0.4rem 0.75rem;
		border-radius: 20px;
		font-size: 0.8rem;
		font-weight: 600;
		background: var(--accent-bg);
		color: var(--accent);
		border: 1px solid var(--accent-border);
	}

	.nav-right :global(.nav-role-badge.seller) {
		background: var(--orange-bg);
		color: var(--orange);
		border-color: var(--orange-border);
	}

	.nav-right :global(.nav-signed-in) {
		padding: 0.4rem 0.75rem;
		border-radius: 20px;
		font-size: 0.8rem;
		font-weight: 600;
		background: var(--success-bg);
		color: var(--success);
		border: 1px solid #22c55e44;
	}

	.nav-right :global(.sign-out) {
		background: transparent;
		border: 1px solid var(--text-dim);
		color: var(--text-muted);
		font-size: 0.8rem;
	}

	.nav-right :global(.sign-out:hover) {
		border-color: var(--error);
		color: var(--error);
		background: transparent;
	}

	button {
		padding: 0.5rem 1rem;
		border-radius: 4px;
		border: 1px solid var(--border-hover);
		background: var(--border);
		color: var(--text);
		cursor: pointer;
	}

	button:hover {
		background: var(--border-hover);
	}

	button.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--bg);
		font-weight: 600;
	}

	button.primary:hover {
		background: var(--accent-hover);
	}

	main {
		flex: 1;
		padding: 1.5rem;
		width: 100%;
	}

	@media (max-width: 768px) {
		nav {
			padding: 0 1rem;
		}
		.logo {
			font-size: 1.2rem;
			gap: 0.4rem;
		}
		.logo-icon {
			width: 36px;
			height: 36px;
		}
		main {
			padding: 1rem;
		}
	}

	@media (max-width: 480px) {
		main {
			padding: 0.75rem;
		}
	}
</style>
