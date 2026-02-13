import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import { Toaster } from 'react-hot-toast';

export default function Layout() {
    return (
        <div className="flex h-screen bg-background text-white font-sans overflow-hidden">
            <Sidebar />
            <main className="flex-1 overflow-auto bg-background/50 relative">
                <Outlet />
            </main>
            <Toaster
                position="bottom-right"
                toastOptions={{
                    style: {
                        background: '#16213e',
                        color: '#fff',
                        border: '1px solid rgba(255,255,255,0.1)',
                    },
                }}
            />
        </div>
    );
}
