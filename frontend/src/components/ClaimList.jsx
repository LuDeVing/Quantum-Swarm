// Displays structured claims extracted from agent outputs.
// Each claim: { entity, assertion, confidence, source_type, verified }
export default function ClaimList({ claims }) {
  if (!claims.length) {
    return <p className="text-gray-500 text-sm">No claims yet.</p>
  }

  return (
    <ul className="space-y-2">
      {claims.map((c, i) => (
        <li
          key={i}
          className="bg-gray-900 border border-gray-800 rounded-lg p-3 text-sm"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium text-gray-100">{c.assertion}</span>
            <ConfidenceBadge value={c.confidence} />
          </div>
          <div className="text-gray-500 mt-1 text-xs">
            {c.entity} — {c.source_type}
            {!c.verified && (
              <span className="ml-2 text-yellow-500">UNVERIFIED</span>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}

function ConfidenceBadge({ value }) {
  const pct = Math.round((value ?? 0) * 100)
  const color =
    pct >= 75 ? 'text-green-400' : pct >= 50 ? 'text-yellow-400' : 'text-red-400'
  return <span className={`font-mono text-xs ${color}`}>{pct}%</span>
}
