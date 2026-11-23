# Guia de instalação do zero (Windows 11)

Tempo estimado: 30 a 45 minutos (a maior parte é download). Requisitos mínimos: Windows 11 (64 bits), 8 GB de RAM (recomendado 16 GB), 15 GB livres de disco, virtualização habilitada na BIOS/UEFI e acesso à internet.

## 1. Habilitar o WSL2

O Docker Desktop usa o WSL2 (Subsistema do Windows para Linux) para rodar os containers.

1. Abra o **PowerShell como administrador** (botão direito no menu Iniciar, "Terminal (Administrador)").
2. Instale o WSL:

```powershell
wsl --install
```

3. Reinicie o computador quando pedido.
4. Depois de reiniciar, confira:

```powershell
wsl --status
wsl --update
```

A versão padrão deve ser a 2. Se aparecer erro de virtualização, veja a seção "Solução de problemas".

## 2. Instalar o Docker Desktop

1. Baixe em https://www.docker.com/products/docker-desktop/ e instale, mantendo marcada a opção **Use WSL 2 instead of Hyper-V**. Alternativa pelo terminal:

```powershell
winget install -e --id Docker.DockerDesktop
```

2. Abra o Docker Desktop e aceite os termos. Espere o ícone da baleia ficar estável (Docker running).
3. Confira no PowerShell:

```powershell
docker version
docker compose version
```

Os dois comandos devem mostrar "Client" e "Server" sem erro.

## 3. Instalar o Git

```powershell
winget install -e --id Git.Git
```

Feche e reabra o PowerShell e confira com `git --version`.

Configure o Git para **não converter fim de linha** (os containers são Linux e precisam de LF):

```powershell
git config --global core.autocrlf false
```

## 4. Clonar o projeto

```powershell
cd C:\dev
git clone https://github.com/tiagolm16/monitor-redes.git
cd monitor-redes
```

(Se a pasta `C:\dev` não existir, crie com `mkdir C:\dev`.)

## 5. Subir tudo

```powershell
docker compose up -d --build
```

Na primeira vez o Docker baixa as imagens e constrói o `monitor` e o `loadgen` (de 3 a 8 minutos). Depois confira:

```powershell
docker compose ps
```

Devem aparecer 6 containers: `rd-nginx`, `rd-postgres`, `rd-coredns`, `rd-mailpit`, `rd-monitor` e `rd-loadgen`, todos `Up`.

Teste a API (espere cerca de 1 minuto para haver dados):

```powershell
curl.exe http://localhost:8000/api/health
```

A resposta deve conter `"status":"ok"`.

## 6. Rodar o scan de vulnerabilidades (Trivy)

```powershell
docker compose --profile scan run --rm trivy
```

Na primeira execução baixa o banco de CVEs (cerca de 140 MB) e escaneia as 4 imagens, em 2 a 5 minutos. Em segundos o painel passa a mostrar as vulnerabilidades na aba Segurança.

## 7. Abrir o painel e o Mailpit

| O que | Endereço |
|---|---|
| Painel de monitoramento | http://localhost:8000 |
| Mailpit (e-mails de alerta) | http://localhost:8025 |
| Site monitorado (nginx) | http://localhost:8081 (rota `/admin` com `admin` / `admin123`) |
| Swagger da API | http://localhost:8000/docs |

Dica: nos primeiros 2 a 3 minutos a aba Segurança ainda não mostra z-score (o monitor precisa de cerca de 2 minutos de histórico de tráfego).

## 8. Rodar os testes automatizados

