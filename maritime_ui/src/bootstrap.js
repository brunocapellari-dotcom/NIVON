// Security bootstrap executes before the Maritime application module.
// Query-string endpoint/style overrides are useful during local development but are
// intentionally disabled in production so a shared link cannot redirect the cockpit
// to an arbitrary API or untrusted MapLibre style document.
if (!import.meta.env.DEV) {
  const url = new URL(window.location.href);
  let changed = false;
  for (const key of ['api', 'style']) {
    if (url.searchParams.has(key)) {
      url.searchParams.delete(key);
      changed = true;
    }
  }
  if (changed) {
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  }
}

await import('./main.js');
