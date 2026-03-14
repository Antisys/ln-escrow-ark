import { writable } from 'svelte/store';

export const walletStore = writable({
	initialized: false,
	locked: true,
	publicKey: '',
	address: '',
	boardingAddress: '',
	balance: { total: 0, offchain: 0, boarding: 0 },
});