Requisitos: Python 3.12 ou mais novo (https://www.python.org/downloads/, marque "Add python.exe to PATH") e o Google Chrome instalado.

```powershell
pip install playwright pytest
python -m pytest tests/e2e
```

A suíte leva cerca de 4 minutos e **derruba serviços e simula ataques de propósito**; ela restaura tudo no final. Os prints dos testes vão para `docs/img/testes/`.

Para gerar as figuras do artigo: `python scripts/capturar_prints.py`.

## 9. Parar e limpar

```powershell
docker compose down          # para os containers (mantém os dados)
docker compose down -v       # para e apaga também os volumes (dados do banco e do monitor)
```

## Solução de problemas comuns

**Porta ocupada (`Bind for 0.0.0.0:8081 failed: port is already allocated`)**
Descubra quem usa a porta e troque a porta do host no `docker-compose.yml`:

```powershell
netstat -ano | findstr :8081
```

Portas usadas pelo projeto no host: 8000, 8081, 8025, 1025, 1053, 9153, 5433 e 8090. Exemplo: para mudar o nginx de 8081 para 8082, edite `ports: ["8081:80"]` para `["8082:80"]` e rode `docker compose up -d` de novo. Para liberar uma porta, finalize o programa que a usa (o número no final da saída do `netstat` é o PID: `taskkill /PID 1234 /F`).

**A rede `172.28.77.0/24` conflita com outra rede (VPN, por exemplo)**
Erro como `Pool overlaps with other one on this address space`. Troque a faixa no `docker-compose.yml` (campo `subnet`) e os IPs fixos (`ipv4_address`), no `services/coredns/lab.local.db` e no `DNS_SERVER` do monitor e do loadgen, ou desconecte a VPN.

**Docker Desktop não inicia / "WSL 2 installation is incomplete"**
```powershell
wsl --update
wsl --shutdown
```
Depois abra o Docker Desktop de novo. Se persistir, confirme que a virtualização está ligada: Gerenciador de Tarefas, aba Desempenho, CPU, "Virtualização: Habilitado". Se estiver desabilitada, ative "Intel VT-x" ou "SVM Mode" na BIOS. Confira também se os recursos "Plataforma de Máquina Virtual" e "Subsistema do Windows para Linux" estão ligados em "Ativar ou desativar recursos do Windows".

**Erros estranhos em configs (`nginx: [emerg] unknown directive`, `Corefile` inválido) ou `exec format error` em scripts**
Quase sempre é fim de linha CRLF. O repositório força LF pelo `.gitattributes`. Se você clonou com a conversão ligada:

```powershell
git config core.autocrlf false
git rm --cached -r .
git reset --hard
```

(Atenção: `git reset --hard` descarta alterações locais não commitadas.)

**Os containers sobem mas o painel não mostra dados**
Espere 30 a 60 s. Veja `docker compose logs monitor --tail 50`. O monitor só inicia depois que o Postgres fica saudável (`docker compose ps` mostra `healthy`).

**O Trivy encontra 0 vulnerabilidades em tudo**
O banco de CVEs veio vazio. O `docker-compose.yml` já aponta para o espelho `public.ecr.aws`. Se acontecer mesmo assim, apague o cache e rode de novo:

```powershell
docker volume rm monitor-redes_trivy-cache
docker compose --profile scan run --rm trivy
```

**Alerta de configuração alterada logo depois de editar um arquivo de `services/`**
É o comportamento esperado (o monitor detecta a mudança). Se a alteração foi proposital, use o botão "Aceitar nova baseline" na aba Segurança.

**Edição de `nginx.conf` ou `postgresql.conf` não surte efeito**
Esses serviços só releem a configuração ao reiniciar: `docker compose restart nginx postgres`.

**O PowerShell não deixa rodar os scripts (`running scripts is disabled`)**
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\demo_ddos.ps1
```

**Pouca memória (Docker lento ou containers sendo encerrados)**
No Docker Desktop, Settings, Resources, ou crie `%UserProfile%\.wslconfig` com `[wsl2]` e `memory=4GB`, e rode `wsl --shutdown`.

**Os testes E2E falham por tempo**
Em máquinas lentas, a propagação de arquivos entre o Windows e o container demora mais. Feche programas pesados e rode de novo; os tempos limite estão em `tests/e2e/`.
