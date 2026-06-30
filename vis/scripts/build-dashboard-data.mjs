import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..', '..')
const visRoot = resolve(import.meta.dirname, '..')
const results = resolve(root, 'demo', 'results')

const readJson = async (path) => JSON.parse(await readFile(path, 'utf8'))
const readJsonl = async (path) => (await readFile(path, 'utf8'))
  .trim()
  .split(/\r?\n/)
  .filter(Boolean)
  .map(JSON.parse)

const compactDebug = (row) => ({
  adaptive_mode: row.adaptive_mode,
  returned_count: row.returned_count,
  firewall_blocked_count: row.firewall_blocked_count,
  expected_net_profit: row.expected_net_profit,
  total_decision_ms: row.total_decision_ms,
  top_5_order_scores: (row.top_5_order_scores || []).slice(0, 4).map((item) => ({
    cargo_id: item.cargo_id,
    score: item.score,
    net_profit: item.net_profit,
  })),
})

const compactAction = (row) => ({
  simulation_end_time: row.simulation_end_time,
  position_after: row.position_after,
  action: {
    action: row.action?.action,
    params: row.action?.params,
  },
})

const actionFiles = {
  D001: 'actions_202603_D001_20260607_112455.jsonl',
  D002: 'actions_202603_D002_20260607_112455.jsonl',
}

const data = {
  runSummary: await readJson(resolve(results, 'run_summary_202603.json')),
  income: await readJson(resolve(results, 'monthly_income_202603.json')),
  strategyCsv: await readFile(resolve(results, 'experiments', 'summary.csv'), 'utf8'),
  actions: {},
  debug: {},
}

for (const driverId of Object.keys(actionFiles)) {
  data.actions[driverId] = (await readJsonl(resolve(results, actionFiles[driverId]))).map(compactAction)
  data.debug[driverId] = (await readJsonl(resolve(results, 'agent_debug', `${driverId}.jsonl`))).map(compactDebug)
}

await mkdir(resolve(visRoot, 'src', 'data'), { recursive: true })
await writeFile(
  resolve(visRoot, 'src', 'data', 'dashboard.json'),
  JSON.stringify(data),
  'utf8',
)
