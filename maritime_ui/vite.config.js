import {fileURLToPath, URL} from 'node:url';
import {defineConfig} from 'vite';

export default defineConfig({
  base: '/maritime/',
  resolve: {
    alias: [
      {
        find: /^maplibre-gl$/,
        replacement: fileURLToPath(new URL('./src/maplibre-compat.js', import.meta.url)),
      },
      {
        find: /^@deck\.gl\/mapbox$/,
        replacement: fileURLToPath(new URL('./src/deck-maplibre-compat.js', import.meta.url)),
      },
    ],
  },
  build: {
    sourcemap: true,
  },
});
