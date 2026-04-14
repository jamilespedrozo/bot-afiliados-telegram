#!/bin/bash
# =============================================================
# Setup do Bot Telegram Afiliados — Oracle Cloud Ubuntu
# Execute este script como usuário 'ubuntu' no servidor
# =============================================================

set -e  # Para ao encontrar erro

echo "============================================="
echo " BOT AFILIADOS — Setup do Servidor Oracle"
echo "============================================="

# ---- 1. Atualizar sistema ----
echo "[1/7] Atualizando o sistema..."
sudo apt-get update -y && sudo apt-get upgrade -y

# ---- 2. Instalar dependências do sistema ----
echo "[2/7] Instalando Python, ffmpeg e ferramentas..."
sudo apt-get install -y python3.11 python3.11-venv python3-pip git ffmpeg curl

# ---- 3. Clonar o repositório ----
echo "[3/7] Clonando repositório do GitHub..."
echo ""
echo "  ATENÇÃO: Cole o link do seu repositório GitHub quando solicitado."
echo "  Formato: https://github.com/SEU_USUARIO/bot-afiliados-telegram.git"
echo ""
read -p "URL do repositório GitHub: " REPO_URL

# Se repositório privado, pede o token
read -p "É um repositório privado? (s/n): " PRIVADO
if [ "$PRIVADO" = "s" ] || [ "$PRIVADO" = "S" ]; then
    read -p "Seu GitHub Username: " GH_USER
    read -s -p "Seu GitHub Personal Access Token: " GH_TOKEN
    echo ""
    # Injeta credenciais na URL
    REPO_URL_AUTH=$(echo "$REPO_URL" | sed "s|https://|https://$GH_USER:$GH_TOKEN@|")
    git clone "$REPO_URL_AUTH" /home/ubuntu/bot-afiliados
else
    git clone "$REPO_URL" /home/ubuntu/bot-afiliados
fi

cd /home/ubuntu/bot-afiliados

# ---- 4. Criar ambiente virtual e instalar dependências ----
echo "[4/7] Criando ambiente virtual Python..."
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# ---- 5. Configurar variáveis de ambiente (.env) ----
echo "[5/7] Configurando variáveis de ambiente..."
echo ""
echo "  Agora precisamos configurar as chaves do bot."
echo ""
read -p "TELEGRAM_BOT_TOKEN: " BOT_TOKEN
read -p "GEMINI_API_KEY: " GEMINI_KEY
read -p "ALLOWED_USERS (IDs separados por vírgula, ou ENTER para permitir todos): " ALLOWED

cat > /home/ubuntu/bot-afiliados/.env << EOF
TELEGRAM_BOT_TOKEN=$BOT_TOKEN
GEMINI_API_KEY=$GEMINI_KEY
ALLOWED_USERS=$ALLOWED
EOF

echo "  Arquivo .env criado com sucesso!"

# ---- 6. Criar pasta de downloads ----
mkdir -p /home/ubuntu/bot-afiliados/downloads

# ---- 7. Instalar e iniciar serviço systemd ----
echo "[6/7] Configurando serviço systemd..."
sudo cp /home/ubuntu/bot-afiliados/bot-afiliados.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bot-afiliados
sudo systemctl start bot-afiliados

echo ""
echo "============================================="
echo " ✅ DEPLOY CONCLUÍDO COM SUCESSO!"
echo "============================================="
echo ""
echo " Status do bot:"
sudo systemctl status bot-afiliados --no-pager
echo ""
echo " Comandos úteis:"
echo "   Ver logs ao vivo:  journalctl -u bot-afiliados -f"
echo "   Reiniciar bot:     sudo systemctl restart bot-afiliados"
echo "   Parar bot:         sudo systemctl stop bot-afiliados"
echo "   Ver status:        sudo systemctl status bot-afiliados"
echo ""
echo " Seu bot está online 24/7! 🚀"
