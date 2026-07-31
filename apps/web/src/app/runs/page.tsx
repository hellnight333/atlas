'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

type Run = { id: string; title: string; studio: string; status: string };

const statusLabel = (status: string) => {
  switch (status.toLowerCase()) {
    case 'running':
      return 'badge badge-running';
    case 'pending':
      return 'badge badge-pending';
    case 'completed':
      return 'badge badge-completed';
    case 'failed':
      return 'badge badge-failed';
    default:
      return 'badge badge-pending';
  }
};

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    fetch('http://127.0.0.1:8000/runs')
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to fetch runs');
        }
        return response.json();
      })
      .then((data) => {
        if (active) {
          setRuns(Array.isArray(data) ? data : []);
        }
      })
      .catch(() => {
        if (active) {
          setError('Atlas could not load run data. Check that the backend is running on port 8000.');
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  const totals = useMemo(() => {
    const initial = { total: 0, running: 0, pending: 0, completed: 0, failed: 0 };
    return runs.reduce((acc, run) => {
      acc.total += 1;
      const key = run.status.toLowerCase();
      if (key in acc) {
        (acc as any)[key] += 1;
      }
      return acc;
    }, initial);
  }, [runs]);

  return (
    <main>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', marginBottom: '2rem' }}>
        <div>
          <p style={{ margin: 0, color: '#7dd3fc', textTransform: 'uppercase', letterSpacing: '0.2em', fontSize: '0.78rem' }}>Atlas</p>
          <h1 style={{ margin: '0.75rem 0 0', fontSize: 'clamp(2rem, 3vw, 2.75rem)' }}>Runs overview</h1>
          <p style={{ margin: '1rem 0 0', maxWidth: 680, color: '#cbd5e1', lineHeight: 1.75 }}>
            Monitor active executions, queued work, and run status in a single dashboard. This view connects directly to the backend API and shows live run state as it becomes available.
          </p>
        </div>
        <Link href="/">
          <button>Back to dashboard</button>
        </Link>
      </header>

      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem', marginBottom: '1.75rem' }}>
        <div className="glass-card" style={{ padding: '1.25rem' }}>
          <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.85rem' }}>Total runs</p>
          <p style={{ margin: '0.85rem 0 0', fontSize: '2rem', fontWeight: 700 }}>{totals.total}</p>
        </div>
        <div className="glass-card" style={{ padding: '1.25rem' }}>
          <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.85rem' }}>Running</p>
          <p style={{ margin: '0.85rem 0 0', fontSize: '2rem', fontWeight: 700 }}>{totals.running}</p>
        </div>
        <div className="glass-card" style={{ padding: '1.25rem' }}>
          <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.85rem' }}>Completed</p>
          <p style={{ margin: '0.85rem 0 0', fontSize: '2rem', fontWeight: 700 }}>{totals.completed}</p>
        </div>
        <div className="glass-card" style={{ padding: '1.25rem' }}>
          <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.85rem' }}>Pending</p>
          <p style={{ margin: '0.85rem 0 0', fontSize: '2rem', fontWeight: 700 }}>{totals.pending}</p>
        </div>
      </section>

      {error ? (
        <div className="glass-card" style={{ padding: '1.5rem', color: '#fecaca' }}>
          <p style={{ margin: 0, fontWeight: 600 }}>Error loading runs</p>
          <p style={{ margin: '0.75rem 0 0', color: '#f8fafc' }}>{error}</p>
        </div>
      ) : loading ? (
        <div className="glass-card" style={{ padding: '1.5rem' }}>
          <p style={{ margin: 0, color: '#94a3b8' }}>Loading runs...</p>
        </div>
      ) : runs.length === 0 ? (
        <div className="glass-card" style={{ padding: '1.5rem' }}>
          <p style={{ margin: 0, color: '#94a3b8' }}>No runs available yet.</p>
          <p style={{ margin: '0.75rem 0 0', color: '#cbd5e1' }}>Create a new run from the dashboard once the backend is connected.</p>
        </div>
      ) : (
        <div className="glass-card" style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', minWidth: 720, borderCollapse: 'collapse' }}>
            <thead style={{ background: '#111827' }}>
              <tr>
                <th style={{ textAlign: 'left', padding: '1rem 1.25rem', color: '#94a3b8' }}>Run</th>
                <th style={{ textAlign: 'left', padding: '1rem 1.25rem', color: '#94a3b8' }}>Studio</th>
                <th style={{ textAlign: 'left', padding: '1rem 1.25rem', color: '#94a3b8' }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id} style={{ borderTop: '1px solid rgba(148, 163, 184, 0.12)' }}>
                  <td style={{ padding: '1rem 1.25rem' }}>
                    <Link href={`/runs/${run.id}`} style={{ color: '#e2e8f0', fontWeight: 600 }}>{run.title || run.id}</Link>
                  </td>
                  <td style={{ padding: '1rem 1.25rem', color: '#cbd5e1' }}>{run.studio || 'Unknown'}</td>
                  <td style={{ padding: '1rem 1.25rem' }}>
                    <span className={statusLabel(run.status)}>{run.status || 'Pending'}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
