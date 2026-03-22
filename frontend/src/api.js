const BASE = '/api'

export async function createTask(text, tokenBudget = 100000) {
  const res = await fetch(`${BASE}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, token_budget: tokenBudget }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getReport(taskId) {
  const res = await fetch(`${BASE}/tasks/${taskId}/report`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteTask(taskId) {
  const res = await fetch(`${BASE}/tasks/${taskId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}
