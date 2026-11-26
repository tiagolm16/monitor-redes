"""Gera video/NARRACAO.md e video/cenas.json (duracao estimada por cena) a partir dos textos abaixo.
Uso: python video/gerar_narracao.py"""
import json
from pathlib import Path

PASTA = Path(__file__).parent
PALAVRAS_POR_MINUTO = 150

CENAS = [
    {
        "id": "cena01",
        "titulo": "Abertura e arquitetura",
        "tela": "Diagrama de arquitetura (fig00) em tela cheia, depois o painel abrindo na Visão Geral.",
        "texto": (
            "Olá! Este é o nosso trabalho final de Redes de Computadores: uma plataforma de monitoramento para DevOps. "
            "Ela observa quatro serviços de rede: um servidor web, um banco de dados, um servidor de nomes, o DNS, "
            "e um servidor de e-mail. "
            "Veja a arquitetura. Seis containers sobem com um único comando do Docker Compose. "
            "O monitor consulta cada serviço a cada cinco segundos, usando os próprios protocolos deles: "
            "HTTP, SQL, DNS e SMTP. "
            "Guarda tudo num banco leve, o SQLite, e entrega os dados para este painel e para o motor de alertas. "
            "Um gerador de tráfego simula usuários e também ataques."
        ),
    },
    {
        "id": "cena02",
        "titulo": "Visão geral e páginas dos serviços",
        "tela": "Visão Geral; depois as páginas Web, Banco, DNS e SMTP, uma por vez, com os gráficos e o seletor de período.",
        "texto": (
            "Esta é a visão geral. Cada card é um serviço, com a cor do estado: verde, está tudo bem; "
            "amarelo pede atenção; vermelho é crítico. "
            "O card de segurança fica amarelo porque as imagens públicas têm falhas conhecidas. "
            "Na página Web, vemos disponibilidade, requisições por segundo, tempo de resposta, taxa de erro e a contagem por código HTTP. "
            "No banco de dados: consultas por segundo, conexões abertas, uso de processador e memória, tamanho do banco e consultas lentas. "
            "No DNS: tempo de resolução e taxa de falha. "
            "E no e-mail: taxa de entrega, fila de envio e latência. "
            "Dá para escolher cinco minutos, quinze minutos ou uma hora, e tudo se atualiza sozinho."
        ),
    },
    {
        "id": "cena03",
        "titulo": "Queda do banco e e-mails",
        "tela": "Faixa com o comando; card do banco vermelho; Mailpit com o e-mail [CRÍTICO]; banco religado, card verde e e-mail [RECUPERADO].",
        "texto": (
            "Agora vamos derrubar o banco de dados. Este comando para o container do Postgres. "
            "Em cerca de dez segundos, o card do banco fica vermelho. "
            "E chega um e-mail crítico na caixa de entrada, com o serviço, o valor medido, o limite, o horário de Brasília e um link para o painel. "
            "Para não gerar alarme falso, a regra só dispara depois de algumas leituras seguidas ruins. "
            "Agora religamos o banco. "
            "Em poucos segundos o card volta ao verde, e chega o e-mail de recuperação, informando quanto tempo durou o incidente."
        ),
    },
    {
        "id": "cena04",
        "titulo": "Página de Alertas",
        "tela": "Página Alertas: incidente do banco resolvido, filtros por nível e serviço, tabela de regras.",
        "texto": (
            "Na página de alertas fica o histórico. Aqui está o incidente do banco, com a hora de abertura, "
            "o pior nível que ele atingiu e a duração. "
            "Dá para filtrar por nível e por serviço. "
            "Mais abaixo estão as regras, lidas de um arquivo de configuração. "
            "Cada regra mostra os limites do amarelo e do vermelho e quantas leituras seguidas são necessárias para mudar de estado. "
            "São três níveis: verde, amarelo e vermelho."
        ),
    },
    {
        "id": "cena05",
        "titulo": "Segurança: tráfego anormal e tentativas de invasão",
        "tela": "Aba Segurança: modo pico (z-score e top 5 IPs), depois modo brute force (IPs suspeitos e contas alvo).",
        "texto": (
            "Agora, a segurança. Vamos simular um ataque de negação de serviço, quando muitos acessos inundam o servidor. "
            "O sistema compara o tráfego atual com a média dos últimos dez minutos. "
            "Essa conta se chama z-score: quantos desvios padrão acima do normal. "
            "Normalmente fica perto de zero. Aqui passou de cem, e o alerta ficou vermelho. "
            "A lista mostra os cinco endereços que mais acessaram, e as três origens do ataque aparecem no topo. "
            "Agora, tentativas repetidas de senha errada. "
            "O sistema conta as falhas por endereço, em janelas de sessenta segundos, "
            "no painel administrativo do servidor web e no banco de dados. "
            "Os endereços suspeitos aparecem na tabela, junto com a conta mais atacada."
        ),
    },
    {
        "id": "cena06",
        "titulo": "Segurança: configuração e vulnerabilidades",
        "tela": "Comando em faixa; seção de configuração com hashes e diff; seção de vulnerabilidades com os CVEs.",
        "texto": (
            "Também vigiamos os arquivos de configuração. "
            "De cada arquivo, guardamos uma impressão digital, o hash SHA-256. "
            "Vamos acrescentar um comentário no arquivo do servidor web. "
            "Em poucos segundos o sistema detecta, mostra a impressão digital antiga e a nova, e as linhas que mudaram. "
            "Basta mudar um único caractere para o hash ser totalmente diferente. "
            "Por fim, o Trivy escaneia as imagens dos containers. "
            "O painel mostra, por serviço, quantas vulnerabilidades conhecidas existem em cada gravidade, "
            "com o pacote afetado e a versão que corrige o problema."
        ),
    },
    {
        "id": "cena07",
        "titulo": "Celular e testes",
        "tela": "Painel em tamanho de celular com o menu aberto; depois o resultado dos testes (16 de 16).",
        "texto": (
            "O painel também funciona no celular. O menu vira um botão, e as páginas não têm rolagem lateral. "
            "Para garantir a qualidade, criamos dezesseis testes automatizados. "
            "Eles abrem cada página, conferem os gráficos e os filtros, "
            "e reproduzem as falhas e os ataques, verificando até a chegada dos e-mails. "
            "O resultado final: dezesseis de dezesseis aprovados."
        ),
    },
    {
        "id": "cena08",
        "titulo": "Encerramento",
        "tela": "Painel na Visão Geral; depois a tela de encerramento com o endereço do repositório.",
        "texto": (
            "Resumindo: monitoramos quatro serviços de rede, com painéis, alertas em três níveis com e-mail, "
            "e quatro frentes de segurança, tudo funcionando com um único comando. "
            "O código, a documentação e o relatório estão no nosso repositório do GitHub. "
            "Obrigado pela atenção!"
        ),
    },
]


