#!/usr/bin/env bash
set -e

echo "============================================="
echo "  IT Help - Workstation Management Suite"
echo "============================================="
echo

# Install deps if needed
python3 -c "import fastapi" 2>/dev/null || {
    echo "Installing dependencies..."
    python3 -m pip install -r requirements.txt
}

LOCAL_IP=$(python3 -c "import socket; s=socket.socket(); s.connect(('8.8.8.8',80)); print(s.getsockname()[0]); s.close()" 2>/dev/null || echo "localhost")

echo
echo "  Starting server..."
echo "  Local:   http://localhost:8080"
echo "  Network: http://$LOCAL_IP:8080"
echo
echo "  Open the URL above in any browser."
echo "  Press Ctrl+C to stop."
echo "============================================="
echo

python3 server.py
