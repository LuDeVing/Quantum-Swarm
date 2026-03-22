import { useEffect, useState } from 'react'
import { getReport } from '../api'
import AgentTrace from './AgentTrace'
import ClaimList from './ClaimList'

const POLL_INTERVAL = 2000

export default function TaskReport({ taskId }) {
  const [report, setReport] = useState(null)
  const [status, setStatus] = useState('PENDING')

  useEffect(() => {
    let timer

    async function poll() {
      const data = await getReport(taskId)
      setStatus(data.status)
      if (data.status === 'DONE' || data.status === 'FAILED') {
        setReport(data)
      } else {
        timer = setTimeout(poll, POLL_INTERVAL)
      }
    }

    poll()
    return () => clearTimeout(timer)
  }, [taskId])

  if (status === 'PENDING' || status === 'RUNNING') {
    return (
      <div className="text-gray-400 animate-pulse">
        Swarm running — agents active…
      </div>
    )
  }

  if (status === 'FAILED') {
    return <div className="text-red-400">Task failed. Check agent trace.</div>
  }

  if (!report) return null

  return (
    <div className="space-y-6">
      {/* token usage */}
      <div className="text-xs text-gray-500">
        Tokens used: {report.tokens_used?.toLocaleString() ?? '—'} /{' '}
        {report.tokens_budget?.toLocaleString()}
      </div>

      {/* claims */}
      <section>
        <h2 className="text-lg font-semibold mb-3">Findings</h2>
        {/* TODO: replace with real data */}
        <ClaimList claims={report.claims ?? []} />
      </section>

      {/* agent trace */}
      <section>
        <h2 className="text-lg font-semibold mb-3">Agent trace</h2>
        {/* TODO: replace with real data */}
        <AgentTrace events={report.trace ?? []} />
      </section>
    </div>
  )
}
