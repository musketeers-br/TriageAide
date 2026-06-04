#!/bin/bash

PORTA=8003
SUBDOMINIO="dark-ways-itch"
URL_DESEJADA="https://${SUBDOMINIO}.loca.lt"

while true; do
    echo "Tentando fixar o túnel em: $URL_DESEJADA"
    
    # Inicia o túnel em segundo plano e captura a URL gerada
    npx localtunnel --port $PORTA --subdomain $SUBDOMINIO > tunnel.log 2>&1 &
    PID_TUNNEL=$!
    
    # Aguarda 5 segundos para o comando inicializar e gerar a URL
    sleep 5
    
    # Lê a URL que o localtunnel gerou de fato
    URL_GERADA=$(grep -oE "https://[^ ]+\.loca\.lt" tunnel.log | head -n 1)
    
    if [ "$URL_GERADA" = "$URL_DESEJADA" ]; then
        echo "Sucesso! O túnel está ativo em: $URL_GERADA"
        # Aguarda o processo do túnel terminar (vai ficar preso aqui até cair)
        wait $PID_TUNNEL
    else
        echo "O servidor atribuiu a URL errada ($URL_GERADA)."
        echo "Fechando e limpando conexão..."
        kill $PID_TUNNEL 2>/dev/null
        # Tempo maior para o servidor do Localtunnel expirar sua sessão antiga
        echo "Aguardando 15 segundos para o servidor liberar o nome..."
        sleep 15
    fi
done
