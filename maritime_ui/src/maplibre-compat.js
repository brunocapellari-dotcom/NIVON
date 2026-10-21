import * as maplibregl from 'maplibre-gl/dist/maplibre-gl.mjs';
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';

maplibregl.setWorkerUrl(maplibreWorkerUrl);

export default maplibregl;
