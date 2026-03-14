<script>
	import { createWallet, unlockWallet, hasWallet, getPublicKey, getBalance, getBoardingAddress } from '$lib/ark-wallet.js';
	import { walletStore } from '$lib/stores/wallet.js';

	let password = $state('');
	let error = $state('');
	let loading = $state(false);
	let seedPhrase = $state('');

	const existing = hasWallet();

	async function handleCreate() {
		if (!password || password.length < 4) { error = 'Password must be at least 4 characters'; return; }
		loading = true; error = '';
		try {
			const { privateKey, publicKey } = await createWallet(password);
			seedPhrase = privateKey; // In production: convert to BIP39 mnemonic
			await updateWalletState();
		} catch (e) { error = e.message; }
		loading = false;
	}

	async function handleUnlock() {
		if (!password) { error = 'Enter password'; return; }
		loading = true; error = '';
		const ok = await unlockWallet(password);
		if (!ok) { error = 'Wrong password'; loading = false; return; }
		await updateWalletState();
		loading = false;
	}

	async function updateWalletState() {
		const balance = await getBalance();
		const boardingAddr = await getBoardingAddress();
		walletStore.set({
			initialized: true, locked: false,
			publicKey: getPublicKey(),
			address: '', boardingAddress: boardingAddr,
			balance,
		});
	}
</script>

<div class="wallet-setup">
	{#if seedPhrase}
		<div class="seed-backup">
			<h3>Backup your key</h3>
			<p class="warning">Save this private key. You need it to recover your wallet.</p>
			<code class="seed">{seedPhrase}</code>
			<button onclick={() => seedPhrase = ''}>I saved it</button>
		</div>
	{:else if existing}
		<h3>Unlock Wallet</h3>
		<input type="password" bind:value={password} placeholder="Password" onkeydown={(e) => e.key === 'Enter' && handleUnlock()} />
		<button onclick={handleUnlock} disabled={loading}>{loading ? 'Unlocking...' : 'Unlock'}</button>
	{:else}
		<h3>Create Wallet</h3>
		<p>Your wallet lives in this browser. Set a password to protect it.</p>
		<input type="password" bind:value={password} placeholder="Choose password" onkeydown={(e) => e.key === 'Enter' && handleCreate()} />
		<button onclick={handleCreate} disabled={loading}>{loading ? 'Creating...' : 'Create Wallet'}</button>
	{/if}
	{#if error}<p class="error">{error}</p>{/if}
</div>

<style>
	.wallet-setup { max-width: 400px; margin: 2rem auto; text-align: center; }
	h3 { margin-bottom: 1rem; }
	input { width: 100%; padding: 0.75rem; border: 1px solid #333; border-radius: 8px; background: #1a1a1a; color: #fff; font-size: 1rem; margin-bottom: 0.75rem; }
	button { width: 100%; padding: 0.75rem; border: none; border-radius: 8px; background: #f7931a; color: #000; font-weight: bold; font-size: 1rem; cursor: pointer; }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	.error { color: #ff4444; margin-top: 0.5rem; }
	.warning { color: #f7931a; font-size: 0.9rem; }
	.seed { display: block; background: #111; padding: 1rem; border-radius: 8px; word-break: break-all; font-size: 0.8rem; margin: 1rem 0; color: #4ecdc4; }
	.seed-backup button { margin-top: 1rem; }
</style>
