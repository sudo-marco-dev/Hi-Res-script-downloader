import { useEffect, useState } from 'react';

const SOCKET_URL = 'ws://localhost:8000/api/download/ws/progress';

export function useProgressSocket() {
    const [messages, setMessages] = useState({});
    const [isConnected, setIsConnected] = useState(false);

    useEffect(() => {
        let ws;
        let reconnectTimer;

        const connect = () => {
            ws = new WebSocket(SOCKET_URL);

            ws.onopen = () => {
                setIsConnected(true);
                console.log('Connected to progress socket');
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    // Update message for this specific job_id
                    if (data.job_id) {
                        setMessages((prev) => ({
                            ...prev,
                            [data.job_id]: data,
                        }));
                    }
                } catch (e) {
                    console.error('WebSocket parse error:', e);
                }
            };

            ws.onclose = () => {
                setIsConnected(false);
                console.log('Socket closed, reconnecting in 3s...');
                reconnectTimer = setTimeout(connect, 3000);
            };

            ws.onerror = (err) => {
                console.error('Socket error:', err);
                ws.close();
            };
        };

        connect();

        return () => {
            if (ws) ws.close();
            clearTimeout(reconnectTimer);
        };
    }, []);

    return { isConnected, progress: messages };
}
