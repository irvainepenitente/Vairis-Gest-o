# Robô Vairis — servidor Python

Etapa 1: acessar exclusivamente a lista de eventos APSo, selecionar Todos, filtrar, ordenar Encerra em e devolver a tabela e uma imagem privada. Não baixa extratos nesta versão. Não acessa Bradesco.

## Hospedagem indicada: Render

Crie um Web Service com linguagem Docker e este diretório como contexto. Use uma única instância, disco persistente montado em `/app/data`, health check `/health` e porta definida por `PORT` (padrão 8080). Dimensione memória para Chromium; valide a execução real antes de escolher definitivamente o plano. Discos persistentes no Render requerem serviço pago. Não usar o serviço gratuito para prometer continuidade de dados.

O Dockerfile instala Python, Playwright e Chromium no servidor. O usuário do Vairis não instala nada. O repositório da hospedagem deve conter estes arquivos, sem senhas ou cookies. Não é necessário migrar o site Vairis para hospedar este serviço.

Documentação: https://render.com/docs/docker e https://render.com/docs/disks

## Configuração protegida

No painel do servidor, configure valores de runtime:

- `ROBOT_API_TOKEN`: token aleatório de pelo menos 32 caracteres. Gerar, por exemplo, com `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Não enviar ao chat, navegador ou Git.
- `EVENTOS_USERNAME` e `EVENTOS_PASSWORD`: acesso ao portal. Use a senha atualizada e cadastre diretamente no painel protegido da hospedagem. Não colocar no Dockerfile, em arquivos públicos ou no repositório.
- `ROBOT_DATA_DIR=/app/data`.

No Vairis, configurar a variável `AUTOMATION_RUNNER_URL` com a URL HTTPS do serviço e o segredo `AUTOMATION_RUNNER_TOKEN` com o mesmo token. O Worker autentica o usuário e faz a comunicação; o navegador não recebe o token.

## Dados e operação

SQLite guarda o andamento e resultado por identificador de usuário; a imagem da tabela fica no disco privado. O site recupera apenas as consultas do usuário atual. Faça backups do disco e defina a retenção de imagens/resultados antes de usar regularmente. Não salva senha em tarefas e não captura tela de login. Não registra detalhes de exceções que possam conter dados do portal.

Executa uma consulta por vez. Repetir o mesmo identificador não cria uma segunda tarefa. Após reinício, tarefas incompletas viram interrompidas; o usuário pode iniciar nova consulta. Credenciais APSo são de uma única conta configurada no servidor: esse serviço é para o proprietário do Vairis, não para um produto multiusuário com contas APSo distintas.

O fluxo foi preparado a partir das telas informadas. Se campos, captcha, autenticação ou tabela diferirem, retorna um aviso para revisão. Login real e hospedagem ainda precisam de validação. A tabela retornada contém somente a página visível; não declara conter todos os eventos de todas as páginas.

## API interna

`GET /health` é público e não contém dados. Demais rotas exigem `Authorization: Bearer <token>`.
`GET /status` verifica configuração. `POST /jobs` recebe `{id: UUID, owner: hash SHA256}`.
`GET /jobs/<id>` e `/jobs/<id>/image` exigem `X-Vairis-Owner` e retornam apenas dados desse proprietário.

Para desenvolvimento: instale requirements, Chromium e execute `python server.py`. Para testes de API sem acesso ao portal: `python -m unittest test_server.py`.
