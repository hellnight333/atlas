'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';

export default function RunDetailPage() {
  const params = useParams();
  const [run, setRun] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!params?.id) {
      setError('Missing run id');
      setLoading(false);
      return;
    }

    fetch(`http://127.0.0.1:8000/runs/${params.id}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to load run');
        }
        return response.json();
      })
      .then((data) => {
        setRun(data);
      })
      .catch(() => {
        setError('Unable to load run detail. Make sure the backend is running.');
      })
      .finally(() => {
        setLoading(false);
      });
  }, [params]);

  if (loading) {
    return <main style={{ padding: '2rem' }}>Loading run details...</main>;
  }

  if (error) {
    return <main style={{ padding: '2rem', color: '#fecaca' }}>{error}</main>;
  }

  if (!run) {
    return <main style={{ padding: '2rem' }}>Run not found.</main>;
  }

  return (
    <main style={{ padding: '2rem' }}>
      <h1 style={{ margin: 0, fontSize: '2rem' }}>{run.title}</h1>
      <p style={{ color: '#94a3b8', marginTop: '0.75rem' }}>{run.description}</p>
      <div style={{ marginTop: '1.5rem', display: 'grid', gap: '1rem' }}>
        <div className="glass-card" style={{ padding: '1.25rem' }}>
          <p style={{ margin: 0, color: '#94a3b8' }}>Studio</p>
          <p style={{ margin: '0.5rem 0 0', fontWeight: 700 }}>{run.studio}</p>
        </div>
        <div className="glass-card" style={{ padding: '1.25rem' }}>
          <p style={{ margin: 0, color: '#94a3b8' }}>Status</p>
          <p style={{ margin: '0.5rem 0 0', fontWeight: 700 }}>{run.status}</p>
        </div>
        <div className="glass-card" style={{ padding: '1.25rem' }}>
          <p style={{ margin: 0, color: '#94a3b8' }}>Jobs</p>
          <p style={{ margin: '0.5rem 0 0', fontWeight: 700 }}>{run.job_count}</p>
        </div>
      </div>

      <section style={{ marginTop: '2rem' }}>
        <h2 style={{ marginBottom: '1rem' }}>Jobs</h2>
        <div style={{ display: 'grid', gap: '1rem' }}>
          {run.jobs.map((job: any) => (
            <div key={job.id} className="glass-card" style={{ padding: '1.25rem' }}>
              <div style={{ display: 'grid', gap: '0.75rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                  <div>
                    <p style={{ margin: 0, color: '#94a3b8' }}>Action</p>
                    <p style={{ margin: '0.5rem 0 0', fontWeight: 700 }}>{job.action}</p>
                  </div>
                  <div>
                    <p style={{ margin: 0, color: '#94a3b8' }}>Status</p>
                    <p style={{ margin: '0.5rem 0 0', fontWeight: 700 }}>{job.status}</p>
                  </div>
                </div>
                <div style={{ display: 'grid', gap: '0.5rem' }}>
                  <p style={{ margin: 0, color: '#94a3b8' }}>Provider</p>
                  <p style={{ margin: '0.5rem 0 0', fontWeight: 700 }}>{job.provider_name || 'pending'}</p>
                </div>
                {job.output ? (
                  <div style={{ background: '#0f172a', borderRadius: 16, padding: '1rem' }}>
                    <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.85rem' }}>Output</p>
                    <pre style={{ margin: '0.5rem 0 0', color: '#e2e8f0', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {JSON.stringify(job.output, null, 2)}
                    </pre>
                  </div>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
