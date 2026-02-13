import { useState } from 'react';
import toast from 'react-hot-toast';
import { FaList, FaDownload } from 'react-icons/fa';

export default function Playlists() {
    const [url, setUrl] = useState('');
    const [name, setName] = useState('');
    const [format, setFormat] = useState('flac');
    const [submitting, setSubmitting] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!url || !name) {
            toast.error('Please fill in all fields');
            return;
        }

        setSubmitting(true);
        try {
            const res = await fetch('/api/download/playlist', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url,
                    playlist_name: name,
                    format
                })
            });

            if (res.ok) {
                toast.success('Playlist download started!');
                setUrl('');
                setName('');
            } else {
                toast.error('Failed to start download');
            }
        } catch (error) {
            toast.error('Error submitting request');
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="p-8 max-w-4xl mx-auto">
            <header className="mb-8">
                <h1 className="text-3xl font-bold">Playlists</h1>
                <p className="text-gray-400">Download full playlists to organized folders</p>
            </header>

            <div className="bg-surface border border-white/5 rounded-2xl p-8">
                <form onSubmit={handleSubmit} className="space-y-6">
                    <div>
                        <label className="block text-sm font-medium text-gray-300 mb-2">Playlist URL</label>
                        <input
                            type="text"
                            value={url}
                            onChange={(e) => setUrl(e.target.value)}
                            placeholder="https://music.youtube.com/playlist?list=..."
                            className="w-full bg-background/50 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:border-primary transition-colors"
                        />
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label className="block text-sm font-medium text-gray-300 mb-2">Folder Name</label>
                            <input
                                type="text"
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                placeholder="My Awesome Playlist"
                                className="w-full bg-background/50 border border-white/10 rounded-xl px-4 py-3 focus:outline-none focus:border-primary transition-colors"
                            />
                            <p className="text-xs text-gray-500 mt-1">Saved to <code>Music/Playlists/[Name]</code></p>
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-gray-300 mb-2">Format</label>
                            <div className="flex bg-background/50 rounded-xl p-1 border border-white/10">
                                <button
                                    type="button"
                                    onClick={() => setFormat('flac')}
                                    className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${format === 'flac' ? 'bg-primary text-white' : 'text-gray-400 hover:text-white'}`}
                                >
                                    FLAC
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setFormat('mp3')}
                                    className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${format === 'mp3' ? 'bg-primary text-white' : 'text-gray-400 hover:text-white'}`}
                                >
                                    MP3
                                </button>
                            </div>
                        </div>
                    </div>

                    <div className="pt-4">
                        <button
                            type="submit"
                            disabled={submitting}
                            className="w-full bg-primary hover:bg-primary/80 text-white font-bold py-4 rounded-xl transition-all transform active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                        >
                            {submitting ? (
                                <span className="animate-pulse">Starting...</span>
                            ) : (
                                <>
                                    <FaDownload /> Start Download
                                </>
                            )}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