def main():
    total_palavras = 0
    total_seg = 0.0
    linhas = [
        "# Narração do vídeo explicativo",
        "",
        "Leia exatamente o texto de cada cena, em ritmo natural (cerca de 150 palavras por minuto). "
        "Grave **um arquivo por cena** e salve em `video/audio/` com estes nomes exatos "
        "(formato `.m4a`; `.mp3` ou `.wav` também funcionam, mas mantenha o nome da cena):",
        "",
        "`cena01.m4a`, `cena02.m4a`, `cena03.m4a`, `cena04.m4a`, `cena05.m4a`, `cena06.m4a`, `cena07.m4a`, `cena08.m4a`",
        "",
        "O vídeo tem uma tela de abertura (título, disciplina, integrantes) e uma de encerramento (repositório) sem narração. "
        "Não há legendas.",
        "",
    ]
    meta = {}
    for c in CENAS:
        n = len(c["texto"].split())
        seg = n / PALAVRAS_POR_MINUTO * 60
        c["palavras"], c["segundos"] = n, round(seg, 1)
        total_palavras += n
        total_seg += seg
        meta[c["id"]] = {"titulo": c["titulo"], "segundos": c["segundos"]}
        linhas += [
            f"## {c['id']}: {c['titulo']}",
            "",
            f"- **Arquivo de áudio:** `{c['id']}.m4a`",
            f"- **O que aparece na tela:** {c['tela']}",
            f"- **Duração estimada:** {c['segundos']:.0f} s ({n} palavras)",
            "",
            "**Texto para ler:**",
            "",
            f"> {c['texto']}",
            "",
        ]
    linhas += [
        "---",
        "",
        f"**Total:** {total_palavras} palavras, cerca de {total_seg / 60:.1f} minutos de narração "
        f"(mais cerca de 10 segundos das telas de abertura e encerramento).",
        "",
    ]
    (PASTA / "NARRACAO.md").write_text("\n".join(linhas), encoding="utf-8", newline="\n")
    (PASTA / "cenas.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    for c in CENAS:
        print(c["id"], c["palavras"], "palavras", c["segundos"], "s")
    print("TOTAL", total_palavras, "palavras", round(total_seg / 60, 2), "min")


if __name__ == "__main__":
    main()
