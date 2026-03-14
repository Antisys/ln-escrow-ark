import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		port: 5173,
		host: '0.0.0.0',
		cors: true,
		allowedHosts: ['.localhost:8001']
	},
	define: {
		'global': 'globalThis',
		'process.env': {},
		'process.browser': true
	},
	resolve: {
		alias: {
			buffer: 'buffer',
		}
	},
	optimizeDeps: {
		include: ['buffer'],
		esbuildOptions: {
			define: {
				global: 'globalThis'
			}
		}
	},
	ssr: {
		external: ['buffer']
	}
});
