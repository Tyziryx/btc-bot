#!/bin/bash
echo "Stopping dashboard..."
pkill -f "uvicorn dashboard" 2>/dev/null || true
pkill -f "next start" 2>/dev/null || true
pkill -f "ngrok http" 2>/dev/null || true
echo "Dashboard stopped."
