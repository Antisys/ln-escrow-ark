import { writable, get } from 'svelte/store';
import { browser } from '$app/environment';

function persistentWritable(key, initialValue) {
	let initial = initialValue;
	if (browser) {
		try {
			const stored = localStorage.getItem(key);
			if (stored) initial = JSON.parse(stored);
		} catch {
			localStorage.removeItem(key);
		}
	}
	const store = writable(initial);

	if (browser) {
		store.subscribe(value => {
			localStorage.setItem(key, JSON.stringify(value));
		});
	}

	return store;
}

// User's name (persistent)
export const userName = persistentWritable('vault_user_name', '');

// Stored private keys per deal, per role (persistent)
// Format: { [dealId]: { seller?: {privateKey, publicKey}, buyer?: {privateKey, publicKey} } }
// Legacy format (auto-migrated): { [dealId]: {privateKey, publicKey} }
export const dealKeys = persistentWritable('vault_deal_keys', {});

// LNURL-auth records per deal, per role (persistent)
// Format: { [dealId]: { seller?: {linkingKey, userId}, buyer?: {linkingKey, userId}, activeRole: string } }
// Legacy format (auto-migrated): { [dealId]: { linkingKey, role } }
export const dealAuths = persistentWritable('vault_deal_auths', {});

// --- Migration helpers ---
// Detect legacy format: has `privateKey` directly (not nested under role)
function isLegacyKeyEntry(entry) {
	return entry && 'privateKey' in entry && !('seller' in entry || 'buyer' in entry);
}
// Detect legacy format: has `role` as a string (not nested roles)
function isLegacyAuthEntry(entry) {
	return entry && typeof entry.role === 'string' && !('seller' in entry || 'buyer' in entry);
}

// Helper to store a key for a deal+role
export function storeKeyForDeal(dealId, privateKey, publicKey, role) {
	dealKeys.update(keys => {
		const existing = keys[dealId] || {};
		// Migrate legacy entry if present
		let migrated = existing;
		if (isLegacyKeyEntry(existing)) {
			// Can't know the old role — just start fresh with new role
			migrated = {};
		}
		return {
			...keys,
			[dealId]: { ...migrated, [role]: { privateKey, publicKey } }
		};
	});
}

// Helper to get key for a deal+role
export function getKeyForDeal(dealId, role) {
	const keys = get(dealKeys);
	const entry = keys[dealId];
	if (!entry) return null;
	if (isLegacyKeyEntry(entry)) return entry;
	return role ? (entry[role] || null) : null;
}

// Get the key entry for a deal (role-aware object or legacy)
export function getKeyEntryForDeal(dealId) {
	const keys = get(dealKeys);
	return keys[dealId] || null;
}

// Helper to store auth record for a deal+role
export function storeAuthForDeal(dealId, linkingKey, role, userId) {
	dealAuths.update(auths => {
		const existing = auths[dealId] || {};
		// Migrate legacy entry
		let migrated = existing;
		if (isLegacyAuthEntry(existing)) {
			const oldRole = existing.role;
			migrated = { [oldRole]: { linkingKey: existing.linkingKey, userId: existing.userId }, activeRole: oldRole };
		}
		return {
			...auths,
			[dealId]: {
				...migrated,
				[role]: { linkingKey, userId },
				activeRole: role,  // most recently signed-in role is active
			}
		};
	});
}

// Helper to get auth record for a deal
export function getAuthForDeal(dealId) {
	const auths = get(dealAuths);
	const entry = auths[dealId];
	if (!entry) return null;
	if (isLegacyAuthEntry(entry)) {
		return { role: entry.role, linkingKey: entry.linkingKey, userId: entry.userId };
	}
	const role = entry.activeRole;
	const roleData = entry[role];
	return roleData ? { role, linkingKey: roleData.linkingKey, userId: roleData.userId } : null;
}

// Get all roles stored for a deal
export function getRolesForDeal(dealId) {
	const auths = get(dealAuths);
	const entry = auths[dealId];
	if (!entry) return [];
	if (isLegacyAuthEntry(entry)) return [entry.role];
	return ['seller', 'buyer'].filter(r => entry[r]);
}

// Switch the active role for a deal
export function switchActiveRole(dealId, role) {
	dealAuths.update(auths => {
		const entry = auths[dealId];
		if (!entry) return auths;
		return { ...auths, [dealId]: { ...entry, activeRole: role } };
	});
}

// Escrow recovery codes per deal (buyer stores after funding — non-custodial key)
// Format: { [dealId]: string }
export const dealSecretCodes = persistentWritable('vault_deal_secret_codes', {});

export function storeSecretCodeForDeal(dealId, secretCode) {
	dealSecretCodes.update(codes => ({ ...codes, [dealId]: secretCode }));
}

export function getSecretCodeForDeal(dealId) {
	const codes = get(dealSecretCodes);
	return codes[dealId] || null;
}

export function clearSecretCodeForDeal(dealId) {
	dealSecretCodes.update(codes => {
		const { [dealId]: removed, ...rest } = codes;
		return rest;
	});
}

// Hidden (archived) deal IDs (persistent)
export const hiddenDeals = persistentWritable('vault_hidden_deals', []);

export function hideDeal(dealId) {
	hiddenDeals.update(ids => ids.includes(dealId) ? ids : [...ids, dealId]);
}

export function unhideDeal(dealId) {
	hiddenDeals.update(ids => ids.filter(id => id !== dealId));
}

// Helper to remove a deal from auth records (for cleanup of deleted deals)
export function removeAuthForDeal(dealId) {
	dealAuths.update(auths => {
		const { [dealId]: removed, ...rest } = auths;
		return rest;
	});
	// Also remove any stored keys for this deal
	dealKeys.update(keys => {
		const { [dealId]: removed, ...rest } = keys;
		return rest;
	});
}
