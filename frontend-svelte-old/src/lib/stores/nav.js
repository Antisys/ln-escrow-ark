import { writable } from 'svelte/store';

// Store for nav bar auth state
// Components set this to show auth buttons in the global nav
export const navAuth = writable(null);

// Example value:
// {
//   role: 'buyer' | 'seller' | null,  // Current user role (if signed in)
//   deal: { ... },                     // Deal data for showing join buttons
//   onJoinSeller: () => {},            // Callback for "Join as Seller"
//   onJoinBuyer: () => {},             // Callback for "Join as Buyer"
// }

// Helper to clear nav auth (call on component destroy)
export function clearNavAuth() {
	navAuth.set(null);
}
