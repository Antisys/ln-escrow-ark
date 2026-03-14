<svelte:head>
	<title>How it works - trustMeBro-ARK</title>
</svelte:head>

<div class="how-page">
	<h1>How trustMeBro-ARK works</h1>
	<p class="subtitle">Secure Bitcoin escrow for peer-to-peer trades. No accounts, no custody, just Lightning.</p>

	<!-- The Flow -->
	<section class="section">
		<h2>The deal flow</h2>
		<div class="flow">
			<div class="flow-step">
				<div class="flow-num">1</div>
				<div class="flow-content">
					<strong>Create a deal</strong>
					<p>The seller sets the price, terms, and timeout. They get a shareable link.</p>
				</div>
			</div>
			<div class="flow-connector"></div>
			<div class="flow-step">
				<div class="flow-num">2</div>
				<div class="flow-content">
					<strong>Buyer joins and pays</strong>
					<p>The buyer opens the link, signs in with their Lightning wallet, and pays a Lightning invoice. Funds are locked in escrow.</p>
				</div>
			</div>
			<div class="flow-connector"></div>
			<div class="flow-step">
				<div class="flow-num">3</div>
				<div class="flow-content">
					<strong>Seller delivers</strong>
					<p>The seller ships the goods or delivers the service. They can mark the deal as shipped with tracking info.</p>
				</div>
			</div>
			<div class="flow-connector"></div>
			<div class="flow-step">
				<div class="flow-num">4</div>
				<div class="flow-content">
					<strong>Buyer releases funds</strong>
					<p>Once satisfied, the buyer releases the escrow. The seller receives sats instantly via Lightning.</p>
				</div>
			</div>
		</div>
	</section>

	<!-- Trust Model -->
	<section class="section">
		<h2>Where are the funds?</h2>
		<div class="card">
			<p>Your sats are held in a <strong>Fedimint federation</strong> &mdash; a group of independent guardians who jointly custody the funds. No single party (including us) can move your money.</p>
			<p>The service itself never holds your keys. It coordinates the deal, but the escrow is trustless.</p>
		</div>
	</section>

	<!-- What if things go wrong -->
	<section class="section">
		<h2>What if something goes wrong?</h2>
		<div class="scenarios">
			<div class="scenario">
				<div class="scenario-icon">T</div>
				<div class="scenario-content">
					<strong>Deal times out</strong>
					<p>Every deal has a timeout (set by the seller). When it expires, funds are automatically returned based on the timeout action &mdash; typically a refund to the buyer.</p>
				</div>
			</div>
			<div class="scenario">
				<div class="scenario-icon">!</div>
				<div class="scenario-content">
					<strong>Dispute</strong>
					<p>Either party can open a dispute. Three independent oracles review the case and decide who gets the funds. Two out of three must agree.</p>
				</div>
			</div>
			<div class="scenario">
				<div class="scenario-icon">X</div>
				<div class="scenario-content">
					<strong>Service goes offline</strong>
					<p>If the service disappears, the Fedimint timeout will automatically execute. Your funds are never permanently stuck.</p>
				</div>
			</div>
		</div>
	</section>

	<!-- Identity -->
	<section class="section">
		<h2>No accounts needed</h2>
		<div class="card">
			<p>You sign in with your Lightning wallet via <strong>LNURL-auth</strong>. No email, no password, no KYC. Your wallet proves your identity with a cryptographic signature.</p>
			<p>Deal keys are stored in your browser. Sign in from any device with the same wallet to recover your deals.</p>
		</div>
	</section>

	<!-- Quick facts -->
	<section class="section">
		<h2>Quick facts</h2>
		<div class="facts">
			<div class="fact">
				<span class="fact-label">Payment</span>
				<span class="fact-value">Lightning only</span>
			</div>
			<div class="fact">
				<span class="fact-label">Min deal</span>
				<span class="fact-value">1,000 sats</span>
			</div>
			<div class="fact">
				<span class="fact-label">Timeout</span>
				<span class="fact-value">1 hour to 30 days</span>
			</div>
			<div class="fact">
				<span class="fact-label">Disputes</span>
				<span class="fact-value">2-of-3 oracle resolution</span>
			</div>
			<div class="fact">
				<span class="fact-label">Custody</span>
				<span class="fact-value">Fedimint federation (not us)</span>
			</div>
		</div>
	</section>

	<div class="cta">
		<a href="/create" class="btn primary large">Create your first deal</a>
		<a href="/" class="btn secondary">Back to home</a>
	</div>
