const CONFLICT_FLAGS = new Set([
  'ais_port_divergence',
  'terminal_divergence',
  'lineup_says_berthed_but_ais_waiting',
  'lineup_realized_not_confirmed',
]);

const FRESHNESS_THRESHOLDS_MINUTES = {
  AIS_OBSERVED: {fresh: 15, delayed: 60},
  LINEUP_PROGRAMMED: {fresh: 360, delayed: 1440},
  RECONCILIATION: {fresh: 60, delayed: 360},
};

function parseFlags(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function classifyMatch(row) {
  const confidence = Number(row?.match_confidence);
  if (!row?.reconciliation_id || !Number.isFinite(confidence) || confidence <= 0) {
    return {key: 'SEM_MATCH', label: 'Sem match'};
  }

  const flags = parseFlags(row.flags_json);
  if (flags.some(flag => CONFLICT_FLAGS.has(flag))) {
    return {key: 'CONFLITO', label: 'Conflito'};
  }

  const method = String(row.match_method || '').toUpperCase();
  if (method === 'IMO' || method === 'MMSI') {
    return {key: 'CONFIRMADO', label: 'Confirmado'};
  }
  if (method === 'NAME_FUZZY') {
    return {key: 'PROVAVEL', label: 'Provável'};
  }
  return {key: 'PROVAVEL', label: 'Provável'};
}

export function summarizeMatches(rows) {
  const summary = {CONFIRMADO: 0, PROVAVEL: 0, CONFLITO: 0, SEM_MATCH: 0};
  for (const row of rows || []) {
    summary[classifyMatch(row).key] += 1;
  }
  return summary;
}

function latestTimestamp(rows, field) {
  let latest = null;
  for (const row of rows || []) {
    if (!row?.[field]) continue;
    const ts = new Date(row[field]).getTime();
    if (!Number.isFinite(ts)) continue;
    if (latest == null || ts > latest) latest = ts;
  }
  return latest;
}

function freshnessEntry(kind, label, timestampMs, nowMs) {
  if (timestampMs == null) {
    return {kind, label, status: 'UNAVAILABLE', ageMinutes: null, latestAt: null};
  }
  const ageMinutes = Math.max(0, (nowMs - timestampMs) / 60000);
  const threshold = FRESHNESS_THRESHOLDS_MINUTES[kind];
  let status = 'FRESH';
  if (threshold && ageMinutes > threshold.delayed) status = 'STALE';
  else if (threshold && ageMinutes > threshold.fresh) status = 'DELAYED';
  return {
    kind,
    label,
    status,
    ageMinutes,
    latestAt: new Date(timestampMs).toISOString(),
    monitoringThresholdMinutes: threshold?.fresh ?? null,
  };
}

export function buildSourceHealth(vessels, lineup, now = new Date()) {
  const nowMs = now.getTime();
  return [
    freshnessEntry(
      'AIS_OBSERVED',
      'AIS observado',
      latestTimestamp(vessels, 'observed_at'),
      nowMs,
    ),
    freshnessEntry(
      'LINEUP_PROGRAMMED',
      'Line-up informado',
      latestTimestamp(lineup, 'collected_at'),
      nowMs,
    ),
    freshnessEntry(
      'RECONCILIATION',
      'Reconciliação AIS × line-up',
      latestTimestamp(lineup, 'calculated_at'),
      nowMs,
    ),
  ];
}

export function buildOperationalBrief(summary = {}, lineup = []) {
  const matches = summarizeMatches(lineup);
  const conflicts = (lineup || []).filter(row => classifyMatch(row).key === 'CONFLITO');
  const unmatched = (lineup || []).filter(row => classifyMatch(row).key === 'SEM_MATCH');
  return {
    matches,
    conflicts,
    unmatched,
    sections: [
      {
        title: 'Situação física',
        evidence: 'AIS_OBSERVED',
        text: `${Number(summary.vessels_live || 0)} navios recentes; ${Number(summary.vessels_approaching || 0)} em aproximação, ${Number(summary.vessels_waiting || 0)} aguardando e ${Number(summary.vessels_berthed || 0)} em berço.`,
      },
      {
        title: 'Programação',
        evidence: 'LINEUP_PROGRAMMED',
        text: `${Number(summary.lineup_calls || 0)} escalas no horizonte selecionado. Programação permanece separada de realização operacional.`,
      },
      {
        title: 'Confronto AIS × line-up',
        evidence: 'DERIVED',
        text: `${matches.CONFIRMADO} confirmados, ${matches.PROVAVEL} prováveis, ${matches.CONFLITO} conflitos e ${matches.SEM_MATCH} sem match.`,
      },
      {
        title: 'Desempenho observado',
        evidence: 'DERIVED',
        text: `Espera P50 ${formatHours(summary.waiting_p50_hours)}, P90 ${formatHours(summary.waiting_p90_hours)}, erro absoluto médio de ETA ${formatHours(summary.eta_mae_hours)} e permanência média em berço ${formatHours(summary.berth_avg_hours)}.`,
      },
      {
        title: 'Modelos avançados',
        evidence: 'DATA_GATED',
        text: 'VQI, Port Pressure Score e previsão de fila 6/24/48h permanecem bloqueados até histórico e calibração suficientes; nenhum score é fabricado na V1.',
      },
    ],
  };
}

function formatHours(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(1)} h` : '—';
}
