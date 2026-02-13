import { useState, useEffect } from 'react';
import toast from 'react-hot-toast';

export function useLibrary() {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [stats, setStats] = useState({ total_artists: 0, total_albums: 0, total_tracks: 0 });

    const fetchLibrary = async () => {
        setLoading(true);
        try {
            const res = await fetch('/api/library');
            if (!res.ok) throw new Error('Failed to fetch library');
            const data = await res.json();
            setItems(data.items);
            setStats({
                total_artists: data.total_artists,
                total_albums: data.total_albums,
                total_tracks: data.total_tracks,
            });
        } catch (err) {
            toast.error(err.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchLibrary();
    }, []);

    const refreshLibrary = async () => {
        const toastId = toast.loading('Scanning library...');
        try {
            const res = await fetch('/api/library/refresh', { method: 'POST' });
            if (!res.ok) throw new Error('Refresh failed');
            const data = await res.json();
            toast.success(`Scan complete: ${data.total_tracks} tracks found`, { id: toastId });
            fetchLibrary();
        } catch (err) {
            toast.error('Failed to rescan library', { id: toastId });
        }
    };

    return { items, stats, loading, refreshLibrary };
}
