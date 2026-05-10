#!/bin/bash
set -e

INSTALL_DIR="/root/ERP"
REPO_URL="https://github.com/mzrakhimov-ui/ERP"
SERVICE="atex-erp"

echo "==> Tizim paketlari yangilanmoqda..."
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv git

echo "==> Repozitoriy yuklanmoqda..."
if [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR" && git pull
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

echo "==> Virtual muhit va kutubxonalar o'rnatilmoqda..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/Requirements"

echo "==> .env fayl tekshirilmoqda..."
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    echo ""
    echo "⚠️  MUHIM: $INSTALL_DIR/.env faylini oching va BOT_TOKEN ni kiriting!"
    echo "    nano $INSTALL_DIR/.env"
    echo ""
    exit 1
fi

echo "==> Systemd xizmat o'rnatilmoqda..."
cp "$INSTALL_DIR/atex-erp.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

echo ""
echo "✅ Bot ishga tushdi!"
echo "   Holat:  systemctl status $SERVICE"
echo "   Loglar: journalctl -u $SERVICE -f"
