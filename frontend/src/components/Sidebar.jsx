import { Link, useLocation } from 'react-router-dom';
import { FaMusic, FaDownload, FaCog, FaList } from 'react-icons/fa';

export default function Sidebar() {
    const location = useLocation();

    const menuItems = [
        { path: '/', icon: FaDownload, label: 'Downloads' },
        { path: '/library', icon: FaMusic, label: 'Library' },
        { path: '/playlists', icon: FaList, label: 'Playlists' },
        { path: '/settings', icon: FaCog, label: 'Settings' },
    ];

    return (
        <div className="w-64 bg-surface h-screen flex flex-col border-r border-white/5">
            <div className="p-6 flex items-center space-x-3">
                <div className="w-8 h-8 bg-gradient-to-br from-primary to-secondary rounded-lg"></div>
                <span className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-primary to-secondary">
                    Snowsky
                </span>
            </div>

            <nav className="flex-1 px-4 space-y-2 mt-4">
                {menuItems.map((item) => {
                    const isActive = location.pathname === item.path;
                    return (
                        <Link
                            key={item.path}
                            to={item.path}
                            className={`flex items-center space-x-3 px-4 py-3 rounded-xl transition-all duration-200 ${isActive
                                    ? 'bg-primary/10 text-primary font-medium shadow-sm'
                                    : 'text-gray-400 hover:bg-white/5 hover:text-white'
                                }`}
                        >
                            <item.icon className={isActive ? 'text-primary' : 'text-gray-500'} />
                            <span>{item.label}</span>
                        </Link>
                    );
                })}
            </nav>

            <div className="p-4 border-t border-white/5 text-xs text-gray-500 text-center">
                v2.0.0
            </div>
        </div>
    );
}
