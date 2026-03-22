import { useState } from 'react'
import { createTask } from '../api'

export default function TaskForm({ onTaskCreated }) {
  const [text, setText] = useState('')
  const [budget, setBudget] = useState(100000)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const task = await createTask(text, budget)
      onTaskCreated(task.id)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm text-gray-400 mb-1">Task</label>
        <textarea
          className="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 text-gray-100 resize-none focus:outline-none focus:border-violet-500"
          rows={4}
          placeholder="e.g. Find mispriced markets on Polymarket in the US politics category"
          value={text}
          onChange={e => setText(e.target.value)}
          required
        />
      </div>

      <div>
        <label className="block text-sm text-gray-400 mb-1">
          Token budget: {budget.toLocaleString()}
        </label>
        <input
          type="range"
          min={10000}
          max={500000}
          step={10000}
          value={budget}
          onChange={e => setBudget(Number(e.target.value))}
          className="w-full accent-violet-500"
        />
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      <button
        type="submit"
        disabled={loading || !text.trim()}
        className="bg-violet-600 hover:bg-violet-500 disabled:opacity-40 px-5 py-2 rounded-lg font-medium transition-colors"
      >
        {loading ? 'Launching swarm…' : 'Run swarm'}
      </button>
    </form>
  )
}