</div>

<style>
	.how-page {
		max-width: 640px;
		width: 100%;
		margin: 0 auto;
		padding-bottom: 3rem;
	}

	h1 {
		color: var(--text);
		font-size: 1.75rem;
		text-align: center;
		margin-bottom: 0.5rem;
		padding-top: 1rem;
	}

	.subtitle {
		color: var(--text-muted);
		text-align: center;
		font-size: 0.95rem;
		margin-bottom: 2rem;
	}

	.section {
		margin-bottom: 2rem;
	}

	h2 {
		color: var(--text);
		font-size: 1.15rem;
		margin-bottom: 0.75rem;
	}

	/* Flow */
	.flow {
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	.flow-step {
		display: flex;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
	}

	.flow-num {
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
		margin-top: 0.1rem;
	}

	.flow-content strong {
		color: var(--text);
		font-size: 0.95rem;
		display: block;
		margin-bottom: 0.2rem;
	}

	.flow-content p {
		color: var(--text-muted);
		font-size: 0.85rem;
		line-height: 1.4;
		margin: 0;
	}

	.flow-connector {
		width: 2px;
		height: 16px;
		background: var(--border);
		margin-left: 2.1rem;
	}

	/* Card */
	.card {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 1rem 1.25rem;
	}

	.card p {
		color: var(--text-muted);
		font-size: 0.9rem;
		line-height: 1.5;
		margin: 0 0 0.5rem;
	}

	.card p:last-child {
		margin-bottom: 0;
	}

	.card strong {
		color: var(--accent);
	}

	/* Scenarios */
	.scenarios {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.scenario {
		display: flex;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
	}

	.scenario-icon {
		min-width: 32px;
		height: 32px;
		border-radius: 6px;
		background: var(--orange-bg);
		color: var(--orange);
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 0.8rem;
		font-weight: 700;
		flex-shrink: 0;
	}

	.scenario-content strong {
		color: var(--text);
		font-size: 0.9rem;
		display: block;
		margin-bottom: 0.15rem;
	}

	.scenario-content p {
		color: var(--text-muted);
		font-size: 0.85rem;
		line-height: 1.4;
		margin: 0;
	}

	/* Facts */
	.facts {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		overflow: hidden;
	}

	.fact {
		display: flex;
		justify-content: space-between;
		padding: 0.6rem 1rem;
		border-bottom: 1px solid var(--border);
	}

	.fact:last-child {
		border-bottom: none;
	}

	.fact-label {
		color: var(--text-muted);
		font-size: 0.85rem;
	}

	.fact-value {
		color: var(--text);
		font-size: 0.85rem;
		font-weight: 500;
	}

	/* CTA */
	.cta {
		display: flex;
		justify-content: center;
		gap: 1rem;
		margin-top: 2rem;
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
		padding: 0.85rem 2rem;
		font-size: 1rem;
	}

	.btn.secondary {
		background: transparent;
		border: 1px solid var(--border-hover);
		color: var(--text-muted);
	}

	.btn.secondary:hover {
		border-color: var(--accent);
		color: var(--accent);
		text-decoration: none;
	}

	@media (max-width: 640px) {
		h1 {
			font-size: 1.4rem;
		}

		.cta {
			flex-direction: column;
			align-items: center;
		}
	}
</style>
