import { defineConfig } from 'vite';

export default defineConfig({
	build: {
		lib: {
			entry: 'src/ark-service-worker.js',
			formats: ['es'],
			fileName: () => 'ark-service-worker.mjs',
		},
		outDir: 'static',
		emptyOutDir: false,
		rollupOptions: {
			output: {
				entryFileNames: 'ark-service-worker.mjs',
			},
		},
	},
});
