import type { Project } from '../types/domain'

import { Panel } from './Panel'

export function ProjectCard({ project }: { project: Project }) {
  return (
    <Panel title={project.name} subtitle={`${project.studio} · ${project.status}`}>
      <div className="text-sm text-slate-300">Progress {project.progress}%</div>
      <div className="mt-2 h-1.5 overflow-hidden rounded bg-slate-800">
        <div className="h-full bg-cyan-400" style={{ width: `${project.progress}%` }} />
      </div>
    </Panel>
  )
}
