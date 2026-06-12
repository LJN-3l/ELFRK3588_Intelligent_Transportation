cat > /root/start_all.sh <<'EOF'
#!/bin/sh
set -eu

echo "=== A. Stop old services ==="
pkill -f mjpeg_server.py || true
pkill -f web_dashboard_v4.py || true
pkill -f start_mjpeg_server_fast.sh || true
pkill -f start_rk_yolo_dashboard.sh || true
sleep 1

echo
echo "=== B. Start UART MJPEG service (5001) ==="
nohup sh /root/start_mjpeg_server_fast.sh > /root/mjpeg_server.log 2>&1 &
sleep 2
tail -n 20 /root/mjpeg_server.log || true

echo
echo "=== C. Start Smart Traffic dashboard (5000) ==="
nohup sh /root/start_rk_yolo_dashboard.sh > /root/dashboard.log 2>&1 &
sleep 3
tail -n 30 /root/dashboard.log || true

echo
echo "=== D. Check ports ==="
ss -lntp | grep -E '5000|5001' || true

echo
echo "=== E. Local checks ==="
curl --max-time 3 http://127.0.0.1:5001/status || true
echo
curl -I --max-time 3 http://127.0.0.1:5000/ || true

echo
echo "=== F. Ready ==="
echo "RK3588 dashboard: http://192.168.137.82:5000"
echo "K230 stream:      http://192.168.137.82:5001/video"
echo "Then start the K230 camera script."
EOF

chmod +x /root/start_all.sh
echo "installed: /root/start_all.sh"
