# 🤖 Bot Telegram de Afiliados

Bot que baixa vídeos de TikTok, Instagram, Pinterest e YouTube, remove metadados e gera descrições prontas para afiliados usando IA.

---

## ✅ O que o bot faz

1. **Recebe um link** de TikTok, Instagram, Pinterest, YouTube ou MP4 direto
2. **Baixa o vídeo** sem marca d'água usando `yt-dlp`
3. **Remove metadados** (autor, GPS, câmera, rastreadores) com FFmpeg
4. **Gera descrições** prontas para grupos e Instagram Story com Google Gemini AI
5. **Devolve tudo** no Telegram

---

## 📦 Pré-requisitos

- Python 3.10 ou superior
- FFmpeg instalado no sistema
- Token do @BotFather (Telegram)
- Chave da API Google Gemini (grátis)

---

## 🚀 Instalação Passo a Passo

### 1. Instalar Python
Baixe em: https://www.python.org/downloads/

### 2. Instalar FFmpeg (Windows)

**Opção A — via Winget (recomendado):**
```bash
winget install ffmpeg
```

**Opção B — manual:**
1. Baixe em: https://ffmpeg.org/download.html
2. Extraia para `C:\ffmpeg`
3. Adicione `C:\ffmpeg\bin` ao PATH do sistema

Verifique: `ffmpeg -version`

### 3. Instalar dependências Python

```bash
cd c:\Users\User\projetoADROOM\TelegramBot
pip install -r requirements.txt
```

### 4. Criar o bot no Telegram

1. Abra o Telegram e procure por **@BotFather**
2. Digite `/newbot`
3. Escolha um nome (ex: `Meu Bot Afiliados`)
4. Escolha um username (ex: `@meubotafiliados_bot`)
5. Copie o **token** gerado (parece com: `7123456789:AAH...`)

### 5. Obter chave do Google Gemini (grátis)

1. Acesse: https://aistudio.google.com/app/apikey
2. Clique em **Create API Key**
3. Copie a chave gerada

### 6. Configurar o .env

```bash
# No terminal, dentro da pasta TelegramBot:
copy .env.example .env
```

Abra o arquivo `.env` e preencha:
```
TELEGRAM_BOT_TOKEN=7123456789:AAHseuToken...
GEMINI_API_KEY=AIzaSy...suaChave...
```

### 7. Iniciar o bot

```bash
python bot.py
```

---

## 💬 Como usar

No Telegram, envie qualquer link:

```
https://www.tiktok.com/@usuario/video/7123456789
https://www.instagram.com/reel/AbCdEfGhIjK/
https://www.youtube.com/shorts/AbCdEfGhIjK
https://br.pinterest.com/pin/123456789/
```

O bot vai:
- Baixar o vídeo automaticamente
- Limpar todos os metadados
- Te enviar o vídeo + 2 descrições prontas

---

## ⌨️ Comandos disponíveis

| Comando   | Descrição                          |
|-----------|-------------------------------------|
| `/start`  | Exibe mensagem de boas-vindas       |
| `/ajuda`  | Dicas de uso e plataformas suportadas |
| `/status` | Verifica se FFmpeg e Gemini estão OK |

---

## 🔒 Restringir acesso (opcional)

Para que apenas você use o bot, adicione seu ID no `.env`:

1. Descubra seu ID: envie uma mensagem para **@userinfobot** no Telegram
2. Adicione no `.env`:
```
ALLOWED_USERS=123456789
```

---

## 🗂️ Estrutura do projeto

```
TelegramBot/
├── bot.py           # Bot principal
├── downloader.py    # Download de vídeos (yt-dlp)
├── cleaner.py       # Remoção de metadados (FFmpeg)
├── generator.py     # Geração de descrições (Gemini AI)
├── requirements.txt # Dependências Python
├── .env.example     # Modelo de configuração
├── .env             # Suas credenciais (NÃO compartilhe!)
├── downloads/       # Pasta temporária (gerada automaticamente)
└── bot.log          # Log de execução
```

---

## ⚠️ Avisos

- Vídeos acima de **50 MB** não serão enviados (limite do Telegram)
- Vídeos **privados** não funcionam (apenas públicos)
- Mantenha o `yt-dlp` atualizado: `pip install -U yt-dlp`
- O arquivo `.env` contém suas senhas — nunca compartilhe nem envie ao GitHub

---

## 🆘 Problemas comuns

| Problema | Solução |
|----------|---------|
| `FFmpeg não encontrado` | Instale o FFmpeg e adicione ao PATH |
| `DownloadError: Private video` | O vídeo é privado, use um público |
| `Token inválido` | Verifique o token no `.env` |
| `Vídeo não encontrado` | Link inválido ou expirado |
| TikTok não baixa | Atualize: `pip install -U yt-dlp` |
