import { useState, useEffect } from 'react';
import toast from 'react-hot-toast';
import { FaSave, FaFolderOpen } from 'react-icons/fa';

export default function Settings() {
    const [config, setConfig] = useState(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        fetch('/api/config')
            .then(res => res.json())
            .then(data => {
                setConfig(data);
                setLoading(false);
            })
            .catch(err => {
                toast.error('Failed to load settings');
                setLoading(false);
            });
    }, []);

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        setConfig(prev => ({
            ...prev,
            [name]: type === 'checkbox' ? checked : value
        }));
    };

    const handleSave = async () => {
        setSaving(true);
        try {
            const res = await fetch('/api/config', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });

            if (res.ok) {
                toast.success('Settings saved successfully');
                // Reload config to confirm
                const updated = await res.json();
                setConfig(updated);
            } else {
                toast.error('Failed to save settings');
            }
        } catch (error) {
            toast.error('Error saving settings');
        } finally {
            setSaving(false);
        }
    };

    if (loading) return <div className="p-8">Loading settings...</div>;

    return (
        <div className="p-8 max-w-4xl mx-auto">
            <header className="mb-8">
                <h1 className="text-3xl font-bold">Settings</h1>
                <p className="text-gray-400">Configure download behavior and paths</p>
            </header>

            <div className="bg-surface border border-white/5 rounded-2xl p-6 space-y-6">
                {/* General Settings */}
                <section className="space-y-4">
                    <h2 className="text-xl font-semibold text-primary border-b border-white/10 pb-2">General</h2>

                    <div>
                        <label className="block text-sm font-medium text-gray-300 mb-1">Music Folder</label>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                name="music_folder"
                                value={config.music_folder || ''}
                                onChange={handleChange}
                                className="flex-1 bg-background/50 border border-white/10 rounded-lg px-4 py-2 focus:outline-none focus:border-primary"
                            />
                            {/* Folder picker would require native dialog, sticking to text input for web */}
                        </div>
                        <p className="text-xs text-gray-500 mt-1">Absolute path where music will be saved.</p>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-300 mb-1">Filename Template</label>
                        <input
                            type="text"
                            name="filename_template"
                            value={config.filename_template || ''}
                            onChange={handleChange}
                            className="w-full bg-background/50 border border-white/10 rounded-lg px-4 py-2 focus:outline-none focus:border-primary font-mono text-sm"
                        />
                        <p className="text-xs text-gray-500 mt-1">yt-dlp output template (e.g. <code>%(playlist_index|00|)s %(title)s.%(ext)s</code>)</p>
                    </div>
                </section>

                {/* Download Behavior */}
                <section className="space-y-4">
                    <h2 className="text-xl font-semibold text-primary border-b border-white/10 pb-2">Download Behavior</h2>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <Toggle
                            label="MP3 Mode"
                            name="mp3_mode"
                            checked={config.mp3_mode}
                            onChange={handleChange}
                            description="Convert to MP3 instead of FLAC"
                        />

                        <Toggle
                            label="Music Only Filter"
                            name="music_only"
                            checked={config.music_only}
                            onChange={handleChange}
                            description="Reject videos that aren't music/tracks"
                        />

                        <Toggle
                            label="Auto-Fetch Lyrics"
                            name="lyrics_mode"
                            checked={config.lyrics_mode}
                            onChange={handleChange}
                            description="Download synced lyrics from LRCLIB"
                        />

                        <Toggle
                            label="Parallel Mode"
                            name="parallel_mode"
                            checked={config.parallel_mode}
                            onChange={handleChange}
                            description="Download multiple files at once"
                        />
                    </div>
                </section>

                {/* Advanced */}
                <section className="space-y-4">
                    <h2 className="text-xl font-semibold text-primary border-b border-white/10 pb-2">Advanced</h2>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium text-gray-300 mb-1">Max Workers</label>
                            <input
                                type="number"
                                name="max_workers"
                                value={config.max_workers || 2}
                                onChange={handleChange}
                                min="1"
                                max="10"
                                className="w-full bg-background/50 border border-white/10 rounded-lg px-4 py-2 focus:outline-none focus:border-primary"
                            />
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-gray-300 mb-1">Cookies Browser</label>
                            <select
                                name="cookies_browser"
                                value={config.cookies_browser || ''}
                                onChange={handleChange}
                                className="w-full bg-background/50 border border-white/10 rounded-lg px-4 py-2 focus:outline-none focus:border-primary"
                            >
                                <option value="">None (Use cookies.txt)</option>
                                <option value="chrome">Chrome</option>
                                <option value="firefox">Firefox</option>
                                <option value="edge">Edge</option>
                                <option value="opera">Opera</option>
                            </select>
                        </div>
                    </div>
                </section>

                <div className="pt-4 flex justify-end">
                    <button
                        onClick={handleSave}
                        disabled={saving}
                        className="flex items-center gap-2 bg-primary hover:bg-primary/80 text-white px-6 py-3 rounded-xl font-medium transition-colors disabled:opacity-50"
                    >
                        {saving ? 'Saving...' : <><FaSave /> Save Changes</>}
                    </button>
                </div>
            </div>
        </div>
    );
}

function Toggle({ label, name, checked, onChange, description }) {
    return (
        <div className="flex items-start justify-between bg-background/30 p-3 rounded-lg border border-white/5">
            <div>
                <span className="font-medium text-gray-200">{label}</span>
                {description && <p className="text-xs text-gray-500 mt-0.5">{description}</p>}
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
                <input
                    type="checkbox"
                    name={name}
                    checked={checked || false}
                    onChange={onChange}
                    className="sr-only peer"
                />
                <div className="w-11 h-6 bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
            </label>
        </div>
    );
}
