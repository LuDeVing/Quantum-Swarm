// Displays the per-step agent event log.
// Each event: { agent, event, energy, timestamp }
export default function AgentTrace({ events }) {
  if (!events.length) {
    return <p className="text-gray-500 text-sm">No events yet.</p>
  }

  return (
    <ol className="space-y-1 font-mono text-xs text-gray-400">
      {events.map((e, i) => (
        <li key={i} className="flex gap-3">
          <span className="text-gray-600 w-6 text-right">{i + 1}</span>
          <span className="text-violet-400 w-20 shrink-0">{e.agent}</span>
          <span className="flex-1">{e.event}</span>
          {e.energy != null && (
            <span className="text-gray-600">H={e.energy.toFixed(4)}</span>
          )}
        </li>
      ))}
    </ol>
  )
}
