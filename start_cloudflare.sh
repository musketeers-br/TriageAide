#!/bin/bash

PORTA=8003

# FUNÇÃO SEGURA PARA INSTALAR O CLOUDFLARED VIA REPOSITÓRIO APT
verificar_e_instalar() {
    if ! command -v cloudflared &> /dev/null; then
        echo "[$(date +'%T')] Cloudflared não encontrado. Configurando repositório oficial para Ubuntu..."
        
        # Cria a pasta de chaves se não existir
        sudo mkdir -p --mode=0755 /usr/share/keyrings
        
        # Baixa a chave GPG oficial da Cloudflare
        echo "[$(date +'%T')] Importando chave de segurança da Cloudflare..."
        curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
        
        # Adiciona o repositório oficial nas fontes do APT
        echo "[$(date +'%T')] Adicionando repositório às fontes do sistema..."
        echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflared.list >/dev/null
        
        # Atualiza a lista do APT e instala o pacote de forma oficial
        echo "[$(date +'%T')] Atualizando pacotes e instalando cloudflared..."
        sudo apt-get update -y && sudo apt-get install -y cloudflared
        
        # Valida se agora o comando está disponível
        if ! command -v cloudflared &> /dev/null; then
            echo "[$(date +'%T')] ERRO: Falha crítica na instalação via APT. O script foi interrompido."
            exit 1
        fi
        echo "[$(date +'%T')] Cloudflared instalado com sucesso de forma oficial!"
    fi
}

# Executa a verificação/instalação estável
verificar_e_instalar

echo "[$(date +'%T')] Iniciando monitor do Cloudflare Tunnel..."

while true; do
    echo "[$(date +'%T')] Tentando abrir túnel na porta $PORTA..."
    
    # Inicia o cloudflared direcionando a saída padrão (stdout) e erros para a tela e para o arquivo temporário
    cloudflared tunnel --url http://localhost:$PORTA 2>&1 | tee .cf_tmp.log &
    PID_CF=$!
    
    # Aguarda o tempo necessário para iniciar e gerar o domínio de teste
    sleep 7
    
    # Busca a URL gerada pela Cloudflare no arquivo temporário (.trycloudflare.com)
    URL_GERADA=$(grep -oE "https://[^ ]+\.trycloudflare\.com" .cf_tmp.log | head -n 1)
    
    if [ -n "$URL_GERADA" ]; then
        echo -e "\n\033[1;32m[$(date +'%T')] TÚNEL ATIVO! Acesse em: $URL_GERADA\033[0m\n"
        rm -f .cf_tmp.log
        
        # LOOP DE MONITORAMENTO: Fica preso aqui verificando se o processo continua vivo
        while true; do
            sleep 15
            if ! kill -0 $PID_CF 2>/dev/null; then
                echo "[$(date +'%T')] Alerta: O processo do túnel caiu espontaneamente!"
                break
            fi
        done
    else
        echo "[$(date +'%T')] Falha ao capturar a URL (serviço ocupado ou sem resposta). Forçando reinício em 10 segundos..."
        kill -9 $PID_CF 2>/dev/null
        rm -f .cf_tmp.log
        sleep 10
        continue
    fi
    
    sleep 5
done
