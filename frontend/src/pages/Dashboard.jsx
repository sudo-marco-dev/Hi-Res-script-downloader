import { useState, useEffect } from 'react';
import { useProgressSocket } from '../hooks/useProgressSocket';
import { FaServer, FaCheck, FaExclamationTriangle, FaDownload } from 'react-icons/fa';
import toast from 'react-hot-toast';

export default function Dashboard() {
    const { isConnected, progress } = useProgressSocket();
    const [health, setHealth] = useState(null);
    const [jobs, setJobs] = useState([]);

    // Fetch initial health check
    useEffect(() => {
        fetch('/api/health')
            .then(res => res.json())
            .then(setHealth)
            .catch(err => toast.error('Backend offline'));

        // Initial jobs fetch
        fetch('/api/download/jobs')
            .then(res => res.json())
            .then(data => setJobs(data.jobs || []))
            .catch(console.error);
    }, []);

    // Update jobs list when socket messages arrive
    useEffect(() => {
        if (Object.keys(progress).length > 0) {
            // Merge progress into jobs list
            setJobs(currentJobs => {
                const jobMap = new Map(currentJobs.map(j => [j.job_id, j]));
                Object.values(progress).forEach(p => {
                    jobMap.set(p.job_id, { ...jobMap.get(p.job_id), ...p });
                });
                return Array.from(jobMap.values());
            });
        }
    }, [progress]);

    const startTestDownload = async () => {
        // Quick test download
        try {
            const res = await fetch('/api/download/single', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url: 'https://music.youtube.com/watch?v=3eeIu7N7xS0',
                    folder_name: 'Test Downloads',
                    format: 'flac'
                })
            });
            const data = await res.json();
            if (data.status === 'started') toast.success('Download started!');
        } catch (e) {
            toast.error('Failed to start download');
        }
    };

    return (
        <div className="p-8 space-y-8">
            <header className="flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-bold">Dashboard</h1>
                    <p className="text-gray-400">System overview and active downloads</p>
                </div>
                <div className={`px-4 py-2 rounded-full flex items-center space-x-2 text-sm font-medium ${isConnected ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
                    <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-400' : 'bg-red-400'}`}></div>
                    <span>{isConnected ? 'Backend Connected' : 'Disconnected'}</span>
                </div>
            </header>

            {/* Stats / Health */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <HealthCard label="FFmpeg" status={health?.ffmpeg_available} />
                <HealthCard label="yt-dlp" status={health?.ytdlp_available} />
                <HealthCard label="Node.js" status={health?.node_available} />
                <HealthCard label="Cookies" status={health?.cookies_found} />
            </div>

            {/* Active Downloads */}
            <div className="bg-surface rounded-2xl p-6 border border-white/5">
                <div className="flex justify-between items-center mb-6">
                    <h2 className="text-xl font-bold flex items-center gap-2">
                        <FaDownload className="text-primary" /> Active Downloads
                    </h2>
                    <button
                        onClick={startTestDownload}
                        className="px-4 py-2 bg-primary hover:bg-primary/80 transition rounded-lg text-sm font-medium"
                    >
                        Start Test Download
                    </button>
                </div>

                <div className="space-y-4">
                    {jobs.length === 0 ? (
                        <div className="text-center py-12 text-gray-500">
                            No active downloads
                        </div>
                    ) : (
                        jobs.map(job => (
                            <JobRow key={job.job_id} job={job} />
                        ))
                    )}
                </div>
            </div>
        </div>
    );
}

function HealthCard({ label, status }) {
    if (status === undefined) return <div className="bg-surface h-24 rounded-xl animate-pulse"></div>;
    return (
        <div className="bg-surface p-4 rounded-xl border border-white/5 flex items-center justify-between">
            <span className="font-medium text-gray-300">{label}</span>
            {status ? <FaCheck className="text-green-400" /> : <FaExclamationTriangle className="text-yellow-400" />}
        </div>
    );
}

function JobRow({ job }) {
    const isDone = job.status === 'done';
    const isFailed = job.status === 'failed';

    return (
        <div className="bg-background/50 p-4 rounded-xl border border-white/5">
            <div className="flex justify-between items-start mb-2">
                <div>
                    <h3 className="font-medium truncate max-w-md">{job.current_file || job.url}</h3>
                    <p className="text-xs text-gray-400">{job.folder}</p>
                </div>
                <span className={`text-xs px-2 py-1 rounded bg-white/5 uppercase ${isDone ? 'text-green-400' : isFailed ? 'text-red-400' : 'text-blue-400'
                    }`}>
                    {job.status}
                </span>
            </div>

            {!isDone && !isFailed && (
                <div className="space-y-1">
                    <div className="flex justify-between text-xs text-gray-400">
                        <span>{job.speed || '0 MiB/s'}</span>
                        <span>{job.eta || '--:--'}</span>
                    </div>
                    <div className="h-2 bg-white/10 rounded-full overflow-hidden">
                        <div
                            className="h-full bg-primary transition-all duration-300"
                            style={{ width: `${job.percent || 0}%` }}
                        ></div>
                    </div>
                </div>
            )}

            {isFailed && <p className="text-xs text-red-400 mt-2">Error: {job.error}</p>}
        </div>
    );
}
