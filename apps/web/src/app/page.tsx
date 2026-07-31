'use client';

import Link from 'next/link';
import { useState } from 'react';

const navItems = [
  { label: 'Dashboard', href: '/' },
  { label: 'Runs', href: '/runs' },
  { label: 'Studio', href: '/runs' },
  { label: 'Models', href: '/runs' },
];

const stats = [
  { label: 'Active Runs', value: '8', accent: '#38bdf8' },
  { label: 'Queued Jobs', value: '14', accent: '#facc15' },
  { label: 'Providers', value: '6', accent: '#a78bfa' },
  { label: 'System Load', value: '42%', accent: '#34d399' },
];

const projectCards = [
  { title: 'Atlas Web Platform', subtitle: 'AI orchestration shell', progress: 78 },
  { title: 'Image Studio', subtitle: 'Render workflow engine', progress: 59 },
  { title: 'Agent Runtime', subtitle: 'Plugin execution layer', progress: 42 },
];

export default function HomePage() {
  const [title, setTitle] = useState('New Atlas run');
  const [description, setDescription] = useState('Orchestrate a fresh workflow');
  const [studio, setStudio] = useState('image');
  const [statusMessage, setStatusMessage] = useState('');
  const [creating, setCreating] = useState(false);

  const createRun = async () => {
    setCreating(true);
    setStatusMessage('Creating run...');
    try {
      const response = await fetch('http://127.0.0.1:8000/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, description, studio }),
      });

      if (!response.ok) {
        throw new Error('Failed to create run');
      }

      const data = await response.json();
      setStatusMessage(`Run created: ${data.run_id}`);
      setTitle('New Atlas run');
      setDescription('Orchestrate a fresh workflow');
    } catch (error) {
      setStatusMessage('Unable to create run. Is the Atlas backend running?');
    } finally {
      setCreating(false);
    }
  };

  return (
    <main>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', marginBottom: '2rem' }}>
        <div>
          <p style={{ margin: 0, textTransform: 'uppercase', letterSpacing: '0.2em', color: '#7dd3fc', fontSize: '0.75rem' }}>Atlas</p>
          <h1 style={{ margin: '0.5rem 0 0', fontSize: 'clamp(2.2rem, 3vw, 3.5rem)' }}>AI operations made visible.</h1>
          <p style={{ maxWidth: 720, marginTop: '1rem', color: '#cbd5e1', fontSize: '1rem', lineHeight: 1.75 }}>
            Track runs, workflows, and provider status in one unified control plane. Atlas gives your AI stack a working dashboard with observability, run management, and a polished dark studio experience.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <Link href="/runs">
            <button>View Runs</button>
          </Link>
          <button style={{ background: '#334155' }} disabled>
            Open Studio
          </button>
        </div>
      </header>

      <nav style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '2rem' }}>
        {navItems.map((item) => (
          <Link key={item.label} href={item.href} style={{ color: '#94a3b8', padding: '0.75rem 1rem', borderRadius: 999, background: 'rgba(148, 163, 184, 0.08)' }}>
            {item.label}
          </Link>
        ))}
      </nav>

      <section style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: '1rem', marginBottom: '2rem' }}>
        <div className="glass-card" style={{ padding: '1.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', marginBottom: '1.25rem' }}>
            <div>
              <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.18em' }}>Quick start</p>
              <h2 style={{ margin: '0.75rem 0 0', fontSize: '1.85rem' }}>Launch your first run</h2>
            </div>
          </div>
          <div style={{ display: 'grid', gap: '1rem' }}>
            <label style={{ display: 'grid', gap: '0.5rem', color: '#e2e8f0' }}>
              Run title
              <input value={title} onChange={(event) => setTitle(event.target.value)} style={{ width: '100%', padding: '0.9rem 1rem', borderRadius: 16, border: '1px solid rgba(148, 163, 184, 0.18)', background: '#09101d', color: '#f8fafc' }} />
            </label>
            <label style={{ display: 'grid', gap: '0.5rem', color: '#e2e8f0' }}>
              Description
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} style={{ width: '100%', padding: '0.9rem 1rem', borderRadius: 16, border: '1px solid rgba(148, 163, 184, 0.18)', background: '#09101d', color: '#f8fafc' }} />
            </label>
            <label style={{ display: 'grid', gap: '0.5rem', color: '#e2e8f0' }}>
              Studio
              <select value={studio} onChange={(event) => setStudio(event.target.value)} style={{ width: '100%', padding: '0.9rem 1rem', borderRadius: 16, border: '1px solid rgba(148, 163, 184, 0.18)', background: '#09101d', color: '#f8fafc' }}>
                <option value="image">Image</option>
                <option value="text">Text</option>
                <option value="code">Code</option>
              </select>
            </label>
            <button onClick={createRun} disabled={creating} style={{ width: '100%' }}>
              {creating ? 'Creating...' : 'Create run'}
            </button>
            {statusMessage ? <p style={{ margin: 0, color: '#94a3b8' }}>{statusMessage}</p> : null}
          </div>
        </div>

        <aside className="glass-card" style={{ padding: '1.5rem' }}>
          <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.18em' }}>System summary</p>
          <div style={{ display: 'grid', gap: '1rem', marginTop: '1.25rem' }}>
            {stats.map((stat) => (
              <div key={stat.label} style={{ padding: '1rem', borderRadius: 20, background: 'rgba(148, 163, 184, 0.06)' }}>
                <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.85rem' }}>{stat.label}</p>
                <p style={{ margin: '0.75rem 0 0', fontSize: '1.75rem', fontWeight: 700, color: stat.accent }}>{stat.value}</p>
              </div>
            ))}
          </div>
        </aside>
      </section>

      <section style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '2rem' }}>
        <div className="glass-card" style={{ padding: '1.5rem' }}>
          <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.18em' }}>Overview</p>
          <h2 style={{ margin: '0.75rem 0 1rem', fontSize: '1.85rem' }}>Workflow health</h2>
          <p style={{ color: '#cbd5e1', lineHeight: 1.75 }}>
            Atlas is designed to keep your run queue visible, your providers connected, and your team ready to deploy workflows. The first release surface includes run management, job tracking, and a modular kernel foundation.
          </p>
        </div>
        <div className="glass-card" style={{ padding: '1.5rem' }}>
          <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.18em' }}>Latest updates</p>
          <div style={{ marginTop: '1.25rem', display: 'grid', gap: '1rem' }}>
            <div style={{ display: 'grid', gap: '0.25rem' }}>
              <p style={{ margin: 0, color: '#e2e8f0', fontWeight: 600 }}>Run queue stabilized</p>
              <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.95rem' }}>The backend now supports persistent runs and a worker queue with Postgres storage.</p>
            </div>
            <div style={{ display: 'grid', gap: '0.25rem' }}>
              <p style={{ margin: 0, color: '#e2e8f0', fontWeight: 600 }}>Dark UI dashboard</p>
              <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.95rem' }}>A premium control plane look and feel is now live in the web app shell.</p>
            </div>
          </div>
        </div>
      </section>

      <section>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
          <div>
            <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.18em' }}>Active projects</p>
            <h2 style={{ margin: '0.65rem 0 0', fontSize: '1.75rem' }}>Workflows in motion</h2>
          </div>
          <button>New workflow</button>
        </div>

        <div style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
          {projectCards.map((project) => (
            <div key={project.title} className="glass-card" style={{ padding: '1.35rem' }}>
              <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.85rem' }}>{project.subtitle}</p>
              <h3 style={{ margin: '0.75rem 0 1rem', fontSize: '1.25rem' }}>{project.title}</h3>
              <div style={{ height: 8, borderRadius: 999, background: 'rgba(148, 163, 184, 0.12)', overflow: 'hidden' }}>
                <div style={{ width: `${project.progress}%`, height: '100%', borderRadius: 999, background: '#38bdf8' }} />
              </div>
              <p style={{ margin: '0.75rem 0 0', color: '#94a3b8' }}>{project.progress}% complete</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
