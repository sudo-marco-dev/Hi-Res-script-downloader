import { useState } from 'react';
import { FaMusic, FaCompactDisc, FaFolder, FaSync, FaSearch } from 'react-icons/fa';
import { useLibrary } from '../hooks/useLibrary';

export default function Library() {
    const { items, stats, loading, refreshLibrary } = useLibrary();
    const [filter, setFilter] = useState('');

    const filteredItems = items.filter(item =>
        item.artist.toLowerCase().includes(filter.toLowerCase()) ||
        item.album.toLowerCase().includes(filter.toLowerCase())
    );

    return (
        <div className="p-8 h-full flex flex-col">
            <header className="flex justify-between items-center mb-8">
                <div>
                    <h1 className="text-3xl font-bold">Library</h1>
                    <p className="text-gray-400">
                        {stats.total_albums} albums • {stats.total_artists} artists • {stats.total_tracks} tracks
                    </p>
                </div>
                <div className="flex gap-4">
                    <div className="relative group">
                        <FaSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-primary transition-colors" />
                        <input
                            type="text"
                            placeholder="Search library..."
                            value={filter}
                            onChange={(e) => setFilter(e.target.value)}
                            className="bg-surface border border-white/10 rounded-xl py-2 pl-10 pr-4 w-64 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all"
                        />
                    </div>
                    <button
                        onClick={refreshLibrary}
                        className="p-2 bg-surface hover:bg-white/5 border border-white/10 rounded-xl transition-colors"
                        title="Rescan Library"
                    >
                        <FaSync className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>
            </header>

            {loading ? (
                <div className="flex-1 flex items-center justify-center text-gray-500">
                    <div className="animate-spin text-4xl mb-4">⠋</div>
                    <span className="ml-3">Loading library...</span>
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 pb-8">
                    {filteredItems.map((item) => (
                        <LibraryCard key={item.path} item={item} />
                    ))}
                    {filteredItems.length === 0 && (
                        <div className="col-span-full text-center py-20 text-gray-500">
                            No matching albums found.
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

function LibraryCard({ item }) {
    // Use backend proxied URL for covers
    const coverSrc = item.cover_url ? `/api/${item.cover_url}`.replace('/api//', '/api/') : null;
    // Actually, StaticFiles is mounted at /covers on backend (port 8000).
    // Vite proxies /api to port 8000. 
    // It does NOT proxy /covers.
    // We need to proxy /covers as well in vite.config.js OR use full URL.
    // Using full URL http://localhost:8000/covers/... is easier but CORS might block if not configured (it is configured).
    // But wait, our backend mount is at /covers.
    // The item.cover_url is like "/covers/Artist/Album/cover.jpg".
    // So we should just use "http://localhost:8000" + item.cover_url.

    const imageUrl = item.cover_url ? `http://localhost:8000${item.cover_url}` : null;

    return (
        <div className="bg-surface/50 hover:bg-surface border border-white/5 hover:border-primary/30 rounded-xl p-4 transition-all group cursor-pointer group">
            <div className="aspect-square bg-black/40 rounded-lg mb-4 flex items-center justify-center text-gray-600 group-hover:text-primary transition-colors relative overflow-hidden">
                {imageUrl ? (
                    <img
                        src={imageUrl}
                        alt={item.album}
                        className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
                        onError={(e) => { e.target.style.display = 'none'; }}
                    />
                ) : (
                    <FaCompactDisc className="text-4xl" />
                )}
                {imageUrl && <FaCompactDisc className="text-4xl absolute opacity-0 group-hover:opacity-0" />}
            </div>
            <div>
                <h3 className="font-bold truncate text-white group-hover:text-primary transition-colors">{item.album}</h3>
                <p className="text-sm text-gray-400 truncate">{item.artist}</p>
                <div className="flex items-center gap-2 mt-2 text-xs text-gray-500">
                    <FaMusic size={10} /> <span>{item.tracks} tracks</span>
                </div>
            </div>
        </div>
    );
}
