import React from 'react'

export default function KpiStrip({ track, latency, agents, diagrams }) {
  const cells = [
    { label: 'Overall score', value: track },
    { label: 'Time taken', value: latency },
    { label: 'Agents that ran', value: agents },
    { label: 'Diagrams produced', value: diagrams },
  ]
  return (
    <div className="panel grid grid-cols-2 md:grid-cols-4 divide-y md:divide-y-0 md:divide-x divide-borderSubtle">
      {cells.map((c) => (
        <div key={c.label} className="p-5 space-y-1">
          <div className="label">{c.label}</div>
          <div className="text-lg font-semibold text-white">{c.value}</div>
        </div>
      ))}
    </div>
  )
}
