import { useState } from 'react'
import TaskForm from './components/TaskForm'
import TaskReport from './components/TaskReport'

export default function App() {
  const [taskId, setTaskId] = useState(null)

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 p-6">
      <header className="max-w-3xl mx-auto mb-10">
        <h1 className="text-3xl font-bold tracking-tight">QuantumSwarm</h1>
        <p className="text-gray-400 mt-1">Physics-informed multi-agent AI</p>
      </header>

      <main className="max-w-3xl mx-auto space-y-8">
        <TaskForm onTaskCreated={setTaskId} />
        {taskId && <TaskReport taskId={taskId} />}
      </main>
    </div>
  )
}
